from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Collection, Document, User


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
    user = User(email="collections@example.com", username="collector", hashed_password=None)
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


def create_document(db, user: User, *, title: str = "Doc", collection_name: str | None = None) -> Document:
    document = Document(
        user_id=user.id,
        title=title,
        original_filename=f"{title}.txt",
        stored_filename=f"{title}.txt",
        original_file_path=f"uploads/{title}.txt",
        file_size=12,
        mime_type="text/plain",
        source_type="txt",
        status="done",
        collection_name=collection_name,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_create_edit_delete_collection_without_deleting_documents(client, db, user):
    response = client.post("/collections", json={"name": "Inbox", "description": "todo"})
    assert response.status_code == 201
    collection_id = response.json()["id"]
    document = create_document(db, user, collection_name="Inbox")

    response = client.patch(f"/collections/{collection_id}", json={"name": "Reading", "description": "books"})
    assert response.status_code == 200
    assert response.json()["name"] == "Reading"
    db.expire_all()
    assert db.get(Document, document.id).collection_name == "Reading"

    response = client.delete(f"/collections/{collection_id}")
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Document, document.id) is not None
    assert db.get(Document, document.id).collection_name is None


def test_collection_permissions_block_other_users(client, db):
    other = User(email="other@example.com", username="other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    collection = Collection(user_id=other.id, name="Other", description=None)
    db.add(collection)
    db.commit()
    db.refresh(collection)

    response = client.patch(f"/collections/{collection.id}", json={"name": "Changed", "description": ""})
    assert response.status_code == 403
    response = client.delete(f"/collections/{collection.id}")
    assert response.status_code == 403


def test_add_get_and_remove_document_from_collection(client, db, user):
    collection_response = client.post("/collections", json={"name": "Papers", "description": ""})
    collection_id = collection_response.json()["id"]
    document = create_document(db, user, title="Paper")

    response = client.post(f"/collections/{collection_id}/documents/{document.id}")
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Document, document.id).collection_name == "Papers"

    response = client.get(f"/collections/{collection_id}/documents")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == document.id

    response = client.delete(f"/collections/{collection_id}/documents/{document.id}")
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Document, document.id).collection_name is None


def test_cannot_add_other_users_document_to_collection(client, db):
    collection_response = client.post("/collections", json={"name": "Private", "description": ""})
    collection_id = collection_response.json()["id"]
    other = User(email="other-doc@example.com", username="otherdoc", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = create_document(db, other, title="OtherDoc")

    response = client.post(f"/collections/{collection_id}/documents/{document.id}")
    assert response.status_code == 403
