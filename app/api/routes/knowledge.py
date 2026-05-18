from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
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
    response_model=list[CollectionRead],
    summary="List knowledge collections",
    description=explain_interface(
        responsibility="Return named user-owned collections used to organize knowledge documents.",
        database="Reads collections only.",
        files="none",
    ),
)
def list_collections(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CollectionRead]:
    collections = (
        db.query(Collection)
        .filter(Collection.user_id == current_user.id)
        .order_by(Collection.name.asc())
        .all()
    )
    return [CollectionRead.model_validate(collection) for collection in collections]


@router.post(
    "/collections",
    response_model=CollectionRead,
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
) -> CollectionRead:
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
    return CollectionRead.model_validate(collection)


def build_statistics(current_user: User, db: Session) -> DashboardStatsResponse:
    base_filters = [Document.user_id == current_user.id, Document.status != "deleted"]
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
