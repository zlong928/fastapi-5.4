from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Document, JobRun
from app.schemas.document import (
    DocumentBatchUploadItem,
    DocumentChunkRead,
    DocumentDetailResponse,
    DocumentEventRead,
    DocumentKgResponse,
    DocumentListResponse,
    DocumentProcessingMode,
    ParseJobRead,
    DocumentSearchResponse,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService
from app.services.document_search_service import DocumentSearchService
from app.services.document_upload_service import DocumentUploadService
from app.services.job_run_service import JobRunService
from app.models import KgEntity, KgRelation
from app.models import DocumentChunk
from app.utils.json import json_loads_object_or_none

router = APIRouter(prefix="/documents", tags=["documents"])

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
    return DocumentDetailResponse(
        id=document.id,
        user_id=document.user_id,
        title=document.title,
        original_filename=document.original_filename,
        source_type=document.source_type,
        processing_mode=document.processing_mode,
        processing_strategy=document.processing_strategy,
        status=document.status,
        file_size=document.file_size,
        mime_type=document.mime_type,
        parsed_text=document.parsed_text,
        cleaned_text=document.cleaned_text,
        parse_quality_json=document.parse_quality_json,
        references_text=document.references_text,
        error_message=document.error_message,
        created_at=document.created_at,
        uploaded_at=document.uploaded_at,
        parsed_at=document.parsed_at,
        latest_parse_job=serialize_latest_parse_job(latest_parse_job),
        events=[DocumentEventRead.model_validate(event) for event in events],
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    processing_mode: DocumentProcessingMode = Form(DocumentProcessingMode.AUTO),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """上传单个文档。

    支持 PDF, Markdown, TXT 文件。
    
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
        return DocumentUploadResponse(
            document_id=document.id,
            status=document.status,
            parse_job_id=job.id,
            job_id=job.job_id,
            processing_mode=document.processing_mode,
            message="Document uploaded and queued for parsing.",
        )
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
            detail=f"Upload failed: {str(exc)}",
        ) from exc


@router.post("/batch-upload", response_model=list[DocumentBatchUploadItem], status_code=status.HTTP_202_ACCEPTED)
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
        except Exception as exc:
            results.append(DocumentBatchUploadItem(filename=filename, ok=False, error=str(exc)))

    return results


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
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
    documents, total = service.get_user_documents(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )

    items = []
    for doc in documents:
        latest_job = service.get_latest_parse_job(doc.id)
        items.append(
            {
            "id": doc.id,
            "title": doc.title,
            "original_filename": doc.original_filename,
            "source_type": doc.source_type,
            "processing_mode": doc.processing_mode,
            "processing_strategy": doc.processing_strategy,
            "status": doc.status,
            "file_size": doc.file_size,
            "error_message": doc.error_message,
            "latest_parse_job_status": latest_job.status if latest_job else None,
            "created_at": doc.created_at,
            "uploaded_at": doc.uploaded_at,
            "parsed_at": doc.parsed_at,
            }
        )

    return DocumentListResponse(total=total, items=items)


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    mode: str = Query("keyword", pattern="^(keyword|hybrid)$"),
    include_unparsed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSearchResponse:
    service = DocumentSearchService(db)
    hits = service.hybrid_search(current_user.id, q, limit=limit) if mode == "hybrid" else service.search(current_user.id, q, limit=limit)
    if not include_unparsed:
        hits = [hit for hit in hits if hit.document.status == "parsed"]
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


@router.get("/{document_id}", response_model=DocumentDetailResponse)
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


@router.get("/{document_id}/file")
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


@router.post("/{document_id}/retry-parse", response_model=DocumentDetailResponse)
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
                detail="Document parsing is already queued or running.",
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


@router.delete("/{document_id}", response_model=dict)
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """软删除文档。

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

    document = service.soft_delete_document(document_id)

    return {"id": document.id, "status": document.status, "message": "Document deleted."}


@router.get("/{document_id}/events", response_model=list[DocumentEventRead])
async def get_document_events(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentEventRead]:
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

    return [DocumentEventRead.model_validate(event) for event in document.events]


@router.get("/{document_id}/parse-jobs", response_model=list[ParseJobRead])
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


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkRead])
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


@router.get("/{document_id}/kg", response_model=DocumentKgResponse)
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
