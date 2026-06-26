"""Extraction repository — encapsulates all extraction-related DB queries.

Consolidates queries previously scattered across routes, services, and
presentation layers into a single responsible data-access layer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import (
    Document,
    DocumentAsset,
    DocumentEvent,
    ExtractionEvidence,
    ExtractionItem,
    ExtractionJob,
    ExtractionResult,
    ExtractionRun,
    User,
)
from app.repositories.base import BaseRepository
from app.services.extraction.constants import PHASE_BASE_PERCENT


class ExtractionRepository(BaseRepository[ExtractionJob]):
    """Repository for all extraction-related data access."""

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Legacy Job CRUD ───────────────────────────────────────────────

    def create_job(
        self, paper_id: int, query: str, status: str = "pending"
    ) -> ExtractionJob:
        job = ExtractionJob(paper_id=paper_id, query=query, status=status)
        self._db.add(job)
        self._db.flush()
        return job

    def get_job(self, job_id: int) -> ExtractionJob | None:
        return self._db.get(ExtractionJob, job_id)

    def get_job_or_404(self, job_id: int) -> ExtractionJob:
        from fastapi import HTTPException, status
        job = self._db.get(ExtractionJob, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Extraction job not found.",
            )
        return job

    def get_jobs_for_user(
        self, user_id: int, paper_id: int | None = None
    ) -> list[tuple[ExtractionJob, Document]]:
        """List extraction jobs for a user, ordered newest first."""
        query = (
            self._db.query(ExtractionJob, Document)
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(
                Document.user_id == user_id,
                Document.source_type == "pdf",
                Document.is_deleted == False,
            )
        )
        if paper_id is not None:
            query = query.filter(ExtractionJob.paper_id == paper_id)
        return (
            query.order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
            .all()
        )

    # ── Legacy Result queries ─────────────────────────────────────────

    def delete_results_for_job(self, job_id: int) -> None:
        """Delete all legacy results for a job (used during reprojection)."""
        (
            self._db.query(ExtractionResult)
            .filter(ExtractionResult.job_id == job_id)
            .delete(synchronize_session=False)
        )

    def get_result_count_for_job(self, job_id: int) -> int:
        return (
            self._db.query(func.count(ExtractionResult.id))
            .filter(ExtractionResult.job_id == job_id)
            .scalar()
            or 0
        )

    # ── Metrics ───────────────────────────────────────────────────────

    def get_metrics_base_query(self, user_id: int):
        """Return base query for extraction metrics calculation."""
        return (
            self._db.query(ExtractionJob)
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(
                Document.user_id == user_id,
                Document.source_type == "pdf",
                Document.is_deleted == False,
            )
        )

    def get_job_status_counts(self, user_id: int) -> dict[str, int]:
        """Get counts of jobs by status for a user."""
        rows = (
            self._db.query(ExtractionJob.status, func.count(ExtractionJob.id))
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(
                Document.user_id == user_id,
                Document.source_type == "pdf",
                Document.is_deleted == False,
            )
            .group_by(ExtractionJob.status)
            .all()
        )
        return {str(status_value): int(count) for status_value, count in rows}

    def get_active_jobs(self, user_id: int) -> list[ExtractionJob]:
        """Get pending/running jobs for a user."""
        base = self.get_metrics_base_query(user_id)
        return (
            base.filter(ExtractionJob.status.in_(["pending", "running"]))
            .order_by(ExtractionJob.created_at.asc(), ExtractionJob.id.asc())
            .all()
        )

    def get_active_paper_ids(self, user_id: int) -> list[int]:
        """Get distinct paper IDs with active extraction jobs."""
        base = self.get_metrics_base_query(user_id)
        rows = (
            base.filter(ExtractionJob.status.in_(["pending", "running"]))
            .with_entities(ExtractionJob.paper_id)
            .distinct()
            .all()
        )
        return [row[0] for row in rows]

    def get_finished_jobs(self, user_id: int) -> list[ExtractionJob]:
        """Get all done or failed jobs for a user."""
        base = self.get_metrics_base_query(user_id)
        return base.filter(ExtractionJob.status.in_(["done", "failed"])).all()

    def get_latest_finished_job(self, user_id: int) -> ExtractionJob | None:
        """Get the most recently updated finished job."""
        base = self.get_metrics_base_query(user_id)
        return (
            base.filter(ExtractionJob.status.in_(["done", "failed"]))
            .order_by(ExtractionJob.updated_at.desc(), ExtractionJob.id.desc())
            .first()
        )

    def get_recent_job_count(self, user_id: int, days: int = 7) -> int:
        """Count jobs created in the last N days."""
        base = self.get_metrics_base_query(user_id)
        since = app_now() - timedelta(days=days)
        return base.filter(ExtractionJob.created_at >= since).count()

    def get_job_count(self, user_id: int) -> int:
        """Get total job count for a user."""
        return self.get_metrics_base_query(user_id).count()

    # ── V2 Run / Item / Evidence ──────────────────────────────────────

    def get_run(self, run_id: int) -> ExtractionRun | None:
        return self._db.get(ExtractionRun, run_id)

    def get_run_for_job(self, job_id: int) -> ExtractionRun | None:
        return (
            self._db.query(ExtractionRun)
            .filter(ExtractionRun.legacy_job_id == job_id)
            .order_by(ExtractionRun.id.desc())
            .first()
        )

    def get_runs_for_paper(
        self,
        paper_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[ExtractionRun]]:
        """List extraction runs for a paper with pagination."""
        query = self._db.query(ExtractionRun).filter(
            ExtractionRun.paper_id == paper_id,
            ExtractionRun.is_deleted == False,
        )
        if status:
            query = query.filter(ExtractionRun.status == status)
        total = query.count()
        runs = (
            query.order_by(ExtractionRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, runs

    def get_items_for_run(
        self,
        run_id: int,
        source_type: str | None = None,
        verified: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[ExtractionItem]]:
        """List items for a run with optional filtering."""
        query = self._db.query(ExtractionItem).filter(
            ExtractionItem.run_id == run_id
        )
        if source_type:
            query = query.filter(ExtractionItem.source_type == source_type)
        if verified is not None:
            query = query.filter(ExtractionItem.verified == verified)
        total = query.count()
        items = (
            query.order_by(ExtractionItem.id).offset(offset).limit(limit).all()
        )
        return total, items

    def get_all_items_for_run(self, run_id: int) -> list[ExtractionItem]:
        return (
            self._db.query(ExtractionItem)
            .filter(ExtractionItem.run_id == run_id)
            .order_by(ExtractionItem.id)
            .all()
        )

    def get_evidence_for_items(
        self, item_ids: list[int]
    ) -> list[ExtractionEvidence]:
        if not item_ids:
            return []
        return (
            self._db.query(ExtractionEvidence)
            .filter(ExtractionEvidence.item_id.in_(item_ids))
            .order_by(ExtractionEvidence.id.asc())
            .all()
        )

    def get_evidence_for_item(self, item_id: int) -> list[ExtractionEvidence]:
        return (
            self._db.query(ExtractionEvidence)
            .filter(ExtractionEvidence.item_id == item_id)
            .all()
        )

    def get_item_count_for_run(self, run_id: int) -> int:
        return (
            self._db.query(func.count(ExtractionItem.id))
            .filter(ExtractionItem.run_id == run_id)
            .scalar()
            or 0
        )

    def get_run_item_counts(
        self, job_ids: list[int]
    ) -> dict[int, int]:
        """Get item counts for runs linked to the given legacy job IDs."""
        if not job_ids:
            return {}
        rows = (
            self._db.query(ExtractionRun.legacy_job_id, func.count(ExtractionItem.id))
            .join(ExtractionItem, ExtractionItem.run_id == ExtractionRun.id)
            .filter(ExtractionRun.legacy_job_id.in_(job_ids))
            .group_by(ExtractionRun.legacy_job_id)
            .all()
        )
        return {int(job_id): int(count) for job_id, count in rows if job_id is not None}
