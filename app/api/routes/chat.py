from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import config as app_config
from app.core.time import app_now
from app.db.session import get_db
from app.models import ChatMessage, ChatMessageSource, ChatSession, Document, DocumentChunk, ExtractionJob, ExtractionResult, User
from app.services.document_search_service import DocumentSearchService
from app.services.web_search_service import WebSearchService

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))
DONE_STATUSES = ("done", "completed")


class ChatStreamRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(5, ge=1, le=20)
    document_id: int | None = Field(None, ge=1)
    threshold: float = Field(0.0, ge=0.0, le=1.0)
    session_id: int | None = Field(None, ge=1)
    enable_web_search: bool = Field(False, description="是否启用网页搜索")


class ChatSourceRead(BaseModel):
    source_type: str
    source_id: int | None = None
    chunk_id: int | None = None
    document_id: int | None = None
    document_title: str | None = None
    filename: str | None = None
    chunk_index: int | None = None
    chunk_type: str | None = None
    score: float = 0.0
    text: str = ""
    source: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    extraction_job_id: int | None = None
    field_name: str | None = None
    content: str | None = None
    evidence: str | None = None
    confidence: float | None = None


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    sources: list[dict[str, Any]] = Field(default_factory=list)


class ChatSessionListItem(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: str | None = None


class ChatSessionDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead]


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _openai_chat_urls(base_url: str) -> list[str]:
    base = base_url.strip().rstrip("/")
    if base.endswith("/v1"):
        return [f"{base}/chat/completions"]
    return [f"{base}/v1/chat/completions", f"{base}/chat/completions"]


def _openai_config() -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", app_config.OPENAI_API_KEY).strip()
    base_url = os.getenv("OPENAI_BASE_URL", app_config.OPENAI_BASE_URL).strip() or "https://api.openai.com/v1"
    model = os.getenv("OPENAI_MODEL", app_config.OPENAI_MODEL).strip() or "gpt-4o-mini"
    return api_key, base_url, model


def openai_chat_tokens(messages: list[dict[str, str]]) -> Iterable[str]:
    api_key, base_url, model = _openai_config()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    last_error_detail: str | None = None

    for url in _openai_chat_urls(base_url):
        try:
            with httpx.stream("POST", url, headers=headers, json=body, timeout=CHAT_TIMEOUT_SECONDS) as response:
                # Try to extract error details before raising
                status_code = int(getattr(response, "status_code", 200) or 200)
                is_success = bool(getattr(response, "is_success", 200 <= status_code < 300))
                if not is_success:
                    try:
                        error_body = response.read().decode("utf-8")
                        error_json = json.loads(error_body)
                        if "error" in error_json and isinstance(error_json["error"], dict):
                            error_msg = error_json["error"].get("message", "")
                            error_type = error_json["error"].get("type", "")
                            last_error_detail = f"{error_msg} ({error_type})" if error_type else error_msg
                            # Check if it's a "Client not allowed" error
                            if "client not allowed" in error_msg.lower():
                                logger.warning("API blocked User-Agent, consider using browser fallback")
                    except Exception:
                        pass

                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[len("data:") :].strip()
                    if line == "[DONE]":
                        return
                    try:
                        payload = json.loads(line)
                        # Check for error in streaming response
                        if "error" in payload:
                            error_info = payload["error"]
                            if isinstance(error_info, dict):
                                error_msg = error_info.get("message", str(error_info))
                                raise RuntimeError(f"API error: {error_msg}")
                            raise RuntimeError(f"API error: {error_info}")
                    except json.JSONDecodeError:
                        continue
                    choice = (payload.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    token = delta.get("content")
                    if token:
                        yield str(token)
                    message = choice.get("message") or {}
                    if message.get("content"):
                        yield str(message["content"])
                return
        except Exception as exc:
            last_error = exc
            continue

    error_msg = last_error_detail or str(last_error) if last_error else "Unknown error"
    raise RuntimeError(f"OpenAI chat stream failed for model {model}: {error_msg}")


def _query_terms(query: str) -> list[str]:
    """\u63d0\u53d6\u67e5\u8be2\u5173\u952e\u8bcd\uff08\u6539\u8fdb\u7248 - \u63d0\u9ad8\u4e2d\u6587\u53ec\u56de\u7387\uff09"""
    # 1. \u4f7f\u7528\u6b63\u5219\u63d0\u53d6\u4e2d\u82f1\u6587\u8bcd\u6c47\uff08\u5355\u4e2a\u6c49\u5b57\u5206\u8bcd\uff09
    import re
    # \u4fee\u590d\uff1a\u6bcf\u4e2a\u6c49\u5b57\u5355\u72ec\u63d0\u53d6\uff0c\u4e0d\u8981\u805a\u5408\u6210\u957f\u4e32
    tokens = re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]', query.lower())

    # 2. \u53bb\u9664\u4e2d\u6587\u505c\u7528\u8bcd\uff08\u51cf\u5c11\u505c\u7528\u8bcd\u5217\u8868\uff0c\u4fdd\u7559\u66f4\u591a\u6709\u610f\u4e49\u7684\u8bcd\uff09
    stopwords = {
        "\u7684", "\u4e86", "\u662f", "\u5728", "\u6211", "\u6709", "\u548c", "\u5c31", "\u4e0d", "\u4eba", "\u90fd",
        "\u4e00", "\u4e2a", "\u8fd9", "\u90a3", "\u4ec0", "\u4e48", "\u600e", "\u54ea"
    }

    # 3. \u8fc7\u6ee4\uff1a\u53bb\u9664\u505c\u7528\u8bcd\uff0c\u4f46\u4fdd\u7559\u66f4\u591a\u5355\u5b57\uff08\u5355\u5b57\u4e5f\u53ef\u80fd\u662f\u5173\u952e\u4fe1\u606f\uff09
    filtered = []
    for token in tokens:
        if token in stopwords:
            continue
        # \u53ea\u8fc7\u6ee4\u7eaf\u6807\u70b9\u548c\u7a7a\u767d\uff0c\u4fdd\u7559\u6240\u6709\u6709\u610f\u4e49\u7684\u5355\u5b57
        if token.strip():
            filtered.append(token)

    # 4. \u53bb\u91cd\u4f46\u4fdd\u6301\u987a\u5e8f
    unique_terms: list[str] = []
    seen = set()
    for term in filtered:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)

    return unique_terms[:15]  # \u589e\u52a0\u523015\u4e2a\u5173\u952e\u8bcd\uff0c\u63d0\u9ad8\u53ec\u56de\u7387


