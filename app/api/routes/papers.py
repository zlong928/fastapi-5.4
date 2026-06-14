from __future__ import annotations

import json
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import app_now
from app.db.session import get_db
from app.models import Document, DocumentAsset, DocumentClaim, DocumentEvent, ExtractionJob, ExtractionResult, PaperTable, User
from app.schemas.paper import (
    ChartRecipeCatalogItem,
    ChartTypeCatalogItem,
    PaperAskEvidence,
    PaperAskRequest,
    PaperAskResponse,
    PaperDetailResponse,
    PaperFigureRead,
    PaperListItem,
    PaperStatisticsResponse,
    PaperTableRead,
    PaperUploadResponse,
)
from app.services.chart_extraction import CHART_TYPE_CATALOG, chart_recipe_catalog
from app.services.export_service import ExportService
from app.services.file_storage import FileStorageService
from app.services.paper_demo_service import PaperDemoService
from app.services.paper.coordinate_preview import coordinate_preview_read
from app.services.paper.evidence import asset_bbox, asset_image_url, asset_metadata, normalize_evidence_type

router = APIRouter(prefix="/papers", tags=["papers"])
PAPER_ASSET_TYPES = ("figure", "page_snapshot")
PAPER_FIGURE_DISPLAY_TYPES = ("figure",)
DOCUMENT_ASSET_SOURCE_TYPES = {"table", "figure", "page_snapshot", "asset"}
EXPLICIT_TABLE_LABEL_RE = re.compile(r"(?i)^(?:supplementary\s+)?table\s+(?:\d+[a-z]?|[ivxlcdm]+)\b|^表\s*\d+[a-z]?\b")


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
    metadata = asset_metadata(asset)
    source = str(metadata.get("source") or "") or None
    default_visual_role = "image_object" if source == "extracted_image" else ("figure_candidate" if asset.asset_type == "figure" else source or "")
    visual_role = str(metadata.get("visual_role") or default_visual_role) or None
    image_url = asset_image_url(asset)
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
        visual_role=visual_role,
        evidence_type=normalize_evidence_type(asset=asset, metadata=metadata),
        image_url=image_url,
        thumbnail_url=image_url,
        bbox=asset_bbox(metadata),
        confidence=float(metadata["confidence"]) if isinstance(metadata.get("confidence"), (int, float)) else None,
        notes=str(metadata.get("notes") or metadata.get("context") or "") or None,
        analysis_status=str(metadata.get("agent_analysis_status") or "") or None,
        analysis_error=str(metadata.get("agent_analysis_error") or "") or None,
        coordinate_preview=coordinate_preview_read(asset, metadata),
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
    if (table.table_label or "").startswith("Detected Table-like Block"):
        return "partial"
    if _content_is_markdown_table(table.content):
        return "success"
    if EXPLICIT_TABLE_LABEL_RE.search(table.table_label or ""):
        return "fallback"
    return "partial"


def _table_source(table: PaperTable, parse_status: str) -> str:
    if parse_status == "success":
        return "pdfplumber"
    if parse_status == "fallback":
        return "fallback_candidate"
    if (table.table_label or "").startswith("Detected Table-like Block"):
        return "weak_table_candidate"
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
        source=_table_source(table, parse_status),
        created_at=table.created_at,
    )


def _table_asset_read(asset: DocumentAsset) -> PaperTableRead:
    content = asset.markdown or asset.text_content or asset.ocr_text or ""
    parse_status = "success" if _content_is_markdown_table(content) else "partial"
    metadata = {}
    if asset.metadata_json:
        try:
            metadata = json.loads(asset.metadata_json)
        except Exception:
            metadata = {}
    error_message = None
    if not content.strip():
        parse_status = "failed"
        error_message = "表格内容为空，可能提取失败"
    elif parse_status == "partial":
        error_message = "表格结构不完整，未能解析为标准 Markdown 表格"
    return PaperTableRead(
        id=asset.id,
        paper_id=asset.document_id,
        table_label=asset.label or f"Table {asset.asset_index + 1 if asset.asset_index is not None else asset.id}",
        content=content,
        page=asset.page_number,
        parse_status=parse_status,
        source="document_asset",
        error_message=error_message,
        created_at=asset.created_at,
    )


def _parse_error(paper: Document) -> str | None:
    if paper.status != "failed":
        return None
    return paper.fail_reason or paper.error_message


