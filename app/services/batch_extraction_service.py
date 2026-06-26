"""批量图片提取服务"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.config import (
    BATCH_CONCURRENCY,
    BATCH_EXTRACTION_QUEUE_NAME,
    BATCH_EXTRACTION_STALE_AFTER_SECONDS,
    BATCH_PROGRESS_INTERVAL,
    IMAGE_EXTRACT_TIMEOUT,
)
from app.core.time import app_now
from app.models import BatchExtractionJob, BatchExtractionItem, DocumentAsset, DocumentEvent
from app.queue.redis_queue import RedisQueue
from app.services.chart_extraction.batch import process_mineru_image_record
from app.services.chart_extraction.models import ImageRecord
from app.services.file_storage import FileStorageService
from app.services.paper.evidence import asset_metadata

if TYPE_CHECKING:
    from app.models import Document, User

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = ("pending", "processing")


class BatchExtractionService:
    """批量图片提取服务"""

    def __init__(self, db: Session):
        self.db = db
        self.storage = FileStorageService()

    # ── job lifecycle (sync, unchanged) ──────────────────────────────

    def create_job(self, document: Document, user: User) -> BatchExtractionJob:
        """创建批量提取任务"""
        assets = (
            self.db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == document.id,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
                DocumentAsset.file_path.isnot(None),
            )
            .all()
        )

        if not assets:
            raise ValueError("未找到可提取的图片资产")

        valid_assets = []
        for asset in assets:
            image_path = self.storage.get_file_path(asset.file_path)
            if image_path.exists():
                valid_assets.append(asset)

        if not valid_assets:
            raise ValueError("所有图片文件都不存在")

        job = BatchExtractionJob(
            document_id=document.id,
            user_id=user.id,
            status="pending",
            total_images=len(valid_assets),
            processed_images=0,
            success_count=0,
            skipped_count=0,
            failed_count=0,
        )
        self.db.add(job)
        self.db.flush()

        for asset in valid_assets:
            item = BatchExtractionItem(
                job_id=job.id,
                asset_id=asset.id,
                status="pending",
            )
            self.db.add(item)

        self.db.commit()

        self.db.add(
            DocumentEvent(
                document_id=document.id,
                user_id=user.id,
                event_type="batch_extraction_started",
                message="格式提取已开始",
            )
        )
        self.db.commit()

        return job

    def submit_job_to_queue(self, job_id: int) -> None:
        """将任务提交到 Redis 队列"""
        queue = RedisQueue(queue_name=BATCH_EXTRACTION_QUEUE_NAME)
        task_data = {
            "task_type": "batch_extraction",
            "job_id": job_id,
        }
        queue.enqueue(task_data)
        logger.info("Batch extraction job %d submitted to queue", job_id)

    def submit_job_to_queue_if_missing(self, job_id: int) -> bool:
        """将任务提交到队列；若队列里已有同一任务则不重复提交。"""
        if self.is_job_queued(job_id):
            return False
        self.submit_job_to_queue(job_id)
        return True

    def is_job_queued(self, job_id: int) -> bool:
        queue = RedisQueue(queue_name=BATCH_EXTRACTION_QUEUE_NAME)
        for payload_str in queue.snapshot():
            payload = self._parse_queue_payload(payload_str)
            if payload and payload.get("job_id") == job_id:
                return True
        return False

    @staticmethod
    def _parse_queue_payload(payload_str: str) -> dict | None:
        try:
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("task_type") != "batch_extraction":
            return None
        return payload

    def active_job_for_document(self, document_id: int) -> BatchExtractionJob | None:
        return (
            self.db.query(BatchExtractionJob)
            .filter(
                BatchExtractionJob.document_id == document_id,
                BatchExtractionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(BatchExtractionJob.created_at.desc())
            .first()
        )

    def recover_interrupted_job(self, job: BatchExtractionJob, *, force: bool = False) -> BatchExtractionJob:
        """恢复被 worker 重启/崩溃打断的批量任务状态。"""
        if job.status == "processing" and not force and not self._job_is_stale(job):
            return job

        if job.status == "processing":
            processing_items = (
                self.db.query(BatchExtractionItem)
                .filter(
                    BatchExtractionItem.job_id == job.id,
                    BatchExtractionItem.status == "processing",
                )
                .all()
            )
            for item in processing_items:
                item.status = "pending"
                item.error_message = None
                item.processed_at = None

        items = self.db.query(BatchExtractionItem).filter(BatchExtractionItem.job_id == job.id).all()
        job.total_images = len(items)
        job.success_count = sum(1 for item in items if item.status == "success")
        job.skipped_count = sum(1 for item in items if item.status == "skipped")
        job.failed_count = sum(1 for item in items if item.status == "failed")
        job.processed_images = job.success_count + job.skipped_count + job.failed_count

        if job.processed_images >= job.total_images and job.total_images > 0:
            job.status = "completed"
            job.completed_at = job.completed_at or app_now()
        else:
            job.status = "pending"
            job.completed_at = None
            job.error_message = None

        self.db.commit()
        self.db.refresh(job)
        return job

    def _job_is_stale(self, job: BatchExtractionJob) -> bool:
        last_activity = job.updated_at or job.started_at or job.created_at
        if last_activity is None:
            return True
        now = app_now()
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=now.tzinfo or timezone.utc)
        return (app_now() - last_activity).total_seconds() >= BATCH_EXTRACTION_STALE_AFTER_SECONDS

    def recover_active_jobs(self) -> list[BatchExtractionJob]:
        """恢复卡住的 processing 任务和被标记为 completed 但有 pending 项的已完成任务。"""
        jobs = (
            self.db.query(BatchExtractionJob)
            .filter(BatchExtractionJob.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(BatchExtractionJob.created_at.asc())
            .all()
        )
        completed_with_pending = (
            self.db.query(BatchExtractionJob)
            .filter(
                BatchExtractionJob.status == "completed",
                BatchExtractionJob.total_images > 0,
            )
            .all()
        )
        for j in completed_with_pending:
            pending_count = (
                self.db.query(BatchExtractionItem)
                .filter(
                    BatchExtractionItem.job_id == j.id,
                    BatchExtractionItem.status == "pending",
                )
                .count()
            )
            if pending_count > 0:
                jobs.append(j)

        recovered: list[BatchExtractionJob] = []
        for job in jobs:
            recovered_job = self.recover_interrupted_job(job, force=True)
            if recovered_job.status == "pending":
                self.submit_job_to_queue_if_missing(recovered_job.id)
            recovered.append(recovered_job)
        return recovered

    def get_job(self, job_id: int) -> BatchExtractionJob | None:
        """获取任务"""
        return self.db.get(BatchExtractionJob, job_id)

    # ── async processing ─────────────────────────────────────────────

    async def async_process_job(self, job_id: int, thread_pool: ThreadPoolExecutor) -> None:
        """异步处理批量提取任务"""
        job = self.get_job(job_id)
        if not job:
            logger.error("Batch extraction job %d not found", job_id)
            return
        if job.status != "pending":
            logger.warning("Batch extraction job %d is not pending (status: %s)", job_id, job.status)
            return

        job.status = "processing"
        job.started_at = app_now()
        self.db.commit()

        logger.info(
            "Processing async batch extraction job %d with %d images (concurrency=%d, timeout=%ds)",
            job_id, job.total_images, BATCH_CONCURRENCY, IMAGE_EXTRACT_TIMEOUT
        )

        loop = asyncio.get_running_loop()
        document_id = job.document_id
        user_id = job.user_id

        try:
            items = (
                self.db.query(BatchExtractionItem)
                .filter(BatchExtractionItem.job_id == job_id, BatchExtractionItem.status == "pending")
                .all()
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                await self._process_items_batched_async(job, items, temp_path, thread_pool, loop)

            self.db.commit()
            self._sync_job_from_items(job)

            job.status = "completed"
            job.completed_at = app_now()
            self.db.commit()

            self.db.add(
                DocumentEvent(
                    document_id=document_id,
                    user_id=user_id,
                    event_type="batch_extraction_completed",
                    message="格式提取结束",
                )
            )
            self.db.commit()

            logger.info(
                "Async batch extraction job %d completed: %d success, %d skipped, %d failed",
                job_id, job.success_count, job.skipped_count, job.failed_count
            )

        except Exception as e:
            logger.exception("Async batch extraction job %d failed: %s", job_id, e)
            try:
                failed_job = self.get_job(job_id)
                if failed_job:
                    failed_job.status = "failed"
                    failed_job.error_message = str(e)
                    failed_job.completed_at = app_now()
                    self.db.commit()
                    self.db.add(
                        DocumentEvent(
                            document_id=document_id,
                            user_id=user_id,
                        event_type="batch_extraction_failed",
                        message="格式提取失败",
                        )
                    )
                    self.db.commit()
            except Exception as inner_e:
                logger.exception("Failed to record job failure for %d: %s", job_id, inner_e)

    async def _process_items_batched_async(
        self, job: BatchExtractionJob, items: list, temp_path: Path,
        thread_pool: ThreadPoolExecutor, loop: asyncio.AbstractEventLoop
    ) -> None:
        """
        异步并发处理多个图片项。

        设计：
        - asyncio.Semaphore 控制最大并发数（BATCH_CONCURRENCY）
        - 提取逻辑在线程池中执行（_run_extraction_in_thread）
        - 结果写入在主协程中串行执行（无竞争）
        - 后台协程每 BATCH_PROGRESS_INTERVAL 秒输出进度
        """
        sem = asyncio.Semaphore(BATCH_CONCURRENCY)

        item_data_list = []
        for item in items:
            asset = self.db.get(DocumentAsset, item.asset_id)
            if not asset:
                logger.warning("Asset %d not found for item %d, skipping", item.asset_id, item.id)
                continue
            record_dict = self._item_data_dict(item, asset)
            item_data_list.append((item, asset, record_dict))

        total = len(item_data_list)
        if total == 0:
            logger.info("No processable items for job %d", job.id)
            return

        logger.info("Batch async: %d items to process (concurrency=%d)", total, BATCH_CONCURRENCY)

        progress = {"done": 0, "ok": 0, "skip": 0, "fail": 0}
        progress_lock = asyncio.Lock()

        async def process_one(item: BatchExtractionItem, asset: DocumentAsset, record_dict: dict) -> None:
            async with sem:
                try:
                    extraction_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            thread_pool,
                            self._run_extraction_in_thread,
                            record_dict, str(temp_path)
                        ),
                        timeout=IMAGE_EXTRACT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.warning("Asset %d extraction timed out (%ds)", asset.id, IMAGE_EXTRACT_TIMEOUT)
                    extraction_result = {"status": "failed", "reason": f"图表提取超时({IMAGE_EXTRACT_TIMEOUT}秒)"}
                except (Exception, asyncio.CancelledError) as exc:
                    logger.warning("Asset %d extraction error: %s", asset.id, exc)
                    extraction_result = {"status": "failed", "reason": str(exc)}

                if extraction_result is None:
                    extraction_result = {"status": "failed", "reason": "extraction returned None"}
                self._apply_extraction_result(job, item, asset, extraction_result)

                async with progress_lock:
                    progress["done"] += 1
                    s = extraction_result.get("status")
                    if s in ("accepted", "review_required", "success"):
                        progress["ok"] += 1
                    elif s in ("skipped", "empty"):
                        progress["skip"] += 1
                    else:
                        progress["fail"] += 1

        tasks = [asyncio.create_task(process_one(item, asset, rd)) for item, asset, rd in item_data_list]

        async def progress_reporter():
            while not all(t.done() for t in tasks):
                await asyncio.sleep(BATCH_PROGRESS_INTERVAL)
                async with progress_lock:
                    p = dict(progress)
                if p["done"] > 0:
                    job.processed_images = p["done"]
                    job.success_count = p["ok"]
                    job.skipped_count = p["skip"]
                    job.failed_count = p["fail"]
                    self.db.commit()
                    logger.info(
                        "Progress job=%d: %d/%d (ok=%d skip=%d fail=%d)",
                        job.id, p["done"], total, p["ok"], p["skip"], p["fail"]
                    )
            async with progress_lock:
                p = dict(progress)
            logger.info(
                "Progress job=%d final: %d/%d (ok=%d skip=%d fail=%d)",
                job.id, p["done"], total, p["ok"], p["skip"], p["fail"]
            )

        await asyncio.gather(asyncio.gather(*tasks), progress_reporter())

    def _item_data_dict(self, item: BatchExtractionItem, asset: DocumentAsset) -> dict:
        """准备可序列化的提取参数（线程安全，无 DB 引用）"""
        image_path = self.storage.get_file_path(asset.file_path)
        metadata = asset_metadata(asset)
        ordinal = asset.asset_index if asset.asset_index is not None else asset.id
        if isinstance(ordinal, str):
            try:
                ordinal = int(ordinal)
            except (ValueError, TypeError):
                ordinal = asset.id
        return {
            "item_id": item.id,
            "asset_id": asset.id,
            "document_id": asset.document_id,
            "image_path": str(image_path),
            "ordinal": ordinal,
            "mineru_type": str(metadata.get("mineru_type", "image")),
            "mineru_sub_type": str(metadata.get("mineru_sub_type", "")),
            "caption": asset.caption or "",
            "content": asset.caption or "",
        }

    @staticmethod
    def _run_extraction_in_thread(record_dict: dict, temp_path_str: str) -> dict:
        """Pure extraction function, runs in thread pool (no DB access)."""
        record = ImageRecord(
            path=Path(record_dict["image_path"]),
            ordinal=record_dict["ordinal"],
            mineru_type=record_dict["mineru_type"],
            mineru_sub_type=record_dict["mineru_sub_type"],
            caption=record_dict["caption"],
            content=record_dict["content"],
        )
        return process_mineru_image_record(record, Path(temp_path_str), sample_limit=200)

    def _apply_extraction_result(
        self, job: BatchExtractionJob, item: BatchExtractionItem,
        asset: DocumentAsset, extraction_result: dict
    ) -> None:
        """将提取结果写入 DB（在主协程中串行执行，无竞争）"""
        metadata = asset_metadata(asset)

        status = extraction_result.get("status")

        # "empty" = VLM 正确判断为非图表（照片/表格/示意图），不算失败
        if status in ("skipped", "empty"):
            item.status = "skipped"
            item.skip_reason = extraction_result.get("reason", status)
            item.processed_at = app_now()
            job.skipped_count += 1

        elif status in ("accepted", "review_required") and extraction_result.get("csv_path"):
            csv_rel_path = self._save_extraction_to_asset(
                self.db, asset, metadata, extraction_result,
                self.storage, job.document_id
            )
            if csv_rel_path:
                item.status = "success"
                item.image_type = extraction_result.get("image_type", "")
                item.row_count = extraction_result.get("row_count", 0)
                item.csv_path = csv_rel_path
                item.data_quality = extraction_result.get("data_quality", "good")
                item.processed_at = app_now()
                job.success_count += 1
            else:
                item.status = "failed"
                item.error_message = "CSV file not generated"
                item.processed_at = app_now()
                job.failed_count += 1
        else:
            item.status = "failed"
            item.error_message = extraction_result.get("reason", "未知错误")
            item.processed_at = app_now()
            job.failed_count += 1

        self.db.commit()

    def _sync_job_from_items(self, job: BatchExtractionJob) -> None:
        """从 items 重新统计 job 计数（用于最终同步）"""
        items = self.db.query(BatchExtractionItem).filter(BatchExtractionItem.job_id == job.id).all()
        job.total_images = len(items)
        job.success_count = sum(1 for item in items if item.status == "success")
        job.skipped_count = sum(1 for item in items if item.status == "skipped")
        job.failed_count = sum(1 for item in items if item.status == "failed")
        job.processed_images = job.success_count + job.skipped_count + job.failed_count

    @staticmethod
    def _save_extraction_to_asset(
        local_db: Session, asset: DocumentAsset, metadata: dict,
        extraction_result: dict, storage: FileStorageService, document_id: int
    ) -> str | None:
        """保存提取结果到资产元数据和文件存储。返回 csv_rel_path 或 None。"""
        csv_temp_path = Path(extraction_result["csv_path"])
        if not csv_temp_path.exists():
            return None
        csv_rel_path = f"papers/{document_id}/extractions/asset_{asset.id}_coordinates.csv"
        csv_dest = storage.get_file_path(csv_rel_path)
        csv_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(csv_temp_path, csv_dest)

        metadata["coordinate_preview"] = {
            "status": extraction_result.get("review_status", "accepted"),
            "coordinate_csv_path": csv_rel_path,
            "row_count": extraction_result.get("row_count", 0),
            "data_quality": extraction_result.get("data_quality", "good"),
            "needs_review": extraction_result.get("needs_review", False),
        }
        metadata["agent_analysis_status"] = "success"
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)
        local_db.add(asset)
        return csv_rel_path
