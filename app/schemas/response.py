from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


TaskStatus = Literal["queued", "processing", "success", "failed"]


class FileResult(BaseModel):
    file_name: str
    file_size: int
    file_type: str
    total_lines: int
    error_count: int
    warn_count: int
    processing_time_ms: float


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


class ProcessResponse(BaseModel):
    processed: list[TaskDetail]


class HealthResponse(BaseModel):
    status: str
    queued_tasks: int
    tracked_tasks: int