def _asset_counts(paper: Document) -> dict[str, int]:
    counts = {"table": 0, "figure": 0, "page_snapshot": 0}
    for asset in paper.assets:
        if asset.asset_type in counts:
            counts[asset.asset_type] += 1
    return counts


def _progress_label(paper: Document) -> str:
    if paper.status in {"done", "completed", "parsed"}:
        counts = _asset_counts(paper)
        if counts["table"] or counts["figure"] or counts["page_snapshot"]:
            return "就绪（可提取）"
        return "正文已解析"
    if paper.status in {"pending", "uploaded"}:
        return "等待解析"
    if paper.status in {"processing", "parsing", "extracting"}:
        return "解析中"
    if paper.status == "failed":
        return "解析失败"
    return paper.status


def _json_metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _should_display_figure(asset: DocumentAsset) -> bool:
    if asset.asset_type == "figure":
        return True
    if asset.asset_type != "page_snapshot":
        return False
    metadata = _json_metadata(asset.metadata_json)
    source = metadata.get("source", "")
    visual_role = metadata.get("visual_role", "")
    if source == "fallback_snapshot" or visual_role == "fallback_snapshot":
        return False
    if source == "page_visual_snapshot" or visual_role == "page_evidence":
        return True
    return False


def _detail(db: Session, paper: Document) -> PaperDetailResponse:
    all_visual_assets = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper.id, DocumentAsset.asset_type.in_(PAPER_ASSET_TYPES))
        .order_by(DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    figures = [asset for asset in all_visual_assets if _should_display_figure(asset)]
    table_assets = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper.id, DocumentAsset.asset_type == "table")
        .order_by(DocumentAsset.asset_index.asc().nullslast(), DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
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
        tables=[_table_asset_read(asset) for asset in table_assets],
        latest_extraction_job=latest_job,
    )


def _asset_label(asset: DocumentAsset | None) -> str | None:
    if asset is None:
        return None
    metadata = _json_metadata(asset.metadata_json)
    return asset.label or str(metadata.get("figure_label") or metadata.get("label") or "") or None


def _source_asset_map(db: Session, claims: list[DocumentClaim]) -> dict[int, DocumentAsset]:
    asset_ids = sorted({claim.source_id for claim in claims if claim.source_type in DOCUMENT_ASSET_SOURCE_TYPES and claim.source_id is not None})
    if not asset_ids:
        return {}
    assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
    return {asset.id: asset for asset in assets}


