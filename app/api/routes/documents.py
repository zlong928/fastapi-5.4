from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.routing import APIRoute
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentAsset, DocumentChunk, DocumentClaim, DocumentEvent, JobRun, KgEntity, KgRelation, User
from app.schemas.document import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchTagRequest,
    BatchTagResponse,
    BookmarkCreate,
    BookmarkCreateResponse,
    ChunkSearchHit,
    ChunkSearchResponse,
    DocumentAssetRead,
    DocumentBatchUploadItem,
    DocumentClaimRead,
    DocumentChunkRead,
    DocumentDetailResponse,
    DocumentEventRead,
    DocumentKgResponse,
    DocumentListResponse,
    DocumentProcessingMode,
    DocumentProcessingStatusResponse,
    DocumentSearchResponse,
    DocumentUpdate,
    DocumentUploadResponse,
    PaginatedDocumentEvents,
    ParseJobRead,
    TagRead,
)
from app.services.bookmark_service import BookmarkError, BookmarkService
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_service import DONE_STATUSES, DocumentService
from app.services.document_search_service import DocumentSearchService
from app.services.document_upload_service import DocumentUploadService, DuplicateUploadError
from app.services.export_service import ExportService
from app.services.job_run_service import JobRunService
from app.services.paper.evidence import asset_image_url, asset_metadata, normalize_evidence_type
from app.services.soft_delete_service import SoftDeleteService
from app.utils.json import json_loads_object_or_none

router = APIRouter(prefix="/documents", tags=["documents"])
asset_router = APIRouter(tags=["document-assets"])
SOURCE_TYPE_PATTERN = "^(pdf|markdown|txt|image|docx|epub|bookmark|note|diary)$"


def explain_interface(*, responsibility: str, database: str, files: str, future: str | None = None) -> str:
    parts = [f"Responsibility: {responsibility}", f"Database: {database}", f"Files: {files}"]
    if future:
        parts.append(f"Future simplification: {future}")
    return "\n\n".join(parts)


def assert_document_owner(document: Document, current_user: User) -> None:
    if document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")


def serialize_latest_parse_job(job_run: JobRun | None) -> ParseJobRead | None:
    if job_run is None:
        return None
    metadata = json_loads_object_or_none(job_run.metadata_json) or {}
    return ParseJobRead(id=job_run.id, job_id=job_run.job_id, document_id=job_run.document_id or 0, user_id=job_run.user_id, status=job_run.status, job_type=str(metadata.get("job_type") or job_run.kind), metadata_json=job_run.metadata_json, error_message=job_run.error_message, started_at=job_run.started_at, finished_at=job_run.finished_at, created_at=job_run.created_at, updated_at=job_run.updated_at)


def _json_object(value: str | None) -> dict:
    parsed = json_loads_object_or_none(value)
    return parsed if isinstance(parsed, dict) else {}


def _asset_counts(document: Document) -> dict[str, int]:
    counts = {"table": 0, "figure": 0, "page_snapshot": 0}
    for asset in document.assets:
        if asset.asset_type in counts:
            counts[asset.asset_type] += 1
    return counts


def _evidence_counts(document: Document) -> dict[str, int]:
    asset_counts = _asset_counts(document)
    return {
        "chunks": len(document.document_chunks),
        "tables": asset_counts["table"],
        "figures": asset_counts["figure"],
        "page_snapshots": asset_counts["page_snapshot"],
        "claims": len(document.claims),
    }


