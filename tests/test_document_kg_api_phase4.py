from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentChunk, KgEntity, KgRelation, User


def make_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.services.task_service.SessionLocal", session_factory)
    client = TestClient(app)
    return client, session_factory


def create_user(session_factory) -> User:
    db = session_factory()
    user = User(email="kgapi@example.com", username="kgapi", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def test_document_kg_endpoint_returns_evidence_backed_relations(monkeypatch):
    client, session_factory = make_client(monkeypatch)
    user = create_user(session_factory)
    app.dependency_overrides[get_current_user] = lambda: user

    db = session_factory()
    document = Document(
        user_id=user.id,
        title="KG API",
        original_filename="kg.txt",
        stored_filename="kg.txt",
        original_file_path="1/kg.txt",
        file_size=10,
        mime_type="text/plain",
        source_type="txt",
        status="parsed",
    )
    db.add(document)
    db.commit()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        chunk_type="body",
        text="OpenAI created ChatGPT.",
        cleaned_text="OpenAI created ChatGPT.",
    )
    db.add(chunk)
    db.commit()
    subject = KgEntity(document_id=document.id, chunk_id=chunk.id, name="OpenAI", normalized_name="openai")
    object_entity = KgEntity(document_id=document.id, chunk_id=chunk.id, name="ChatGPT", normalized_name="chatgpt")
    db.add_all([subject, object_entity])
    db.commit()
    relation = KgRelation(
        document_id=document.id,
        chunk_id=chunk.id,
        subject_entity_id=subject.id,
        object_entity_id=object_entity.id,
        subject_text="OpenAI",
        predicate="created",
        object_text="ChatGPT",
        evidence_text="OpenAI created ChatGPT",
    )
    db.add(relation)
    db.commit()
    document_id = document.id
    chunk_id = chunk.id
    db.close()

    response = client.get(f"/documents/{document_id}/kg")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert {entity["name"] for entity in payload["entities"]} == {"OpenAI", "ChatGPT"}
    assert payload["relations"][0]["chunk_id"] == chunk_id
    assert payload["relations"][0]["evidence_text"] == "OpenAI created ChatGPT"

    app.dependency_overrides.clear()
