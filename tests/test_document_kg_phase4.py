from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import Document, DocumentChunk, KgEntity, KgRelation, User
from app.services.document_kg_service import DocumentKgService
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.file_storage import FileStorageService


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
    user = User(email="kg@example.com", username="kg", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def create_parsed_document(session_factory, storage: FileStorageService, user_id: int, text: str) -> int:
    relative_path, stored_filename = storage.store_file(
        user_id=user_id,
        original_filename="kg.txt",
        file_content=text.encode("utf-8"),
        file_extension="txt",
    )
    db = session_factory()
    document = Document(
        user_id=user_id,
        title="KG",
        original_filename="kg.txt",
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


def test_kg_extraction_persists_entities_and_evidence_backed_relations(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    document_id = create_parsed_document(
        session_factory,
        storage,
        user.id,
        "OpenAI created ChatGPT. PostgreSQL supports pgvector.",
    )

    result = DocumentKgService(session_factory=session_factory).extract_document(document_id)

    db = session_factory()
    entities = db.scalars(select(KgEntity).where(KgEntity.document_id == document_id)).all()
    relations = db.scalars(select(KgRelation).where(KgRelation.document_id == document_id)).all()
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document_id))

    assert result.entity_count >= 4
    assert result.relation_count == 2
    assert {entity.name for entity in entities} >= {"OpenAI", "ChatGPT", "PostgreSQL", "pgvector"}
    assert chunk is not None
    assert relations
    assert all(relation.evidence_text for relation in relations)
    assert all(relation.document_id == document_id for relation in relations)
    assert all(relation.chunk_id == chunk.id for relation in relations)
    assert {(relation.subject_text, relation.predicate, relation.object_text) for relation in relations} >= {
        ("OpenAI", "created", "ChatGPT"),
        ("PostgreSQL", "supports", "pgvector"),
    }
    db.close()
