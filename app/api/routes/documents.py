from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentEventRead,
    DocumentKgResponse,
    DocumentListResponse,
    DocumentSearchResponse,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService
from app.services.document_search_service import DocumentSearchService
from app.services.file_storage import FileStorageService
from app.models import KgEntity, KgRelation

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    """获取文档服务实例。"""
    return DocumentService(db)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = None,
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
    # 验证文件类型
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required.",
        )

    # 获取文件扩展名
    filename_parts = file.filename.rsplit(".", 1)
    if len(filename_parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have an extension.",
        )

    original_filename, ext = filename_parts
    ext = ext.lower()

    # 映射扩展名到 source_type
    ext_map = {
        "pdf": "pdf",
        "md": "markdown",
        "markdown": "markdown",
        "txt": "txt",
        "text": "txt",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
        "webp": "image",
    }

    if ext not in ext_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Only PDF, Markdown, TXT, PNG, JPG, JPEG, and WEBP are allowed.",
        )

    source_type = ext_map[ext]
    mime_type = file.content_type or "application/octet-stream"

    try:
        # 读取文件内容
        content = await file.read()
        file_size = len(content)

        # 存储文件
        file_storage = FileStorageService()
        relative_path, stored_filename = file_storage.store_file(
            user_id=current_user.id,
            original_filename=file.filename,
            file_content=content,
            file_extension=ext,
        )

        # 创建文档记录
        service = DocumentService(db, file_storage)
        document = service.create_document(
            user_id=current_user.id,
            title=title or original_filename,
            original_filename=file.filename,
            stored_filename=stored_filename,
            original_file_path=relative_path,
            file_size=file_size,
            mime_type=mime_type,
            source_type=source_type,
        )

        # 同步解析（当前阶段）
        document = service.parse_document(document.id)

        return DocumentUploadResponse.model_validate(document)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )


@router.post("/batch-upload", response_model=list[DocumentUploadResponse])
async def upload_batch(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentUploadResponse]:
    """批量上传文档。

    Args:
        files: 上传的文件列表
        current_user: 当前用户
        db: 数据库会话

    Returns:
        list[DocumentUploadResponse]: 上传响应列表
    """
    results = []

    for file in files:
        try:
            # 重用单个上传的逻辑
            if not file.filename:
                continue

            filename_parts = file.filename.rsplit(".", 1)
            if len(filename_parts) != 2:
                continue

            original_filename, ext = filename_parts
            ext = ext.lower()

            ext_map = {
                "pdf": "pdf",
                "md": "markdown",
                "markdown": "markdown",
                "txt": "txt",
                "text": "txt",
                "png": "image",
                "jpg": "image",
                "jpeg": "image",
                "webp": "image",
            }

            if ext not in ext_map:
                continue

            source_type = ext_map[ext]
            mime_type = file.content_type or "application/octet-stream"

            # 读取文件内容
            content = await file.read()
            file_size = len(content)

            # 存储文件
            file_storage = FileStorageService()
            relative_path, stored_filename = file_storage.store_file(
                user_id=current_user.id,
                original_filename=file.filename,
                file_content=content,
                file_extension=ext,
            )

            # 创建文档记录
            service = DocumentService(db, file_storage)
            document = service.create_document(
                user_id=current_user.id,
                title=original_filename,
                original_filename=file.filename,
                stored_filename=stored_filename,
                original_file_path=relative_path,
                file_size=file_size,
                mime_type=mime_type,
                source_type=source_type,
            )

            # 同步解析
            document = service.parse_document(document.id)
            results.append(DocumentUploadResponse.model_validate(document))

        except Exception:
            # 跳过错误的文件，继续处理其他文件
            continue

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

    items = [
        {
            "id": doc.id,
            "title": doc.title,
            "source_type": doc.source_type,
            "status": doc.status,
            "file_size": doc.file_size,
            "created_at": doc.created_at,
            "uploaded_at": doc.uploaded_at,
            "parsed_at": doc.parsed_at,
        }
        for doc in documents
    ]

    return DocumentListResponse(total=total, items=items)


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    mode: str = Query("keyword", pattern="^(keyword|hybrid)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSearchResponse:
    service = DocumentSearchService(db)
    hits = service.hybrid_search(current_user.id, q, limit=limit) if mode == "hybrid" else service.search(current_user.id, q, limit=limit)
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

    events = [DocumentEventRead.model_validate(event) for event in document.events]

    return DocumentDetailResponse(
        id=document.id,
        user_id=document.user_id,
        title=document.title,
        original_filename=document.original_filename,
        source_type=document.source_type,
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
        events=events,
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
        document = service.retry_parse(document_id)
        events = [DocumentEventRead.model_validate(event) for event in document.events]

        return DocumentDetailResponse(
            id=document.id,
            user_id=document.user_id,
            title=document.title,
            original_filename=document.original_filename,
            source_type=document.source_type,
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
            events=events,
        )
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
