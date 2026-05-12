from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk


@dataclass(slots=True)
class DocumentSearchHit:
    document: Document
    snippet: str
    matched_field: str


class DocumentSearchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, user_id: int, query: str, limit: int = 20) -> list[DocumentSearchHit]:
        normalized = query.strip()
        if not normalized:
            return []
        pattern = f"%{normalized}%"
        documents = (
            self.db.query(Document)
            .outerjoin(DocumentChunk)
            .filter(Document.user_id == user_id, Document.status != "deleted")
            .filter(
                or_(
                    Document.title.ilike(pattern),
                    Document.cleaned_text.ilike(pattern),
                    Document.parsed_text.ilike(pattern),
                    DocumentChunk.cleaned_text.ilike(pattern),
                )
            )
            .distinct()
            .order_by(Document.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._build_hit(document, normalized) for document in documents]

    def _build_hit(self, document: Document, query: str) -> DocumentSearchHit:
        for field_name, value in (
            ("title", document.title),
            ("cleaned_text", document.cleaned_text),
            ("parsed_text", document.parsed_text),
        ):
            if value and query.lower() in value.lower():
                return DocumentSearchHit(document, self._snippet(value, query), field_name)

        for chunk in document.document_chunks:
            if query.lower() in chunk.cleaned_text.lower():
                return DocumentSearchHit(document, self._snippet(chunk.cleaned_text, query), "chunk")

        return DocumentSearchHit(document, document.title, "document")

    def _snippet(self, text: str, query: str, radius: int = 80) -> str:
        index = text.lower().find(query.lower())
        if index < 0:
            return text[: radius * 2].strip()
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"