def _claim_relevance_score(claim: DocumentClaim, question: str) -> int:
    question_terms = {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", question)}
    haystack = f"{claim.claim_text} {claim.evidence_text}".lower()
    return sum(1 for term in question_terms if term in haystack)


def _claims_for_answer(db: Session, papers: list[Document], question: str) -> list[DocumentClaim]:
    paper_ids = [paper.id for paper in papers]
    claims = (
        db.query(DocumentClaim)
        .filter(DocumentClaim.document_id.in_(paper_ids))
        .order_by(DocumentClaim.confidence.asc(), DocumentClaim.page_number.asc().nullslast(), DocumentClaim.id.asc())
        .all()
    )
    return sorted(claims, key=lambda claim: (_claim_relevance_score(claim, question), claim.confidence == "high", claim.id), reverse=True)[:8]


def _uncertainties_from_assets(assets: list[DocumentAsset]) -> list[str]:
    uncertainties: list[str] = []
    for asset in assets:
        metadata = _json_metadata(asset.metadata_json)
        for item in metadata.get("uncertainties") or []:
            text = str(item).strip()
            if text and text not in uncertainties:
                uncertainties.append(text)
        if asset.asset_type == "figure" and metadata.get("precise_values_extracted") is False:
            text = "未进行精确数值还原"
            if text not in uncertainties:
                uncertainties.append(text)
    return uncertainties


def _fallback_uncertainties(question: str) -> list[str]:
    return [f"没有找到与问题“{question}”相关的正文、表格或图片证据，无法给出确定结论。"]


def _answer_from_claims(claims: list[DocumentClaim], papers_by_id: dict[int, Document]) -> str:
    grouped: dict[int, list[DocumentClaim]] = {}
    for claim in claims:
        grouped.setdefault(claim.document_id, []).append(claim)

    parts: list[str] = []
    for document_id, document_claims in grouped.items():
        paper = papers_by_id[document_id]
        claim_sentences = "；".join(claim.claim_text.strip() for claim in document_claims[:3] if claim.claim_text.strip())
        if claim_sentences:
            parts.append(f"{paper.title}: {claim_sentences}")
    return "\n".join(parts) if parts else "不确定：没有找到可核对证据。"


@router.post("/ask", response_model=PaperAskResponse)
async def ask_papers(payload: PaperAskRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperAskResponse:
    papers = (
        db.query(Document)
        .filter(
            Document.id.in_(payload.document_ids),
            Document.user_id == current_user.id,
            Document.source_type == "pdf",
            Document.is_deleted == False,
        )
        .all()
    )
    found_ids = {paper.id for paper in papers}
    missing_ids = [document_id for document_id in payload.document_ids if document_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Paper not found: {missing_ids[0]}")

    claims = _claims_for_answer(db, papers, payload.question)
    if not claims:
        return PaperAskResponse(answer="不确定：没有找到可核对证据，不能给出确定结论。", evidence=[], uncertainties=_fallback_uncertainties(payload.question))

    assets_by_id = _source_asset_map(db, claims)
    evidence: list[PaperAskEvidence] = []
    for claim in claims:
        asset = assets_by_id.get(claim.source_id) if claim.source_id is not None else None
        label = _asset_label(asset)
        source_type = "asset" if asset is not None else claim.source_type
        source_id = asset.id if asset is not None else claim.source_id or claim.id
        page_number = asset.page_number if asset is not None else claim.page_number
        evidence.append(
            PaperAskEvidence(
                document_id=claim.document_id,
                source_type=source_type,
                source_id=source_id,
                asset_type=asset.asset_type if asset is not None else None,
                asset_id=asset.id if asset is not None else None,
                label=label,
                page_number=page_number,
                reason=claim.evidence_text[:300],
            )
        )

    answer = _answer_from_claims(claims, {paper.id: paper for paper in papers})
    uncertainties = _uncertainties_from_assets(list(assets_by_id.values()))
    return PaperAskResponse(answer=answer, evidence=evidence, uncertainties=uncertainties)


@router.post("/upload", response_model=PaperUploadResponse, status_code=status.HTTP_410_GONE)
async def upload_paper() -> PaperUploadResponse:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail="请使用 /documents/upload 上传 PDF，论文页只是 PDF documents 的视图层。")


@router.get("", response_model=list[PaperListItem])
async def list_papers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PaperListItem]:
    papers = (
        db.query(Document)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [
        PaperListItem(
            id=paper.id,
            title=paper.title,
            status=paper.status,
            parse_error=_parse_error(paper),
            progress_label=_progress_label(paper),
            asset_counts=_asset_counts(paper),
            uploaded_at=paper.uploaded_at,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
        )
        for paper in papers
    ]


@router.get("/statistics", response_model=PaperStatisticsResponse)
async def get_paper_statistics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperStatisticsResponse:
    base = [Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False]
    total = db.query(func.count(Document.id)).filter(*base).scalar() or 0
    parsed = db.query(func.count(Document.id)).filter(*base, Document.status.in_(["done", "completed", "parsed"])).scalar() or 0
    failed = db.query(func.count(Document.id)).filter(*base, Document.status == "failed").scalar() or 0
    processing = db.query(func.count(Document.id)).filter(*base, Document.status.in_(["pending", "processing", "parsing"])).scalar() or 0

    paper_ids_subq = db.query(Document.id).filter(*base).subquery()
    total_extractions = db.query(func.count(ExtractionJob.id)).filter(ExtractionJob.paper_id.in_(paper_ids_subq.select())).scalar() or 0
    successful_extractions = db.query(func.count(ExtractionJob.id)).filter(ExtractionJob.paper_id.in_(paper_ids_subq.select()), ExtractionJob.status == "done").scalar() or 0
    failed_extractions = db.query(func.count(ExtractionJob.id)).filter(ExtractionJob.paper_id.in_(paper_ids_subq.select()), ExtractionJob.status == "failed").scalar() or 0

    total_figures = db.query(func.count(DocumentAsset.id)).filter(
        DocumentAsset.document_id.in_(paper_ids_subq.select()),
        DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
    ).scalar() or 0
    total_tables = db.query(func.count(DocumentAsset.id)).filter(
        DocumentAsset.document_id.in_(paper_ids_subq.select()),
        DocumentAsset.asset_type == "table",
    ).scalar() or 0

    avg_conf = db.query(func.avg(ExtractionResult.confidence)).join(
        ExtractionJob, ExtractionResult.job_id == ExtractionJob.id
    ).filter(
        ExtractionJob.paper_id.in_(paper_ids_subq.select()),
        ExtractionResult.confidence.isnot(None),
    ).scalar()

    recent_since = app_now() - timedelta(days=7)
    recent_papers = db.query(func.count(Document.id)).filter(*base, Document.created_at >= recent_since).scalar() or 0
    recent_extractions = db.query(func.count(ExtractionJob.id)).filter(
        ExtractionJob.paper_id.in_(paper_ids_subq.select()),
        ExtractionJob.created_at >= recent_since,
    ).scalar() or 0

    return PaperStatisticsResponse(
        total_papers=total,
        parsed_papers=parsed,
        failed_papers=failed,
        processing_papers=processing,
        total_extractions=total_extractions,
        successful_extractions=successful_extractions,
        failed_extractions=failed_extractions,
        total_figures=total_figures,
        total_tables=total_tables,
        avg_confidence=round(avg_conf, 4) if avg_conf is not None else None,
        recent_7_days_papers=recent_papers,
        recent_7_days_extractions=recent_extractions,
    )


@router.get("/chart-types", response_model=list[ChartTypeCatalogItem])
async def get_chart_type_catalog(current_user: User = Depends(get_current_user)) -> list[ChartTypeCatalogItem]:
    return [
        ChartTypeCatalogItem(
            image_type=spec.image_type,
            label=spec.label,
            suitable_for_csv=spec.suitable_for_csv,
            processing_chain=spec.processing_chain,
            typical_content=list(spec.typical_content),
            coordinate_output=spec.coordinate_output,
            binding_requirements=list(spec.binding_requirements),
            requires_review=spec.requires_review,
        )
        for spec in CHART_TYPE_CATALOG
    ]


@router.get("/chart-recipes", response_model=list[ChartRecipeCatalogItem])
async def get_chart_recipe_catalog(current_user: User = Depends(get_current_user)) -> list[ChartRecipeCatalogItem]:
    return [ChartRecipeCatalogItem(**item) for item in chart_recipe_catalog()]


@router.get("/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(paper_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperDetailResponse:
    return _detail(db, _paper_or_404(db, paper_id, current_user))


@router.post("/{paper_id}/parse", response_model=PaperDetailResponse)
async def parse_paper(paper_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaperDetailResponse:
    paper = _paper_or_404(db, paper_id, current_user)
    if paper.status not in ("done", "failed"):
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


@router.get("/assets/{asset_id}/coordinate-preview.csv")
async def get_paper_coordinate_preview(asset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(DocumentAsset, asset_id)
    if asset is None or asset.asset_type not in PAPER_ASSET_TYPES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coordinate preview not found.")
    paper = _paper_or_404(db, asset.document_id, current_user)
    if paper.id != asset.document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coordinate preview not found.")
    metadata = asset_metadata(asset)
    preview = metadata.get("coordinate_preview")
    if not isinstance(preview, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coordinate preview not found.")
    csv_path = str(preview.get("coordinate_csv_path") or metadata.get("chart_data_csv_path") or "")
    if not csv_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coordinate preview not found.")
    path = FileStorageService().get_file_path(csv_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coordinate preview file not found.")
    return FileResponse(
        path=path,
        media_type="text/csv; charset=utf-8",
        filename=f"asset-{asset.id}-coordinate-preview.csv",
    )


@router.get("/export")
async def export_papers(
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Response:
    """Export papers list to CSV or JSON format."""
    papers = (
        db.query(Document)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False)
        .order_by(Document.created_at.desc())
        .all()
    )

    if not papers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No papers found")

    if format == "csv":
        content = ExportService.export_documents_to_csv(papers)
        media_type = "text/csv"
        filename = f"papers_export_{len(papers)}_items.csv"
    else:  # json
        content = ExportService.export_documents_to_json(papers)
        media_type = "application/json"
        filename = f"papers_export_{len(papers)}_items.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.delete("/{paper_id}")
async def delete_paper(paper_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    paper = _paper_or_404(db, paper_id, current_user)
    paper.status = "deleted"
    paper.updated_at = app_now()
    db.add(
        DocumentEvent(
            document_id=paper.id,
            user_id=current_user.id,
            event_type="paper_deleted",
            message=f"论文已删除：{paper.title}",
            event_metadata=json.dumps({"paper_id": paper.id, "title": paper.title}, ensure_ascii=False),
        )
    )
    db.commit()
    return {"message": "论文已删除"}
