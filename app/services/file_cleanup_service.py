from __future__ import annotations

from datetime import timedelta
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, DocumentAsset, FileCleanupJob
from app.models.file_cleanup_job import (
    FILE_CLEANUP_STATUS_DONE,
    FILE_CLEANUP_STATUS_FAILED,
    FILE_CLEANUP_STATUS_PENDING,
    FILE_CLEANUP_STATUS_PROCESSING,
)
from app.services.file_storage import FileStorageService

logger = logging.getLogger(__name__)


class FileCleanupService:
    def __init__(
        self,
        db: Session,
        file_storage: FileStorageService | None = None,
        *,
        retry_delay_seconds: int = 300,
    ) -> None:
        self.db = db
        self.file_storage = file_storage or FileStorageService()
        self.retry_delay_seconds = retry_delay_seconds

    def run_once(self, *, limit: int = 100) -> int:
        jobs = self._next_jobs(limit=limit)
        processed = 0
        for job in jobs:
            self._process_job(job)
            processed += 1
        return processed

    def _next_jobs(self, *, limit: int) -> list[FileCleanupJob]:
        now = app_now()
        due = or_(FileCleanupJob.next_run_at.is_(None), FileCleanupJob.next_run_at <= now)
        retryable_failed = (
            (FileCleanupJob.status == FILE_CLEANUP_STATUS_FAILED)
            & (FileCleanupJob.attempts < FileCleanupJob.max_attempts)
        )
        return (
            self.db.query(FileCleanupJob)
            .filter(due)
            .filter(or_(FileCleanupJob.status == FILE_CLEANUP_STATUS_PENDING, retryable_failed))
            .order_by(FileCleanupJob.created_at.asc(), FileCleanupJob.id.asc())
            .limit(limit)
            .all()
        )

    def _process_job(self, job: FileCleanupJob) -> None:
        job.status = FILE_CLEANUP_STATUS_PROCESSING
        try:
            self._safe_delete(job.file_path)
        except Exception as exc:
            self.db.rollback()
            self.db.refresh(job)
            self._mark_failed(job, exc)
            return

        job.status = FILE_CLEANUP_STATUS_DONE
        job.last_error = None
        self.db.commit()

    def _safe_delete(self, relative_path: str) -> None:
        self.file_storage.get_file_path(relative_path)
        if self._path_is_still_referenced(relative_path):
            logger.info("Skipping cleanup for file still referenced by another database row: %s", relative_path)
            return
        try:
            self.file_storage.delete_file(relative_path)
        except FileNotFoundError:
            logger.debug("File already removed: %s", relative_path)
        self._remove_empty_parent_dirs(relative_path)

    def _path_is_still_referenced(self, relative_path: str) -> bool:
        return (
            self.db.query(Document.id).filter(Document.original_file_path == relative_path).first() is not None
            or self.db.query(DocumentAsset.id).filter(DocumentAsset.file_path == relative_path).first() is not None
        )

    def _mark_failed(self, job: FileCleanupJob, exc: Exception) -> None:
        job.attempts += 1
        job.last_error = f"{type(exc).__name__}: {exc}"
        if job.attempts >= job.max_attempts:
            job.status = FILE_CLEANUP_STATUS_FAILED
        else:
            job.status = FILE_CLEANUP_STATUS_PENDING
        job.next_run_at = app_now() + timedelta(seconds=self.retry_delay_seconds)
        logger.warning(
            "File cleanup failed for job_id=%s path=%s attempts=%s/%s: %s",
            job.id,
            job.file_path,
            job.attempts,
            job.max_attempts,
            exc,
        )
        self.db.commit()

    def _remove_empty_parent_dirs(self, relative_path: str) -> None:
        parent = self.file_storage.get_file_path(relative_path).parent
        upload_root = self.file_storage.upload_dir.resolve()
        while parent.resolve() != upload_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
