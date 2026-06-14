from __future__ import annotations

import io
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import (
    MINERU_API_BASE_URL,
    MINERU_API_KEY,
    MINERU_LANGUAGE,
    MINERU_MODEL_VERSION,
    MINERU_POLL_INTERVAL_SECONDS,
    MINERU_RESULT_RATE_LIMIT_PER_MINUTE,
    MINERU_SUBMIT_RATE_LIMIT_PER_MINUTE,
    MINERU_TIMEOUT_SECONDS,
)
from app.services.document_parser import ParsedDocument, ParsedElement, ParsedPage


class MinerUParserError(RuntimeError):
    pass


class MinerUParserUnavailable(MinerUParserError):
    pass


class MinuteRateLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, amount: int = 1) -> None:
        if self.limit <= 0:
            return
        if amount > self.limit:
            raise MinerUParserError(f"Rate limit amount {amount} exceeds per-minute limit {self.limit}.")
        while True:
            with self._lock:
                now = time.monotonic()
                self._discard_expired(now)
                if len(self._events) + amount <= self.limit:
                    self._events.extend([now] * amount)
                    return
                sleep_for = max(0.0, self.window_seconds - (now - self._events[0]))
            time.sleep(sleep_for)

    def _discard_expired(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_seconds:
            self._events.popleft()


_submit_rate_limiter = MinuteRateLimiter(limit=MINERU_SUBMIT_RATE_LIMIT_PER_MINUTE)
_result_rate_limiter = MinuteRateLimiter(limit=MINERU_RESULT_RATE_LIMIT_PER_MINUTE)


@dataclass(slots=True)
class MinerUParseResult:
    parsed_document: ParsedDocument
    batch_id: str
    file_name: str
    full_zip_url: str
    markdown_file: str
    artifact_dir: str | None = None
    zip_path: str | None = None
    extract_dir: str | None = None
    content_list_path: str | None = None
    layout_path: str | None = None
    extracted_files: list[str] = field(default_factory=list)


class MinerUParserService:
    """Client for MinerU's token-based local file parsing API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = MINERU_API_BASE_URL,
        model_version: str = MINERU_MODEL_VERSION,
        language: str = MINERU_LANGUAGE,
        timeout_seconds: int = MINERU_TIMEOUT_SECONDS,
        poll_interval_seconds: float = MINERU_POLL_INTERVAL_SECONDS,
        client: httpx.Client | None = None,
        submit_rate_limiter: MinuteRateLimiter = _submit_rate_limiter,
        result_rate_limiter: MinuteRateLimiter = _result_rate_limiter,
    ) -> None:
        self.api_key = (api_key if api_key is not None else MINERU_API_KEY).strip()
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.client = client
        self.submit_rate_limiter = submit_rate_limiter
        self.result_rate_limiter = result_rate_limiter

    def parse_pdf_file(
        self,
        file_path: str | Path,
        *,
        data_id: str | None = None,
        is_ocr: bool = False,
        enable_formula: bool = True,
        enable_table: bool = True,
        output_root: str | Path | None = None,
    ) -> MinerUParseResult:
        if not self.api_key:
            raise MinerUParserUnavailable("MINERU_API_KEY is not configured.")

        path = Path(file_path)
        if not path.is_file():
            raise MinerUParserError(f"File not found: {path}")

        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=60)
        try:
            batch_id, upload_url = self._request_upload_url(
                client,
                file_name=path.name,
                data_id=data_id,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                enable_table=enable_table,
            )
            self._upload_file(client, upload_url, path)
            result = self._wait_for_result(client, batch_id, path.name)
            archive_bytes = self._download_result_zip(client, result["full_zip_url"])
            artifact_paths = self._save_result_artifacts(archive_bytes, output_root, batch_id) if output_root is not None else {}
            markdown, markdown_name = self._markdown_from_zip(archive_bytes)
            parsed_document = self._markdown_to_parsed_document(
                markdown,
                source_url=result["full_zip_url"],
                batch_id=batch_id,
                file_name=result.get("file_name") or path.name,
                markdown_file=markdown_name,
            )
            return MinerUParseResult(
                parsed_document=parsed_document,
                batch_id=batch_id,
                file_name=result.get("file_name") or path.name,
                full_zip_url=result["full_zip_url"],
                markdown_file=markdown_name,
                artifact_dir=artifact_paths.get("artifact_dir"),
                zip_path=artifact_paths.get("zip_path"),
                extract_dir=artifact_paths.get("extract_dir"),
                content_list_path=artifact_paths.get("content_list_path"),
                layout_path=artifact_paths.get("layout_path"),
                extracted_files=list(artifact_paths.get("extracted_files") or []),
            )
        finally:
            if owns_client:
                client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def _request_upload_url(
        self,
        client: httpx.Client,
        *,
        file_name: str,
        data_id: str | None,
        is_ocr: bool,
        enable_formula: bool,
        enable_table: bool,
    ) -> tuple[str, str]:
        file_payload = {"name": file_name, "is_ocr": is_ocr}
        if data_id:
            file_payload["data_id"] = data_id
        payload = {
            "files": [file_payload],
            "model_version": self.model_version,
            "language": self.language,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
        }
        self.submit_rate_limiter.acquire(amount=1)
        response = client.post(f"{self.base_url}/api/v4/file-urls/batch", headers=self._headers(), json=payload)
        data = self._json_response(response)
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise MinerUParserError("MinerU did not return a batch_id and upload URL.")
        return str(batch_id), str(file_urls[0])

    def _upload_file(self, client: httpx.Client, upload_url: str, path: Path) -> None:
        with path.open("rb") as file_obj:
            response = client.put(upload_url, content=file_obj)
        if response.status_code != 200:
            raise MinerUParserError(f"MinerU upload failed with HTTP {response.status_code}.")

    def _wait_for_result(self, client: httpx.Client, batch_id: str, file_name: str) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        last_state = "unknown"
        while time.monotonic() <= deadline:
            self.result_rate_limiter.acquire(amount=1)
            response = client.get(f"{self.base_url}/api/v4/extract-results/batch/{batch_id}", headers=self._headers())
            data = self._json_response(response)
            for item in data.get("extract_result") or []:
                if item.get("file_name") not in {file_name, None} and len(data.get("extract_result") or []) > 1:
                    continue
                state = str(item.get("state") or "")
                last_state = state or last_state
                if state == "done":
                    full_zip_url = item.get("full_zip_url")
                    if not full_zip_url:
                        raise MinerUParserError("MinerU task completed without full_zip_url.")
                    return item
                if state == "failed":
                    raise MinerUParserError(str(item.get("err_msg") or "MinerU parsing failed."))
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"MinerU parsing timed out while task state was {last_state}.")

    def _download_result_zip(self, client: httpx.Client, full_zip_url: str) -> bytes:
        response = client.get(full_zip_url)
        if response.status_code != 200:
            raise MinerUParserError(f"MinerU result download failed with HTTP {response.status_code}.")
        return response.content

    def _markdown_from_zip(self, archive_bytes: bytes) -> tuple[str, str]:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            markdown_names = [
                name for name in archive.namelist()
                if name.lower().endswith(".md") and not name.endswith("/")
            ]
            if not markdown_names:
                raise MinerUParserError("MinerU result zip did not contain a Markdown file.")
            markdown_name = self._choose_markdown_file(markdown_names)
            markdown = archive.read(markdown_name).decode("utf-8", errors="replace").strip()
        if not markdown:
            raise MinerUParserError("MinerU Markdown result is empty.")
        return markdown, markdown_name

    def _save_result_artifacts(self, archive_bytes: bytes, output_root: str | Path, batch_id: str) -> dict[str, str | list[str]]:
        artifact_dir = Path(output_root) / batch_id
        extract_dir = artifact_dir / "extracted"
        zip_path = artifact_dir / "result.zip"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(archive_bytes)

        extracted_files: list[str] = []
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                destination = extract_dir / name
                try:
                    destination.resolve().relative_to(extract_dir.resolve())
                except ValueError:
                    raise MinerUParserError(f"Unsafe path in MinerU result zip: {name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
                extracted_files.append(str(destination.resolve()))

        content_list_path = self._first_existing(
            extract_dir,
            suffixes=("_content_list.json", "content_list.json"),
            exclude=("_content_list_v2.json",),
        )
        layout_path = self._first_existing(extract_dir, suffixes=("layout.json",))
        return {
            "artifact_dir": str(artifact_dir.resolve()),
            "zip_path": str(zip_path.resolve()),
            "extract_dir": str(extract_dir.resolve()),
            "content_list_path": str(content_list_path.resolve()) if content_list_path else "",
            "layout_path": str(layout_path.resolve()) if layout_path else "",
            "extracted_files": extracted_files,
        }

    def _first_existing(self, root: Path, *, suffixes: tuple[str, ...], exclude: tuple[str, ...] = ()) -> Path | None:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            name = path.name.lower()
            if exclude and any(name.endswith(item.lower()) for item in exclude):
                continue
            if any(name.endswith(item.lower()) for item in suffixes):
                return path
        return None

    def _json_response(self, response: httpx.Response) -> dict:
        if response.status_code != 200:
            raise MinerUParserError(f"MinerU API returned HTTP {response.status_code}.")
        payload = response.json()
        if payload.get("code") != 0:
            raise MinerUParserError(str(payload.get("msg") or payload.get("code") or "MinerU API error."))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MinerUParserError("MinerU API returned invalid data.")
        return data

    def _choose_markdown_file(self, names: list[str]) -> str:
        for preferred in ("full.md", "auto/full.md"):
            for name in names:
                if name.lower().endswith(preferred):
                    return name
        return sorted(names, key=lambda item: (item.count("/"), len(item), item))[0]

    def _markdown_to_parsed_document(
        self,
        markdown: str,
        *,
        source_url: str,
        batch_id: str,
        file_name: str,
        markdown_file: str,
    ) -> ParsedDocument:
        metadata = {
            "source_type": "pdf",
            "parser_engine": "mineru",
            "mineru_batch_id": batch_id,
            "mineru_file_name": file_name,
            "mineru_markdown_file": markdown_file,
            "mineru_full_zip_url": source_url,
        }
        return ParsedDocument(
            pages=[
                ParsedPage(
                    page_number=1,
                    profile=None,
                    elements=[
                        ParsedElement(
                            element_type="paragraph",
                            text=markdown,
                            page_number=None,
                            extractor="mineru",
                            metadata=metadata,
                        )
                    ],
                )
            ],
            source_type="pdf",
            parser_version="mineru_api_v4",
            parser_engine="mineru",
            pymupdf_available=True,
            table_extraction_enabled=True,
            table_extraction_reason=None,
        )
