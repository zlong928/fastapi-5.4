from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Document, DocumentEvent, JobRun
from app.schemas.document import (
    ChunkSearchHit,
    ChunkSearchResponse,
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchTagRequest,
    BatchTagResponse,
    DocumentBatchUploadItem,
    DocumentChunkRead,
    DocumentDetailResponse,
    DocumentEventRead,
    DocumentUpdate,
    DocumentKgResponse,
    DocumentListResponse,
    DocumentProcessingMode,
    DocumentProcessingStatusResponse,
    PaginatedDocumentEvents,
    ParseJobRead,
    TagRead,
    DocumentSearchResponse,
    DocumentUploadResponse,
)
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_service import DONE_STATUSES, DocumentService
from app.services.document_search_service import DocumentSearchService
from app.services.document_upload_service import DocumentUploadService, DuplicateUploadError
from app.services.job_run_service import JobRunService
from app.models import KgEntity, KgRelation
from app.models import DocumentChunk
from app.utils.json import json_loads_object_or_none

router = APIRouter(prefix="/documents", tags=["documents"])


def explain_interface(*, responsibility: str, database: str, files: str, future: str | None = None) -> str:
    parts = [
        f"Responsibility: {responsibility}",
        f"Database: {database}",
        f"Files: {files}",
    ]
    if future:
        parts.append(f"Future simplification: {future}")
    return "\n\n".join(parts)

def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    """获取文档服务实例。"""
    return DocumentService(db)


def assert_document_owner(document: Document, current_user: User) -> None:
    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )


def serialize_latest_parse_job(job_run: JobRun | None) -> ParseJobRead | None:
    if job_run is None:
        return None
    metadata = json_loads_object_or_none(job_run.metadata_json) or {}
    return ParseJobRead(
        id=job_run.id,
        job_id=job_run.job_id,
        document_id=job_run.document_id or 0,
        user_id=job_run.user_id,
        status=job_run.status,
        job_type=str(metadata.get("job_type") or job_run.kind),
        metadata_json=job_run.metadata_json,
        error_message=job_run.error_message,
        started_at=job_run.started_at,
        finished_at=job_run.finished_at,
        created_at=job_run.created_at,
        updated_at=job_run.updated_at,
    )


def serialize_document_detail(document: Document, latest_parse_job=None) -> DocumentDetailResponse:
    events = sorted(document.events, key=lambda event: event.created_at)
    tags = [TagRead.model_validate(link.tag) for link in document.tag_links]
    return DocumentDetailResponse(
        id=document.id,
        user_id=document.user_id,
        title=document.title,
        original_filename=document.original_filename,
        source_type=document.source_type,
        processing_mode=document.processing_mode,
        processing_strategy=document.processing_strategy,
        status=document.status,
        processing_status=document.status,
        file_size=document.file_size,
        mime_type=document.mime_type,
        parsed_text=document.parsed_text,
        cleaned_text=document.cleaned_text,
        parse_quality_json=document.parse_quality_json,
        references_text=document.references_text,
        collection_name=document.collection_name,
        content_hash=document.content_hash,
        content_summary=document.content_summary,
        chunk_count=document.chunk_count,
        error_message=document.error_message,
        fail_reason=document.fail_reason,
        processing_error=document.fail_reason or document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        uploaded_at=document.uploaded_at,
        parsed_at=document.parsed_at,
        latest_parse_job=serialize_latest_parse_job(latest_parse_job),
        events=[DocumentEventRead.model_validate(event) for event in events],
        tags=tags,
    )


