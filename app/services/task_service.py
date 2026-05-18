from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select

from app.core.time import app_now
from ..core.config import ENABLE_BACKGROUND_WORKER, RESULT_DIR, UPLOAD_DIR
from ..db.session import SessionLocal
from ..core.logging_config import get_api_logger, get_task_logger
from app.constants.jobs import JOB_KIND_BASIC_FILE_PROCESSING, SUBJECT_TYPE_FILE
from ..models import JobRun
from ..queue.redis_queue import RedisQueue
from ..schemas.response import FileResult, TaskDetail, TaskResultResponse, TaskSummary
from .file_service import FileService
from .job_run_service import JobRunService
from .pdf_service import PdfService

#TaskService 是 FastAPI 路由和 FileService 的中间层 + 异步队列调度中心,后用redis替代任务存储 + 队列管理 + 异步执行
@dataclass(slots=True)
class TaskRecord:#service实例内部存储任务状态
    task_id: str
    file_name: str
    file_size: int
    file_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    storage_path: str
    user_id: int | None = None
    result_path: str | None = None
    error: str | None = None
    task_kind: str = "basic_file_processing"
    document_id: int | None = None
    progress: int = 0
    completed_at: datetime | None = None
    metadata_json: str | None = None

    def to_summary(self) -> TaskSummary:
        return TaskSummary(**self._base_payload())

    def to_detail(self) -> TaskDetail:
        payload = self._base_payload()
        payload.update({"storage_path": self.storage_path, "result_path": self.result_path, "error": self.error})
        return TaskDetail(**payload)

    def _base_payload(self) -> dict[str, str | int | datetime | None]:
        return {
            "task_id": self.task_id,
            "file_name": self.file_name,
            "status": self.status,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "task_kind": self.task_kind,
            "document_id": self.document_id,
            "progress": self.progress,
            "completed_at": self.completed_at,
            "metadata_json": self.metadata_json,
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
        if record.status != "succeeded" or not record.result_path:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task result is not ready.")
        result_file = Path(record.result_path)
        if not result_file.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result file not found.")
        result = FileResult(**json.loads(result_file.read_text(encoding="utf-8")))
        return TaskResultResponse(task=record.to_detail(), result=result)

    def clear_tasks(self, user_id: int) -> int:
        with SessionLocal() as db:
            jobs = db.scalars(select(JobRun).where(JobRun.user_id == user_id, JobRun.is_visible.is_(True))).all()
            task_ids = [job.job_id for job in jobs]
            for job_run in jobs:
                job_run.is_visible = False
            db.commit()

        if task_ids and hasattr(self._queue, "remove_many"):
            self._queue.remove_many(task_ids)

        with self._lock:
            for task_id in task_ids:
                self._records.pop(task_id, None)
        return len(task_ids)

    def remove_cached_tasks(self, task_ids: list[str]) -> None:
        if task_ids and hasattr(self._queue, "remove_many"):
            try:
                self._queue.remove_many(task_ids)
            except Exception as exc:  # pragma: no cover - queue cleanup must not block DB cleanup
                self._logger.warning("Failed to remove cleared tasks from queue: %s", exc)
        with self._lock:
            for task_id in task_ids:
                self._records.pop(task_id, None)

    def _refresh_record_from_result(self, record: TaskRecord) -> TaskRecord:
        if record.status in {"succeeded", "failed"}:
            return record

        result_path = RESULT_DIR / f"{record.task_id}.json"
        if not result_path.exists():
            return record

        error = None
        next_status = "succeeded"
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            error = payload.get("error")
            if error:
                next_status = "failed"
        except json.JSONDecodeError:
            error = "Result file is not valid JSON."
            next_status = "failed"

        with SessionLocal() as db:
            job_run = db.query(JobRun).filter(JobRun.job_id == record.task_id).one_or_none()
            if job_run is not None:
                service = JobRunService(db)
                metadata = {"result_path": str(result_path)}
                if next_status == "succeeded":
                    service.mark_succeeded(job_run, output_data=payload if "payload" in locals() else metadata)
                    job_run.metadata_json = self._merge_metadata(job_run.metadata_json, metadata)
                else:
                    service.mark_failed(job_run, error or "Task failed.", metadata=metadata)
                db.commit()
                db.refresh(job_run)
                record = self._record_from_model(job_run)
        with self._lock:
            self._records[record.task_id] = record
        return record

    def queue_size(self) -> int:
        return self._queue.size()

    def tracked_count(self) -> int:
        with SessionLocal() as db:
            return db.query(JobRun).filter(JobRun.kind == JOB_KIND_BASIC_FILE_PROCESSING).count()

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

        record = self._update_task(task_id, status="running", progress=50)

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
            record = self._update_task(task_id, status="succeeded", result_path=str(result_path), error=None, progress=100)
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
            record = self._update_task(task_id, status="failed", result_path=str(result_path), error=str(exc), progress=100)
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
            with SessionLocal() as db:
                job_run = JobRunService(db).create_job(
                    job_id=task_id,
                    user_id=user_id,
                    kind=JOB_KIND_BASIC_FILE_PROCESSING,
                    subject_type=SUBJECT_TYPE_FILE,
                    title=f"Process {saved_name}",
                    file_name=saved_name,
                    file_size=file_size,
                    file_type=file_type,
                    metadata={"storage_path": str(storage_path)},
                )
                db.commit()
                db.refresh(job_run)
                record = self._record_from_model(job_run)
            with self._lock:
                self._records[task_id] = record
            self._queue.enqueue(task_id)
            self._logger.info("Queued task %s for %s", task_id, saved_name)
            created.append(record)
        return created

    def _now(self) -> datetime:
        return app_now()

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
        status_value = "succeeded" if result_path.exists() else "queued"
        now = self._now()
        error = None
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                error = payload.get("error")
                status_value = "failed" if error else "succeeded"
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
            job_run = db.query(JobRun).filter(JobRun.job_id == task_id).one_or_none()
            if job_run is None:
                return None
            if user_id is not None and job_run.user_id != user_id:
                return None
            return self._record_from_model(job_run)

    def _record_from_model(self, job_run: JobRun) -> TaskRecord:
        metadata = {}
        if job_run.metadata_json:
            try:
                metadata = json.loads(job_run.metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        return TaskRecord(
            task_id=job_run.job_id,
            file_name=job_run.file_name or job_run.title or job_run.kind,
            file_size=job_run.file_size or 0,
            file_type=job_run.file_type or "file",
            status=job_run.status,
            created_at=job_run.created_at,
            updated_at=job_run.updated_at,
            storage_path=str(metadata.get("storage_path") or ""),
            user_id=job_run.user_id,
            result_path=metadata.get("result_path") if isinstance(metadata.get("result_path"), str) else None,
            error=job_run.error_message,
            progress=job_run.progress,
            completed_at=job_run.finished_at,
            metadata_json=job_run.metadata_json,
        )

    def _update_task(self, task_id: str, **values: str | int | None) -> TaskRecord:
        with SessionLocal() as db:
            job_run = db.query(JobRun).filter(JobRun.job_id == task_id).one_or_none()
            if job_run is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
            service = JobRunService(db)
            status_value = values.get("status")
            metadata = {}
            if values.get("result_path"):
                metadata["result_path"] = values["result_path"]
            if status_value == "running":
                service.mark_running(job_run, worker_name="task_service")
                service.update_progress(job_run, int(values.get("progress") or 50))
            elif status_value == "succeeded":
                service.mark_succeeded(job_run, output_data=metadata or None)
                if metadata:
                    job_run.metadata_json = self._merge_metadata(job_run.metadata_json, metadata)
            elif status_value == "failed":
                service.mark_failed(job_run, str(values.get("error") or "Task failed."), metadata=metadata or None)
            else:
                if values.get("progress") is not None:
                    service.update_progress(job_run, int(values["progress"]))
            db.commit()
            db.refresh(job_run)
            record = self._record_from_model(job_run)
        with self._lock:
            self._records[task_id] = record
        return record

    @staticmethod
    def _merge_metadata(metadata_json: str | None, patch: dict) -> str:
        metadata = {}
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        metadata.update(patch)
        return json.dumps(metadata, ensure_ascii=False)
