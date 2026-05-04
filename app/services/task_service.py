from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from ..core.config import ENABLE_BACKGROUND_WORKER, RESULT_DIR, UPLOAD_DIR
from ..core.logging_config import get_api_logger, get_task_logger
from ..queue.task_queue import TaskQueue
from ..schemas.response import FileResult, TaskDetail, TaskResultResponse, TaskSummary
from .file_service import FileService

#TaskService 是 FastAPI 路由和 FileService 的中间层 + 异步队列调度中心,后用redis替代任务存储 + 队列管理 + 异步执行
@dataclass(slots=True)
class TaskRecord:#service实例内部存储任务状态
    task_id: str
    file_name: str
    file_size: int
    file_type: str
    status: str
    created_at: str
    updated_at: str
    storage_path: str
    result_path: str | None = None
    error: str | None = None

    def to_summary(self) -> TaskSummary:
        return TaskSummary(**self._base_payload())

    def to_detail(self) -> TaskDetail:
        payload = self._base_payload()
        payload.update({"storage_path": self.storage_path, "result_path": self.result_path, "error": self.error})
        return TaskDetail(**payload)

    def _base_payload(self) -> dict[str, str | int]:
        return {
            "task_id": self.task_id,
            "file_name": self.file_name,
            "status": self.status,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskService:
    def __init__(self) -> None:
        self._logger = get_api_logger()
        self._task_logger = get_task_logger()
        self._file_service = FileService()
        self._queue = TaskQueue()
        self._records: dict[str, TaskRecord] = {}
        self._lock = Lock()
        self._worker_stop = Event()
        self._worker: Thread | None = None
        if ENABLE_BACKGROUND_WORKER:
            self.start_background_worker()

    def process_next(self) -> TaskRecord | None:
        task_id = self._queue.dequeue()
        if task_id is None:
            return None
        return self._process_task(task_id)

    def process_all(self) -> list[TaskRecord]:
        processed: list[TaskRecord] = []
        while True:
            task = self.process_next()
            if task is None:
                break
            processed.append(task)
        return processed

    def get_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self._records.get(task_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return record

    def get_result(self, task_id: str) -> TaskResultResponse:
        record = self.get_task(task_id)
        if record.status != "success" or not record.result_path:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task result is not ready.")
        result_file = Path(record.result_path)
        if not result_file.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result file not found.")
        result = FileResult(**json.loads(result_file.read_text(encoding="utf-8")))
        return TaskResultResponse(task=record.to_detail(), result=result)

    def list_tasks(self, status_filter: str | None = None) -> list[TaskRecord]:
        with self._lock:
            records = list(self._records.values())
        if status_filter:
            records = [record for record in records if record.status == status_filter]
        return sorted(records, key=lambda record: record.created_at)

    def queue_size(self) -> int:
        return self._queue.size()

    def tracked_count(self) -> int:
        with self._lock:
            return len(self._records)

    def start_background_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker_stop.clear()
        self._worker = Thread(target=self._worker_loop, name="task-worker", daemon=True)
        self._worker.start()
        self._logger.info("Background task worker started")

    def stop_background_worker(self) -> None:
        self._worker_stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.5)

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            task_id = self._queue.dequeue(block=True, timeout=0.5)
            if task_id is None:
                continue
            self._process_task(task_id)

    def _process_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
            record.status = "processing"
            record.updated_at = self._now()

        self._task_logger.info("Processing task %s for %s", task_id, record.file_name)
        try:
            analysis = self._file_service.analyze_file(Path(record.storage_path))
            result_path = RESULT_DIR / f"{task_id}.json"
            result_path.write_text(json.dumps(asdict(analysis), ensure_ascii=False, indent=2), encoding="utf-8")#转化为json返回
            with self._lock:
                record.status = "success"
                record.updated_at = self._now()
                record.result_path = str(result_path)
                record.error = None
            self._task_logger.info("Finished task %s", task_id)
        except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
            with self._lock:
                record.status = "failed"
                record.updated_at = self._now()
                record.error = str(exc)
            self._task_logger.exception("Task %s failed", task_id)
        return record

    async def save_uploads(self, uploads: Iterable[UploadFile]) -> list[TaskRecord]:
        created: list[TaskRecord] = []
        for upload in uploads:
            file_name = Path(upload.filename or "").name
            task_id = uuid4().hex
            storage_path = UPLOAD_DIR / f"{task_id}_{file_name}"
            saved_name, file_size, file_type = await self._file_service.save_upload(upload, storage_path)
            now = self._now()
            record = TaskRecord(
                task_id=task_id,
                file_name=saved_name,
                file_size=file_size,
                file_type=file_type,
                status="queued",
                created_at=now,
                updated_at=now,
                storage_path=str(storage_path),
            )
            with self._lock:
                self._records[task_id] = record
            self._queue.enqueue(task_id)
            self._logger.info("Queued task %s for %s", task_id, saved_name)
            created.append(record)
        return created

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
