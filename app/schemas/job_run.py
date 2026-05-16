from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import JobRun
from app.utils.json import json_loads_object_or_none


class JobRunCreate(BaseModel):
    user_id: int
    kind: str
    subject_type: str | None = None
    subject_id: int | None = None
    document_id: int | None = None
    title: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_type: str | None = None
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    max_attempts: int = 1


class JobRunUpdate(BaseModel):
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    output_data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    error_message: str | None = None
    worker_name: str | None = None


class JobRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    kind: str
    status: str
    progress: int
    subject_type: str | None = None
    subject_id: int | None = None
    document_id: int | None = None
    title: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_type: str | None = None
    error: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_job_run(cls, job_run: JobRun) -> "JobRunRead":
        return cls(
            job_id=job_run.job_id,
            kind=job_run.kind,
            status=job_run.status,
            progress=job_run.progress,
            subject_type=job_run.subject_type,
            subject_id=job_run.subject_id,
            document_id=job_run.document_id,
            title=job_run.title,
            file_name=job_run.file_name,
            file_size=job_run.file_size,
            file_type=job_run.file_type,
            error=job_run.error_message,
            input=json_loads_object_or_none(job_run.input_json),
            output=json_loads_object_or_none(job_run.output_json),
            metadata=json_loads_object_or_none(job_run.metadata_json),
            created_at=job_run.created_at,
            updated_at=job_run.updated_at,
            queued_at=job_run.queued_at,
            started_at=job_run.started_at,
            finished_at=job_run.finished_at,
        )


class JobRunListResponse(BaseModel):
    total: int
    items: list[JobRunRead]


class JobHealthCounts(BaseModel):
    queued_jobs: int
    running_jobs: int
    visible_jobs: int
    jobs_total: int
    failed_jobs: int
