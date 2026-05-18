from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.constants.jobs import (
    ACTIVE_JOB_STATUSES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from app.models import Document, JobRun
from app.utils.json import json_dumps_or_none, merge_json_object


@dataclass(slots=True)
class JobRunHealthCounts:
    queued_jobs: int
    running_jobs: int
    visible_jobs: int
    jobs_total: int
    failed_jobs: int


class JobRunService:
    def __init__(self, db: Session):
        self.db = db

    def create_job(
        self,
        *,
        user_id: int,
        kind: str,
        subject_type: str | None = None,
        subject_id: int | None = None,
        document_id: int | None = None,
        title: str | None = None,
        file_name: str | None = None,
        file_size: int | None = None,
        file_type: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        metadata: dict | None = None,
        job_id: str | None = None,
        max_attempts: int = 1,
    ) -> JobRun:
        now = self._now()
        job_run = JobRun(
            job_id=job_id or self._new_job_id(),
            user_id=user_id,
            kind=kind,
            status=JOB_STATUS_QUEUED,
            progress=0,
            subject_type=subject_type,
            subject_id=subject_id,
            document_id=document_id,
            title=title,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            input_json=json_dumps_or_none(input_data),
            output_json=json_dumps_or_none(output_data),
            metadata_json=json_dumps_or_none(metadata),
            max_attempts=max_attempts,
            queued_at=now,
            created_at=now,
            updated_at=now,
            is_visible=True,
        )
        self.db.add(job_run)
        self.db.flush()
        return job_run

    def get_job(self, job_id: str, user_id: int | None = None) -> JobRun | None:
        query = self.db.query(JobRun).filter(JobRun.job_id == job_id)
        if user_id is not None:
            query = query.filter(JobRun.user_id == user_id)
        return query.one_or_none()

    def get_job_by_id(self, id: int) -> JobRun | None:
        return self.db.get(JobRun, id)

    def list_jobs(
        self,
        *,
        user_id: int,
        status_filter: str | None = None,
        kind_filter: str | None = None,
        document_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
        visible_only: bool = True,
    ) -> list[JobRun]:
        query = self.db.query(JobRun).filter(JobRun.user_id == user_id)
        if visible_only:
            query = query.filter(JobRun.is_visible.is_(True))
        if status_filter:
            query = query.filter(JobRun.status == status_filter)
        if kind_filter:
            query = query.filter(JobRun.kind == kind_filter)
        if document_id is not None:
            query = query.filter(JobRun.document_id == document_id)
        return (
            query.order_by(JobRun.updated_at.desc(), JobRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def search_jobs(
        self,
        *,
        user_id: int,
        page: int = 1,
        size: int = 20,
        query_text: str | None = None,
        status_filter: str | None = None,
        kind_filter: str | None = None,
        document_id: int | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        visible_only: bool = True,
    ) -> tuple[list[JobRun], int]:
        document_alias = aliased(Document)
        query = self.db.query(JobRun).outerjoin(document_alias, document_alias.id == JobRun.document_id).filter(JobRun.user_id == user_id)
        if visible_only:
            query = query.filter(JobRun.is_visible.is_(True))
        if status_filter:
            query = query.filter(JobRun.status == status_filter)
        if kind_filter:
            query = query.filter(JobRun.kind == kind_filter)
        if document_id is not None:
            query = query.filter(JobRun.document_id == document_id)
        if query_text:
            pattern = f"%{query_text.strip()}%"
            query = query.filter(
                or_(
                    JobRun.job_id.ilike(pattern),
                    JobRun.title.ilike(pattern),
                    JobRun.file_name.ilike(pattern),
                    JobRun.error_message.ilike(pattern),
                    document_alias.title.ilike(pattern),
                    document_alias.original_filename.ilike(pattern),
                )
            )

        total = query.count()
        sort_columns = {
            "created_at": JobRun.created_at,
            "updated_at": JobRun.updated_at,
            "finished_at": JobRun.finished_at,
            "file_name": func.coalesce(JobRun.file_name, document_alias.original_filename),
            "status": JobRun.status,
            "kind": JobRun.kind,
            "progress": JobRun.progress,
        }
        sort_column = sort_columns.get(sort_by, JobRun.updated_at)
        ordering = sort_column.asc() if sort_order.lower() == "asc" else sort_column.desc()
        jobs = query.order_by(ordering, JobRun.created_at.desc()).offset((page - 1) * size).limit(size).all()
        return jobs, total

    def latest_document_job(self, document_id: int, kind: str | None = None) -> JobRun | None:
        query = self.db.query(JobRun).filter(JobRun.document_id == document_id)
        if kind:
            query = query.filter(JobRun.kind == kind)
        return query.order_by(JobRun.created_at.desc(), JobRun.id.desc()).first()

    def active_document_job(self, document_id: int, kind: str | None = None) -> JobRun | None:
        query = self.db.query(JobRun).filter(
            JobRun.document_id == document_id,
            JobRun.status.in_(ACTIVE_JOB_STATUSES),
        )
        if kind:
            query = query.filter(JobRun.kind == kind)
        return query.order_by(JobRun.created_at.desc(), JobRun.id.desc()).first()

    def mark_running(self, job_run: JobRun, worker_name: str | None = None) -> JobRun:
        job_run.status = JOB_STATUS_RUNNING
        job_run.started_at = job_run.started_at or self._now()
        job_run.updated_at = self._now()
        job_run.worker_name = worker_name
        self.db.flush()
        return job_run

    def update_progress(self, job_run: JobRun, progress: int, metadata: dict | None = None) -> JobRun:
        job_run.progress = self._clamp_progress(progress)
        job_run.updated_at = self._now()
        if metadata:
            job_run.metadata_json = merge_json_object(job_run.metadata_json, metadata)
        self.db.flush()
        return job_run

    def mark_succeeded(self, job_run: JobRun, output_data: dict | None = None) -> JobRun:
        job_run.status = JOB_STATUS_SUCCEEDED
        job_run.progress = 100
        job_run.finished_at = self._now()
        job_run.updated_at = job_run.finished_at
        job_run.output_json = json_dumps_or_none(output_data)
        self.db.flush()
        return job_run

    def mark_failed(self, job_run: JobRun, error_message: str, metadata: dict | None = None) -> JobRun:
        job_run.status = JOB_STATUS_FAILED
        job_run.progress = 100
        job_run.finished_at = self._now()
        job_run.updated_at = job_run.finished_at
        job_run.error_message = error_message
        if metadata:
            job_run.metadata_json = merge_json_object(job_run.metadata_json, metadata)
        self.db.flush()
        return job_run

    def cancel_job(self, job_run: JobRun, reason: str | None = None) -> JobRun:
        job_run.status = JOB_STATUS_CANCELLED
        job_run.finished_at = self._now()
        job_run.updated_at = job_run.finished_at
        job_run.metadata_json = merge_json_object(job_run.metadata_json, {"cancel_reason": reason} if reason else None)
        self.db.flush()
        return job_run

    def hide_jobs_for_user(self, user_id: int) -> int:
        jobs = self.db.query(JobRun).filter(JobRun.user_id == user_id, JobRun.is_visible.is_(True)).all()
        for job_run in jobs:
            job_run.is_visible = False
            job_run.updated_at = self._now()
        self.db.flush()
        return len(jobs)

    def health_counts(self, user_id: int | None = None) -> JobRunHealthCounts:
        query = self.db.query(JobRun)
        if user_id is not None:
            query = query.filter(JobRun.user_id == user_id)
        jobs_total = query.count()
        visible_jobs = query.filter(JobRun.is_visible.is_(True)).count()
        queued_jobs = query.filter(JobRun.status == JOB_STATUS_QUEUED).count()
        running_jobs = query.filter(JobRun.status == JOB_STATUS_RUNNING).count()
        failed_jobs = query.filter(JobRun.status == JOB_STATUS_FAILED).count()
        return JobRunHealthCounts(
            queued_jobs=queued_jobs,
            running_jobs=running_jobs,
            visible_jobs=visible_jobs,
            jobs_total=jobs_total,
            failed_jobs=failed_jobs,
        )

    @staticmethod
    def _clamp_progress(progress: int) -> int:
        return max(0, min(100, int(progress)))

    @staticmethod
    def _new_job_id() -> str:
        return f"job_{uuid4().hex}"

    @staticmethod
    def _now() -> datetime:
        return app_now()