def serialize_document_detail(document: Document, latest_parse_job=None) -> DocumentDetailResponse:
    events = sorted(document.events, key=lambda event: event.created_at)
    tags = [TagRead.model_validate(link.tag) for link in document.tag_links]
    return DocumentDetailResponse(id=document.id, user_id=document.user_id, title=document.title, original_filename=document.original_filename, source_type=document.source_type, source_url=document.source_url, site_name=document.site_name, processing_mode=document.processing_mode, processing_strategy=document.processing_strategy, status=document.status, processing_status=document.status, file_size=document.file_size, mime_type=document.mime_type, parsed_text=document.parsed_text, cleaned_text=document.cleaned_text, parse_quality_json=document.parse_quality_json, references_text=document.references_text, collection_name=document.collection_name, content_hash=document.content_hash, content_summary=document.content_summary, chunk_count=document.chunk_count, page_count=document.page_count, metadata=_json_object(document.metadata_json), evidence_counts=_evidence_counts(document), error_message=document.error_message, fail_reason=document.fail_reason, processing_error=document.fail_reason or document.error_message, created_at=document.created_at, updated_at=document.updated_at, uploaded_at=document.uploaded_at, parsed_at=document.parsed_at, latest_parse_job=serialize_latest_parse_job(latest_parse_job), events=[DocumentEventRead.model_validate(event) for event in events], tags=tags)


def serialize_document_list_item(document: Document, latest_job=None) -> dict:
    return {"id": document.id, "title": document.title, "original_filename": document.original_filename, "source_type": document.source_type, "source_url": document.source_url, "site_name": document.site_name, "processing_mode": document.processing_mode, "processing_strategy": document.processing_strategy, "status": document.status, "processing_status": document.status, "file_size": document.file_size, "error_message": document.error_message, "fail_reason": document.fail_reason, "processing_error": document.fail_reason or document.error_message, "latest_parse_job_status": latest_job.status if latest_job else None, "collection_name": document.collection_name, "content_hash": document.content_hash, "content_summary": document.content_summary, "chunk_count": document.chunk_count, "page_count": document.page_count, "asset_counts": _asset_counts(document), "claim_count": len(document.claims), "created_at": document.created_at, "updated_at": document.updated_at, "uploaded_at": document.uploaded_at, "parsed_at": document.parsed_at, "tags": [TagRead.model_validate(link.tag) for link in document.tag_links]}


def serialize_document_asset(asset: DocumentAsset) -> DocumentAssetRead:
    metadata = asset_metadata(asset)
    evidence_type = normalize_evidence_type(asset=asset, metadata=metadata)
    metadata = {**metadata, "evidence_type": evidence_type, "evidenceType": evidence_type}
    image_url = asset_image_url(asset)
    if image_url:
        metadata.setdefault("imageUrl", image_url)
        metadata.setdefault("thumbnailUrl", image_url)
    return DocumentAssetRead(
        id=asset.id,
        document_id=asset.document_id,
        parse_job_id=asset.parse_job_id,
        asset_type=asset.asset_type,
        asset_index=asset.asset_index,
        label=asset.label,
        caption=asset.caption,
        page_number=asset.page_number,
        file_path=asset.file_path,
        mime_type=asset.mime_type,
        ocr_text=asset.ocr_text,
        markdown=asset.markdown,
        text_content=asset.text_content,
        summary=asset.summary,
        metadata=metadata,
        created_at=asset.created_at,
    )


def serialize_document_claim(claim: DocumentClaim) -> DocumentClaimRead:
    return DocumentClaimRead(
        id=claim.id,
        document_id=claim.document_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        source_type=claim.source_type,
        source_id=claim.source_id,
        page_number=claim.page_number,
        evidence_text=claim.evidence_text,
        confidence=claim.confidence,
        metadata=_json_object(claim.metadata_json),
        created_at=claim.created_at,
    )


