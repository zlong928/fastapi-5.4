from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass

from sqlalchemy import or_, text
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
        hits_by_document: dict[int, DocumentSearchHit] = {
            hit.document.id: DocumentSearchHit(
                document=hit.document,
                snippet=hit.snippet,
                matched_field=hit.matched_field,
                score=1.0,
            )
            for hit in keyword_hits
        }

        # Use sqlite-vec ANN search instead of full-load + Python cosine
        vec_hits = self._vector_search(user_id, query, limit=limit * 2)
        for vec_hit in vec_hits:
            vector_score = vec_hit["score"]
            if vector_score <= 0:
                continue
            doc_id = vec_hit["document_id"]
            existing = hits_by_document.get(doc_id)
            score = 0.7 * vector_score + (existing.score if existing else 0.0)
            if existing is None or score > existing.score:
                # Build a DocumentSearchHit for this vec hit
                doc = (
                    self.db.query(Document)
                    .filter(Document.id == doc_id, Document.user_id == user_id)
                    .first()
                )
                if doc is None:
                    continue
                hits_by_document[doc_id] = DocumentSearchHit(
                    document=doc,
                    snippet=vec_hit["snippet"],
                    matched_field="vector",
                    score=score,
                )

        return sorted(hits_by_document.values(), key=lambda hit: hit.score, reverse=True)[:limit]

    def _vector_search(
        self, user_id: int, query: str, limit: int = 20
    ) -> list[dict]:
        """Run ANN search via sqlite-vec, return results with document context."""
        query_vector = self.embedding_provider.embed([query])[0]
        query_blob = struct.pack(f"{len(query_vector)}f", *query_vector)

        # Load sqlite-vec extension
        raw = self.db.connection().connection
        raw.enable_load_extension(True)
        import sqlite_vec  # noqa: F811
        sqlite_vec.load(raw)
        raw.enable_load_extension(False)

        rows = self.db.execute(
            text(
                "SELECT v.chunk_id, v.distance, c.document_id, c.cleaned_text "
                "FROM vec_document_chunks v "
                "JOIN document_chunks c ON c.id = v.chunk_id "
                "JOIN documents d ON d.id = c.document_id "
                "WHERE d.user_id = :user_id AND d.status != 'deleted' "
                "AND v.embedding MATCH :query_blob AND k = :limit"
            ),
            {"user_id": user_id, "query_blob": query_blob, "limit": limit},
        ).fetchall()

        results = []
        for row in rows:
            chunk_id, distance, document_id, cleaned_text = row
            score = 1.0 - distance  # convert distance to similarity
            if score <= 0:
                continue
            results.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "score": score,
                "snippet": self._snippet(cleaned_text, query),
            })
        return results

    def search_chunks(
        self,
        user_id: int,
        query: str,
        limit: int = 20,
        document_id: int | None = None,
        threshold: float = 0.0,
    ) -> list[dict]:
        """Chunk-level semantic search, returns raw result dicts."""
        query_vector = self.embedding_provider.embed([query])[0]
        query_blob = struct.pack(f"{len(query_vector)}f", *query_vector)

        raw = self.db.connection().connection
        raw.enable_load_extension(True)
        import sqlite_vec  # noqa: F811
        sqlite_vec.load(raw)
        raw.enable_load_extension(False)

        filters = "d.user_id = :user_id AND d.status != 'deleted'"
        params: dict = {"user_id": user_id, "query_blob": query_blob, "limit": limit * 2}
        if document_id is not None:
            filters += " AND c.document_id = :document_id"
            params["document_id"] = document_id

        rows = self.db.execute(
            text(
                "SELECT v.chunk_id, v.distance, c.document_id, c.chunk_index, "
                "c.chunk_type, c.cleaned_text, c.page_start, c.page_end, "
                "d.title "
                f"FROM vec_document_chunks v "
                "JOIN document_chunks c ON c.id = v.chunk_id "
                "JOIN documents d ON d.id = c.document_id "
                f"WHERE {filters} "
                "AND v.embedding MATCH :query_blob AND k = :limit"
            ),
            params,
        ).fetchall()

        results = []
        for row in rows:
            (
                chunk_id,
                distance,
                row_document_id,
                chunk_index,
                chunk_type,
                cleaned_text,
                page_start,
                page_end,
                document_title,
            ) = row
            score = 1.0 - distance
            if score < threshold:
                continue
            results.append({
                "chunk_id": chunk_id,
                "document_id": row_document_id,
                "document_title": document_title,
                "chunk_index": chunk_index,
                "chunk_type": chunk_type,
                "text": cleaned_text,
                "score": score,
                "page_start": page_start,
                "page_end": page_end,
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

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
