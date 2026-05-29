from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import app_now
from app.db.session import SessionLocal, get_db
from app.models import Document, DocumentAsset, DocumentEvent, ExtractionJob, ExtractionResult, User
from app.schemas.paper import ExtractionJobListItem, ExtractionJobRead, ExtractionResultRead, ExtractionRunRequest
from app.services.agent import AgentResultMapper, CoordinatorAdapter, PaperDataAdapter
from app.services.paper.evidence import asset_bbox, asset_image_url, asset_metadata, is_visual_evidence, normalize_evidence_type

router = APIRouter(prefix="/extractions", tags=["extractions"])
logger = logging.getLogger(__name__)


def _paper_or_404(db: Session, paper_id: int, user: User) -> Document:
    paper = db.get(Document, paper_id)
    if paper is None or paper.user_id != user.id or paper.source_type != "pdf":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
    return paper


def _ensure_extractable(paper: Document) -> None:
    if paper.status != "done":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文档解析完成后才能开始提取")


def _job_or_404(db: Session, job_id: int, user: User) -> ExtractionJob:
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found.")
    _paper_or_404(db, job.paper_id, user)
    return job


def _load_sources(db: Session, paper_id: int) -> tuple[list[DocumentAsset], list[DocumentAsset]]:
    figure_candidates = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper_id, DocumentAsset.asset_type.in_(["figure", "page_snapshot"]))
        .order_by(DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    figures = [asset for asset in figure_candidates if is_visual_evidence(asset)]
    tables = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper_id, DocumentAsset.asset_type == "table")
        .order_by(DocumentAsset.asset_index.asc().nullslast(), DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    return figures, tables


def _assets_by_id(db: Session, results: list[ExtractionResult]) -> dict[int, DocumentAsset]:
    asset_ids = sorted({result.source_id for result in results if result.source_id is not None and result.source_type in {"asset", "figure", "table"}})
    if not asset_ids:
        return {}
    assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
    return {asset.id: asset for asset in assets}


def _result_read(result: ExtractionResult, assets_by_id: dict[int, DocumentAsset]) -> ExtractionResultRead:
    asset = assets_by_id.get(result.source_id) if result.source_id is not None else None
    metadata = asset_metadata(asset)
    evidence_type = normalize_evidence_type(source_type=result.source_type, asset=asset, metadata=metadata)
    image_url = asset_image_url(asset)
    caption = None
    source = None
    if asset is not None:
        caption = asset.caption or str(metadata.get("caption") or metadata.get("figure_label") or metadata.get("table_label") or "") or None
        source = str(metadata.get("source") or asset.asset_type) or None
    return ExtractionResultRead(
        id=result.id,
        job_id=result.job_id,
        source_type=result.source_type,
        source_id=result.source_id,
        field_name=result.field_name,
        content=result.content,
        evidence=result.evidence,
        confidence=result.confidence,
        evidence_type=evidence_type,
        image_url=image_url,
        thumbnail_url=image_url,
        page=asset.page_number if asset is not None else None,
        bbox=asset_bbox(metadata),
        caption=caption,
        source=source,
        created_at=result.created_at,
    )


def _job_read(db: Session, job: ExtractionJob) -> ExtractionJobRead:
    results = sorted(job.results, key=lambda result: result.id)
    assets_by_id = _assets_by_id(db, results)
    return ExtractionJobRead(
        id=job.id,
        paper_id=job.paper_id,
        query=job.query,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        results=[_result_read(result, assets_by_id) for result in results],
    )


def _log_event(db: Session, paper: Document, event_type: str, message: str, metadata: dict | None = None) -> None:
    db.add(
        DocumentEvent(
            document_id=paper.id,
            user_id=paper.user_id,
            event_type=event_type,
            message=message[:500],
            event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )
    )


def _run_job(db: Session, job: ExtractionJob, paper: Document) -> ExtractionJob:
    _ensure_extractable(paper)
    job.status = "running"
    job.error_message = None
    job.updated_at = app_now()
    db.commit()
    try:
        figures, tables = _load_sources(db, paper.id)
        paper_data = PaperDataAdapter().build(paper=paper, figures=figures, tables=tables)
        db.commit()
        final_results, events = CoordinatorAdapter().run(paper=paper_data, user_query=job.query)
        rows = AgentResultMapper().map_results(job_id=job.id, final_results=final_results, figures=figures, tables=tables)
        db.query(ExtractionResult).filter(ExtractionResult.job_id == job.id).delete(synchronize_session=False)
        for row in rows:
            db.add(row)
        job.status = "done"
        job.error_message = None
        job.updated_at = app_now()
        _log_event(db, paper, "extraction_done", "论文 Agent 提取完成。", {"job_id": job.id, "result_count": len(rows), "event_count": len(events)})
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
            _log_event(db, paper, "extraction_failed", str(exc), {"job_id": job.id if job else None, "error": str(exc)})
        db.commit()
        if job is None:
            raise
        return job


def _run_job_by_id(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, job_id)
        if job is None:
            logger.warning("Extraction job %s disappeared before it could run", job_id)
            return
        paper = db.get(Document, job.paper_id)
        if paper is None:
            logger.warning("Extraction job %s has no paper %s", job_id, job.paper_id)
            return
        _run_job(db, job, paper)


def _schedule_job(background_tasks: BackgroundTasks, job_id: int) -> None:
    background_tasks.add_task(_run_job_by_id, job_id)


@router.post("/run", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def run_extraction(payload: ExtractionRunRequest, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    paper = _paper_or_404(db, payload.paperId, current_user)
    _ensure_extractable(paper)
    job = ExtractionJob(paper_id=paper.id, query=payload.query, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    _schedule_job(background_tasks, job.id)
    return job


@router.post("/{job_id}/retry", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def retry_extraction(job_id: int, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    old_job = _job_or_404(db, job_id, current_user)
    paper = _paper_or_404(db, old_job.paper_id, current_user)
    _ensure_extractable(paper)
    new_job = ExtractionJob(paper_id=paper.id, query=old_job.query, status="pending")
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    _schedule_job(background_tasks, new_job.id)
    return new_job


@router.get("", response_model=list[ExtractionJobListItem])
async def list_extractions(paper_id: int | None = Query(None, ge=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ExtractionJobListItem]:
    if paper_id is not None:
        _paper_or_404(db, paper_id, current_user)
    query = (
        db.query(ExtractionJob, Document)
        .join(Document, ExtractionJob.paper_id == Document.id)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.status != "deleted")
    )
    if paper_id is not None:
        query = query.filter(ExtractionJob.paper_id == paper_id)
    rows = query.order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()).all()
    return [
        ExtractionJobListItem(
            id=job.id,
            paper_id=paper.id,
            paper_title=paper.title,
            query=job.query,
            status=job.status,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            result_count=len(job.results),
        )
        for job, paper in rows
    ]


@router.get("/{job_id}", response_model=ExtractionJobRead)
async def get_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    return _job_read(db, _job_or_404(db, job_id, current_user))
