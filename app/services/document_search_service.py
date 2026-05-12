from __future__ import annotations

import json
import math
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.document_embedding_service import EmbeddingProvider, HashEmbeddingProvider


@dataclass(slots=True)
class DocumentSearchHit:
    document: Document
    snippet: str
    matched_field: str
    score: float = 0.0


class DocumentSearchService:
    def __init__(self, db: Session, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.db = db
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

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

    def hybrid_search(self, user_id: int, query: str, limit: int = 20) -> list[DocumentSearchHit]:
        keyword_hits = self.search(user_id, query, limit=limit)
        hits_by_document = {
            hit.document.id: DocumentSearchHit(
                document=hit.document,
                snippet=hit.snippet,
                matched_field=hit.matched_field,
                score=1.0,
            )
            for hit in keyword_hits
        }

        query_vector = self.embedding_provider.embed([query])[0]
        chunks = (
            self.db.query(DocumentChunk)
            .join(Document)
            .filter(
                Document.user_id == user_id,
                Document.status != "deleted",
                DocumentChunk.embedding_json.isnot(None),
            )
            .all()
        )
        for chunk in chunks:
            vector = json.loads(chunk.embedding_json or "[]")
            vector_score = self._cosine_similarity(query_vector, vector)
            if vector_score <= 0:
                continue
            existing = hits_by_document.get(chunk.document_id)
            score = 0.7 * vector_score + (existing.score if existing else 0.0)
            if existing is None or score > existing.score:
                hits_by_document[chunk.document_id] = DocumentSearchHit(
                    document=chunk.document,
                    snippet=self._snippet(chunk.cleaned_text, query),
                    matched_field="vector",
                    score=score,
                )

        return sorted(hits_by_document.values(), key=lambda hit: hit.score, reverse=True)[:limit]

    def _build_hit(self, document: Document, query: str) -> DocumentSearchHit:
        for field_name, value in (
            ("title", document.title),
            ("cleaned_text", document.cleaned_text),
            ("parsed_text", document.parsed_text),
        ):
            if value and query.lower() in value.lower():
                return DocumentSearchHit(document, self._snippet(value, query), field_name, score=1.0)

        for chunk in document.document_chunks:
            if query.lower() in chunk.cleaned_text.lower():
                return DocumentSearchHit(document, self._snippet(chunk.cleaned_text, query), "chunk", score=1.0)

        return DocumentSearchHit(document, document.title, "document", score=0.0)

    def _snippet(self, text: str, query: str, radius: int = 80) -> str:
        index = text.lower().find(query.lower())
        if index < 0:
            return text[: radius * 2].strip()
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
