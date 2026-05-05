from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


TaskStatus = Literal["queued", "processing", "success", "failed"]


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
    file_name: str
    status: TaskStatus
    file_size: int
    file_type: str
    created_at: str
    updated_at: str


class TaskDetail(TaskSummary):
    storage_path: str
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
