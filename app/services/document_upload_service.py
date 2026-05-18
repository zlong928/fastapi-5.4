from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import MAX_UPLOAD_SIZE_BYTES
from app.models import Document, JobRun, User
from app.schemas.document import DocumentProcessingMode
from app.services.document_processing_modes import validate_processing_mode_compatibility
from app.services.document_service import DocumentService
from app.services.file_storage import FileStorageService
from app.services.obsidian_service import ObsidianService, ObsidianSyncError


EXTENSION_SOURCE_TYPE = {
    "pdf": "pdf",
    "md": "markdown",
    "markdown": "markdown",
    "txt": "txt",
    "text": "txt",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "webp": "image",
}
IMAGE_MIME_BY_EXTENSION = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
GENERIC_DECLARED_CONTENT_TYPES = {
    "application/octet-stream",
    "binary/octet-stream",
}
DECLARED_CONTENT_TYPES_BY_EXTENSION = {
    "pdf": {"application/pdf", "application/x-pdf"},
    "md": {"text/markdown", "text/plain"},
    "markdown": {"text/markdown", "text/plain"},
    "txt": {"text/plain"},
    "text": {"text/plain"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
}
PARSE_ENQUEUE_FAILED_REASON = "解析任务入队失败，请稍后重试"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadFileInfo:
    source_type: str
    extension: str
    title_stem: str
    filename: str
    detected_mime_type: str


@dataclass(frozen=True)
class DocumentUploadResult:
    document: Document
    parse_job: JobRun


class DuplicateUploadError(ValueError):
    """Raised when the current user already owns the same uploaded bytes."""

    def __init__(self, document: Document) -> None:
        self.document = document
        super().__init__("文件已存在")


class DocumentUploadService:
    """Orchestrates document upload without doing parsing work inline."""

    def __init__(
        self,
        db: Session,
        file_storage: FileStorageService | None = None,
        document_service: DocumentService | None = None,
        obsidian_service: ObsidianService | None = None,
    ) -> None:
        self.file_storage = file_storage or FileStorageService()
        self.document_service = document_service or DocumentService(db, self.file_storage)
        self.obsidian_service = obsidian_service or ObsidianService()

    async def upload_one(
        self,
        *,
        file: UploadFile,
        user: User,
        title: str | None = None,
        processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO,
    ) -> DocumentUploadResult:
        content = await file.read()
        file_size = len(content)
        max_size = MAX_UPLOAD_SIZE_BYTES
        if file_size > max_size:
            raise ValueError(f"File is too large. Maximum size is {max_size} bytes.")
        if file_size == 0:
            raise ValueError("File is empty.")

        file_info = self.validate_upload_file(file, content)
        validate_processing_mode_compatibility(processing_mode, file_info.source_type)
        file_hash = hashlib.sha256(content).hexdigest()
        existing_document = self.document_service.get_user_document_by_file_hash(
            user_id=user.id,
            file_hash=file_hash,
        )
        if existing_document is not None:
            raise DuplicateUploadError(existing_document)

        relative_path: str | None = None
        relative_path, stored_filename = self.file_storage.store_file(
            user_id=user.id,
            original_filename=file_info.filename,
            file_content=content,
            file_extension=file_info.extension,
        )

        try:
            document, job = self.document_service.create_document_with_parse_job(
                user_id=user.id,
                title=title or file_info.title_stem,
                original_filename=file_info.filename,
                stored_filename=stored_filename,
                original_file_path=relative_path,
                file_size=file_size,
                file_hash=file_hash,
                mime_type=file_info.detected_mime_type,
                source_type=file_info.source_type,
                processing_mode=processing_mode.value,
            )
        except Exception:
            self.cleanup_stored_upload(relative_path)
            raise

        self.sync_document_to_obsidian(
            document=document,
            content=content,
            filename=file_info.filename,
            mime_type=file_info.detected_mime_type,
        )
        try:
            self.document_service.enqueue_existing_parse_job(document, job)
        except Exception as exc:
            logger.exception("Failed to enqueue parse job for uploaded document %s", document.id)
            document, job = self.document_service.mark_parse_enqueue_failed(
                document.id,
                job.id,
                PARSE_ENQUEUE_FAILED_REASON,
                exc,
            )

        return DocumentUploadResult(document=document, parse_job=job)

    def validate_upload_file(self, file: UploadFile, content: bytes) -> UploadFileInfo:
        if not file.filename:
            raise ValueError("File name is required.")
        normalized_filename = self.file_storage.safe_original_filename(file.filename)
        filename_parts = normalized_filename.rsplit(".", 1)
        if len(filename_parts) != 2:
            raise ValueError("File must have an extension.")

        title_stem, ext = filename_parts
        ext = ext.lower()
        source_type = EXTENSION_SOURCE_TYPE.get(ext)
        if source_type is None:
            raise ValueError("Unsupported file type. Only PDF, Markdown, TXT, PNG, JPG, JPEG, and WebP are allowed.")

        detected_mime_type = self.detect_allowed_mime_type(
            content=content,
            extension=ext,
            source_type=source_type,
        )
        self.validate_declared_content_type(
            declared_content_type=file.content_type,
            detected_mime_type=detected_mime_type,
            extension=ext,
        )

        return UploadFileInfo(
            source_type=source_type,
            extension=ext,
            title_stem=title_stem,
            filename=normalized_filename,
            detected_mime_type=detected_mime_type,
        )

    def detect_allowed_mime_type(self, *, content: bytes, extension: str, source_type: str) -> str:
        if content.startswith(b"MZ"):
            raise ValueError("Executable files are not allowed.")

        detected_magic_mime_type = self.detect_known_magic_mime_type(content)
        expected_magic_mime_type = self.expected_magic_mime_type(extension=extension, source_type=source_type)
        if detected_magic_mime_type is not None and detected_magic_mime_type != expected_magic_mime_type:
            raise ValueError(
                f"File content type {detected_magic_mime_type} does not match .{extension} extension."
            )

        if source_type == "pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF file: content does not match PDF magic bytes.")
            return "application/pdf"

        if source_type in {"txt", "markdown"}:
            self.decode_text_content(content, label=source_type)
            return "text/markdown" if extension in {"md", "markdown"} else "text/plain"

        if source_type == "image":
            return self.detect_image_mime_type(content=content, extension=extension)

        raise ValueError("Unsupported file type. Only PDF, Markdown, TXT, PNG, JPG, JPEG, and WebP are allowed.")

    def expected_magic_mime_type(self, *, extension: str, source_type: str) -> str | None:
        if source_type == "pdf":
            return "application/pdf"
        if source_type == "image":
            return IMAGE_MIME_BY_EXTENSION[extension]
        return None

    def detect_known_magic_mime_type(self, content: bytes) -> str | None:
        if content.startswith(b"%PDF-"):
            return "application/pdf"
        return self.detect_image_magic_bytes(content)

    def validate_declared_content_type(
        self,
        *,
        declared_content_type: str | None,
        detected_mime_type: str,
        extension: str,
    ) -> None:
        if not declared_content_type:
            return
        media_type = declared_content_type.split(";", 1)[0].strip().lower()
        if not media_type or media_type in GENERIC_DECLARED_CONTENT_TYPES:
            return
        allowed_content_types = DECLARED_CONTENT_TYPES_BY_EXTENSION.get(extension, {detected_mime_type})
        if media_type not in allowed_content_types:
            raise ValueError(
                f"Content-Type {media_type} does not match .{extension} file content ({detected_mime_type})."
            )

    def detect_image_mime_type(self, *, content: bytes, extension: str) -> str:
        expected_mime_type = IMAGE_MIME_BY_EXTENSION[extension]
        detected_mime_type = self.detect_image_magic_bytes(content)
        if detected_mime_type != expected_mime_type:
            raise ValueError(
                f"Invalid image file: content type {detected_mime_type or 'unknown'} "
                f"does not match .{extension} magic bytes."
            )
        return detected_mime_type

    def detect_image_magic_bytes(self, content: bytes) -> str | None:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp"
        return None

    def decode_text_content(self, content: bytes, *, label: str) -> str:
        if b"\x00" in content:
            raise ValueError(f"Invalid {label} file: binary content is not allowed.")
        if any(byte < 32 and byte not in {9, 10, 12, 13} for byte in content) or b"\x7f" in content:
            raise ValueError(f"Invalid {label} file: binary content is not allowed.")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            pass

        try:
            import chardet
        except ImportError as exc:
            raise ValueError(f"Invalid {label} file: unable to decode as UTF-8.") from exc

        detected = chardet.detect(content)
        encoding = detected.get("encoding")
        confidence = float(detected.get("confidence") or 0)
        if not encoding or confidence < 0.5:
            raise ValueError(f"Invalid {label} file: text encoding could not be detected.")
        try:
            return content.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(f"Invalid {label} file: detected encoding could not be decoded.") from exc

    def cleanup_stored_upload(self, relative_path: str | None) -> None:
        if not relative_path:
            return
        try:
            self.file_storage.delete_file(relative_path)
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("Failed to clean up stored upload after database failure")

    def sync_document_to_obsidian(
        self,
        *,
        document: Document,
        content: bytes,
        filename: str,
        mime_type: str,
    ) -> None:
        try:
            result = self.obsidian_service.sync_uploaded_file(
                filename=filename,
                content=content,
                title=document.title,
                source_type=document.source_type,
                mime_type=mime_type,
                document_id=document.id,
                file_size=document.file_size,
                uploaded_at=document.uploaded_at,
            )
        except ObsidianSyncError as exc:
            self.document_service.log_event(
                document.id,
                document.user_id,
                "obsidian_sync_failed",
                str(exc),
            )
            return

        if result.status == "skipped":
            self.document_service.log_event(
                document.id,
                document.user_id,
                "obsidian_sync_skipped",
                result.message or "Obsidian sync disabled or API key not configured.",
            )
            return

        metadata = {
            "directory_path": result.directory_path,
            "original_file_path": result.original_file_path,
            "index_path": result.index_path,
        }
        self.document_service.log_event(
            document.id,
            document.user_id,
            "obsidian_synced",
            "文档已同步到 Obsidian",
            metadata=metadata,
        )
