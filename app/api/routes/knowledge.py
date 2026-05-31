from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import app_now
from app.db.session import get_db
from app.models import Collection, Document, DocumentTag, Tag, User
from app.schemas.auth import MessageResponse
from app.schemas.document import (
    CollectionCreate,
    CollectionRead,
    DashboardStatsResponse,
    DocumentListResponse,
    FileTypeCount,
    StatusCount,
    TagCreate,
    TagRead,
    TagUpdate,
)
from app.services.document_service import DONE_STATUSES

router = APIRouter(tags=["knowledge"])


def explain_interface(*, responsibility: str, database: str, files: str, future: str | None = None) -> str:
    parts = [
        f"Responsibility: {responsibility}",
        f"Database: {database}",
        f"Files: {files}",
    ]
    if future:
        parts.append(f"Future simplification: {future}")
    return "\n\n".join(parts)


def assert_collection_owner(collection: Collection, current_user: User) -> None:
    if collection.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")


def assert_document_owner(document: Document, current_user: User) -> None:
    if document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")


def get_owned_collection(collection_id: int, current_user: User, db: Session) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")
    assert_collection_owner(collection, current_user)
    return collection


def serialize_collection(collection: Collection, db: Session) -> dict:
    document_count = (
        db.query(func.count(Document.id))
        .filter(
            Document.user_id == collection.user_id,
            Document.is_deleted == False,
            Document.collection_name == collection.name,
        )
        .scalar()
        or 0
    )
    return {
        "id": collection.id,
        "user_id": collection.user_id,
        "name": collection.name,
        "description": collection.description,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
        "document_count": document_count,
    }


def serialize_document_list_item(document: Document) -> dict:
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
        "latest_parse_job_status": None,
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


def build_collection_documents_query(
    *,
    db: Session,
    user_id: int,
    collection_name: str,
    keyword: str | None = None,
    file_type: str | None = None,
    status_filter: str | None = None,
):
    query = db.query(Document).filter(
        Document.user_id == user_id,
        Document.is_deleted == False,
        Document.collection_name == collection_name,
    )
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Document.title.ilike(pattern),
                Document.original_filename.ilike(pattern),
                Document.parsed_text.ilike(pattern),
                Document.cleaned_text.ilike(pattern),
            )
        )
    if file_type:
        query = query.filter(Document.source_type == file_type)
    if status_filter:
        if status_filter in DONE_STATUSES:
            query = query.filter(Document.status.in_(DONE_STATUSES))
        else:
            query = query.filter(Document.status == status_filter)
    return query


@router.get(
    "/tags",
    response_model=list[TagRead],
    summary="List knowledge tags",
    description=explain_interface(
        responsibility="Return the current user's reusable knowledge tags.",
        database="Reads tags only.",
        files="none",
    ),
)
def list_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TagRead]:
    tags = db.query(Tag).filter(Tag.user_id == current_user.id).order_by(Tag.name.asc()).all()
    return [TagRead.model_validate(tag) for tag in tags]


