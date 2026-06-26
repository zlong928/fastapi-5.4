"""
Extraction API routes — thin layer: param validation + service delegation.

Business logic lives in:
- ``app.repositories`` for data access
- ``app.services.extraction_metrics_service`` for metrics
- ``app.services.extraction_read_service`` for reading/presenting
- ``app.services.extraction_progress_service`` for progress
- ``app.services.extraction_job_service`` for job orchestration
- ``app.services.export_service`` for exports
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentAsset, ExtractionJob, User
from app.queue.extraction_queue import enqueue_extraction
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.schemas.paper import (
    BatchExtractionResultItem,
    BatchExtractionRunRequest,
    ExtractionJobListItem,
    ExtractionJobRead,
    ExtractionRunRequest,
    StructuredExtractionResponse,
)
from app.services.extraction_job_service import (
    ensure_extractable,
    log_extraction_event,
)
from app.services.extraction_metrics_service import ExtractionMetricsService
from app.services.extraction_read_service import ExtractionReadService
from app.services.export_service import ExportService

router = APIRouter(prefix="/extractions", tags=["extractions"])
logger = logging.getLogger(__name__)

# ── Regex for scoped image asset queries ───────────────────────────────
IMAGE_ASSET_SCOPE_RE = re.compile(r"\[IMAGE_ASSET_SCOPE\s+asset_id=(\d+)\b")


def _scoped_image_asset_id(query: str) -> int | None:
    match = IMAGE_ASSET_SCOPE_RE.search(query)
    if not match:
        return None
    return int(match.group(1))


def _image_asset_scoped_query(query: str, asset: DocumentAsset) -> str:
    """Wrap a query with image asset scoping instructions."""
    from app.services.paper.evidence import asset_metadata
    metadata = asset_metadata(asset)
    label = str(metadata.get("figure_label") or asset.label or f"Asset {asset.id}")
    caption = str(metadata.get("caption") or asset.caption or "")
    page = f"p.{asset.page_number}" if asset.page_number else "unknown page"
    context = (
        f"[IMAGE_ASSET_SCOPE asset_id={asset.id} figure_label=\"{label}\" page=\"{page}\"]\n"
        f"只处理这一个图片资产，不要分析其他图片、正文或表格。图片说明：{caption}\n"
        f"用户提取目标：{query.strip()}"
    )
    return context[:2000]


def _schedule_job(job_id: int) -> None:
    """Enqueue an extraction job."""
    enqueue_extraction(job_id)


def _schedule_job_or_fail(db: Session, paper: Document, job: ExtractionJob) -> bool:
    """Enqueue a job; mark it failed if enqueue fails."""
    from app.core.time import app_now
    try:
        _schedule_job(job.id)
        return True
    except Exception as exc:
        logger.exception("Failed to enqueue extraction job %s", job.id)
        job.status = "failed"
        job.error_message = f"提取任务入队失败: {exc}"
        job.updated_at = app_now()
        log_extraction_event(db, paper, "extraction_enqueue_failed", str(exc), {"job_id": job.id, "error": str(exc)})
        db.commit()
        return False


# ── Routes ─────────────────────────────────────────────────────────────


@router.post("/run", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def run_extraction(
    payload: ExtractionRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExtractionJobRead:
    """Run a new extraction job."""
    doc_repo = DocumentRepository(db)
    extraction_repo = ExtractionRepository(db)

    paper = doc_repo.get_paper_or_404(payload.paperId, current_user)
    ensure_extractable(paper)

    query = payload.query
    if payload.assetId is not None:
        asset = doc_repo.get_paper_asset_or_404(paper.id, payload.assetId)
        query = _image_asset_scoped_query(payload.query, asset)

    job = extraction_repo.create_job(paper_id=paper.id, query=query, status="pending")
    db.commit()

    if not _schedule_job_or_fail(db, paper, job):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="提取任务入队失败，请稍后重试",
        )

    read_service = ExtractionReadService(db)
    bundle = read_service.get_job_bundle(job.id)
    return read_service.get_job_read(bundle)


@router.post("/{job_id}/retry", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def retry_extraction(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExtractionJobRead:
    """Retry a failed extraction job."""
    doc_repo = DocumentRepository(db)
    extraction_repo = ExtractionRepository(db)

    old_job = extraction_repo.get_job_or_404(job_id)
    # Verify ownership via paper
    paper = doc_repo.get_paper_or_404(old_job.paper_id, current_user)
    ensure_extractable(paper)

    new_job = extraction_repo.create_job(paper_id=paper.id, query=old_job.query, status="pending")
    log_extraction_event(
        db, paper, "extraction_retry",
        f"重试提取任务（原任务 #{old_job.id}）。",
        {"old_job_id": old_job.id, "new_job_id": new_job.id},
    )
    db.commit()

    if not _schedule_job_or_fail(db, paper, new_job):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="提取任务入队失败，请稍后重试",
        )

    read_service = ExtractionReadService(db)
    bundle = read_service.get_job_bundle(new_job.id)
    return read_service.get_job_read(bundle)


@router.get("", response_model=list[ExtractionJobListItem])
async def list_extractions(
    paper_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ExtractionJobListItem]:
    """List extraction jobs for the current user."""
    if paper_id is not None:
        DocumentRepository(db).get_paper_or_404(paper_id, current_user)
    return ExtractionReadService(db).list_jobs(user_id=current_user.id, paper_id=paper_id)


@router.get("/metrics")
async def extraction_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get extraction dashboard metrics."""
    return ExtractionMetricsService(db).get_metrics(current_user.id)