@router.post("/bookmarks", response_model=BookmarkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark_document(payload: BookmarkCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BookmarkCreateResponse:
    try:
        document = await BookmarkService(db).create_bookmark(user_id=current_user.id, url=payload.url, title=payload.title, collection_name=payload.collection_name, tag_ids=payload.tag_ids, processing_mode=payload.processing_mode.value)
    except BookmarkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BookmarkCreateResponse(document_id=document.id, status=document.status, processing_status=document.status, source_type=document.source_type, source_url=document.source_url, message="已保存" if document.status in DONE_STATUSES else (document.fail_reason or "保存失败"))


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload document and queue parsing",
    description=explain_interface(
        responsibility="Validate and store one authenticated user upload, then queue document parsing.",
        database="Writes documents, job_runs, and document_events for the uploaded document.",
        files="Writes the stored upload file under UPLOAD_DIR.",
    ),
)
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None), processing_mode: DocumentProcessingMode = Form(DocumentProcessingMode.AUTO), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentUploadResponse:
    try:
        result = await DocumentUploadService(db).upload_one(file=file, user=current_user, title=title, processing_mode=processing_mode)
        document = result.document
        job = result.parse_job
        message = "Document uploaded and queued for parsing."
        if document.source_type in {"epub", "docx"}:
            message = "Document uploaded for preview. Text extraction is not enabled for this file type."
        if document.status == "failed" and job.status == "failed":
            message = "Document uploaded, but parsing could not be queued."
        return DocumentUploadResponse(document_id=document.id, status=document.status, processing_status=document.status, parse_job_id=job.id, job_id=job.job_id, processing_mode=document.processing_mode, message=message)
    except DuplicateUploadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if str(exc).startswith("File is too large.") else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upload failed due to a server error.") from exc


@router.post("/batch-upload", response_model=list[DocumentBatchUploadItem], status_code=status.HTTP_202_ACCEPTED)
async def upload_batch(files: list[UploadFile] = File(...), processing_mode: DocumentProcessingMode = Form(DocumentProcessingMode.AUTO), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DocumentBatchUploadItem]:
    results: list[DocumentBatchUploadItem] = []
    upload_service = DocumentUploadService(db)
    for file in files:
        filename = file.filename or "unknown"
        try:
            result = await upload_service.upload_one(file=file, user=current_user, processing_mode=processing_mode)
            document = result.document
            job = result.parse_job
            results.append(DocumentBatchUploadItem(filename=filename, ok=True, document_id=document.id, parse_job_id=job.id, job_id=job.job_id, status=document.status, processing_mode=document.processing_mode))
        except HTTPException as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error=str(exc.detail)))
        except ValueError as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error=str(exc)))
        except Exception:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error="Upload failed due to a server error."))
    return results


@router.get("", response_model=DocumentListResponse)
async def list_documents(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), skip: int | None = Query(None, ge=0), limit: int | None = Query(None, ge=1, le=100), keyword: str | None = Query(None), tag_id: int | None = Query(None, ge=1), file_type: str | None = Query(None, pattern=SOURCE_TYPE_PATTERN), status: str | None = Query(None, pattern="^(pending|processing|done|completed|failed|deleted)$"), start_date: datetime | None = Query(None), end_date: datetime | None = Query(None), sort_by: str = Query("created_at"), sort_order: str = Query("desc", pattern="^(asc|desc)$"), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentListResponse:
    service = DocumentService(db)
    actual_size = limit or size
    actual_skip = skip if skip is not None else (page - 1) * actual_size
    actual_page = page if skip is None else (actual_skip // actual_size) + 1
    documents, total = service.get_user_documents(user_id=current_user.id, skip=actual_skip, limit=actual_size, exclude_deleted=True, keyword=keyword, tag_id=tag_id, file_type=file_type, status=status, start_date=start_date, end_date=end_date, sort_by=sort_by, sort_order=sort_order)
    return DocumentListResponse(total=total, page=actual_page, size=actual_size, items=[serialize_document_list_item(doc, service.get_latest_parse_job(doc.id)) for doc in documents])


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50), mode: str = Query("keyword", pattern="^(keyword|hybrid|semantic)$"), include_unparsed: bool = Query(False), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentSearchResponse:
    service = DocumentSearchService(db)
    hits = service.hybrid_search(current_user.id, q, limit=limit) if mode == "hybrid" else service.search(current_user.id, q, limit=limit)
    if not include_unparsed:
        hits = [hit for hit in hits if hit.document.status in DONE_STATUSES]
    return DocumentSearchResponse(query=q, total=len(hits), items=[{"id": hit.document.id, "title": hit.document.title, "source_type": hit.document.source_type, "source_url": hit.document.source_url, "site_name": hit.document.site_name, "status": hit.document.status, "snippet": hit.snippet, "matched_field": hit.matched_field, "score": hit.score, "parsed_at": hit.document.parsed_at} for hit in hits])


