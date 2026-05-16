from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from app.core import config


class ObsidianSyncError(RuntimeError):
    """Raised when the Obsidian Local REST API rejects a sync request."""


@dataclass(frozen=True)
class ObsidianSyncResult:
    status: str
    directory_path: str | None = None
    original_file_path: str | None = None
    index_path: str | None = None
    message: str | None = None


class ObsidianService:
    """Small client for the Obsidian Local REST API."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        target_dir: str | None = None,
        sync_enabled: bool | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        self.api_url = (api_url or config.OBSIDIAN_API_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.OBSIDIAN_API_KEY
        self.target_dir = target_dir if target_dir is not None else config.OBSIDIAN_TARGET_DIR
        self.sync_enabled = sync_enabled if sync_enabled is not None else config.OBSIDIAN_SYNC_ENABLED
        self.verify_ssl = verify_ssl if verify_ssl is not None else config.OBSIDIAN_VERIFY_SSL

    @property
    def is_configured(self) -> bool:
        return bool(self.sync_enabled and self.api_url and self.api_key)

    def sync_uploaded_file(
        self,
        *,
        filename: str,
        content: bytes,
        title: str,
        source_type: str,
        mime_type: str,
        document_id: int,
        file_size: int,
        uploaded_at: datetime,
    ) -> ObsidianSyncResult:
        if not self.is_configured:
            return ObsidianSyncResult(status="skipped", message="Obsidian sync disabled or API key not configured.")

        paths = self._document_paths(document_id=document_id, title=title, filename=filename, uploaded_at=uploaded_at)
        self._put_vault_file(
            paths.original_file_path,
            content,
            content_type=mime_type or "application/octet-stream",
        )
        index = self._build_index_note(
            title=title,
            document_id=document_id,
            source_type=source_type,
            mime_type=mime_type,
            file_size=file_size,
            uploaded_at=uploaded_at,
            original_file_path=PurePosixPath(paths.original_file_path).relative_to(paths.directory_path).as_posix(),
        )
        self._put_vault_file(paths.index_path, index.encode("utf-8"), content_type="text/markdown; charset=utf-8")

        return ObsidianSyncResult(
            status="synced",
            directory_path=paths.directory_path,
            original_file_path=paths.original_file_path,
            index_path=paths.index_path,
        )

    def health(self) -> dict:
        if not self.is_configured:
            return {
                "enabled": bool(self.sync_enabled),
                "configured": False,
                "available": False,
                "target_dir": self._target_dir_path(),
                "message": "Obsidian sync disabled or API key not configured.",
            }

        try:
            response = httpx.get(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return {
                "enabled": True,
                "configured": True,
                "available": False,
                "target_dir": self._target_dir_path(),
                "message": str(exc),
            }

        return {
            "enabled": True,
            "configured": True,
            "available": True,
            "target_dir": self._target_dir_path(),
            "message": "Obsidian Local REST API is reachable.",
        }

    def _put_vault_file(self, vault_path: str, content: bytes, *, content_type: str) -> None:
        encoded_path = quote(vault_path, safe="/")
        url = f"{self.api_url}/vault/{encoded_path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
        }
        try:
            response = httpx.put(url, headers=headers, content=content, timeout=20.0, verify=self.verify_ssl)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ObsidianSyncError(f"Failed to sync {vault_path} to Obsidian: {exc}") from exc

    def _document_paths(self, *, document_id: int, title: str, filename: str, uploaded_at: datetime) -> ObsidianSyncResult:
        safe_title = self._safe_segment(title) or "untitled"
        safe_filename = self._safe_path_part(filename) or "uploaded-file"
        uploaded_at = uploaded_at if uploaded_at.tzinfo else uploaded_at.replace(tzinfo=timezone.utc)
        clean_dir_parts = [
            self._safe_path_part(part)
            for part in PurePosixPath(self.target_dir.replace("\\", "/")).parts
            if part not in ("", ".", "/", "..")
        ]
        base_dir = PurePosixPath(*[part for part in clean_dir_parts if part])
        directory = base_dir / f"{uploaded_at.year:04d}" / f"{uploaded_at.month:02d}" / f"{document_id}-{safe_title}"
        original = directory / "original" / safe_filename
        index = directory / "index.md"
        return ObsidianSyncResult(
            status="synced",
            directory_path=directory.as_posix(),
            original_file_path=original.as_posix(),
            index_path=index.as_posix(),
        )

    def _target_dir_path(self) -> str:
        clean_dir_parts = [
            self._safe_path_part(part)
            for part in PurePosixPath(self.target_dir.replace("\\", "/")).parts
            if part not in ("", ".", "/", "..")
        ]
        return PurePosixPath(*[part for part in clean_dir_parts if part]).as_posix() or "Uploads"

    def _build_index_note(
        self,
        *,
        title: str,
        document_id: int,
        source_type: str,
        mime_type: str,
        file_size: int,
        uploaded_at: datetime,
        original_file_path: str,
    ) -> str:
        display_title = title.strip() or PurePosixPath(original_file_path).stem
        uploaded_at = uploaded_at if uploaded_at.tzinfo else uploaded_at.replace(tzinfo=timezone.utc)
        original_link = self._obsidian_link(original_file_path)
        return (
            "---\n"
            f"title: {self._yaml_string(display_title)}\n"
            f"document_id: {self._yaml_string(str(document_id))}\n"
            f"source_type: {self._yaml_string(source_type)}\n"
            f"mime_type: {self._yaml_string(mime_type)}\n"
            f"file_size: {file_size}\n"
            f"uploaded_at: {self._yaml_string(uploaded_at.isoformat())}\n"
            f"original_file: {self._yaml_string(original_file_path)}\n"
            "---\n\n"
            f"# {display_title}\n\n"
            "## Original File\n\n"
            f"{original_link}\n\n"
            "## Status\n\n"
            "- Uploaded to FastAPI.\n"
            "- Synced to Obsidian.\n"
            "- Parsing job queued.\n\n"
            "## Summary\n\n"
            "<!-- AUTO:SUMMARY:START -->\n"
            "待处理。\n"
            "<!-- AUTO:SUMMARY:END -->\n\n"
            "## Parsed Text\n\n"
            "<!-- AUTO:PARSED_TEXT:START -->\n"
            "待处理。\n"
            "<!-- AUTO:PARSED_TEXT:END -->\n\n"
            "## Knowledge Graph\n\n"
            "<!-- AUTO:KNOWLEDGE_GRAPH:START -->\n"
            "待处理。\n"
            "<!-- AUTO:KNOWLEDGE_GRAPH:END -->\n\n"
            "## Events\n\n"
            "<!-- AUTO:EVENTS:START -->\n"
            "待处理。\n"
            "<!-- AUTO:EVENTS:END -->\n\n"
            "## Human Notes\n\n"
            "这里可以手动补充笔记。\n"
        )

    def _obsidian_link(self, path: str) -> str:
        lower = path.lower()
        prefix = "!" if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")) else ""
        return f"{prefix}[[{path}]]"

    def _safe_path_part(self, value: str) -> str:
        part = value.replace("\\", "/")
        part = PurePosixPath(part).name.strip()
        return self._clean_segment(part)

    def _safe_segment(self, value: str) -> str:
        return self._clean_segment(value.replace("/", "-").replace("\\", "-"))

    def _clean_segment(self, value: str) -> str:
        part = value.strip()
        part = re.sub(r"[\x00-\x1f<>:\"|?*]", "-", part)
        part = re.sub(r"\s+", " ", part)
        return part.strip(". -")

    def _yaml_string(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
