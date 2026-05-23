from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Document, DocumentEvent, JobRun
from app.schemas.document import (
    BookmarkCreate,
    BookmarkCreateResponse,
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
from app.services.bookmark_service import BookmarkError, BookmarkService
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
        source_url=document.source_url,
        site_name=document.site_name,
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
        "source_url": document.source_url,
        "site_name": document.site_name,
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


@router.post("/bookmarks", response_model=BookmarkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark_document(
    payload: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookmarkCreateResponse:
    try:
        document = await BookmarkService(db).create_bookmark(
            user_id=current_user.id,
            url=payload.url,
            title=payload.title,
            collection_name=payload.collection_name,
            tag_ids=payload.tag_ids,
            processing_mode=payload.processing_mode.value,
        )
    except BookmarkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BookmarkCreateResponse(
        document_id=document.id,
        status=document.status,
        processing_status=document.status,
        source_type=document.source_type,
        source_url=document.source_url,
        message="已保存" if document.status in DONE_STATUSES else (document.fail_reason or "保存失败"),
    )


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
        if document.source_type in {"epub", "docx"}:
            message = "Document uploaded for preview. Text extraction is not enabled for this file type."
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


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    skip: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    keyword: str | None = Query(None),
    tag_id: int | None = Query(None, ge=1),
    file_type: str | None = Query(None, pattern="^(pdf|markdown|txt|image|docx|epub|bookmark)$"),
    status: str | None = Query(None, pattern="^(pending|processing|done|completed|failed|deleted)$"),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
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


# The rest of this file is intentionally unchanged below this point.