def _relevance_score(text: str, terms: list[str]) -> float:
    haystack = text.lower()
    score = 0.0
    for term in terms:
        if term in haystack:
            score += max(1.0, min(3.0, len(term) / 2))
    return score


def _metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        parsed = json.loads(metadata_json)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _keyword_chunk_sources(db: Session, user_id: int, query: str, limit: int, document_id: int | None) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return []

    # 同时搜索文档标题和chunk内容，提高召回率
    filters = [
        Document.user_id == user_id,
        Document.status.in_(DONE_STATUSES),
        Document.is_deleted == False,
        or_(
            *(DocumentChunk.cleaned_text.ilike(f"%{term}%") for term in terms),
            *(Document.title.ilike(f"%{term}%") for term in terms),  # 新增：搜索文档标题
            *(Document.original_filename.ilike(f"%{term}%") for term in terms),  # 新增：搜索文件名
        ),
    ]
    if document_id is not None:
        filters.append(DocumentChunk.document_id == document_id)

    chunks = (
        db.query(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(*filters)
        .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(limit * 5)  # 增加到5倍，扩大搜索范围
        .all()
    )

    # 使用文档标题+文件名+内容综合计算相关性分数
    ranked = sorted(
        chunks,
        key=lambda chunk: _relevance_score(
            f"{chunk.document.title} {chunk.document.original_filename} {chunk.cleaned_text}",
            terms
        ),
        reverse=True,
    )[:limit]

    results: list[dict[str, Any]] = []
    for chunk in ranked:
        metadata = _metadata(chunk.metadata_json)
        source = metadata.get("source") or metadata.get("url") or chunk.document.source_url
        # 计算更准确的分数
        relevance = _relevance_score(
            f"{chunk.document.title} {chunk.document.original_filename} {chunk.cleaned_text}",
            terms
        )
        results.append(
            {
                "chunk_id": chunk.id,
                "id": chunk.vector_id or str(chunk.id),
                "document_id": chunk.document_id,
                "document_title": chunk.document.title,
                "filename": chunk.document.original_filename,
                "chunk_index": chunk.chunk_index,
                "chunk_type": chunk.chunk_type,
                "text": chunk.cleaned_text,
                "score": relevance if relevance > 0 else 1.0,
                "metadata": metadata,
                "source": str(source) if source else None,
                "start_index": metadata.get("start_index", chunk.char_start),
                "hash": chunk.document.content_hash or metadata.get("hash"),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            }
        )
    return results


def serialize_chunk_sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "document_chunk",
            "source_id": hit.get("chunk_id"),
            "chunk_id": hit.get("chunk_id"),
            "document_id": hit.get("document_id"),
            "document_title": hit.get("document_title"),
            "filename": hit.get("filename"),
            "chunk_index": hit.get("chunk_index"),
            "chunk_type": hit.get("chunk_type"),
            "score": float(hit.get("score", 0.0) or 0.0),
            "text": hit.get("text", ""),
            "source": hit.get("source"),
            "page_start": hit.get("page_start"),
            "page_end": hit.get("page_end"),
        }
        for hit in hits
    ]


