from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import app_now
from app.db.session import get_db
from app.models import Document, DocumentChunk, DocumentTag, Tag, User
from app.schemas.document import DocumentDetailResponse, DocumentEventRead, ParseJobRead, TagRead
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_service import DocumentService

router = APIRouter(prefix="/notes", tags=["notes"])


class NotePayload(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    body: str = Field(default="")
    tags: list[str] = Field(default_factory=list, max_length=50)
    source_type: Literal["note", "diary"] = "note"
    document_title: str | None = Field(default=None, max_length=255)


class NoteRead(BaseModel):
    id: str
    document_id: int
    title: str
    body: str
    tags: list[str]
    source_type: str
    document_title: str | None = None
    created_at: datetime
    updated_at: datetime


def note_uid_from_path(path: str) -> str:
    return path.split(":", 1)[1] if ":" in path else str(path)


def normalize_tag_name(name: str) -> str:
    return name.strip().lstrip("#").strip()


def note_title(title: str | None) -> str:
    cleaned = (title or "").strip()
    return cleaned or "未命名笔记"


def serialize_note(document: Document) -> NoteRead:
    tags = [link.tag.name for link in document.tag_links]
    return NoteRead(
        id=note_uid_from_path(document.original_file_path),
        document_id=document.id,
        title=document.title,
        body=document.cleaned_text or document.parsed_text or "",
        tags=tags,
        source_type=document.source_type,
        document_title=document.site_name,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def serialize_document_detail(document: Document) -> DocumentDetailResponse:
    tags = [TagRead.model_validate(link.tag) for link in document.tag_links]
    events = sorted(document.events, key=lambda event: event.created_at)
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
        latest_parse_job=None,
        events=[DocumentEventRead.model_validate(event) for event in events],
        tags=tags,
    )


def split_note_chunks(text: str, *, max_chars: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars])
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def sync_note_chunks(db: Session, document: Document, body: str) -> None:
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete(synchronize_session=False)
    chunks = split_note_chunks(body)
    position = 0
    for index, chunk in enumerate(chunks):
        start = body.find(chunk, position)
        if start < 0:
            start = position
        end = start + len(chunk)
        db.add(DocumentChunk(
            document_id=document.id,
            chunk_index=index,
            chunk_type="note",
            text=chunk,
            cleaned_text=chunk,
            char_start=start,
            char_end=end,
            token_count=len(chunk.split()),
            metadata_json='{"source_type":"note"}',
        ))
        position = end
    document.chunk_count = len(chunks)


def sync_note_tags(db: Session, document: Document, user_id: int, tag_names: list[str]) -> None:
    clean_names = []
    for name in tag_names:
        cleaned = normalize_tag_name(name)
        if cleaned and cleaned not in clean_names:
            clean_names.append(cleaned)
    db.query(DocumentTag).filter(DocumentTag.document_id == document.id).delete(synchronize_session=False)
    for name in clean_names:
        tag = db.query(Tag).filter(Tag.user_id == user_id, Tag.name == name).first()
        if tag is None:
            tag = Tag(user_id=user_id, name=name)
            db.add(tag)
            db.flush()
        db.add(DocumentTag(document_id=document.id, tag_id=tag.id))


def try_embed_note(document_id: int) -> None:
    try:
        DocumentEmbeddingService().embed_document(document_id)
    except Exception:
        pass


def upsert_note_document(db: Session, current_user: User, payload: NotePayload, *, note_id: str | None = None) -> Document:
    uid = note_id or hashlib.sha1(f"{current_user.id}:{app_now().isoformat()}".encode()).hexdigest()[:24]
    source_type = payload.source_type
    path = f"{source_type}:{uid}"
    title = note_title(payload.title)
    body = payload.body or ""
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    document = db.query(Document).filter(Document.user_id == current_user.id, Document.original_file_path == path).first()
    now = app_now()
    if document is None:
        document = Document(
            user_id=current_user.id,
            title=title,
            original_filename=f"{title}.md",
            stored_filename=f"{uid}.md",
            original_file_path=path,
            file_size=len(body.encode("utf-8")),
            mime_type="text/markdown",
            source_type=source_type,
            site_name=payload.document_title,
            processing_mode="markdown_notes",
            processing_strategy="note_document",
            parsed_text=body,
            cleaned_text=body,
            status="done",
            collection_name="笔记" if source_type == "note" else "日记",
            content_hash=content_hash,
            content_summary=body.strip()[:120] or None,
            parsed_at=now,
        )
        db.add(document)
        db.flush()
    else:
        document.title = title
        document.original_filename = f"{title}.md"
        document.file_size = len(body.encode("utf-8"))
        document.source_type = source_type
        document.site_name = payload.document_title
        document.parsed_text = body
        document.cleaned_text = body
        document.status = "done"
        document.content_hash = content_hash
        document.content_summary = body.strip()[:120] or None
        document.parsed_at = now
    sync_note_tags(db, document, current_user.id, payload.tags)
    sync_note_chunks(db, document, body)
    DocumentService(db).log_event(document.id, current_user.id, "note_saved", "笔记已保存", commit=False)
    db.commit()
    db.refresh(document)
    try_embed_note(document.id)
    db.refresh(document)
    return document


@router.get("", response_model=list[NoteRead])
def list_notes(
    source_type: str | None = Query(None, pattern="^(note|diary)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NoteRead]:
    query = db.query(Document).filter(Document.user_id == current_user.id, Document.status != "deleted", Document.source_type.in_(["note", "diary"]))
    if source_type:
        query = query.filter(Document.source_type == source_type)
    documents = query.order_by(Document.updated_at.desc()).all()
    return [serialize_note(document) for document in documents]


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NotePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NoteRead:
    document = upsert_note_document(db, current_user, payload)
    return serialize_note(document)


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NoteRead:
    document = db.query(Document).filter(Document.user_id == current_user.id, Document.original_file_path.in_([f"note:{note_id}", f"diary:{note_id}"])).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    return serialize_note(document)


@router.patch("/{note_id}", response_model=NoteRead)
def update_note(note_id: str, payload: NotePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NoteRead:
    existing = db.query(Document).filter(Document.user_id == current_user.id, Document.original_file_path.in_([f"note:{note_id}", f"diary:{note_id}"])).first()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    document = upsert_note_document(db, current_user, payload, note_id=note_id)
    return serialize_note(document)


@router.delete("/{note_id}", response_model=dict)
def delete_note(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    document = db.query(Document).filter(Document.user_id == current_user.id, Document.original_file_path.in_([f"note:{note_id}", f"diary:{note_id}"])).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    deleted_id = DocumentService(db).hard_delete_document(document.id)
    return {"id": note_id, "document_id": deleted_id, "status": "deleted"}


@router.get("/{note_id}/document", response_model=DocumentDetailResponse)
def get_note_document(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentDetailResponse:
    document = db.query(Document).filter(Document.user_id == current_user.id, Document.original_file_path.in_([f"note:{note_id}", f"diary:{note_id}"])).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    return serialize_document_detail(document)