def serialize_document_list_item(document: Document, latest_job=None) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "original_filename": document.original_filename,
        "source_type": document.source_type,
        "processing_mode": document.processing_mode,
        "processing_strategy": document.processing_strategy,
        "status": document.status,
        "processing_status": document.status,
        "file_size": document.file_size,
        "error_message": document.error_message,
        "fail_reason": document.fail_reason,
        "processing_error": document.fail_reason or document.error_message,
        "latest_parse_job_status": latest_job.status if latest_job else None,
        "collection_name": document.collection_name,
        "content_hash": document.content_hash,
        "content_summary": document.content_summary,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "uploaded_at": document.uploaded_at,
        "parsed_at": document.parsed_at,
        "tags": [TagRead.model_validate(link.tag) for link in document.tag_links],
    }


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload document and queue parsing",
    description=explain_interface(
        responsibility="Accept one source file, create a document record, create its parse job, sync optional Obsidian metadata, and enqueue background parsing.",
        database="Writes documents, job_runs, and document_events in the upload flow; later parsing writes document_chunks, document_assets, kg_entities, kg_relations, and vector rows.",
        files="Writes the stored upload file under the configured upload directory; may write Obsidian vault files when sync is configured.",
    ),
)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    processing_mode: DocumentProcessingMode = Form(DocumentProcessingMode.AUTO),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """上传单个文档。

    支持 PDF, Markdown, TXT 和图片文件。
    
    Args:
        file: 上传的文件
        title: 可选的文档标题，默认为文件名
        current_user: 当前用户
        db: 数据库会话

    Returns:
        DocumentUploadResponse: 上传响应

    Raises:
        HTTPException: 文件类型不支持或上传失败
    """
    try:
        result = await DocumentUploadService(db).upload_one(
            file=file,
            user=current_user,
            title=title,
            processing_mode=processing_mode,
        )
        document = result.document
        job = result.parse_job
        message = "Document uploaded and queued for parsing."
        if document.status == "failed" and job.status == "failed":
            message = "Document uploaded, but parsing could not be queued."
        return DocumentUploadResponse(
            document_id=document.id,
            status=document.status,
            processing_status=document.status,
            parse_job_id=job.id,
            job_id=job.job_id,
            processing_mode=document.processing_mode,
            message=message,
        )
    except DuplicateUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        if str(exc).startswith("File is too large."):
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed due to a server error.",
        ) from exc


