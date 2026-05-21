from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import OLLAMA_BASE_URL
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User
from app.services.document_search_service import DocumentSearchService

router = APIRouter(prefix="/chat", tags=["chat"])

CHAT_MODEL = os.getenv("CHAT_MODEL", os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b"))
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))


class ChatStreamRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(5, ge=1, le=20)
    document_id: int | None = Field(None, ge=1)
    threshold: float = Field(0.0, ge=0.0, le=1.0)


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def current_user_id_from_header(authorization: str | None) -> int:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header.")
    subject = decode_access_token(token.strip())
    if subject is None or not subject.isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    user_id = int(subject)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive user.")
    return user_id


def serialize_sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": hit.get("chunk_id"),
            "document_id": hit.get("document_id"),
            "document_title": hit.get("document_title"),
            "filename": hit.get("filename"),
            "chunk_index": hit.get("chunk_index"),
            "chunk_type": hit.get("chunk_type"),
            "score": hit.get("score", 0.0),
            "text": hit.get("text", ""),
            "source": hit.get("source"),
            "page_start": hit.get("page_start"),
            "page_end": hit.get("page_end"),
        }
        for hit in hits
    ]


def build_prompt(question: str, sources: list[dict[str, Any]]) -> str:
    context_blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        title = source.get("document_title") or source.get("filename") or f"Source {index}"
        text = str(source.get("text") or "").strip()
        if text:
            context_blocks.append(f"[{index}] {title}\n{text}")
    context = "\n\n".join(context_blocks) or "No relevant document chunks were found."
    return (
        "你是个人知识库问答助手。请只根据给定资料回答；资料不足时要说明不足，不要编造。\n\n"
        f"资料：\n{context}\n\n问题：{question}\n\n回答："
    )


def ollama_tokens(prompt: str) -> Iterable[str]:
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        data=json.dumps({"model": CHAT_MODEL, "prompt": prompt, "stream": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=CHAT_TIMEOUT_SECONDS) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            payload = json.loads(raw_line.decode("utf-8"))
            token = payload.get("response")
            if token:
                yield str(token)
            if payload.get("done"):
                break


def fallback_tokens(question: str, sources: list[dict[str, Any]], reason: str) -> Iterable[str]:
    if sources:
        titles = "、".join(str(source.get("document_title") or source.get("filename") or "未命名资料") for source in sources[:3])
        message = f"暂时无法调用本地聊天模型（{reason}）。已检索到与“{question}”相关的资料：{titles}。请查看下方引用来源，或启动 Ollama 模型后重试。"
    else:
        message = f"暂时无法调用本地聊天模型（{reason}），并且没有检索到可引用的资料片段。请先确认文档已解析完成并启动 Ollama。"
    for start in range(0, len(message), 12):
        yield message[start : start + 12]


@router.post("/stream")
def stream_chat(payload: ChatStreamRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
    user_id = current_user_id_from_header(authorization)
    question = payload.question.strip()

    with SessionLocal() as db:
        search_service = DocumentSearchService(db)
        hits = search_service.search_chunks(
            user_id=user_id,
            query=question,
            limit=payload.top_k,
            document_id=payload.document_id,
            threshold=payload.threshold,
        )
        sources = serialize_sources(hits)

    def generate() -> Iterable[str]:
        yield sse_event("sources", sources)
        prompt = build_prompt(question, sources)
        try:
            emitted = False
            for token in ollama_tokens(prompt):
                emitted = True
                yield sse_event("token", token)
            if not emitted:
                for token in fallback_tokens(question, sources, "模型没有返回内容"):
                    yield sse_event("token", token)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            reason = str(exc) or exc.__class__.__name__
            yield sse_event("error", f"Chat model stream failed: {reason}")
            for token in fallback_tokens(question, sources, reason):
                yield sse_event("token", token)
        except Exception as exc:
            yield sse_event("error", f"Unexpected chat stream error: {exc}")
        finally:
            yield sse_event("done", "[DONE]")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