def extraction_sources(db: Session, user_id: int, query: str, limit: int, document_id: int | None) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    filters = [
        Document.user_id == user_id,
        Document.source_type == "pdf",
        Document.is_deleted == False,
        ExtractionJob.status == "done",
        ExtractionJob.is_deleted == False,
        ExtractionResult.is_deleted == False,
    ]
    if document_id is not None:
        filters.append(Document.id == document_id)
    if terms:
        filters.append(
            or_(
                *(ExtractionResult.field_name.ilike(f"%{term}%") for term in terms),
                *(ExtractionResult.content.ilike(f"%{term}%") for term in terms),
                *(ExtractionResult.evidence.ilike(f"%{term}%") for term in terms),
                *(ExtractionJob.query.ilike(f"%{term}%") for term in terms),
                *(Document.title.ilike(f"%{term}%") for term in terms),
            )
        )

    rows = (
        db.query(ExtractionResult, ExtractionJob, Document)
        .join(ExtractionJob, ExtractionResult.job_id == ExtractionJob.id)
        .join(Document, ExtractionJob.paper_id == Document.id)
        .filter(*filters)
        .order_by(ExtractionJob.created_at.desc(), ExtractionResult.id.asc())
        .limit(limit * 3)
        .all()
    )

    ranked = sorted(
        rows,
        key=lambda row: _relevance_score(
            f"{row[2].title} {row[1].query} {row[0].field_name} {row[0].content} {row[0].evidence}",
            terms,
        ),
        reverse=True,
    )[:limit]

    sources: list[dict[str, Any]] = []
    for result, job, document in ranked:
        text = "\n".join(
            item
            for item in [
                f"提取字段：{result.field_name}",
                f"提取内容：{result.content}",
                f"证据：{result.evidence}",
            ]
            if item
        )
        sources.append(
            {
                "source_type": "extraction_result",
                "source_id": result.id,
                "chunk_id": None,
                "document_id": document.id,
                "document_title": document.title,
                "filename": document.original_filename,
                "chunk_index": None,
                "chunk_type": "extraction",
                "score": _relevance_score(text, terms) or 1.0,
                "text": text,
                "source": "extraction_results",
                "page_start": None,
                "page_end": None,
                "extraction_job_id": job.id,
                "field_name": result.field_name,
                "content": result.content,
                "evidence": result.evidence,
                "confidence": result.confidence,
            }
        )
    return sources


def collect_sources(
    db: Session,
    user_id: int,
    question: str,
    limit: int,
    document_id: int | None,
    threshold: float,
    enable_web_search: bool = False,  # 新增：用户控制的网页搜索开关
) -> list[dict[str, Any]]:
    search_service = DocumentSearchService(db)
    hits = search_service.search_chunks(
        user_id=user_id,
        query=question,
        limit=limit,
        document_id=document_id,
        threshold=threshold,
    )
    if not hits:
        hits = _keyword_chunk_sources(db, user_id, question, limit=limit, document_id=document_id)

    local_sources = [
        *serialize_chunk_sources(hits),
        *extraction_sources(db, user_id, question, limit=limit, document_id=document_id),
    ]

    # 网页搜索：仅在用户明确启用时触发
    if enable_web_search and app_config.WEB_SEARCH_ENABLED:
        web_service = WebSearchService(
            api_key=app_config.TAVILY_API_KEY,
            max_results=app_config.WEB_SEARCH_MAX_RESULTS
        )

        # 当用户启用网页搜索时，仍然使用智能判断逻辑
        if web_service.should_search_web(question, local_sources):
            web_results = web_service.search(question)
            web_sources = []

            for idx, result in enumerate(web_results):
                web_sources.append({
                    "source_type": "web_search",
                    "source_id": None,
                    "chunk_id": None,
                    "document_id": None,
                    "document_title": result["title"],
                    "filename": None,
                    "chunk_index": None,
                    "chunk_type": "web",
                    "score": result.get("score", 1.0),
                    "text": result["snippet"],
                    "source": result["url"],
                    "page_start": None,
                    "page_end": None,
                })

            logger.info(f"Added {len(web_sources)} web search results for query: {question}")
            return local_sources + web_sources

    return local_sources


