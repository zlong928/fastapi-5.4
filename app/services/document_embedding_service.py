from __future__ import annotations

import hashlib
import json
import math
import struct
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.models import DocumentChunk
from app.core.config import EMBEDDING_PROVIDER

from app.services.embedding.resolver import resolve_embedding_provider


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
            vectors = self.embedding_provider.embed(texts)
            now = datetime.now(timezone.utc)
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding_json = json.dumps(vector)
                chunk.embedding_model = self.embedding_provider.model_name
                chunk.embedding_dim = len(vector)
                chunk.embedded_at = now
            db.commit()

            # Write to sqlite-vec table
            self._write_vectors_to_vec_table(document_id, chunks, vectors)

            return len(chunks)

    def _write_vectors_to_vec_table(
        self, document_id: int, chunks: list[DocumentChunk], vectors: list[list[float]]
    ) -> None:
        with self.session_factory() as db:
            raw = db.connection().connection
            raw.enable_load_extension(True)
            import sqlite_vec  # noqa: F811
            sqlite_vec.load(raw)
            raw.enable_load_extension(False)

        # We need a separate raw connection for sqlite-vec writes
        from sqlalchemy import create_engine
        from app.core.config import DATABASE_URL

        engine = create_engine(DATABASE_URL)
        conn = engine.raw_connection()
        try:
            conn.enable_load_extension(True)
            import sqlite_vec  # noqa: F811
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)

            # Delete existing vec entries for this document
            conn.execute(
                "DELETE FROM vec_document_chunks WHERE chunk_id IN "
                "(SELECT id FROM document_chunks WHERE document_id = ?)",
                [document_id],
            )
            # Insert new vectors
            for chunk, vector in zip(chunks, vectors):
                vector_blob = struct.pack(f"{len(vector)}f", *vector)
                conn.execute(
                    "INSERT INTO vec_document_chunks(chunk_id, embedding) VALUES (?, ?)",
                    [chunk.id, vector_blob],
                )
            conn.commit()
        finally:
            conn.close()
