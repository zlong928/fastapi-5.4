from __future__ import annotations

from dataclasses import dataclass

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
DEFAULT_MAX_DOCUMENT_UPLOAD_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class UploadFileInfo:
    source_type: str
    extension: str
    title_stem: str
    filename: str


@dataclass(frozen=True)
class DocumentUploadResult:
    document: Document
    parse_job: JobRun


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
        file_info = self.validate_upload_file(file)
        validate_processing_mode_compatibility(processing_mode, file_info.source_type)
        mime_type = file.content_type or "application/octet-stream"

        content = await file.read()
        file_size = len(content)
        max_size = MAX_UPLOAD_SIZE_BYTES or DEFAULT_MAX_DOCUMENT_UPLOAD_BYTES
        if file_size > max_size:
            raise ValueError(f"File is too large. Maximum size is {max_size} bytes.")

        relative_path, stored_filename = self.file_storage.store_file(
            user_id=user.id,
            original_filename=file_info.filename,
            file_content=content,
            file_extension=file_info.extension,
        )

        document, job = self.document_service.create_document_with_parse_job(
            user_id=user.id,
            title=title or file_info.title_stem,
            original_filename=file_info.filename,
            stored_filename=stored_filename,
            original_file_path=relative_path,
            file_size=file_size,
            mime_type=mime_type,
            source_type=file_info.source_type,
            processing_mode=processing_mode.value,
        )

        self.sync_document_to_obsidian(
            document=document,
            content=content,
            filename=file_info.filename,
            mime_type=mime_type,
        )
        self.document_service.enqueue_existing_parse_job(document, job)

        return DocumentUploadResult(document=document, parse_job=job)

    def validate_upload_file(self, file: UploadFile) -> UploadFileInfo:
        if not file.filename:
            raise ValueError("File name is required.")
        filename_parts = file.filename.rsplit(".", 1)
        if len(filename_parts) != 2:
            raise ValueError("File must have an extension.")

        title_stem, ext = filename_parts
        ext = ext.lower()
        source_type = EXTENSION_SOURCE_TYPE.get(ext)
        if source_type is None:
            raise ValueError("Unsupported file type. Only PDF, Markdown, TXT, PNG, JPG, JPEG, and WEBP are allowed.")

        return UploadFileInfo(
            source_type=source_type,
            extension=ext,
            title_stem=title_stem,
            filename=file.filename,
        )

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
