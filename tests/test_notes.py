from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentChunk, Tag, User


@pytest.fixture()
def db_session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user(db):
    user = User(email="notes@example.com", username="notes", hashed_password=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def client(db_session_factory, user):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_create_note_persists_as_searchable_document(client, db, user):
    response = client.post("/notes", json={
        "title": "React useEffect 问题复盘",
        "body": "新建笔记时不应该用 useEffect 覆盖 draft。",
        "tags": ["React", "笔记"],
        "source_type": "note",
    })

    assert response.status_code == 201
    note = response.json()
    assert note["title"] == "React useEffect 问题复盘"
    document = db.get(Document, note["document_id"])
    assert document is not None
    assert document.source_type == "note"
    assert document.status == "done"
    assert document.cleaned_text == "新建笔记时不应该用 useEffect 覆盖 draft。"
    assert document.chunk_count > 0
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).count() > 0
    assert {tag.name for tag in db.query(Tag).all()} >= {"React", "笔记"}

    title_search = client.get("/documents/search", params={"q": "React useEffect"})
    assert title_search.status_code == 200
    assert title_search.json()["total"] >= 1

    body_search = client.get("/documents/search", params={"q": "覆盖 draft"})
    assert body_search.status_code == 200
    assert body_search.json()["total"] >= 1


def test_update_note_replaces_content_and_chunks(client, db):
    created = client.post("/notes", json={"title": "旧标题", "body": "旧正文 keyword_old", "tags": ["旧"], "source_type": "note"}).json()
    note_id = created["id"]

    response = client.patch(f"/notes/{note_id}", json={"title": "新标题", "body": "新正文 keyword_new", "tags": ["新"], "source_type": "diary"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "新标题"
    assert updated["source_type"] == "diary"
    document = db.get(Document, updated["document_id"])
    assert document.original_file_path == f"diary:{note_id}"
    assert document.cleaned_text == "新正文 keyword_new"
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id, DocumentChunk.text.contains("keyword_new")).count() == 1
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id, DocumentChunk.text.contains("keyword_old")).count() == 0


def test_delete_note_removes_document(client, db):
    created = client.post("/notes", json={"title": "删除测试", "body": "待删除", "tags": [], "source_type": "note"}).json()
    document_id = created["document_id"]

    response = client.delete(f"/notes/{created['id']}")

    assert response.status_code == 200
    assert db.get(Document, document_id) is None


def test_note_permission_is_scoped_to_current_user(client, db):
    other = User(email="other-notes@example.com", username="othernotes", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = Document(
        user_id=other.id,
        title="Other",
        original_filename="Other.md",
        stored_filename="other.md",
        original_file_path="note:other-note",
        file_size=5,
        mime_type="text/markdown",
        source_type="note",
        parsed_text="other",
        cleaned_text="other",
        status="done",
    )
    db.add(document)
    db.commit()

    assert client.get("/notes/other-note").status_code == 404
    assert client.patch("/notes/other-note", json={"title": "x", "body": "x", "tags": [], "source_type": "note"}).status_code == 404
    assert client.delete("/notes/other-note").status_code == 404
