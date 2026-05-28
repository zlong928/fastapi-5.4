from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentAsset, ExtractionJob, PaperTable, User
from app.schemas.paper import PaperDetailResponse, PaperFigureRead, PaperListItem, PaperTableRead, PaperUploadResponse
from app.services.file_storage import FileStorageService
from app.services.paper_demo_service import PaperDemoService

router = APIRouter(prefix="/papers", tags=["papers"])
PAPER_ASSET_TYPES = ("figure", "page_snapshot")


def _paper_or_404(db: Session, paper_id: int, user: User) -> Document:
    paper = db.get(Document, paper_id)
    if paper is None or paper.user_id != user.id or paper.source_type != "pdf" or paper.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
    return paper


def _metadata_fallback(asset: DocumentAsset, metadata: dict, source: str | None) -> bool:
    raw_fallback = metadata.get("fallback")
    if isinstance(raw_fallback, bool):
        return raw_fallback
    if raw_fallback is not None:
        return str(raw_fallback).lower() == "true"
    return asset.asset_type == "page_snapshot" or source == "fallback_snapshot"


def _figure_read(asset: DocumentAsset) -> PaperFigureRead:
    metadata = {}
    if asset.metadata_json:
        try:
            metadata = json.loads(asset.metadata_json)
        except Exception:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    source = str(metadata.get("source") or "") or None
    return PaperFigureRead(
        id=asset.id,
        paper_id=asset.document_id,
        asset_type=asset.asset_type,
        image_path=f"/papers/assets/{asset.id}",
        figure_label=str(metadata.get("figure_label") or f"Figure {asset.id}"),
        caption=str(metadata.get("caption") or ""),
        page=asset.page_number,
        source=source,
        fallback=_metadata_fallback(asset, metadata, source),
        notes=str(metadata.get("notes") or metadata.get("context") or "") or None,
        created_at=asset.created_at,
    )


def _content_is_markdown_table(content: str | None) -> bool:
    if not content:
        return False
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return len(lines) >= 2 and lines[0].startswith("|") and lines[1].startswith("|") and "---" in lines[1]


def _table_parse_status(table: PaperTable) -> str:
    if "Table Candidate" in (table.table_label or ""):
        return "fallback"
    if _content_is_markdown_table(table.content):
        return "success"
    return "partial"


def _table_source(parse_status: str) -> str:
    if parse_status == "success":
        return "pdfplumber"
    if parse_status == "fallback":
        return "fallback_candidate"
    return "text_candidate"


def _table_read(table: PaperTable) -> PaperTableRead:
    parse_status = _table_parse_status(table)
    return PaperTableRead(
        id=table.id,
        paper_id=table.paper_id,
        table_label=table.table_label,
        content=table.content,
        page=table.page,
        parse_status=parse_status,
        source=_table_source(parse_status),
        created_at=table.created_at,
    )


def _parse_error(paper: Document) -> str | None:
    if paper.status != "failed":
        return None
    return paper.fail_reason or paper.error_message


def _detail(db: Session, paper: Document) -> PaperDetailResponse:
    figures = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper.id, DocumentAsset.asset_type.in_(PAPER_ASSET_TYPES))
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
        parse_error=_parse_error(paper),
        text_content=paper.cleaned_text or paper.parsed_text,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        figures=[_figure_read(asset) for asset in figures],
        tables=[_table_read(table) for table in tables],
        latest_extraction_job=latest_job,
    )


@router.post("/upload", response_model=PaperUploadResponse, status_code=status.HTTP_410_GONE)
async def upload_paper() -> PaperUploadResponse:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail="请使用 /documents/upload 上传 PDF，论文页只是 PDF documents 的视图层。")


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
    if paper.status != "done":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文档解析完成后才能进行论文增强解析")
    try:
        parsed = PaperDemoService(db).parse(paper)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"论文增强解析失败：{exc}") from exc
    return _detail(db, parsed)


@router.get("/assets/{asset_id}")
async def get_paper_asset(asset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(DocumentAsset, asset_id)
    if asset is None or asset.asset_type not in PAPER_ASSET_TYPES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    paper = _paper_or_404(db, asset.document_id, current_user)
    if paper.id != asset.document_id or not asset.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    path = FileStorageService().get_file_path(asset.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found.")
    return FileResponse(path=path, media_type=asset.mime_type or "image/png")
