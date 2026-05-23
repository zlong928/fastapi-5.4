from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, DocumentChunk, DocumentEvent, DocumentTag, Tag
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_service import STATUS_DONE, STATUS_FAILED

MAX_BOOKMARK_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
REQUEST_TIMEOUT = 8.0
BOOKMARK_USER_AGENT = "SecondBrainBookmarkFetcher/1.0"
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain")
DOCKER_DESKTOP_PROXY_NET = ipaddress.ip_network("198.18.0.0/15")


class BookmarkError(ValueError):
    pass


@dataclass(slots=True)
class FetchedBookmark:
    final_url: str
    title: str | None
    description: str | None
    text: str
    site_name: str
    content_type: str


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.description: str | None = None
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attr_map = {key.lower(): value for key, value in attrs if key and value}
            if attr_map.get("name", "").lower() == "description" and attr_map.get("content"):
                self.description = attr_map["content"].strip()
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self.title_parts.append(stripped)
        self.text_parts.append(stripped)
        self.text_parts.append(" ")

    @property
    def title(self) -> str | None:
        title = clean_text(" ".join(self.title_parts))
        return title or None

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.text_parts))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _validate_url_shape(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise BookmarkError("仅支持 http/https")
    if not parsed.hostname:
        raise BookmarkError("URL 无效")
    return url


def _resolve_public_host(hostname: str) -> None:
    host = hostname.strip().lower().rstrip(".")
    if host in {"localhost", "0.0.0.0"}:
        raise BookmarkError("不允许访问本机地址")
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None
    if ip_obj is not None:
        _assert_public_ip(ip_obj)
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BookmarkError("域名无法解析") from exc
    if not infos:
        raise BookmarkError("域名无法解析")
    for info in infos:
        ip_text = info[4][0]
        _assert_public_ip(ipaddress.ip_address(ip_text), allow_docker_desktop_proxy=True)


def _assert_public_ip(ip_obj: ipaddress._BaseAddress, *, allow_docker_desktop_proxy: bool = False) -> None:
    if allow_docker_desktop_proxy and isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in DOCKER_DESKTOP_PROXY_NET:
        return
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    ):
        raise BookmarkError("不允许访问内网地址")
    if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in ipaddress.ip_network("100.64.0.0/10"):
        raise BookmarkError("不允许访问保留地址")


def validate_public_url(raw_url: str) -> str:
    url = _validate_url_shape(raw_url)
    parsed = urlparse(url)
    _resolve_public_host(parsed.hostname or "")
    return url


async def fetch_bookmark(url: str) -> FetchedBookmark:
    current_url = validate_public_url(url)
    headers = {"User-Agent": BOOKMARK_USER_AGENT, "Accept": "text/html,text/plain;q=0.9"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False, headers=headers) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            response = await client.get(current_url)
            if response.is_redirect:
                if redirect_count >= MAX_REDIRECTS:
                    raise BookmarkError("重定向过多")
                location = response.headers.get("location")
                if not location:
                    raise BookmarkError("重定向无效")
                current_url = validate_public_url(urljoin(current_url, location))
                continue

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code >= 400:
                raise BookmarkError(f"网页返回 {response.status_code}")
            if content_type and not any(content_type.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES):
                raise BookmarkError("仅支持文本网页")

            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BOOKMARK_BYTES:
                    raise BookmarkError("网页过大")

            text = bytes(content).decode(response.encoding or "utf-8", errors="ignore")
            parsed = urlparse(str(response.url))
            site_name = parsed.netloc
            if content_type.startswith("text/plain"):
                cleaned = clean_text(text)
                if not cleaned:
                    raise BookmarkError("网页正文为空")
                return FetchedBookmark(str(response.url), None, None, cleaned, site_name, content_type)

            parser = _ReadableHTMLParser()
            parser.feed(text)
            cleaned = parser.text
            if not cleaned:
                raise BookmarkError("网页正文为空")
            return FetchedBookmark(str(response.url), parser.title, parser.description, cleaned, site_name, content_type or "text/html")

    raise BookmarkError("抓取失败")


def split_text(text: str, *, chunk_size: int = 1200, overlap: int = 120) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(cleaned[start:end])
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks


