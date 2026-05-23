from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import EMBEDDING_DIM
from app.models import Document, DocumentChunk
from app.services.document_embedding_service import EmbeddingProvider
from app.services.embedding.resolver import resolve_embedding_provider

logger = logging.getLogger(__name__)
DONE_STATUSES = ("done", "completed")


@dataclass(slots=True)
class DocumentSearchHit:
    document: Document
    snippet: str
    matched_field: str
    score: float = 0.0


class DocumentSearchService:
    def __init__(self, db: Session, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.db = db
        self.embedding_provider = embedding_provider or resolve_embedding_provider()

    def search(self, user_id: int, query: str, limit: int = 20) -> list[DocumentSearchHit]:
        normalized = query.strip()
        if not normalized:
            return []
        pattern = f"%{normalized}%"
        documents = (
            self.db.query(Document)
            .outerjoin(DocumentChunk)
            .filter(
                Document.user_id == user_id,
                Document.status != "deleted",
                or_(
                    Document.title.ilike(pattern),
                    Document.cleaned_text.ilike(pattern),
                    Document.parsed_text.ilike(pattern),
                    DocumentChunk.cleaned_text.ilike(pattern),
                ),
            )
            .distinct()
            .order_by(Document.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._build_hit(document, normalized) for document in documents]

    def hybrid_search(self, user_id: int, query: str, limit: int = 20) -> list[DocumentSearchHit]:
        """Combine keyword and vector search results."""
        # 1️⃣ Keyword search (fallback when vector search is unavailable)
        keyword_hits = self.search(user_id, query, limit=limit)

        # Build a dict keyed by document_id for fast lookup
        hits_by_document: dict[int, DocumentSearchHit] = {
            hit.document.id: DocumentSearchHit(
                document=hit.document,
                snippet=hit.snippet,
                matched_field=hit.matched_field,
                score=1.0,  # keyword hits get max score initially
            )
            for hit in keyword_hits
        }

        # 2️⃣ Vector search
        try:
            vec_hits = self._vector_search(user_id, query, limit=limit * 2)
        except Exception as exc:          # pragma: no cover – defensive guard
            logger.warning("Vector search failed: %s", exc)
            vec_hits = []

        # 3️⃣ Merge scores
        for vec_hit in vec_hits:
            vector_score = vec_hit["score"]
            if vector_score <= 0:
                continue
            doc_id = vec_hit["document_id"]
            existing = hits_by_document.get(doc_id)
            # Hybrid score = 30% vector + 70% keyword (adjustable)
            score = 0.7 * vector_score + (existing.score if existing else 0.0)
            if existing is None or score > existing.score:
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

        # Return top results sorted by final score
        return sorted(
            hits_by_document.values(),
            key=lambda hit: hit.score,
            reverse=True,
        )[:limit]

    def _vector_search(
        self, user_id: int, query: str, limit: int = 20
    ) -> list[dict]:
        """Rank ORM-loaded chunk embeddings and return document-level context."""
        query_vector = self._query_vector(query)
        if not query_vector:
            return []

        results: list[dict] = []
        chunks = self._embedding_chunks_query(user_id).all()
        for chunk in chunks:
            score = self._cosine_similarity(query_vector, self._embedding_vector(chunk.embedding_json))
            if score <= 0:
                continue
            results.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "score": score,
                    "snippet": self._snippet(chunk.cleaned_text, query),
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def search_chunks(
        self,
        user_id: int,
        query: str,
        limit: int = 20,
        document_id: int | None = None,
        threshold: float = 0.0,
    ) -> list[dict]:
        """Chunk-level semantic search. Hybrid and rerank hooks can be added after this boundary."""
        try:
            hits = self._semantic_chunk_search(
                user_id=user_id,
                query=query,
                limit=limit,
                document_id=document_id,
                threshold=threshold,
            )
        except Exception as exc:          # pragma: no cover – defensive guard
            logger.warning("Chunk vector search failed, falling back to keyword search: %s", exc)
            hits = []
        if hits:
            return hits
        return self._keyword_chunk_search(
            user_id=user_id,
            query=query,
            limit=limit,
            document_id=document_id,
        )

    def _semantic_chunk_search(
        self,
        user_id: int,
        query: str,
        limit: int = 20,
        document_id: int | None = None,
        threshold: float = 0.0,
    ) -> list[dict]:
        query_vector = self._query_vector(query)
        if not query_vector:
            return []

        results: list[dict] = []
        chunks = self._embedding_chunks_query(user_id, document_id=document_id).all()
        for chunk in chunks:
            score = self._cosine_similarity(query_vector, self._embedding_vector(chunk.embedding_json))
            if score <= 0 or score < threshold:
                continue
            metadata = self._metadata(chunk.metadata_json)
            source = self._chunk_source(chunk, metadata)
            results.append(
                {
                    "chunk_id": chunk.id,
                    "id": chunk.vector_id or str(chunk.id),
                    "document_id": chunk.document_id,
                    "document_title": chunk.document.title,
                    "filename": chunk.document.original_filename,
                    "chunk_index": chunk.chunk_index,
                    "chunk_type": chunk.chunk_type,
                    "text": chunk.cleaned_text,
                    "score": score,
                    "metadata": metadata,
                    "source": source,
                    "start_index": metadata.get("start_index", chunk.char_start),
                    "hash": chunk.document.content_hash or metadata.get("hash"),
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                }
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def _keyword_chunk_search(
        self,
        user_id: int,
        query: str,
        limit: int = 20,
        document_id: int | None = None,
    ) -> list[dict]:
        normalized = query.strip()
        if not normalized:
            return []
        pattern = f"%{normalized}%"
        filters = [
            Document.user_id == user_id,
            Document.status.in_(DONE_STATUSES),
            DocumentChunk.cleaned_text.ilike(pattern),
        ]
        if document_id is not None:
            filters.append(DocumentChunk.document_id == document_id)

        chunks = (
            self.db.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(*filters)
            .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
            .limit(limit)
            .all()
        )
        results = []
        for chunk in chunks:
            metadata = self._metadata(chunk.metadata_json)
            source = self._chunk_source(chunk, metadata)
            results.append({
                "chunk_id": chunk.id,
                "id": chunk.vector_id or str(chunk.id),
                "document_id": chunk.document_id,
                "document_title": chunk.document.title,
                "filename": chunk.document.original_filename,
                "chunk_index": chunk.chunk_index,
                "chunk_type": chunk.chunk_type,
                "text": chunk.cleaned_text,
                "score": 1.0,
                "metadata": metadata,
                "source": source,
                "start_index": metadata.get("start_index", chunk.char_start),
                "hash": chunk.document.content_hash,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            })
        return results

    def _build_hit(self, document: Document, query: str) -> DocumentSearchHit:
        for field_name, value in (
            ("title", document.title),
            ("cleaned_text", document.cleaned_text),
            ("parsed_text", document.parsed_text),
        ):
            if value and query.lower() in value.lower():
                return DocumentSearchHit(
                    document,
                    self._snippet(value, query),
                    field_name,
                    score=1.0,
                )

        for chunk in document.document_chunks:
            if query.lower() in chunk.cleaned_text.lower():
                return DocumentSearchHit(
                    document,
                    self._snippet(chunk.cleaned_text, query),
                    "chunk",
                    score=1.0,
                )

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

    def _metadata(self, metadata_json: str | None) -> dict:
        if not metadata_json:
            return {}
        try:
            parsed = json.loads(metadata_json)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _chunk_source(self, chunk: DocumentChunk, metadata: dict) -> str | None:
        value = metadata.get("source") or metadata.get("url") or chunk.document.source_url
        return str(value) if value else None

    def _query_vector(self, query: str) -> list[float]:
        try:
            query_vector = self.embedding_provider.embed([query])[0]
        except Exception as exc:          # pragma: no cover – defensive guard
            logger.error("Embedding generation failed: %s", exc)
            return []
        if len(query_vector) != EMBEDDING_DIM:
            raise ValueError(f"Expected {EMBEDDING_DIM}-dim vector, got {len(query_vector)}")
        return query_vector

    def _embedding_chunks_query(self, user_id: int, document_id: int | None = None):
        query = (
            self.db.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(
                Document.user_id == user_id,
                Document.status.in_(DONE_STATUSES),
                DocumentChunk.embedding_json.isnot(None),
            )
            .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        )
        if document_id is not None:
            query = query.filter(DocumentChunk.document_id == document_id)
        return query

    def _embedding_vector(self, embedding_json: str | None) -> list[float]:
        if not embedding_json:
            return []
        try:
            parsed = json.loads(embedding_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        vector: list[float] = []
        for value in parsed:
            if not isinstance(value, (int, float)):
                return []
            vector.append(float(value))
        return vector

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