@router.get("/{job_id}", response_model=ExtractionJobRead)
async def get_extraction(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExtractionJobRead:
    """Get a single extraction job with results."""
    # Verify ownership
    extraction_repo = ExtractionRepository(db)
    job = extraction_repo.get_job_or_404(job_id)
    DocumentRepository(db).get_paper_or_404(job.paper_id, current_user)

    read_service = ExtractionReadService(db)
    bundle = read_service.get_job_bundle(job.id)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found.")
    return read_service.get_job_read(bundle)


@router.post("/batch", response_model=list[BatchExtractionResultItem], status_code=status.HTTP_201_CREATED)
async def batch_run_extraction(
    payload: BatchExtractionRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchExtractionResultItem]:
    """Run extraction against multiple papers in batch."""
    results: list[BatchExtractionResultItem] = []
    jobs_to_schedule: list[tuple[ExtractionJob, Document]] = []

    for paper_id in payload.paper_ids:
        paper = db.get(Document, paper_id)
        if paper is None or paper.user_id != current_user.id or paper.source_type != "pdf":
            results.append(BatchExtractionResultItem(
                paper_id=paper_id, paper_title="", status="skipped", error="论文不存在或无权限",
            ))
            continue
        if paper.status != "done":
            results.append(BatchExtractionResultItem(
                paper_id=paper_id, paper_title=paper.title, status="skipped", error="文档未完成解析",
            ))
            continue
        job = ExtractionJob(paper_id=paper.id, query=payload.query, status="pending")
        db.add(job)
        log_extraction_event(db, paper, "extraction_started", "内容提取开始", {"query": payload.query[:200]})
        jobs_to_schedule.append((job, paper))

    if jobs_to_schedule:
        try:
            db.commit()
            for job, _ in jobs_to_schedule:
                db.refresh(job)
        except Exception as e:
            db.rollback()
            logger.exception("Failed to create batch extraction jobs")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"批量创建任务失败: {e}")

    for job, paper in jobs_to_schedule:
        if not _schedule_job_or_fail(db, paper, job):
            results.append(BatchExtractionResultItem(
                paper_id=paper.id, paper_title=paper.title, job_id=job.id, status="failed", error="提取任务入队失败",
            ))
            continue
        results.append(BatchExtractionResultItem(paper_id=paper.id, paper_title=paper.title, job_id=job.id, status="pending"))

    return results


@router.get("/{job_id}/structured", response_model=StructuredExtractionResponse)
async def get_structured_extraction(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StructuredExtractionResponse:
    """Get structured extraction results grouped by type."""
    extraction_repo = ExtractionRepository(db)
    job = extraction_repo.get_job_or_404(job_id)
    DocumentRepository(db).get_paper_or_404(job.paper_id, current_user)

    read_service = ExtractionReadService(db)
    bundle = read_service.get_job_bundle(job.id)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found.")
    return read_service.get_structured_extraction(bundle)


@router.post("/{job_id}/export")
async def export_extraction(
    job_id: int,
    format: str = Query("csv", pattern="^(csv|json|markdown|xlsx)$"),
    result_ids: list[int] | None = Query(None, description="Optional list of result IDs to export."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export a single extraction job to CSV, JSON, Markdown, or Excel."""
    extraction_repo = ExtractionRepository(db)
    job = extraction_repo.get_job_or_404(job_id)
    DocumentRepository(db).get_paper_or_404(job.paper_id, current_user)

    paper = db.get(Document, job.paper_id)
    safe_title = "".join(c for c in (paper.title[:30] if paper else "unknown") if c.isalnum() or c in "._- ")

    format_map = {
        "csv": ("text/csv", f"extraction_{job_id}_{safe_title}.csv", ExportService.export_extraction_to_csv),
        "json": ("application/json", f"extraction_{job_id}_{safe_title}.json", ExportService.export_extraction_to_json),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"extraction_{job_id}_{safe_title}.xlsx", ExportService.export_extraction_to_excel),
        "markdown": ("text/markdown", f"extraction_{job_id}_{safe_title}.md", ExportService.export_extraction_to_markdown),
    }
    media_type, filename, export_fn = format_map[format]

    content = export_fn(db, job, result_ids=result_ids)
    # Ensure bytes for xlsx
    if isinstance(content, bytes):
        content_type = media_type
    else:
        content_type = media_type

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/batch-export")
async def batch_export_extractions(
    job_ids: list[int] = Query(..., description="List of extraction job IDs to export"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export multiple extraction jobs to CSV or JSON."""
    if not job_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No job IDs provided")
    if len(job_ids) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 100 jobs can be exported at once")

    extraction_repo = ExtractionRepository(db)
    doc_repo = DocumentRepository(db)

    jobs = []
    for job_id in job_ids:
        job = extraction_repo.get_job(job_id)
        if job is None:
            logger.warning(f"Job {job_id} not found or not accessible by user {current_user.id}")
            continue
        # Verify ownership
        try:
            doc_repo.get_paper_or_404(job.paper_id, current_user)
            jobs.append(job)
        except HTTPException:
            logger.warning(f"Job {job_id} not accessible by user {current_user.id}")
            continue

    if not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No valid jobs found")

    if format == "csv":
        content = ExportService.export_batch_extractions_to_csv(db, jobs)
        media_type = "text/csv"
        filename = f"batch_extraction_{len(jobs)}_jobs.csv"
    else:
        content = ExportService.export_batch_extractions_to_json(db, jobs)
        media_type = "application/json"
        filename = f"batch_extraction_{len(jobs)}_jobs.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
