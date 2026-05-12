from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.models import DocumentChunk


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    model_name = "hash-embedding-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str, dimensions: int = 32) -> list[float]:
        values = [0.0] * dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % dimensions
            values[index] += 1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return [value / norm for value in values]


class DocumentEmbeddingService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

    def embed_document(self, document_id: int) -> int:
        with self.session_factory() as db:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            if not chunks:
                return 0
            vectors = self.embedding_provider.embed([chunk.cleaned_text for chunk in chunks])
            now = datetime.now(timezone.utc)
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding_json = json.dumps(vector)
                chunk.embedding_model = self.embedding_provider.model_name
                chunk.embedding_dim = len(vector)
                chunk.embedded_at = now
            db.commit()
            return len(chunks)