def build_context_text(sources: list[dict[str, Any]]) -> str:
    context_blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        title = source.get("document_title") or source.get("filename") or f"Source {index}"
        source_type = source.get("source_type") or "source"
        text = str(source.get("text") or source.get("evidence") or "").strip()
        if text:
            context_blocks.append(f"[{index}] {source_type} · {title}\n{text}")
    return "\n\n".join(context_blocks) or "No relevant document chunks or extraction evidence were found."


def build_messages(question: str, sources: list[dict[str, Any]], history: list[ChatMessage]) -> list[dict[str, str]]:
    # 检测是否包含网页来源
    has_web_sources = any(s.get("source_type") == "web_search" for s in sources)
    local_source_count = sum(1 for s in sources if s.get("source_type") != "web_search")
    web_source_count = sum(1 for s in sources if s.get("source_type") == "web_search")

    if has_web_sources:
        system_prompt = (
            "你是个人知识库+网页搜索助手。请根据以下资料回答用户问题。\n\n"
            "【核心规则】\n"
            "1. 优先使用个人知识库中的资料（更可信）\n"
            "2. 知识库不足时，参考网页搜索结果作为补充\n"
            "3. 每个事实陈述都必须标注来源编号 [1] [2] 等\n"
            "4. 明确区分来源类型：知识库来源标注为 [知识库-N]，网页来源标注为 [网页-N]\n"
            "5. 不要编造信息，资料不足时明确说明\n"
            "6. 引用原文时加引号，如：[1] 提到\"具体内容\"\n\n"
            f"【本轮资料统计】知识库资料 {local_source_count} 条，网页资料 {web_source_count} 条\n\n"
            "【本轮可引用资料】\n"
            f"{build_context_text(sources)}"
        )
    else:
        system_prompt = (
            "你是个人知识库问答助手。请严格遵守以下规则：\n\n"
            "【核心原则】\n"
            "1. 只根据【本轮可引用资料】回答，绝对不得使用训练数据中的知识\n"
            "2. 每个事实陈述都必须标注来源编号 [1] [2] 等\n"
            "3. 资料不足时，明确说明\"根据现有资料无法完整回答\"\n\n"
            "【回答要求】\n"
            "- 引用原文时加引号，如：[1] 提到\"具体内容\"\n"
            "- 不要推测、不要补充、不要泛化\n"
            "- 不确定的信息要说明\"资料中未明确\"\n"
            "- 多个资料有矛盾时，说明矛盾并分别列出\n\n"
            "【本轮可引用资料】\n"
            f"{build_context_text(sources)}\n\n"
            "记住：宁可说\"不知道\"，也不要编造信息。"
        )

    messages = [{"role": "system", "content": system_prompt}]
    for message in history[-12:]:
        if message.role in {"user", "assistant"} and message.content.strip():
            messages.append({"role": message.role, "content": message.content})
    messages.append({"role": "user", "content": question})
    return messages


def fallback_tokens(question: str, sources: list[dict[str, Any]], reason: str) -> Iterable[str]:
    # Extract key error messages for better user feedback
    if "balance" in reason.lower() or "insufficient" in reason.lower():
        error_hint = "API 账户余额不足，请充值后重试"
    elif "api key" in reason.lower() or "unauthorized" in reason.lower():
        error_hint = "API Key 无效或未授权"
    elif "502" in reason or "503" in reason or "bad gateway" in reason.lower():
        error_hint = "API 服务暂时不可用，请稍后重试"
    elif "timeout" in reason.lower():
        error_hint = "请求超时，请检查网络连接"
    else:
        error_hint = "服务调用失败"

    if sources:
        titles = "、".join(str(source.get("document_title") or source.get("filename") or "未命名资料") for source in sources[:3])
        message = f"⚠️ {error_hint}（{reason}）\n\n已检索到与\"{question}\"相关的资料：{titles}。\n\n请查看下方引用来源，或解决 API 配置问题后重试。"
    else:
        message = f"⚠️ {error_hint}（{reason}）\n\n没有检索到相关资料。请确认文档已解析完成，并检查 API 配置（OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL）。"

    for start in range(0, len(message), 12):
        yield message[start : start + 12]