@router.get("/search/chunks", response_model=ChunkSearchResponse)
async def search_document_chunks(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50), document_id: int | None = Query(None), threshold: float = Query(0.0, ge=0.0, le=1.0), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ChunkSearchResponse:
    hits = DocumentSearchService(db).search_chunks(current_user.id, q, limit=limit, document_id=document_id, threshold=threshold)
    return ChunkSearchResponse(query=q, total=len(hits), items=[ChunkSearchHit(**hit) for hit in hits])


@router.delete("/batch", response_model=BatchDeleteResponse)
async def batch_delete_documents(payload: BatchDeleteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BatchDeleteResponse:
    success_ids, failed_ids, errors = DocumentService(db).batch_delete_documents(current_user.id, payload.ids)
    return BatchDeleteResponse(success_ids=success_ids, failed_ids=failed_ids, errors=errors)


@router.post("/batch-tag", response_model=BatchTagResponse)
async def batch_tag_documents(payload: BatchTagRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BatchTagResponse:
    try:
        assigned_count = DocumentService(db).batch_tag_documents(current_user.id, payload.document_ids, payload.tag_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BatchTagResponse(document_ids=payload.document_ids, tag_ids=payload.tag_ids, assigned_count=assigned_count)


@router.post("/{document_id}/re-embed", response_model=dict)
async def re_embed_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    if document.status not in DONE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document must be completed first.")
    count = DocumentEmbeddingService().embed_document(document_id)
    return {"document_id": document_id, "chunks_embedded": count, "message": f"Re-embedded {count} chunks."}


@router.post("/re-embed-all", response_model=dict)
async def re_embed_all_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    docs = db.query(Document).filter(Document.user_id == current_user.id, Document.status.in_(DONE_STATUSES)).all()
    total = 0
    for doc in docs:
        try:
            total += DocumentEmbeddingService().embed_document(doc.id)
        except Exception:
            db.rollback()
    return {"user_id": current_user.id, "documents_processed": len(docs), "chunks_embedded": total}


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentDetailResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    return serialize_document_detail(document, service.get_latest_parse_job(document.id))


@router.patch("/{document_id}", response_model=DocumentDetailResponse)
async def update_document(document_id: int, payload: DocumentUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentDetailResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document or document.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    changed = False
    if payload.title is not None:
        document.title = payload.title.strip()
        changed = True
    if payload.collection_name is not None:
        document.collection_name = payload.collection_name.strip() or None
        changed = True
    if changed:
        service.log_event(document.id, current_user.id, "update", "文档信息已更新", commit=False)
        db.commit()
        db.refresh(document)
    return serialize_document_detail(document, service.get_latest_parse_job(document.id))


@router.get("/{document_id}/process/status", response_model=DocumentProcessingStatusResponse)
async def get_document_processing_status(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentProcessingStatusResponse:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    return DocumentProcessingStatusResponse(document_id=document.id, status=document.status, processing_status=document.status, error=document.error_message, processing_error=document.fail_reason or document.error_message, collection_name=document.collection_name, source_url=document.source_url, site_name=document.site_name, hash=document.content_hash, content_summary=document.content_summary, chunk_count=document.chunk_count, created_at=document.created_at, updated_at=document.updated_at)


@router.post("/{document_id}/process", response_model=DocumentProcessingStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentProcessingStatusResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    if service.get_running_parse_job(document_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document processing is already pending or running.")
    try:
        document, _job = service.enqueue_parse_document(document_id, job_type="manual_process")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DocumentProcessingStatusResponse(document_id=document.id, status=document.status, processing_status=document.status, error=document.error_message, processing_error=document.fail_reason or document.error_message, collection_name=document.collection_name, source_url=document.source_url, site_name=document.site_name, hash=document.content_hash, content_summary=document.content_summary, chunk_count=document.chunk_count, created_at=document.created_at, updated_at=document.updated_at)


@router.get(
    "/{document_id}/file",
    summary="Download stored document file",
    description=explain_interface(
        responsibility="Return the original stored file for one authenticated user-owned document.",
        database="Reads documents for ownership and file metadata; does not write database rows.",
        files="reads the stored file from UPLOAD_DIR.",
    ),
)
async def get_document_file(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    if document.source_type in {"bookmark", "note", "diary"} or document.original_file_path.startswith(("bookmark:", "note:", "diary:")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This document has no stored file.")
    file_path = DocumentService(db).file_storage.get_file_path(document.original_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    return FileResponse(path=file_path, media_type=document.mime_type, filename=document.original_filename)


def retry_document_or_raise(document_id: int, current_user: User, db: Session) -> DocumentDetailResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    try:
        running_job = service.get_running_parse_job(document_id)
        if running_job is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document processing is already pending or running.")
        document, job = service.retry_parse(document_id)
        return serialize_document_detail(document, job)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{document_id}/retry", response_model=DocumentDetailResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentDetailResponse:
    return retry_document_or_raise(document_id, current_user, db)


@router.post(
    "/{document_id}/retry-parse",
    response_model=DocumentDetailResponse,
    deprecated=True,
    summary="Retry document parsing compatibility alias",
    description=explain_interface(
        responsibility="Compatibility alias for /documents/{document_id}/retry.",
        database="Same as /documents/{document_id}/retry: writes documents and job_runs for a retry.",
        files="Only reads the stored upload file later when the queued parser runs.",
        future="Prefer /documents/{document_id}/retry.",
    ),
)
async def retry_parse_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentDetailResponse:
    return retry_document_or_raise(document_id, current_user, db)


@router.delete("/{document_id}", response_model=dict)
async def delete_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Soft delete a document. Use /permanent endpoint for permanent deletion."""
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)

    # Perform soft delete instead of hard delete
    SoftDeleteService.soft_delete(db=db, instance=document, deleted_by_user_id=current_user.id)

    return {"id": document_id, "status": "deleted", "message": "Document soft deleted. Use restore endpoint to recover."}



@router.get("/{document_id}/events", response_model=PaginatedDocumentEvents)
async def get_document_events(document_id: int, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PaginatedDocumentEvents:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    query = db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)
    total = query.count()
    events = query.order_by(DocumentEvent.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return PaginatedDocumentEvents(total=total, page=page, size=size, items=[DocumentEventRead.model_validate(event) for event in events])


@router.get("/{document_id}/parse-jobs", response_model=list[ParseJobRead])
async def get_document_parse_jobs(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ParseJobRead]:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    return [item for item in (serialize_latest_parse_job(job) for job in JobRunService(db).list_jobs(user_id=current_user.id, kind_filter="document_parse", document_id=document.id, limit=100)) if item is not None]


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkRead])
async def get_document_chunks(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DocumentChunkRead]:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index).all()
    return [DocumentChunkRead.model_validate(chunk) for chunk in chunks]


@router.get("/{document_id}/assets", response_model=list[DocumentAssetRead])
async def get_document_assets(
    document_id: int,
    asset_type: str | None = Query(None, pattern="^(table|figure|page_snapshot|equation|unknown)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentAssetRead]:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    query = db.query(DocumentAsset).filter(DocumentAsset.document_id == document.id)
    if asset_type:
        query = query.filter(DocumentAsset.asset_type == asset_type)
    assets = query.order_by(DocumentAsset.asset_index.asc().nullslast(), DocumentAsset.created_at.asc(), DocumentAsset.id.asc()).all()
    return [serialize_document_asset(asset) for asset in assets]


@router.get("/{document_id}/claims", response_model=list[DocumentClaimRead])
async def get_document_claims(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentClaimRead]:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    claims = (
        db.query(DocumentClaim)
        .filter(DocumentClaim.document_id == document.id)
        .order_by(DocumentClaim.page_number.asc().nullslast(), DocumentClaim.created_at.asc(), DocumentClaim.id.asc())
        .all()
    )
    return [serialize_document_claim(claim) for claim in claims]


@asset_router.get("/assets/{asset_id}", response_model=DocumentAssetRead)
async def get_asset_detail(asset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentAssetRead:
    asset = db.get(DocumentAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    document = DocumentService(db).get_document_by_id(asset.document_id)
    if not document or document.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    assert_document_owner(document, current_user)
    return serialize_document_asset(asset)


@router.get(
    "/{document_id}/kg",
    response_model=DocumentKgResponse,
    summary="Read document knowledge graph",
    description=explain_interface(
        responsibility="Return extracted knowledge graph data for one authenticated user-owned document.",
        database="Reads documents, kg_entities, and kg_relations; does not write database rows.",
        files="does not touch files.",
    ),
)
async def get_document_kg(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentKgResponse:
    document = DocumentService(db).get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    entities = db.query(KgEntity).filter(KgEntity.document_id == document_id).order_by(KgEntity.name).all()
    relations = db.query(KgRelation).filter(KgRelation.document_id == document_id).order_by(KgRelation.id).all()
    return DocumentKgResponse(document_id=document_id, entities=entities, relations=relations)


@router.get("/export")
async def export_documents(
    source_type: str | None = Query(None, pattern=SOURCE_TYPE_PATTERN),
    status_filter: str | None = Query(None, alias="status"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Response:
    """Export documents list to CSV or JSON format with optional filters."""
    query = db.query(Document).filter(Document.user_id == current_user.id, Document.is_deleted == False)

    if source_type:
        query = query.filter(Document.source_type == source_type)

    if status_filter:
        query = query.filter(Document.status == status_filter)

    documents = query.order_by(Document.created_at.desc()).all()

    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No documents found")

    if format == "csv":
        content = ExportService.export_documents_to_csv(documents)
        media_type = "text/csv"
        filename = f"documents_export_{len(documents)}_items.csv"
    else:  # json
        content = ExportService.export_documents_to_json(documents)
        media_type = "application/json"
        filename = f"documents_export_{len(documents)}_items.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/deleted", response_model=DocumentListResponse)
async def list_deleted_documents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of soft-deleted documents for the current user."""
    documents = SoftDeleteService.get_deleted_documents(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset
    )

    total = SoftDeleteService.count_deleted_documents(db=db, user_id=current_user.id)

    return DocumentListResponse(
        documents=documents,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("/{document_id}/restore")
async def restore_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted document."""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if not document.is_deleted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is not deleted")

    restored_document = SoftDeleteService.restore(db=db, instance=document)

    return {"message": "Document restored successfully", "document_id": restored_document.id}


@router.delete("/{document_id}/permanent")
async def permanent_delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permanently delete a document. This action is irreversible!"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if not document.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must be soft-deleted first before permanent deletion"
        )

    SoftDeleteService.permanent_delete(db=db, instance=document)

    return {"message": "Document permanently deleted", "document_id": document_id}


@router.post("/batch-restore")
async def batch_restore_documents(
    document_ids: list[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Batch restore multiple soft-deleted documents."""
    count = SoftDeleteService.batch_restore_documents(
        db=db,
        document_ids=document_ids,
        user_id=current_user.id
    )

    return {"message": f"Restored {count} documents", "count": count}


def _apply_openapi_boundaries() -> None:
    default_description = explain_interface(responsibility="Operate on authenticated user-owned knowledge documents for the named route.", database="Uses documents and directly related document tables scoped to the current user.", files="Only touches stored upload files when the route explicitly uploads, downloads, or deletes file-backed documents.")
    metadata_by_path_method = {}
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        method = next(iter(route.methods or {"GET"}))
        if method in {"HEAD", "OPTIONS"}:
            continue
        route.summary = route.summary or route.name.replace("_", " ").replace("-", " ").title()
        route.description = route.description or default_description


_apply_openapi_boundaries()
