"""Extraction job service — now a compatibility shell over ExtractionServiceV2.

The old agent-based coordinator (CoordinatorAdapter + VisualBatchAgent + ...)
has been replaced by the new structured pipeline (ExtractionServiceV2).

This module:
- Keeps the ``ExtractionJob`` / ``ExtractionResult`` models as a read-only
  compatibility shell for existing API consumers.
- When ``run_extraction_job()`` is called, delegates to ``ExtractionServiceV2``
  which writes to ``extraction_runs`` / ``extraction_items`` / ``extraction_evidence``.
- No longer writes back to ``DocumentAsset.metadata_json``.
- No longer uses the old agent coordinator or result mapper.
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.db.session import SessionLocal
from app.models import Document, DocumentAsset, DocumentEvent, ExtractionJob, ExtractionResult
from app.services.content_extraction.pipeline import ContentExtractionPipeline

logger = logging.getLogger(__name__)

EXTRACTION_PHASE_EVENT = "extraction_phase"
IMAGE_ASSET_SCOPE_RE = re.compile(r"\[IMAGE_ASSET_SCOPE\s+asset_id=(\d+)\b")


def ensure_extractable(paper: Document) -> None:
    if paper.status != "done":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文档解析完成后才能开始提取",
        )


def log_extraction_event(
    db: Session,
    paper: Document,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        DocumentEvent(
            document_id=paper.id,
            user_id=paper.user_id,
            event_type=event_type,
            message=message[:500],
            event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )
    )


def log_extraction_phase(
    db: Session,
    paper: Document,
    job: ExtractionJob,
    phase: str,
    status_value: str,
    message: str,
    *,
    run_id: int | None = None,
) -> None:
    log_extraction_event(
        db,
        paper,
        EXTRACTION_PHASE_EVENT,
        message,
        {
            "job_id": job.id,
            "extraction_run_id": run_id,
            "phase": phase.upper(),
            "status": status_value,
            "message": message,
        },
    )


def run_extraction_job_by_id(job_id: int) -> None:
    """Entry point called by the Redis queue worker."""
    with SessionLocal() as db:
        job = db.get(ExtractionJob, job_id)
        if job is None:
            logger.warning(
                "Extraction job %s disappeared before it could run", job_id
            )
            return
        paper = db.get(Document, job.paper_id)
        if paper is None:
            logger.warning(
                "Extraction job %s has no paper %s", job_id, job.paper_id
            )
            return
        run_extraction_job(db, job, paper)


def run_extraction_job(
    db: Session, job: ExtractionJob, paper: Document
) -> ExtractionJob:
    """Run an extraction job using the enhanced v2 pipeline.

    ✅ 新特性：
    1. 用户query作为核心提示词（不再解析为indicators列表）
    2. 并行处理图表（从旧Agent系统继承）
    3. 确保所有图表都被覆盖（从旧Agent系统继承）
    4. 灵活的提取模式（quick/standard/deep）

    Results are written to ``extraction_runs`` / ``extraction_items`` / ``extraction_evidence``.
    A compatibility projection to ``ExtractionResult`` rows is maintained for
    existing API consumers.
    """
    try:
        ensure_extractable(paper)
        job.status = "running"
        job.error_message = None
        job.updated_at = app_now()
        log_extraction_event(
            db,
            paper,
            "extraction_started",
            "内容提取开始",
            {"job_id": job.id, "query": job.query[:200]},
        )
        db.commit()

        def record_progress(run, phase: str, message: str) -> None:
            if run.legacy_job_id is None:
                run.legacy_job_id = job.id
            log_extraction_phase(
                db,
                paper,
                job,
                phase,
                run.status or job.status,
                message,
                run_id=run.id,
            )
            db.commit()

        service = ContentExtractionPipeline()
        run = service.run(
            db=db,
            paper=paper,
            user_query=job.query,
            mode="auto",
            progress_callback=record_progress,
        )
        if run.status == "failed":
            raise RuntimeError(run.error_message or "内容提取管线失败")

        # Link the legacy job to the new run
        run.legacy_job_id = job.id
        job.status = "done"
        job.error_message = None
        job.updated_at = app_now()

        # Project new items to legacy ExtractionResult rows for backward compat
        _project_to_legacy_results(db, job, run)

        log_extraction_event(
            db,
            paper,
            "extraction_done",
            "内容提取完成",
            {
                "job_id": job.id,
                "extraction_run_id": run.id,
                "status": run.status,
                "summary": run.summary,
            },
        )
        db.commit()
        db.refresh(job)
        return job

    except Exception as exc:
        logger.exception("Extraction job %s failed", job.id)
        db.rollback()
        job = db.get(ExtractionJob, job.id)
        paper = db.get(Document, paper.id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.updated_at = app_now()
        if paper is not None:
            log_extraction_event(
                db,
                paper,
                "extraction_failed",
                f"内容提取失败: {exc}",
                {
                    "job_id": job.id if job else None,
                    "error": str(exc),
                },
            )
        db.commit()
        if job is None:
            raise
        return job


def _project_to_legacy_results(
    db: Session,
    job: ExtractionJob,
    run,  # ExtractionRun
) -> None:
    """
    DEPRECATED: Project new extraction_items to legacy ExtractionResult rows.

    This maintains backward compatibility for existing API consumers while
    the new extraction_runs/items/evidence tables are the canonical source.

    NOTE: This deletes and recreates old results on every run, which means
    any data written directly to ExtractionResult by external consumers
    will be lost. Migrate consumers to the v2 API to avoid data loss.
    """
    # Clear old results
    (
        db.query(ExtractionResult)
        .filter(ExtractionResult.job_id == job.id)
        .delete(synchronize_session=False)
    )

    from app.models.extraction_v2 import ExtractionItem, ExtractionEvidence

    items = (
        db.query(ExtractionItem)
        .filter(ExtractionItem.run_id == run.id)
        .all()
    )

    for item in items:
        notes = _safe_load_json(item.verification_notes) if item.verification_notes else {}
        status = notes.get("status")
        if status == "sufficient":
            parse_status = "success"
        elif status == "conflicted":
            parse_status = "conflict"
        elif status == "insufficient":
            parse_status = "partial"
        else:
            parse_status = "unsupported"

        # Determine source_type and source_id from evidence
        evidence_records = (
            db.query(ExtractionEvidence)
            .filter(ExtractionEvidence.item_id == item.id)
            .all()
        )
        source_type = item.source_type or "text"
        source_id = None
        caption = None
        for ev in evidence_records:
            if ev.source_type == "figure" and ev.source_id:
                source_type = "asset"
                source_id = ev.source_id
                caption = ev.excerpt
                break
            elif ev.source_type == "table" and ev.source_id:
                source_type = "asset"
                source_id = ev.source_id
                break

        # Build structured_data from the item
        structured_data = None
        if item.data_points_json:
            structured_data = json.dumps(
                {
                    "x_axis": {
                        "label": item.x_axis_label,
                        "unit": item.x_axis_unit,
                        "scale": item.x_axis_scale,
                    },
                    "y_axis": {
                        "label": item.y_axis_label,
                        "unit": item.y_axis_unit,
                        "scale": item.y_axis_scale,
                    },
                    "series": item.series_name,
                    "data_points": item.data_points_json,
                },
                ensure_ascii=False,
            )

        db.add(
            ExtractionResult(
                job_id=job.id,
                source_type=source_type,
                source_id=source_id,
                field_name=item.indicator,
                content=item.value_text or "",
                evidence=(
                    caption or item.verification_notes or ""
                ),
                confidence=item.confidence,
                figure_id=item.figure_label,
                caption=caption,
                notes=item.verification_notes,
                structured_data=structured_data,
                parse_status=parse_status,
                extraction_mode=item.extraction_method,
            )
        )


def _safe_load_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
