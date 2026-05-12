from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import Document, DocumentChunk, User
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_search_service import DocumentSearchService
from app.services.file_storage import FileStorageService


class FakeEmbeddingProvider:
    model_name = "fake-embedding-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), float(text.count("graph")), 1.0] for text in texts]


class SemanticEmbeddingProvider:
    model_name = "semantic-fake-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if "related" in text.lower() or "target" in text.lower():
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def create_user(session_factory) -> User:
    db = session_factory()
    user = User(email="embed@example.com", username="embed", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def create_parsed_document(session_factory, storage: FileStorageService, user_id: int, text: str) -> int:
    relative_path, stored_filename = storage.store_file(
        user_id=user_id,
        original_filename="embedding.txt",
        file_content=text.encode("utf-8"),
        file_extension="txt",
    )
    db = session_factory()
    document = Document(
        user_id=user_id,
        title="Embedding",
        original_filename="embedding.txt",
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=len(text),
        mime_type="text/plain",
        source_type="txt",
        status="pending",
    )
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()
    DocumentParsePipeline(session_factory=session_factory, file_storage=storage).run(document_id)
    return document_id


def test_embedding_job_stores_vectors_on_document_chunks(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    document_id = create_parsed_document(session_factory, storage, user.id, "Graph evidence belongs in chunks.")

    service = DocumentEmbeddingService(session_factory=session_factory, embedding_provider=FakeEmbeddingProvider())
    updated_count = service.embed_document(document_id)

    db = session_factory()
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()

    assert updated_count == len(chunks)
    assert chunks
    assert chunks[0].embedding_json is not None
    assert json.loads(chunks[0].embedding_json) == [33.0, 0.0, 1.0]
    assert chunks[0].embedding_model == "fake-embedding-v1"
    assert chunks[0].embedding_dim == 3
    assert chunks[0].embedded_at is not None
    db.close()


def test_hybrid_search_returns_vector_matches_without_keyword_overlap(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    target_id = create_parsed_document(session_factory, storage, user.id, "Vector target chunk.")
    create_parsed_document(session_factory, storage, user.id, "Ordinary unrelated chunk.")

    provider = SemanticEmbeddingProvider()
    embedder = DocumentEmbeddingService(session_factory=session_factory, embedding_provider=provider)
    embedder.embed_document(target_id)
    db = session_factory()
    other_ids = [
        document_id
        for (document_id,) in db.execute(select(Document.id).where(Document.id != target_id)).all()
    ]
    db.close()
    for document_id in other_ids:
        embedder.embed_document(document_id)

    db = session_factory()
    hits = DocumentSearchService(db, embedding_provider=provider).hybrid_search(user.id, "related concept", limit=5)

    assert hits
    assert hits[0].document.id == target_id
    assert hits[0].matched_field == "vector"
    assert hits[0].score > 0
    db.close()
