from __future__ import annotations

import hashlib
import json
import math
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import app_now
from app.db.session import SessionLocal
from app.models import DocumentChunk
from app.core.config import EMBEDDING_DIM, EMBEDDING_PROVIDER

from app.services.embedding.resolver import resolve_embedding_provider


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    model_name = "hash-embedding-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str, dimensions: int = EMBEDDING_DIM) -> list[float]:
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
    batch_size = 16

    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider or resolve_embedding_provider()

    def embed_document(self, document_id: int) -> int:
        with self.session_factory() as db:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            if not chunks:
                return 0
            texts = [chunk.cleaned_text for chunk in chunks]
            vectors = self._embed_in_batches(texts)
            now = app_now()
            for chunk, vector in zip(chunks, vectors):
                metadata = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
                metadata["embedding_config"] = {
                    "engine": EMBEDDING_PROVIDER,
                    "model": self.embedding_provider.model_name,
                }
                chunk.embedding_json = json.dumps(vector)
                chunk.embedding_model = self.embedding_provider.model_name
                chunk.embedding_dim = len(vector)
                chunk.embedded_at = now
                chunk.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()

            return len(chunks)

    def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self.embedding_provider.embed(texts[start : start + self.batch_size]))
        return vectors
