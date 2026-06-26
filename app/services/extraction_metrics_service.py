"""Extraction metrics service — calculates dashboard metrics for extraction jobs.

Consolidates the metrics logic that was previously in the route handler,
making it testable and reusable.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from app.core.config import EXTRACTION_QUEUE_NAME
from app.core.time import app_now
from app.models import ExtractionJob
from app.queue.redis_queue import RedisQueue
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.document_repository import DocumentRepository

logger = logging.getLogger(__name__)


def _duration_seconds(start, end):
    """Calculate duration between two datetimes, handling timezone-naive/aware mismatch."""
    if start is None or end is None:
        return None
    if start.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif start.tzinfo is not None and end.tzinfo is None:
        start = start.replace(tzinfo=None)
    return max(0.0, (end - start).total_seconds())


def _extraction_queue_size() -> int | None:
    """Get the current extraction queue size."""
    try:
        return int(RedisQueue(queue_name=EXTRACTION_QUEUE_NAME).size())
    except Exception:
        logger.exception("Failed to read extraction queue size")
        return None


class ExtractionMetricsService:
    """Calculates extraction dashboard metrics."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.extraction_repo = ExtractionRepository(db)

    def get_metrics(self, user_id: int) -> dict:
        """Compute all extraction dashboard metrics for a user."""
        now = app_now()
        repo = self.extraction_repo

        # Base counts
        total = repo.get_job_count(user_id)
        by_status = repo.get_job_status_counts(user_id)
        done = by_status.get("done", 0)
        failed = by_status.get("failed", 0)
        pending = by_status.get("pending", 0)
        running = by_status.get("running", 0)
        finished = done + failed
        success_rate = round((done / finished) * 100, 1) if finished else None

        # Recent activity
        recent_7_days = repo.get_recent_job_count(user_id, days=7)

        # Duration calculations
        finished_jobs = repo.get_finished_jobs(user_id)
        durations = [
            d
            for job in finished_jobs
            if (d := _duration_seconds(job.created_at, job.updated_at)) is not None
        ]
        avg_duration_seconds = (
            round(sum(durations) / len(durations), 1) if durations else None
        )

        # Active job
        active_jobs = repo.get_active_jobs(user_id)
        active_job = active_jobs[0] if active_jobs else None
        active_job_elapsed_seconds = (
            round(d, 1)
            if active_job and (d := _duration_seconds(active_job.created_at, now)) is not None
            else None
        )

        # Latest finished job
        latest_finished_job = repo.get_latest_finished_job(user_id)
        latest_finished_duration_seconds = (
            round(d, 1)
            if latest_finished_job
            and (d := _duration_seconds(latest_finished_job.created_at, latest_finished_job.updated_at)) is not None
            else None
        )
        latest_finished_result_count = (
            repo.get_result_count_for_job(latest_finished_job.id)
            if latest_finished_job
            else None
        )

        # Active figure count
        active_paper_ids = repo.get_active_paper_ids(user_id)
        doc_repo = DocumentRepository(self.db)
        active_figure_count = doc_repo.count_active_figures(active_paper_ids)

        return {
            "queue_name": EXTRACTION_QUEUE_NAME,
            "queue_size": _extraction_queue_size(),
            "total_jobs": total,
            "pending_jobs": pending,
            "running_jobs": running,
            "done_jobs": done,
            "failed_jobs": failed,
            "recent_7_days": recent_7_days,
            "success_rate": success_rate,
            "avg_duration_seconds": avg_duration_seconds,
            "active_job_id": active_job.id if active_job else None,
            "active_job_status": active_job.status if active_job else None,
            "active_job_elapsed_seconds": active_job_elapsed_seconds,
            "latest_finished_job_id": latest_finished_job.id if latest_finished_job else None,
            "latest_finished_status": latest_finished_job.status if latest_finished_job else None,
            "latest_finished_duration_seconds": latest_finished_duration_seconds,
            "latest_finished_result_count": latest_finished_result_count,
            "active_figure_count": int(active_figure_count),
            "visual_max_workers": _env_int("VISUAL_LLM_MAX_WORKERS", 4),
            "llm_max_concurrency": _env_int("LLM_MAX_CONCURRENCY", 4),
            "llm_min_request_interval_seconds": _env_float("LLM_MIN_REQUEST_INTERVAL_SECONDS", 0.8),
        }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
