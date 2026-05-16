from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "skipped", "processing", "success", "parsed"]
TaskKind = Literal[
    "basic_file_processing",
    "document_parse",
    "document_translate",
    "document_embedding",
    "document_summary",
    "document_kg_extract",
    "document_ocr_retry",
    "batch_import",
]


class FileResult(BaseModel):
    file_name: str
    file_size: int
    file_type: str
    total_lines: int | None = None
    error_count: int | None = None
    warn_count: int | None = None
    processing_time_ms: float
    title: str | None = None
    abstract: str | None = None
    body_preview: str | None = None


class TaskSummary(BaseModel):
    task_id: str
    task_kind: TaskKind
    document_id: int | None = None
    file_name: str
    file_size: int
    file_type: str
    status: TaskStatus
    progress: int
    created_at: datetime
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    metadata_json: str | None = None


class TaskDetail(TaskSummary):
    """Compatibility read model backed by JobRun.

    The /tasks API still returns task_id/task_kind for the current frontend,
    but the persistence source is JobRun rather than legacy Task or ParseJob.
    """

    storage_path: str | None = None
    result_path: str | None = None
    error: str | None = None


class TaskResultResponse(BaseModel):
    task: TaskDetail
    result: FileResult


class UploadResponse(BaseModel):
    tasks: list[TaskSummary]
    queue_size: int
    task_id: str | None = None


class ProcessResponse(BaseModel):
    processed: list[TaskDetail]


class HealthResponse(BaseModel):
    status: str
    queued_tasks: int
    tracked_tasks: int
    tracked_tasks_total: int
    basic_file_tasks_total: int
    parse_jobs_total: int
    parse_jobs_active: int
    parse_jobs_failed: int
    jobs_total: int = 0
    visible_jobs: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