class BookmarkService:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def create_bookmark(
        self,
        *,
        user_id: int,
        url: str,
        title: str | None = None,
        tag_ids: list[int] | None = None,
        collection_name: str | None = None,
        processing_mode: str = "auto",
    ) -> Document:
        validated_url = validate_public_url(url)
        parsed = urlparse(validated_url)
        domain = parsed.netloc
        content_hash = hashlib.sha256(validated_url.encode("utf-8")).hexdigest()
        document = Document(
            user_id=user_id,
            title=(title or domain or validated_url)[:255],
            original_filename=domain or validated_url[:255],
            stored_filename=content_hash[:32],
            original_file_path=f"bookmark:{validated_url}",
            file_size=0,
            file_hash=None,
            mime_type="text/html",
            source_type="bookmark",
            source_url=validated_url,
            site_name=domain,
            processing_mode=processing_mode,
            processing_strategy="bookmark_fetch",
            collection_name=collection_name,
            status="processing",
        )
        self.db.add(document)
        self.db.flush()
        self._log(document, user_id, "bookmark_created", "链接已保存", {"url": validated_url})
        self._assign_tags(document, user_id, tag_ids or [])
        self.db.commit()
        self.db.refresh(document)

        try:
            self._log(document, user_id, "fetch_started", "开始抓取", commit=True)
            fetched = await fetch_bookmark(validated_url)
            final_url = fetched.final_url
            document.source_url = final_url
            document.site_name = fetched.site_name
            document.original_filename = fetched.site_name or document.original_filename
            document.mime_type = fetched.content_type
            document.title = (title or fetched.title or fetched.site_name or validated_url)[:255]
            document.parsed_text = fetched.text
            document.cleaned_text = fetched.text
            document.content_summary = (fetched.description or fetched.text[:240]).strip()
            document.content_hash = hashlib.sha256(fetched.text.encode("utf-8")).hexdigest()
            document.file_size = len(fetched.text.encode("utf-8"))
            document.status = STATUS_DONE
            document.error_message = None
            document.fail_reason = None
            document.parsed_at = app_now()
            self.db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
            chunks = split_text(fetched.text)
            for index, chunk_text in enumerate(chunks):
                self.db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        chunk_type="web",
                        text=chunk_text,
                        cleaned_text=chunk_text,
                        char_start=None,
                        char_end=None,
                        token_count=None,
                        metadata_json=json.dumps(
                            {
                                "source": final_url,
                                "url": final_url,
                                "domain": fetched.site_name,
                                "site_name": fetched.site_name,
                                "title": document.title,
                                "source_type": "bookmark",
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            document.chunk_count = len(chunks)
            self._log(document, user_id, "fetch_succeeded", "抓取完成", {"chunks": len(chunks)}, commit=False)
            self.db.commit()
            self.db.refresh(document)
            try:
                DocumentEmbeddingService().embed_document(document.id)
                self._log(document, user_id, "embedding_succeeded", "Embedding 完成", commit=True)
            except Exception as exc:  # noqa: BLE001 - embedding should not break saved bookmark
                self.db.rollback()
                self._log(document, user_id, "embedding_failed", "Embedding 失败", {"error": str(exc)}, commit=True)
            return document
        except BookmarkError as exc:
            self.db.rollback()
            document = self.db.get(Document, document.id)
            if document is None:
                raise
            document.status = STATUS_FAILED
            document.error_message = str(exc)
            document.fail_reason = str(exc)
            self._log(document, user_id, "fetch_failed", str(exc), commit=False)
            self.db.commit()
            self.db.refresh(document)
            return document
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            document = self.db.get(Document, document.id)
            if document is None:
                raise
            document.status = STATUS_FAILED
            document.error_message = "抓取失败"
            document.fail_reason = "抓取失败"
            self._log(document, user_id, "fetch_failed", "抓取失败", {"error": str(exc)}, commit=False)
            self.db.commit()
            self.db.refresh(document)
            return document

    def _assign_tags(self, document: Document, user_id: int, tag_ids: list[int]) -> None:
        if not tag_ids:
            return
        tags = self.db.query(Tag).filter(Tag.id.in_(tag_ids), Tag.user_id == user_id).all()
        for tag in tags:
            self.db.add(DocumentTag(document_id=document.id, tag_id=tag.id))

    def _log(
        self,
        document: Document,
        user_id: int,
        event_type: str,
        message: str,
        metadata: dict | None = None,
        *,
        commit: bool = False,
    ) -> None:
        self.db.add(
            DocumentEvent(
                document_id=document.id,
                user_id=user_id,
                event_type=event_type,
                message=message,
                event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
            )
        )
        if commit:
            self.db.commit()
