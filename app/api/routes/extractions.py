from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import app_now
from app.db.session import get_db
from app.models import Document, DocumentAsset, ExtractionJob, ExtractionResult, PaperTable, User
from app.schemas.paper import ExtractionJobRead, ExtractionRunRequest
from app.services.agent import AgentResultMapper, CoordinatorAdapter, PaperDataAdapter

router = APIRouter(prefix="/extractions", tags=["extractions"])


def _paper_or_404(db: Session, paper_id: int, user: User) -> Document:
    paper = db.get(Document, paper_id)
    if paper is None or paper.user_id != user.id or paper.source_type != "pdf":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
    return paper


def _job_or_404(db: Session, job_id: int, user: User) -> ExtractionJob:
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found.")
    _paper_or_404(db, job.paper_id, user)
    return job


def _load_sources(db: Session, paper_id: int) -> tuple[list[DocumentAsset], list[PaperTable]]:
    figures = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper_id, DocumentAsset.asset_type.in_(["paper_figure", "paper_page_snapshot"]))
        .order_by(DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    tables = db.query(PaperTable).filter(PaperTable.paper_id == paper_id).order_by(PaperTable.created_at.asc(), PaperTable.id.asc()).all()
    return figures, tables


def _run_job(db: Session, job: ExtractionJob, paper: Document) -> ExtractionJob:
    job.status = "running"
    job.error_message = None
    job.updated_at = app_now()
    paper.status = "extracting"
    db.commit()
    try:
        figures, tables = _load_sources(db, paper.id)
        paper_data = PaperDataAdapter().build(paper=paper, figures=figures, tables=tables)
        final_results, events = CoordinatorAdapter().run(paper=paper_data, user_query=job.query)
        rows = AgentResultMapper().map_results(job_id=job.id, final_results=final_results, figures=figures, tables=tables)
        db.query(ExtractionResult).filter(ExtractionResult.job_id == job.id).delete(synchronize_session=False)
        for row in rows:
            db.add(row)
        job.status = "done"
        job.error_message = None
        job.updated_at = app_now()
        paper.status = "done"
        paper.updated_at = app_now()
        db.commit()
        db.refresh(job)
        return job
    except Exception as exc:
        db.rollback()
        job = db.get(ExtractionJob, job.id)
        paper = db.get(Document, paper.id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.updated_at = app_now()
        if paper is not None:
            paper.status = "failed"
            paper.error_message = str(exc)
            paper.fail_reason = str(exc)
            paper.updated_at = app_now()
        db.commit()
        if job is None:
            raise
        return job


@router.post("/run", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def run_extraction(payload: ExtractionRunRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    paper = _paper_or_404(db, payload.paperId, current_user)
    job = ExtractionJob(paper_id=paper.id, query=payload.query, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return _run_job(db, job, paper)


@router.post("/{job_id}/retry", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def retry_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    old_job = _job_or_404(db, job_id, current_user)
    paper = _paper_or_404(db, old_job.paper_id, current_user)
    new_job = ExtractionJob(paper_id=paper.id, query=old_job.query, status="pending")
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return _run_job(db, new_job, paper)


@router.get("/{job_id}", response_model=ExtractionJobRead)
async def get_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    return _job_or_404(db, job_id, current_user)