def _session_or_404(db: Session, session_id: int, user_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
    return session


def _session_title(question: str) -> str:
    title = re.sub(r"\s+", " ", question).strip()
    return title[:80] or "新会话"


def _prepare_session(db: Session, user_id: int, question: str, session_id: int | None) -> tuple[ChatSession, list[ChatMessage]]:
    if session_id is not None:
        session = _session_or_404(db, session_id, user_id)
        history = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
    else:
        session = ChatSession(user_id=user_id, title=_session_title(question))
        db.add(session)
        db.flush()
        history = []

    db.add(ChatMessage(session_id=session.id, role="user", content=question))
    session.updated_at = app_now()
    db.commit()
    db.refresh(session)
    return session, history


def _save_assistant_message(db: Session, session_id: int, answer: str, sources: list[dict[str, Any]]) -> None:
    try:
        session = db.get(ChatSession, session_id)
        if session is None:
            logger.warning("Chat session %s disappeared before assistant message save", session_id)
            return
        assistant = ChatMessage(session_id=session_id, role="assistant", content=answer)
        db.add(assistant)
        db.flush()
        for source in sources:
            db.add(
                ChatMessageSource(
                    message_id=assistant.id,
                    source_type=str(source.get("source_type") or "unknown"),
                    source_id=source.get("source_id"),
                    document_id=source.get("document_id"),
                    payload_json=json.dumps(source, ensure_ascii=False),
                )
            )
        session.updated_at = app_now()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist chat assistant message for session %s", session_id)
        raise


def _source_payload(source: ChatMessageSource) -> dict[str, Any]:
    payload = _metadata(source.payload_json)
    if not payload:
        payload = {
            "source_type": source.source_type,
            "source_id": source.source_id,
            "document_id": source.document_id,
        }
    payload.setdefault("source_type", source.source_type)
    payload.setdefault("source_id", source.source_id)
    payload.setdefault("document_id", source.document_id)
    return payload


def _message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        sources=[_source_payload(source) for source in sorted(message.sources, key=lambda item: item.id)],
    )


def _session_list_item(db: Session, session: ChatSession) -> ChatSessionListItem:
    message_count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session.id).scalar() or 0
    last_message = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .first()
    )
    return ChatSessionListItem(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=int(message_count),
        last_message=last_message.content[:160] if last_message is not None else None,
    )


@router.get("/sessions", response_model=list[ChatSessionListItem])
def list_chat_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ChatSessionListItem]:
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .all()
    )
    return [_session_list_item(db, session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session(session_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ChatSessionDetail:
    session = _session_or_404(db, session_id, current_user.id)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[_message_read(message) for message in messages],
    )


@router.post("/stream")
def stream_chat(
    payload: ChatStreamRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    question = payload.question.strip()
    session, history = _prepare_session(db, current_user.id, question, payload.session_id)
    sources = collect_sources(
        db=db,
        user_id=current_user.id,
        question=question,
        limit=payload.top_k,
        document_id=payload.document_id,
        threshold=payload.threshold,
        enable_web_search=payload.enable_web_search,  # 新增：传递网页搜索开关
    )
    session_payload = {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }
    messages = build_messages(question, sources, history)

    def generate() -> Iterable[str]:
        answer_parts: list[str] = []
        yield sse_event("session", session_payload)
        yield sse_event("sources", sources)
        try:
            emitted = False
            for token in openai_chat_tokens(messages):
                emitted = True
                answer_parts.append(token)
                yield sse_event("token", token)
            if not emitted:
                for token in fallback_tokens(question, sources, "模型没有返回内容"):
                    answer_parts.append(token)
                    yield sse_event("token", token)
        except (httpx.HTTPError, json.JSONDecodeError, RuntimeError, OSError) as exc:
            reason = str(exc) or exc.__class__.__name__
            yield sse_event("error", f"Chat model stream failed: {reason}")
            for token in fallback_tokens(question, sources, reason):
                answer_parts.append(token)
                yield sse_event("token", token)
        except Exception as exc:
            logger.exception("Unexpected chat stream error")
            yield sse_event("error", f"Unexpected chat stream error: {exc}")
        finally:
            answer = "".join(answer_parts).strip()
            if answer:
                try:
                    _save_assistant_message(db, session.id, answer, sources)
                except Exception as exc:
                    yield sse_event("error", f"Failed to save chat message: {exc}")
            yield sse_event("done", "[DONE]")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
