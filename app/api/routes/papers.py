from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentAsset, ExtractionJob, PaperTable, User
from app.schemas.paper import PaperDetailResponse, PaperFigureRead, PaperListItem, PaperTableRead, PaperUploadResponse
from app.services.file_storage import FileStorageService
from app.services.paper_demo_service import PaperDemoService

router = APIRouter(prefix="/papers", tags=["papers"])


def _paper_or_404(db: Session, paper_id: int, user: User) -> Document:
    paper = db.get(Document, paper_id)
    if paper is None or paper.user_id != user.id or paper.source_type != "pdf":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
    return paper


def _figure_read(asset: DocumentAsset) -> PaperFigureRead:
    import json

    metadata = {}
    if asset.metadata_json:
        try:
            metadata = json.loads(asset.metadata_json)
        except Exception:
            metadata = {}
    return PaperFigureRead(
        id=asset.id,
        paper_id=asset.document_id,
        image_path=f"/papers/assets/{asset.id}",
        figure_label=str(metadata.get("figure_label") or f"Figure {asset.id}"),
        caption=str(metadata.get("caption") or ""),
        page=asset.page_number,
        created_at=asset.created_at,
    )


def _detail(db: Session, paper: Document) -> PaperDetailResponse:
    figures = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper.id, DocumentAsset.asset_type.in_(["paper_figure", "paper_page_snapshot"]))
        .order_by(DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    tables = db.query(PaperTable).filter(PaperTable.paper_id == paper.id).order_by(PaperTable.created_at.asc(), PaperTable.id.asc()).all()
    latest_job = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.paper_id == paper.id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
        .first()
    )
    return PaperDetailResponse(
        id=paper.id,
        user_id=paper.user_id,
        title=paper.title,
        file_path=paper.original_file_path,
        status=paper.status,
        parse_error=paper.fail_reason or paper.error_message,
        text_content=paper.cleaned_text or paper.parsed_text,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        figures=[_figure_read(asset) for asset in figures],
        tables=[PaperTableRead.model_validate(table) for table in tables],
        latest_extraction_job=latest_job,
    )


@router.post("/upload", response_model=PaperUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_paper(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperUploadResponse:
    try:
        paper = await PaperDemoService(db).upload_pdf(file=file, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaperUploadResponse(id=paper.id, title=paper.title, status=paper.status)


@router.get("", response_model=list[PaperListItem])
async def list_papers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PaperListItem]:
    papers = (
        db.query(Document)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.status != "deleted")
        .order_by(Document.created_at.desc())
        .all()
    )
    return [PaperListItem(id=paper.id, title=paper.title, status=paper.status, created_at=paper.created_at, updated_at=paper.updated_at) for paper in papers]


@router.get("/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(paper_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperDetailResponse:
    return _detail(db, _paper_or_404(db, paper_id, current_user))


@router.post("/{paper_id}/parse", response_model=PaperDetailResponse)
async def parse_paper(paper_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperDetailResponse:
    paper = _paper_or_404(db, paper_id, current_user)
    try:
        parsed = PaperDemoService(db).parse(paper)
    except Exception as exc:
        failed = db.get(Document, paper_id)
        if failed is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.") from exc
        return _detail(db, failed)
    return _detail(db, parsed)


@router.get("/assets/{asset_id}")
async def get_paper_asset(asset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(DocumentAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    paper = _paper_or_404(db, asset.document_id, current_user)
    if paper.id != asset.document_id or not asset.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    path = FileStorageService().get_file_path(asset.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found.")
    return FileResponse(path=path, media_type=asset.mime_type or "image/png")