@router.post(
    "/tags",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge tag",
    description=explain_interface(
        responsibility="Create one reusable tag for classifying documents in the user's knowledge base.",
        database="Writes tags; uniqueness is scoped to the current user.",
        files="none",
    ),
)
def create_tag(
    payload: TagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TagRead:
    tag = Tag(user_id=current_user.id, name=payload.name.strip(), color=payload.color)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.") from exc
    db.refresh(tag)
    return TagRead.model_validate(tag)


@router.patch(
    "/tags/{tag_id}",
    response_model=TagRead,
    summary="Update knowledge tag",
    description=explain_interface(
        responsibility="Rename or recolor one user-owned knowledge tag.",
        database="Reads and updates tags.",
        files="none",
    ),
)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TagRead:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    if tag.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")
    if payload.name is not None:
        tag.name = payload.name.strip()
    if payload.color is not None:
        tag.color = payload.color
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.") from exc
    db.refresh(tag)
    return TagRead.model_validate(tag)


@router.delete(
    "/tags/{tag_id}",
    response_model=MessageResponse,
    summary="Delete knowledge tag",
    description=explain_interface(
        responsibility="Delete one user-owned tag and remove its document assignments.",
        database="Deletes document_tags links, then deletes the tag from tags.",
        files="none",
    ),
)
def delete_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    if tag.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")
    db.query(DocumentTag).filter(DocumentTag.tag_id == tag.id).delete()
    db.delete(tag)
    db.commit()
    return MessageResponse(message="Tag deleted.")


@router.get(
    "/collections",
    response_model=list[dict],
    summary="List knowledge collections",
    description=explain_interface(
        responsibility="Return named user-owned collections used to organize knowledge documents.",
        database="Reads collections and counts matching documents.",
        files="none",
    ),
)
def list_collections(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    collections = (
        db.query(Collection)
        .filter(Collection.user_id == current_user.id)
        .order_by(Collection.name.asc())
        .all()
    )
    return [serialize_collection(collection, db) for collection in collections]


@router.post(
    "/collections",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge collection",
    description=explain_interface(
        responsibility="Create one named collection for grouping knowledge documents.",
        database="Writes collections; uniqueness is scoped to the current user.",
        files="none",
    ),
)
def create_collection(
    payload: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    collection = Collection(
        user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(collection)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collection already exists.") from exc
    db.refresh(collection)
    return serialize_collection(collection, db)


@router.patch(
    "/collections/{collection_id}",
    response_model=dict,
    summary="Update knowledge collection",
    description=explain_interface(
        responsibility="Rename or describe one user-owned collection.",
        database="Updates collections and keeps document collection_name values in sync when renamed.",
        files="none",
    ),
)
def update_collection(
    collection_id: int,
    payload: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    collection = get_owned_collection(collection_id, current_user, db)
    old_name = collection.name
    next_name = payload.name.strip()
    collection.name = next_name
    collection.description = payload.description
    if old_name != next_name:
        db.query(Document).filter(
            Document.user_id == current_user.id,
            Document.collection_name == old_name,
        ).update({Document.collection_name: next_name}, synchronize_session=False)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collection already exists.") from exc
    db.refresh(collection)
    return serialize_collection(collection, db)


@router.delete(
    "/collections/{collection_id}",
    response_model=MessageResponse,
    summary="Delete knowledge collection",
    description=explain_interface(
        responsibility="Delete one collection without deleting documents.",
        database="Clears matching document collection_name values, then deletes the collection row.",
        files="none",
    ),
)
def delete_collection(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    collection = get_owned_collection(collection_id, current_user, db)
    db.query(Document).filter(
        Document.user_id == current_user.id,
        Document.collection_name == collection.name,
    ).update({Document.collection_name: None}, synchronize_session=False)
    db.delete(collection)
    db.commit()
    return MessageResponse(message="Collection deleted.")


@router.get(
    "/collections/{collection_id}/documents",
    response_model=DocumentListResponse,
    summary="List collection documents",
    description=explain_interface(
        responsibility="Return documents assigned to one authenticated user-owned collection.",
        database="Reads collections and documents filtered by collection_name.",
        files="none",
    ),
)
def list_collection_documents(
    collection_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    file_type: str | None = Query(None, pattern="^(pdf|markdown|txt|image|docx|epub|bookmark)$"),
    status_filter: str | None = Query(None, alias="status", pattern="^(pending|processing|done|completed|failed|deleted)$"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    collection = get_owned_collection(collection_id, current_user, db)
    query = build_collection_documents_query(
        db=db,
        user_id=current_user.id,
        collection_name=collection.name,
        keyword=keyword,
        file_type=file_type,
        status_filter=status_filter,
    )
    total = query.count()
    sort_columns = {
        "created_at": Document.created_at,
        "uploaded_at": Document.uploaded_at,
        "parsed_at": Document.parsed_at,
        "title": Document.title,
        "file_size": Document.file_size,
        "status": Document.status,
        "source_type": Document.source_type,
    }
    sort_column = sort_columns.get(sort_by, Document.created_at)
    ordering = sort_column.asc() if sort_order.lower() == "asc" else sort_column.desc()
    documents = query.order_by(ordering).offset((page - 1) * size).limit(size).all()
    return DocumentListResponse(total=total, page=page, size=size, items=[serialize_document_list_item(doc) for doc in documents])


@router.post(
    "/collections/{collection_id}/documents/{document_id}",
    response_model=MessageResponse,
    summary="Add document to collection",
    description=explain_interface(
        responsibility="Assign one authenticated user-owned document to a collection.",
        database="Reads collections and documents; updates documents.collection_name.",
        files="none",
    ),
)
def add_document_to_collection(
    collection_id: int,
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    collection = get_owned_collection(collection_id, current_user, db)
    document = db.get(Document, document_id)
    if document is None or document.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    document.collection_name = collection.name
    db.commit()
    return MessageResponse(message="Document added to collection.")


@router.delete(
    "/collections/{collection_id}/documents/{document_id}",
    response_model=MessageResponse,
    summary="Remove document from collection",
    description=explain_interface(
        responsibility="Remove one authenticated user-owned document from a collection.",
        database="Reads collections and documents; clears documents.collection_name.",
        files="none",
    ),
)
def remove_document_from_collection(
    collection_id: int,
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    collection = get_owned_collection(collection_id, current_user, db)
    document = db.get(Document, document_id)
    if document is None or document.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    assert_document_owner(document, current_user)
    if document.collection_name == collection.name:
        document.collection_name = None
        db.commit()
    return MessageResponse(message="Document removed from collection.")


def build_statistics(current_user: User, db: Session) -> DashboardStatsResponse:
    base_filters = [Document.user_id == current_user.id, Document.is_deleted == False]
    total = db.query(func.count(Document.id)).filter(*base_filters).scalar() or 0
    done = db.query(func.count(Document.id)).filter(*base_filters, Document.status.in_(DONE_STATUSES)).scalar() or 0
    failed = db.query(func.count(Document.id)).filter(*base_filters, Document.status == "failed").scalar() or 0
    recent_since = app_now() - timedelta(days=7)
    recent = db.query(func.count(Document.id)).filter(*base_filters, Document.uploaded_at >= recent_since).scalar() or 0

    file_type_rows = (
        db.query(Document.source_type, func.count(Document.id))
        .filter(*base_filters)
        .group_by(Document.source_type)
        .all()
    )
    status_rows = (
        db.query(Document.status, func.count(Document.id))
        .filter(*base_filters)
        .group_by(Document.status)
        .all()
    )
    denominator = done + failed
    return DashboardStatsResponse(
        total_documents=total,
        done_documents=done,
        failed_documents=failed,
        parse_success_rate=round(done / denominator, 4) if denominator else 0.0,
        recent_7_days_documents=recent,
        file_type_distribution=[
            FileTypeCount(file_type=file_type, count=count, ratio=round(count / total, 4) if total else 0.0)
            for file_type, count in file_type_rows
        ],
        status_distribution=[StatusCount(status=status_value, count=count) for status_value, count in status_rows],
    )


@router.get(
    "/statistics",
    response_model=DashboardStatsResponse,
    summary="Read knowledge dashboard statistics",
    description=explain_interface(
        responsibility="Return aggregate knowledge-base document counts for dashboard views.",
        database="Reads documents only; this endpoint is read-only.",
        files="none",
    ),
)
def get_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    return build_statistics(current_user, db)


@router.get(
    "/dashboard/stats",
    response_model=DashboardStatsResponse,
    deprecated=True,
    summary="Read dashboard statistics compatibility alias",
    description=explain_interface(
        responsibility="Compatibility alias for /statistics.",
        database="Same as /statistics: reads documents only and is read-only.",
        files="none",
        future="Prefer /statistics so dashboard metrics have one canonical endpoint.",
    ),
)
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    return build_statistics(current_user, db)