@router.post(
    "/batch-upload",
    response_model=list[DocumentBatchUploadItem],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload multiple documents and queue parsing",
    description=explain_interface(
        responsibility="Apply the single-document upload flow to each submitted file and return per-file success or failure.",
        database="For each accepted file, writes documents, job_runs, and document_events; failed files do not create document rows.",
        files="Writes one stored upload file per accepted item; may write Obsidian vault files when sync is configured.",
    ),
)
async def upload_batch(
    files: list[UploadFile] = File(...),
    processing_mode: DocumentProcessingMode = Form(DocumentProcessingMode.AUTO),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentBatchUploadItem]:
    """批量上传文档。

    Args:
        files: 上传的文件列表
        current_user: 当前用户
        db: 数据库会话

    Returns:
        list[DocumentUploadResponse]: 上传响应列表
    """
    results: list[DocumentBatchUploadItem] = []
    upload_service = DocumentUploadService(db)

    for file in files:
        filename = file.filename or "unknown"
        try:
            result = await upload_service.upload_one(
                file=file,
                user=current_user,
                processing_mode=processing_mode,
            )
            document = result.document
            job = result.parse_job
            results.append(
                DocumentBatchUploadItem(
                    filename=filename,
                    ok=True,
                    document_id=document.id,
                    parse_job_id=job.id,
                    job_id=job.job_id,
                    status=document.status,
                    processing_mode=document.processing_mode,
                )
            )

        except HTTPException as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error=str(exc.detail)))
        except ValueError as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error=str(exc)))
        except Exception as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error="Upload failed due to a server error."))

    return results


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description=explain_interface(
        responsibility="Return the current user's document inventory with filtering, sorting, pagination, tags, and latest parse-job status.",
        database="Reads documents, document_tags, tags, and job_runs; excludes soft-deleted documents by default.",
        files="none",
    ),
)
async def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    skip: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    keyword: str | None = Query(None),
    tag_id: int | None = Query(None, ge=1),
    file_type: str | None = Query(None, pattern="^(pdf|markdown|txt)$"),
    status: str | None = Query(None, pattern="^(pending|processing|done|completed|failed|deleted)$"),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """获取用户的文档列表。

    Args:
        skip: 跳过的记录数
        limit: 返回的最大记录数
        current_user: 当前用户
        db: 数据库会话

    Returns:
        DocumentListResponse: 文档列表响应
    """
    service = DocumentService(db)
    actual_size = limit or size
    actual_skip = skip if skip is not None else (page - 1) * actual_size
    actual_page = page if skip is None else (actual_skip // actual_size) + 1
    documents, total = service.get_user_documents(
        user_id=current_user.id,
        skip=actual_skip,
        limit=actual_size,
        keyword=keyword,
        tag_id=tag_id,
        file_type=file_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    items = []
    for doc in documents:
        latest_job = service.get_latest_parse_job(doc.id)
        items.append(serialize_document_list_item(doc, latest_job))

    return DocumentListResponse(total=total, page=actual_page, size=actual_size, items=items)


@router.get(
    "/search",
    response_model=DocumentSearchResponse,
    summary="Search documents",
    description=explain_interface(
        responsibility="Search document-level title/text content and optionally combine keyword and vector-backed results.",
        database="Reads documents and document_chunks through ORM queries.",
        files="none",
    ),
)
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    mode: str = Query("keyword", pattern="^(keyword|hybrid|semantic)$"),
    include_unparsed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSearchResponse:
    service = DocumentSearchService(db)
    if mode == "hybrid":
        hits = service.hybrid_search(current_user.id, q, limit=limit)
    elif mode == "semantic":
        # Use vector search at document level
        hits = service.search(current_user.id, q, limit=limit)  # fallback; pure semantic at chunk level
        # For now, semantic mode at document level falls back to keyword
    else:
        hits = service.search(current_user.id, q, limit=limit)
    if not include_unparsed:
        hits = [hit for hit in hits if hit.document.status in DONE_STATUSES]
    return DocumentSearchResponse(
        query=q,
        total=len(hits),
        items=[
            {
                "id": hit.document.id,
                "title": hit.document.title,
                "source_type": hit.document.source_type,
                "status": hit.document.status,
                "snippet": hit.snippet,
                "matched_field": hit.matched_field,
                "score": hit.score,
                "parsed_at": hit.document.parsed_at,
            }
            for hit in hits
        ],
    )


@router.get(
    "/search/chunks",
    response_model=ChunkSearchResponse,
    summary="Search document chunks",
    description=explain_interface(
        responsibility="Search chunk-level parsed content for RAG-style retrieval, with semantic ranking when stored embeddings are available and keyword fallback otherwise.",
        database="Reads documents and document_chunks through ORM queries.",
        files="none",
    ),
)
async def search_document_chunks(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    document_id: int | None = Query(None),
    threshold: float = Query(0.0, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChunkSearchResponse:
    service = DocumentSearchService(db)
    hits = service.search_chunks(
        user_id=current_user.id,
        query=q,
        limit=limit,
        document_id=document_id,
        threshold=threshold,
    )
    return ChunkSearchResponse(
        query=q,
        total=len(hits),
        items=[ChunkSearchHit(**hit) for hit in hits],
    )


@router.delete(
    "/batch",
    response_model=BatchDeleteResponse,
    summary="Batch hard-delete documents",
    description=explain_interface(
        responsibility="Hard-delete multiple owned documents and return per-document success or failure.",
        database="Deletes each owned document row and cascades document tags, chunks, assets, job runs, events, and knowledge graph rows.",
        files="Deletes each stored upload file and parser asset when it exists; missing files are logged and tolerated so database state stays consistent.",
    ),
)
async def batch_delete_documents(
    payload: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchDeleteResponse:
    service = DocumentService(db)
    success_ids, failed_ids, errors = service.batch_delete_documents(current_user.id, payload.ids)
    return BatchDeleteResponse(success_ids=success_ids, failed_ids=failed_ids, errors=errors)


@router.post(
    "/batch-tag",
    response_model=BatchTagResponse,
    summary="Batch assign document tags",
    description=explain_interface(
        responsibility="Attach existing user-owned tags to existing user-owned documents.",
        database="Reads documents and tags, writes document_tags, and writes document_events for updated documents in one transaction.",
        files="none",
    ),
)
async def batch_tag_documents(
    payload: BatchTagRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchTagResponse:
    service = DocumentService(db)
    try:
        assigned_count = service.batch_tag_documents(
            user_id=current_user.id,
            document_ids=payload.document_ids,
            tag_ids=payload.tag_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BatchTagResponse(
        document_ids=payload.document_ids,
        tag_ids=payload.tag_ids,
        assigned_count=assigned_count,
    )


@router.post(
    "/{document_id}/re-embed",
    response_model=dict,
    summary="Rebuild document embeddings",
    description=explain_interface(
        responsibility="Regenerate embeddings for a completed document's existing chunks.",
        database="Reads documents and document_chunks, updates document_chunks embedding fields through ORM writes.",
        files="none",
    ),
)
async def re_embed_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")
    if document.status not in DONE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document must be completed first.")

    embedding_service = DocumentEmbeddingService()
    count = embedding_service.embed_document(document_id)
    return {"document_id": document_id, "chunks_embedded": count, "message": f"Re-embedded {count} chunks."}


@router.post(
    "/re-embed-all",
    response_model=dict,
    summary="Rebuild all document embeddings",
    description=explain_interface(
        responsibility="Regenerate embeddings for every completed document owned by the current user.",
        database="Reads documents and document_chunks, updates document_chunks embedding fields through ORM writes.",
        files="none",
    ),
)
async def re_embed_all_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    docs = db.query(Document).filter(
        Document.user_id == current_user.id,
        Document.status.in_(DONE_STATUSES),
    ).all()
    embedding_service = DocumentEmbeddingService()
    total = 0
    for doc in docs:
        try:
            total += embedding_service.embed_document(doc.id)
        except Exception as exc:
            db.rollback()
    return {"user_id": current_user.id, "documents_processed": len(docs), "chunks_embedded": total}


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Read document detail",
    description=explain_interface(
        responsibility="Return one owned document with parsed text, quality metadata, tags, events, and latest parse-job summary.",
        database="Reads documents, document_events, document_tags, tags, and job_runs.",
        files="none",
    ),
)
async def get_document_detail(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    """获取文档详情。

    Args:
        document_id: 文档 ID
        current_user: 当前用户
        db: 数据库会话

    Returns:
        DocumentDetailResponse: 文档详情

    Raises:
        HTTPException: 文档不存在或无权限
    """
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )

    return serialize_document_detail(document, service.get_latest_parse_job(document.id))


@router.patch(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Update document metadata",
    description=explain_interface(
        responsibility="Update editable document metadata such as title and collection name.",
        database="Updates documents and writes a document_events audit row when values change.",
        files="none",
    ),
)
async def update_document(
    document_id: int,
    payload: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
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


@router.get(
    "/{document_id}/process/status",
    response_model=DocumentProcessingStatusResponse,
    summary="Read document processing status",
    description=explain_interface(
        responsibility="Return the current parse lifecycle state and derived processing metadata for one owned document.",
        database="Reads documents.",
        files="none",
    ),
)
async def get_document_processing_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentProcessingStatusResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    return DocumentProcessingStatusResponse(
        document_id=document.id,
        status=document.status,
        processing_status=document.status,
        error=document.error_message,
        processing_error=document.fail_reason or document.error_message,
        collection_name=document.collection_name,
        hash=document.content_hash,
        content_summary=document.content_summary,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.post(
    "/{document_id}/process",
    response_model=DocumentProcessingStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue document processing",
    description=explain_interface(
        responsibility="Create and enqueue a manual parse job for an owned document that is not already processing.",
        database="Reads and updates documents, writes job_runs, and writes document_events.",
        files="none during the request; the background parser later reads the stored upload file.",
    ),
)
async def process_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentProcessingStatusResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    running_job = service.get_running_parse_job(document_id)
    if running_job is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document processing is already pending or running.")
    try:
        document, _job = service.enqueue_parse_document(document_id, job_type="manual_process")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DocumentProcessingStatusResponse(
        document_id=document.id,
        status=document.status,
        processing_status=document.status,
        error=document.error_message,
        processing_error=document.fail_reason or document.error_message,
        collection_name=document.collection_name,
        hash=document.content_hash,
        content_summary=document.content_summary,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get(
    "/{document_id}/file",
    summary="Download original document file",
    description=explain_interface(
        responsibility="Stream the original uploaded file for one owned document.",
        database="Reads documents and does not write database rows.",
        files="reads the stored file from the upload directory; does not write files.",
    ),
)
async def get_document_file(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )

    file_path = service.file_storage.get_file_path(document.original_file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    return FileResponse(
        path=file_path,
        media_type=document.mime_type,
        filename=document.original_filename,
    )


def retry_document_or_raise(document_id: int, current_user: User, db: Session) -> DocumentDetailResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )

    try:
        running_job = service.get_running_parse_job(document_id)
        if running_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document processing is already pending or running.",
            )
        document, job = service.retry_parse(document_id)
        return serialize_document_detail(document, job)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{document_id}/retry",
    response_model=DocumentDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry failed document parsing",
    description=explain_interface(
        responsibility="Clear failed parse outputs for one failed document and queue a retry parse job.",
        database="Updates documents, writes job_runs, and writes document_events.",
        files="none during the request; the background parser later reads the stored upload file.",
    ),
)
async def retry_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    return retry_document_or_raise(document_id, current_user, db)


@router.post(
    "/{document_id}/retry-parse",
    response_model=DocumentDetailResponse,
    deprecated=True,
    summary="Retry failed document parsing compatibility alias",
    description=explain_interface(
        responsibility="Compatibility alias for /documents/{document_id}/retry.",
        database="Same as /documents/{document_id}/retry: updates documents, writes job_runs, and writes document_events.",
        files="Same as /documents/{document_id}/retry: no file write during the request; the background parser later reads the stored upload file.",
        future="Prefer /documents/{document_id}/retry so retry behavior has one canonical endpoint.",
    ),
)
async def retry_parse_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    """重新解析文档。

    Args:
        document_id: 文档 ID
        current_user: 当前用户
        db: 数据库会话

    Returns:
        DocumentDetailResponse: 更新后的文档详情

    Raises:
        HTTPException: 文档不存在、无权限或状态无效
    """
    return retry_document_or_raise(document_id, current_user, db)


@router.delete(
    "/{document_id}",
    response_model=dict,
    summary="Hard-delete document",
    description=explain_interface(
        responsibility="Hard-delete one owned document after ownership verification.",
        database="Deletes the document row, cascades document tags, chunks, assets, job runs, events, and knowledge graph rows, and enqueues file cleanup jobs in the same transaction.",
        files="Physical file deletion is handled after commit by the cleanup outbox so request success is not coupled to filesystem availability.",
    ),
)
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """硬删除文档。

    Args:
        document_id: 文档 ID
        current_user: 当前用户
        db: 数据库会话

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 文档不存在或无权限
    """
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this document.",
        )

    deleted_id = service.hard_delete_document(document_id)

    return {"id": deleted_id, "status": "deleted", "message": "Document deleted."}


@router.get(
    "/{document_id}/events",
    response_model=PaginatedDocumentEvents,
    summary="List document events",
    description=explain_interface(
        responsibility="Return the audit timeline for one owned document.",
        database="Reads documents and document_events.",
        files="none",
    ),
)
async def get_document_events(
    document_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedDocumentEvents:
    """获取文档事件日志。

    Args:
        document_id: 文档 ID
        current_user: 当前用户
        db: 数据库会话

    Returns:
        list[DocumentEventRead]: 事件列表

    Raises:
        HTTPException: 文档不存在或无权限
    """
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )

    query = db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)
    total = query.count()
    events = (
        query.order_by(DocumentEvent.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return PaginatedDocumentEvents(
        total=total,
        page=page,
        size=size,
        items=[DocumentEventRead.model_validate(event) for event in events],
    )


@router.get(
    "/{document_id}/parse-jobs",
    response_model=list[ParseJobRead],
    summary="List document parse jobs",
    description=explain_interface(
        responsibility="Return recent parse job runs for one owned document.",
        database="Reads documents and job_runs.",
        files="none",
    ),
)
async def get_document_parse_jobs(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ParseJobRead]:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    return [
        serialized
        for serialized in (
            serialize_latest_parse_job(job_run)
            for job_run in JobRunService(db).list_jobs(
                user_id=current_user.id,
                kind_filter="document_parse",
                document_id=document.id,
                limit=100,
            )
        )
        if serialized is not None
    ]


@router.get(
    "/{document_id}/chunks",
    response_model=list[DocumentChunkRead],
    summary="List document chunks",
    description=explain_interface(
        responsibility="Return parser-generated chunks for one owned document in chunk order.",
        database="Reads documents and document_chunks.",
        files="none",
    ),
)
async def get_document_chunks(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentChunkRead]:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    if document.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    return [DocumentChunkRead.model_validate(chunk) for chunk in chunks]


@router.get(
    "/{document_id}/kg",
    response_model=DocumentKgResponse,
    summary="Read document knowledge graph",
    description=explain_interface(
        responsibility="Return extracted entities and relations for one owned document.",
        database="Reads documents, kg_entities, and kg_relations.",
        files="does not touch files.",
    ),
)
async def get_document_kg(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentKgResponse:
    service = DocumentService(db)
    document = service.get_document_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this document.",
        )

    entities = (
        db.query(KgEntity)
        .filter(KgEntity.document_id == document_id)
        .order_by(KgEntity.name)
        .all()
    )
    relations = (
        db.query(KgRelation)
        .filter(KgRelation.document_id == document_id)
        .order_by(KgRelation.id)
        .all()
    )
    return DocumentKgResponse(
        document_id=document_id,
        entities=entities,
        relations=relations,
    )
