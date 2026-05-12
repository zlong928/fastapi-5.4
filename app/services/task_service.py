from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select

from ..core.config import ENABLE_BACKGROUND_WORKER, RESULT_DIR, UPLOAD_DIR
from ..db.session import SessionLocal
from ..core.logging_config import get_api_logger, get_task_logger
from ..models import Task
from ..queue.redis_queue import RedisQueue
from ..schemas.response import FileResult, TaskDetail, TaskResultResponse, TaskSummary
from .file_service import FileService
from .pdf_service import PdfService

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
    user_id: int | None = None
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
        self._pdf_service = PdfService()
        self._queue = RedisQueue()
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
        return self.process_task(task_id)

    def process_all(self) -> list[TaskRecord]:
        processed: list[TaskRecord] = []
        while True:
            task = self.process_next()
            if task is None:
                break
            processed.append(task)
        return processed

    def get_task(self, task_id: str, user_id: int | None = None) -> TaskRecord:
        record = self._record_from_db(task_id, user_id=user_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return self._refresh_record_from_result(record)

    def get_result(self, task_id: str, user_id: int | None = None) -> TaskResultResponse:
        record = self.get_task(task_id, user_id=user_id)
        if record.status != "success" or not record.result_path:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task result is not ready.")
        result_file = Path(record.result_path)
        if not result_file.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result file not found.")
        result = FileResult(**json.loads(result_file.read_text(encoding="utf-8")))
        return TaskResultResponse(task=record.to_detail(), result=result)

    def list_tasks(self, status_filter: str | None = None, user_id: int | None = None) -> list[TaskRecord]:
        with SessionLocal() as db:
            statement = select(Task)
            if user_id is not None:
                statement = statement.where(Task.user_id == user_id)
            if status_filter:
                statement = statement.where(Task.status == status_filter)
            statement = statement.order_by(Task.created_at)
            records = [self._record_from_model(task) for task in db.scalars(statement).all()]
        records = [self._refresh_record_from_result(record) for record in records]
        return sorted(records, key=lambda record: record.created_at)

    def _refresh_record_from_result(self, record: TaskRecord) -> TaskRecord:
        if record.status in {"success", "failed"}:
            return record

        result_path = RESULT_DIR / f"{record.task_id}.json"
        if not result_path.exists():
            return record

        error = None
        next_status = "success"
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            error = payload.get("error")
            if error:
                next_status = "failed"
        except json.JSONDecodeError:
            error = "Result file is not valid JSON."
            next_status = "failed"

        with SessionLocal() as db:
            task = db.get(Task, record.task_id)
            if task is not None:
                task.status = next_status
                task.result_path = str(result_path)
                task.error = error
                db.commit()
                db.refresh(task)
                record = self._record_from_model(task)
        with self._lock:
            self._records[record.task_id] = record
        return record

    def queue_size(self) -> int:
        return self._queue.size()

    def tracked_count(self) -> int:
        with SessionLocal() as db:
            return db.query(Task).count()

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
            self.process_task(task_id)

    def process_task(self, task_id: str) -> TaskRecord:
        record = self._ensure_record(task_id)
        if record.result_path and Path(record.result_path).exists():
            self._task_logger.info("Skipping already processed task %s", task_id)
            return record

        record = self._update_task(task_id, status="processing")

        self._task_logger.info("Processing task %s for %s", task_id, record.file_name)
        try:
            storage_path = Path(record.storage_path)
            if record.file_type == "pdf":
                analysis = self._pdf_service.analyze_pdf(storage_path)
            else:
                analysis = self._file_service.analyze_file(storage_path)
            result_path = RESULT_DIR / f"{task_id}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(asdict(analysis), ensure_ascii=False, indent=2), encoding="utf-8")#转化为json返回
            record = self._update_task(task_id, status="success", result_path=str(result_path), error=None)
            self._task_logger.info("Finished task %s", task_id)
        except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
            result_path = RESULT_DIR / f"{task_id}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "file_name": record.file_name,
                        "file_size": record.file_size,
                        "file_type": record.file_type,
                        "processing_time_ms": 0.0,
                        "title": None,
                        "abstract": None,
                        "body_preview": None,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            record = self._update_task(task_id, status="failed", result_path=str(result_path), error=str(exc))
            self._task_logger.exception("Task %s failed", task_id)
        return record

    def scan_uploads(self) -> list[TaskRecord]:
        records: list[TaskRecord] = []
        if not UPLOAD_DIR.exists():
            return records
        for task_dir in sorted(path for path in UPLOAD_DIR.iterdir() if path.is_dir()):
            try:
                records.append(self._ensure_record(task_dir.name))
            except HTTPException:
                self._task_logger.warning("Skipping upload directory without a PDF: %s", task_dir)
        return records

    def process_uploads(self) -> list[TaskRecord]:
        processed: list[TaskRecord] = []
        for record in self.scan_uploads():
            if record.result_path and Path(record.result_path).exists():
                continue
            processed.append(self.process_task(record.task_id))
        return processed

    async def save_uploads(self, uploads: Iterable[UploadFile], user_id: int) -> list[TaskRecord]:
        created: list[TaskRecord] = []
        for upload in uploads:
            file_name = Path(upload.filename or "").name
            task_id = uuid4().hex
            storage_path = UPLOAD_DIR / task_id / file_name
            saved_name, file_size, file_type = await self._file_service.save_upload(upload, storage_path)
            now = self._now()
            with SessionLocal() as db:
                task = Task(
                    task_id=task_id,
                    user_id=user_id,
                    file_name=saved_name,
                    file_size=file_size,
                    file_type=file_type,
                    status="queued",
                    storage_path=str(storage_path),
                )
                db.add(task)
                db.commit()
                db.refresh(task)
                record = self._record_from_model(task)
            with self._lock:
                self._records[task_id] = record
            self._queue.enqueue(task_id)
            self._logger.info("Queued task %s for %s", task_id, saved_name)
            created.append(record)
        return created

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_record(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self._records.get(task_id)
        if record is not None:
            return record

        record = self._record_from_db(task_id)
        if record is not None:
            with self._lock:
                self._records[task_id] = record
            return record

        task_dir = UPLOAD_DIR / task_id
        if not task_dir.is_dir():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        pdfs = sorted(task_dir.glob("*.pdf"))
        if not pdfs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF upload not found.")
        storage_path = pdfs[0]
        result_path = RESULT_DIR / f"{task_id}.json"
        status_value = "success" if result_path.exists() else "queued"
        now = self._now()
        error = None
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                error = payload.get("error")
                status_value = "failed" if error else "success"
            except json.JSONDecodeError:
                status_value = "failed"
                error = "Result file is not valid JSON."

        record = TaskRecord(
            task_id=task_id,
            file_name=storage_path.name,
            file_size=storage_path.stat().st_size,
            file_type=storage_path.suffix.lower().lstrip("."),
            status=status_value,
            created_at=now,
            updated_at=now,
            storage_path=str(storage_path),
            result_path=str(result_path) if result_path.exists() else None,
            error=error,
        )
        with self._lock:
            self._records[task_id] = record
        return record

    def _record_from_db(self, task_id: str, user_id: int | None = None) -> TaskRecord | None:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                return None
            if user_id is not None and task.user_id != user_id:
                return None
            return self._record_from_model(task)

    def _record_from_model(self, task: Task) -> TaskRecord:
        return TaskRecord(
            task_id=task.task_id,
            file_name=task.file_name,
            file_size=task.file_size,
            file_type=task.file_type,
            status=task.status,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat(),
            storage_path=task.storage_path,
            user_id=task.user_id,
            result_path=task.result_path,
            error=task.error,
        )

    def _update_task(self, task_id: str, **values: str | None) -> TaskRecord:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
            for key, value in values.items():
                setattr(task, key, value)
            db.commit()
            db.refresh(task)
            record = self._record_from_model(task)
        with self._lock:
            self._records[task_id] = record
        return record
