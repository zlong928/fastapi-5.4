from __future__ import annotations

from io import BytesIO
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.config import EMBEDDING_DIM
from app.core.time import app_now
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentAsset, DocumentChunk, DocumentEvent, FileCleanupJob, JobRun, User
from app.schemas.document import DocumentProcessingMode
from app.services.bookmark_service import BookmarkError, validate_public_url
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.file_storage import FileStorageService
from app.services.document_service import DocumentService
from app.services.file_cleanup_service import FileCleanupService

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
PDF_BYTES = b"%PDF-1.4\n"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
MOV_BYTES = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    user = User(email="doc@example.com", username="docuser", hashed_password=None)
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


@pytest.fixture(autouse=True)
def no_document_parse_queue(monkeypatch):
    monkeypatch.setattr("app.services.document_service.enqueue_document_parse", lambda _document_id, _parse_job_id: None)


@pytest.fixture()
def storage(tmp_path: Path) -> FileStorageService:
    return FileStorageService(upload_dir=str(tmp_path / "uploads"))


def create_document(
    db,
    storage: FileStorageService,
    user: User,
    *,
    status: str = "pending",
    filename: str = "sample.txt",
    content: bytes | None = None,
) -> Document:
    extension = filename.rsplit(".", 1)[1]
    if content is None:
        if extension == "pdf":
            content = PDF_BYTES
        elif extension == "png":
            content = PNG_BYTES
        else:
            content = b"DocumentParser uses Redis."
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename=filename,
        file_content=content,
        file_extension=extension,
    )
    document = Document(
        user_id=user.id,
        title=filename.rsplit(".", 1)[0],
        original_filename=filename,
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=len(content),
        mime_type="text/plain",
        source_type="txt",
        status=status,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_delete_own_document_soft_deletes_database_record_without_cleanup_jobs(client, db, storage, user, monkeypatch):
    monkeypatch.setattr("app.services.document_service.FileStorageService", lambda: storage)
    document = create_document(db, storage, user)
    asset_relative_path, _ = storage.store_file(
        user_id=user.id,
        original_filename="asset.txt",
        file_content=b"intermediate",
        file_extension="txt",
    )
    db.add(
        DocumentAsset(
            document_id=document.id,
            asset_type="cache",
            file_path=asset_relative_path,
            mime_type="text/plain",
        )
    )
    db.commit()
    original_relative_path = document.original_file_path
    original_path = storage.get_file_path(document.original_file_path)
    asset_path = storage.get_file_path(asset_relative_path)
    document_id = document.id

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    db.expire_all()
    deleted_document = db.get(Document, document_id)
    assert deleted_document is not None
    assert deleted_document.is_deleted is True
    assert deleted_document.deleted_by == user.id
    assert deleted_document.deleted_at is not None
    assert db.query(DocumentAsset).filter(DocumentAsset.document_id == document_id).count() == 1
    assert db.query(FileCleanupJob).count() == 0
    assert original_path.exists()
    assert asset_path.exists()


def test_delete_missing_physical_file_still_soft_deletes_database_record(client, db, storage, user, monkeypatch):
    monkeypatch.setattr("app.services.document_service.FileStorageService", lambda: storage)
    document = create_document(db, storage, user)
    original_relative_path = document.original_file_path
    storage.get_file_path(original_relative_path).unlink()
    document_id = document.id

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    db.expire_all()
    deleted_document = db.get(Document, document_id)
    assert deleted_document is not None
    assert deleted_document.is_deleted is True
    assert deleted_document.deleted_by == user.id
    assert db.query(FileCleanupJob).count() == 0


def test_hard_delete_bookmark_does_not_create_cleanup_job(db, user):
    document = Document(
        user_id=user.id,
        title="Example",
        original_filename="example.com",
        stored_filename="bookmark",
        original_file_path="bookmark:https://example.com",
        file_size=0,
        mime_type="text/html",
        source_type="bookmark",
        source_url="https://example.com",
        site_name="example.com",
        status="done",
    )
    db.add(document)
    db.commit()
    document_id = document.id

    deleted_id = DocumentService(db).hard_delete_document(document_id)

    assert deleted_id == document_id
    assert db.get(Document, document_id) is None
    assert db.query(FileCleanupJob).count() == 0


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8000",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://198.18.0.96",
    ],
)
def test_validate_public_url_rejects_ssrf_targets(url):
    with pytest.raises(BookmarkError):
        validate_public_url(url)


def test_validate_public_url_allows_docker_proxy_dns_for_hostname(monkeypatch):
    monkeypatch.setattr(
        "app.services.bookmark_service.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", ("198.18.0.96", 0))],
    )

    assert validate_public_url("https://example.com") == "https://example.com"


def test_cleanup_missing_physical_file_marks_job_done(db, storage, user):
    document = create_document(db, storage, user)
    storage.get_file_path(document.original_file_path).unlink()
    DocumentService(db, storage).hard_delete_document(document.id)

    processed = FileCleanupService(db, storage).run_once()

    assert processed == 1
    cleanup_job = db.query(FileCleanupJob).one()
    assert cleanup_job.status == "done"
    assert cleanup_job.attempts == 0
    assert cleanup_job.last_error is None


def test_soft_delete_double_dot_filename_preserves_physical_file(client, db, storage, user, monkeypatch):
    monkeypatch.setattr("app.services.document_service.FileStorageService", lambda: storage)
    document = create_document(db, storage, user, filename="foo..bar.txt")
    original_path = storage.get_file_path(document.original_file_path)
    document_id = document.id

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 200
    db.expire_all()
    deleted_document = db.get(Document, document_id)
    assert deleted_document is not None
    assert deleted_document.is_deleted is True
    assert original_path.exists()
    assert db.query(FileCleanupJob).count() == 0


def test_cleanup_delete_failure_records_error_and_retries(db, storage, user, monkeypatch, caplog):
    document = create_document(db, storage, user)
    DocumentService(db, storage).hard_delete_document(document.id)

    def fail_delete_file(_relative_path: str) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(storage, "delete_file", fail_delete_file)

    processed = FileCleanupService(db, storage, retry_delay_seconds=1).run_once()

    assert processed == 1
    cleanup_job = db.query(FileCleanupJob).one()
    assert cleanup_job.status == "pending"
    assert cleanup_job.attempts == 1
    assert "permission denied" in cleanup_job.last_error
    assert cleanup_job.next_run_at is not None
    assert "permission denied" in caplog.text


def test_cleanup_rejects_paths_outside_upload_dir(db, storage, user, tmp_path):
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("keep me")
    job = FileCleanupJob(
        user_id=user.id,
        file_path=f"../{outside_path.name}",
        max_attempts=1,
    )
    db.add(job)
    db.commit()

    processed = FileCleanupService(db, storage).run_once()

    assert processed == 1
    assert outside_path.read_text() == "keep me"
    db.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 1
    assert "Invalid path" in job.last_error


def test_hard_delete_keeps_files_when_database_delete_fails(db, storage, user):
    document = create_document(db, storage, user)
    original_relative_path = document.original_file_path
    original_path = storage.get_file_path(original_relative_path)

    def fail_document_delete(conn, cursor, statement, parameters, context, executemany):
        if "DELETE FROM documents" in statement:
            raise SQLAlchemyError("document delete failed")

    event.listen(db.bind, "before_cursor_execute", fail_document_delete)
    try:
        with pytest.raises(SQLAlchemyError, match="document delete failed"):
            DocumentService(db, storage).hard_delete_document(document.id)
    finally:
        event.remove(db.bind, "before_cursor_execute", fail_document_delete)

    db.rollback()
    assert db.get(Document, document.id) is not None
    assert original_path.exists()


def test_hard_delete_commits_database_and_keeps_cleanup_job_when_physical_delete_would_fail(db, storage, user, monkeypatch):
    document = create_document(db, storage, user)
    original_relative_path = document.original_file_path
    original_path = storage.get_file_path(original_relative_path)
    document_id = document.id

    def fail_delete_file(_relative_path: str) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(storage, "delete_file", fail_delete_file)

    deleted_id = DocumentService(db, storage).hard_delete_document(document_id)

    assert deleted_id == document_id
    db.expire_all()
    assert db.get(Document, document_id) is None
    assert original_path.exists()
    cleanup_job = db.query(FileCleanupJob).one()
    assert cleanup_job.file_path == original_relative_path
    assert cleanup_job.status == "pending"


def test_delete_preserves_file_referenced_by_another_document(db, storage, user):
    first = create_document(db, storage, user)
    shared_relative_path = first.original_file_path
    shared_path = storage.get_file_path(shared_relative_path)
    second = Document(
        user_id=user.id,
        title="shared",
        original_filename="shared.txt",
        stored_filename=first.stored_filename,
        original_file_path=shared_relative_path,
        file_size=first.file_size,
        mime_type="text/plain",
        source_type="txt",
        processing_mode="auto",
        processing_strategy="plain_text",
        status="done",
    )
    db.add(second)
    db.commit()
    first_id = first.id
    second_id = second.id

    deleted_id = DocumentService(db, storage).hard_delete_document(first_id)

    assert deleted_id == first_id
    db.expire_all()
    assert db.get(Document, first_id) is None
    assert db.get(Document, second_id) is not None
    assert shared_path.exists()
    assert storage.read_file(shared_relative_path) == b"DocumentParser uses Redis."


def test_delete_missing_file_prunes_empty_parent_dirs(db, storage, user):
    document = create_document(db, storage, user)
    original_path = storage.get_file_path(document.original_file_path)
    month_dir = original_path.parent
    original_path.unlink()
    document_id = document.id

    deleted_id = DocumentService(db, storage).hard_delete_document(document_id)
    processed = FileCleanupService(db, storage).run_once()

    assert deleted_id == document_id
    assert processed == 1
    db.expire_all()
    assert db.get(Document, document_id) is None
    assert not month_dir.exists()


def test_delete_other_users_document_returns_403_and_preserves_record(client, db, storage, user, monkeypatch):
    monkeypatch.setattr("app.services.document_service.FileStorageService", lambda: storage)
    other = User(email="other-doc@example.com", username="other-doc", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = create_document(db, storage, other)
    original_path = storage.get_file_path(document.original_file_path)

    response = client.delete(f"/documents/{document.id}")

    assert response.status_code == 403
    assert db.get(Document, document.id) is not None
    assert db.query(FileCleanupJob).count() == 0
    assert original_path.exists()


def test_delete_missing_document_returns_404(client):
    response = client.delete("/documents/999999")

    assert response.status_code == 404


def test_same_user_duplicate_upload_returns_file_exists(client, db, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)

    first = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second = client.post(
        "/documents/upload",
        files={"file": ("copy.txt", b"same bytes", "text/plain")},
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == "文件已存在"
    assert db.query(Document).count() == 1
    document = db.get(Document, first.json()["document_id"])
    assert document is not None
    assert document.file_hash


def test_different_users_can_upload_same_file_hash(db_session_factory, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)

    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        first_session = db_session_factory()
        second_session = db_session_factory()
        first_user = User(email="first-hash@example.com", username="first-hash", hashed_password=None)
        second_user = User(email="second-hash@example.com", username="second-hash", hashed_password=None)
        first_session.add(first_user)
        first_session.commit()
        first_session.refresh(first_user)
        second_session.add(second_user)
        second_session.commit()
        second_session.refresh(second_user)
        first_session.close()
        second_session.close()

        first_id = first_user.id
        second_id = second_user.id

        def current_user_one():
            session = db_session_factory()
            try:
                return session.get(User, first_id)
            finally:
                session.close()

        def current_user_two():
            session = db_session_factory()
            try:
                return session.get(User, second_id)
            finally:
                session.close()

        with TestClient(app) as local_client:
            app.dependency_overrides[get_current_user] = current_user_one
            first = local_client.post(
                "/documents/upload",
                files={"file": ("same.txt", b"shared bytes", "text/plain")},
            )
            app.dependency_overrides[get_current_user] = current_user_two
            second = local_client.post(
                "/documents/upload",
                files={"file": ("same.txt", b"shared bytes", "text/plain")},
            )

        verification_session = db_session_factory()
        try:
            documents = verification_session.query(Document).order_by(Document.user_id).all()
            assert first.status_code == 202
            assert second.status_code == 202
            assert len(documents) == 2
            assert documents[0].file_hash == documents[1].file_hash
            assert documents[0].user_id != documents[1].user_id
        finally:
            verification_session.close()
    finally:
        app.dependency_overrides.clear()


def test_upload_queues_parse_job(client, db, monkeypatch):
    enqueued: list[tuple[int, int]] = []

    def fake_enqueue(document_id: int, parse_job_id: int) -> None:
        enqueued.append((document_id, parse_job_id))

    monkeypatch.setattr("app.services.document_service.enqueue_document_parse", fake_enqueue)

    response = client.post(
        "/documents/upload",
        files={"file": ("sample.txt", b"hello async pipeline", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["parse_job_id"]

    document = db.get(Document, payload["document_id"])
    job = db.get(JobRun, payload["parse_job_id"])
    assert document is not None
    assert document.status == "pending"
    assert job is not None
    event_types = {
        event.event_type
        for event in db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)
    }
    assert "uploaded" in event_types
    assert enqueued == [(document.id, job.id)]


def test_upload_enqueue_failure_marks_document_and_job_failed(client, db, monkeypatch):
    def fail_enqueue(_document_id: int, _parse_job_id: int) -> None:
        raise RuntimeError("redis offline")

    monkeypatch.setattr("app.services.document_service.enqueue_document_parse", fail_enqueue)

    response = client.post(
        "/documents/upload",
        files={"file": ("sample.txt", b"hello async pipeline", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["processing_status"] == "failed"
    assert "could not be queued" in payload["message"]

    document = db.get(Document, payload["document_id"])
    job = db.get(JobRun, payload["parse_job_id"])
    assert document is not None
    assert document.status == "failed"
    assert "入队失败" in document.fail_reason
    assert job is not None
    assert job.status == "failed"
    assert "入队失败" in job.error_message
    event_types = {
        event.event_type
        for event in db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)
    }
    assert "parse_enqueue_failed" in event_types


def test_upload_cleans_stored_file_when_database_create_fails(client, db, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)

    def fail_create_document(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(
        "app.services.document_upload_service.DocumentService.create_document_with_parse_job",
        fail_create_document,
    )

    response = client.post(
        "/documents/upload",
        files={"file": ("orphan.txt", b"orphan content", "text/plain")},
    )

    assert response.status_code == 500
    assert db.query(Document).count() == 0
    assert [path for path in storage.upload_dir.rglob("*") if path.is_file()] == []


def test_upload_rejects_file_over_backend_size_limit(client, db, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.MAX_UPLOAD_SIZE_BYTES", 5)

    response = client.post(
        "/documents/upload",
        files={"file": ("large.txt", b"too large", "text/plain")},
    )

    assert response.status_code == 413
    assert "Maximum size is 5 bytes" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_rejects_spoofed_extension_with_invalid_magic_bytes(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("fake.pdf", b"plain text pretending to be a PDF", "application/pdf")},
    )

    assert response.status_code == 400
    assert "magic bytes" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_rejects_declared_content_type_mismatch(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"plain text", "application/pdf")},
    )

    assert response.status_code == 400
    assert "Content-Type" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_rejects_magic_bytes_for_a_different_allowed_type(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", PDF_BYTES, "text/plain")},
    )

    assert response.status_code == 400
    assert "does not match .txt" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_rejects_extension_that_requires_sanitization(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("payload.p$d$f", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 400
    assert "File extension is invalid" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_rejects_binary_control_bytes_in_text(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("control.txt", b"\x01\x02\x03not text", "text/plain")},
    )

    assert response.status_code == 400
    assert "binary content" in response.json()["detail"]
    assert db.query(Document).count() == 0


def test_upload_sanitizes_path_traversal_filename(client, db, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)

    response = client.post(
        "/documents/upload",
        files={"file": ("../../Unsafe Notes?.txt", b"safe text", "text/plain")},
    )

    assert response.status_code == 202
    document = db.get(Document, response.json()["document_id"])
    assert document is not None
    assert document.original_filename == "Unsafe Notes.txt"
    assert document.stored_filename == "Unsafe Notes.txt"
    stored_path = storage.get_file_path(document.original_file_path).resolve()
    stored_path.relative_to(storage.upload_dir.resolve())
    assert ".." not in document.original_file_path
    assert stored_path.name == "Unsafe Notes.txt"


def test_upload_auto_renames_duplicate_user_filename(client, db, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)

    first = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"first", "text/plain")},
    )
    second = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"second", "text/plain")},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_document = db.get(Document, first.json()["document_id"])
    second_document = db.get(Document, second.json()["document_id"])
    assert first_document.stored_filename == "notes.txt"
    assert second_document.stored_filename == "notes-1.txt"
    assert storage.get_file_path(first_document.original_file_path).read_bytes() == b"first"
    assert storage.get_file_path(second_document.original_file_path).read_bytes() == b"second"


@pytest.mark.parametrize(
    ("filename", "content", "declared_mime_type", "expected_mime_type"),
    [
        ("screen-recording.mp4", MP4_BYTES, "video/mp4", "video/mp4"),
        ("clip.mov", MOV_BYTES, "video/quicktime", "video/quicktime"),
    ],
)
def test_upload_video_is_stored_for_preview_without_parse_queue(
    client,
    db,
    storage,
    monkeypatch,
    filename,
    content,
    declared_mime_type,
    expected_mime_type,
):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)
    enqueued: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(
        "/documents/upload",
        files={"file": (filename, content, declared_mime_type)},
    )

    assert response.status_code == 202
    payload = response.json()
    document = db.get(Document, payload["document_id"])
    job = db.get(JobRun, payload["parse_job_id"])
    assert document.source_type == "video"
    assert document.mime_type == expected_mime_type
    assert document.status == "done"
    assert document.content_summary == "文件已保存，可在知识库中预览；当前版本未抽取全文用于检索。"
    assert job.status == "succeeded"
    assert enqueued == []
    assert storage.get_file_path(document.original_file_path).read_bytes() == content

    list_response = client.get("/documents", params={"file_type": "video"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [document.id]

    export_response = client.get("/documents/export", params={"source_type": "video", "format": "json"})
    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["summary"]["total_documents"] == 1
    assert exported["documents"][0]["source_type"] == "video"


def test_export_selected_uploaded_files_returns_zip(client, db, storage, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.FileStorageService", lambda: storage)
    monkeypatch.setattr("app.services.document_service.FileStorageService", lambda: storage)

    text_response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"selected notes", "text/plain")},
    )
    video_response = client.post(
        "/documents/upload",
        files={"file": ("screen-recording.mp4", MP4_BYTES, "video/mp4")},
    )
    assert text_response.status_code == 202
    assert video_response.status_code == 202
    document_ids = [text_response.json()["document_id"], video_response.json()["document_id"]]

    response = client.post("/documents/export-files", json={"document_ids": document_ids})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "knowledge_files_2_items.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["notes.txt", "screen-recording.mp4"]
        assert archive.read("notes.txt") == b"selected notes"
        assert archive.read("screen-recording.mp4") == MP4_BYTES

    metadata_response = client.get(
        "/documents/export",
        params=[("document_ids", str(document_ids[1])), ("document_ids", str(document_ids[0])), ("format", "json")],
    )
    assert metadata_response.status_code == 200
    exported_documents = metadata_response.json()["documents"]
    assert [document["id"] for document in exported_documents] == [document_ids[1], document_ids[0]]


def test_create_document_with_parse_job_writes_three_tables_in_one_transaction(db, storage, user):
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="atomic.txt",
        file_content=b"atomic",
        file_extension="txt",
    )

    document, job = DocumentService(db, storage).create_document_with_parse_job(
        user_id=user.id,
        title="atomic",
        original_filename="atomic.txt",
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=6,
        mime_type="text/plain",
        source_type="txt",
        processing_mode="plain_text",
    )

    event = db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id).one()
    assert db.query(Document).count() == 1
    assert db.query(JobRun).count() == 1
    assert db.query(DocumentEvent).count() == 1
    assert job.document_id == document.id
    assert event.user_id == user.id
    assert event.event_type == "uploaded"
    assert json.loads(event.event_metadata)["job_run_id"] == job.id


def test_create_document_rolls_back_when_parse_job_insert_fails(db, storage, user):
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="parse-fails.txt",
        file_content=b"rollback",
        file_extension="txt",
    )

    def fail_parse_job_insert(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO job_runs" in statement:
            raise SQLAlchemyError("job run insert failed")

    event.listen(db.bind, "before_cursor_execute", fail_parse_job_insert)
    try:
        with pytest.raises(SQLAlchemyError, match="job run insert failed"):
            DocumentService(db, storage).create_document_with_parse_job(
                user_id=user.id,
                title="parse-fails",
                original_filename="parse-fails.txt",
                stored_filename=stored_filename,
                original_file_path=relative_path,
                file_size=8,
                mime_type="text/plain",
                source_type="txt",
            )
    finally:
        event.remove(db.bind, "before_cursor_execute", fail_parse_job_insert)

    assert db.query(Document).count() == 0
    assert db.query(JobRun).count() == 0
    assert db.query(DocumentEvent).count() == 0


def test_create_document_rolls_back_when_document_event_insert_fails(db, storage, user):
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="event-fails.txt",
        file_content=b"rollback",
        file_extension="txt",
    )

    def fail_event_insert(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO document_events" in statement:
            raise SQLAlchemyError("document event insert failed")

    event.listen(db.bind, "before_cursor_execute", fail_event_insert)
    try:
        with pytest.raises(SQLAlchemyError, match="document event insert failed"):
            DocumentService(db, storage).create_document_with_parse_job(
                user_id=user.id,
                title="event-fails",
                original_filename="event-fails.txt",
                stored_filename=stored_filename,
                original_file_path=relative_path,
                file_size=8,
                mime_type="text/plain",
                source_type="txt",
            )
    finally:
        event.remove(db.bind, "before_cursor_execute", fail_event_insert)

    assert db.query(Document).count() == 0
    assert db.query(JobRun).count() == 0
    assert db.query(DocumentEvent).count() == 0


def test_legacy_chunk_model_is_not_registered_or_imported():
    assert "chunks" not in Base.metadata.tables
    assert not hasattr(Document, "chunks")

    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[Path] = []
    for path in app_root.rglob("*.py"):
        if "db/migrations/versions" in path.as_posix():
            continue
        text = path.read_text()
        if "from app.models.chunk import Chunk" in text or "from .chunk import Chunk" in text:
            offenders.append(path)

    assert offenders == []


def test_upload_syncs_to_obsidian_when_enabled(client, db, monkeypatch):
    enqueued: list[tuple[int, int]] = []
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_put(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_SYNC_ENABLED", True)
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_API_KEY", "test-api-key")
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_API_URL", "http://127.0.0.1:27123")
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_TARGET_DIR", "Uploads")
    monkeypatch.setattr("app.services.obsidian_service.httpx.put", fake_put)
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(
        "/documents/upload",
        data={"title": "../Unsafe / Title: 01"},
        files={"file": ("../source bad?.txt", b"hello obsidian", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert enqueued == [(payload["document_id"], payload["parse_job_id"])]
    assert "test-api-key" not in response.text

    expected_month_path = app_now().strftime("%Y/%m")
    written_paths = [unquote(request["url"].split("/vault/", 1)[1]) for request in requests]
    assert written_paths == [
        f"Uploads/{expected_month_path}/{payload['document_id']}-Unsafe - Title- 01/original/source bad.txt",
        f"Uploads/{expected_month_path}/{payload['document_id']}-Unsafe - Title- 01/index.md",
    ]
    assert all(request["headers"]["Authorization"] == "Bearer test-api-key" for request in requests)
    assert all(request["url"].startswith("http://127.0.0.1:27123/vault/") for request in requests)

    index_request = requests[1]
    index_text = index_request["content"].decode("utf-8")
    assert "title: \"../Unsafe / Title: 01\"" in index_text
    assert 'original_file: "original/source bad.txt"' in index_text
    assert "[[original/source bad.txt]]" in index_text
    assert "## Parsed Text" in index_text
    assert "## Knowledge Graph" in index_text
    assert "## Events" in index_text
    assert "## Human Notes" in index_text
    assert "test-api-key" not in index_text
    assert "Authorization" not in index_text
    assert "127.0.0.1" not in index_text
    assert all(".." not in path and "\\" not in path for path in written_paths)

    event = (
        db.query(DocumentEvent)
        .filter(
            DocumentEvent.document_id == payload["document_id"],
            DocumentEvent.event_type == "obsidian_synced",
        )
        .one()
    )
    assert "Obsidian" in event.message
    metadata = json.loads(event.event_metadata)
    assert metadata == {
        "directory_path": f"Uploads/{expected_month_path}/{payload['document_id']}-Unsafe - Title- 01",
        "original_file_path": f"Uploads/{expected_month_path}/{payload['document_id']}-Unsafe - Title- 01/original/source bad.txt",
        "index_path": f"Uploads/{expected_month_path}/{payload['document_id']}-Unsafe - Title- 01/index.md",
    }


def test_upload_continues_when_obsidian_sync_fails(client, db, monkeypatch):
    enqueued: list[tuple[int, int]] = []

    class FakeObsidianService:
        is_configured = True

        def sync_uploaded_file(self, **_kwargs):
            from app.services.obsidian_service import ObsidianSyncError

            raise ObsidianSyncError("Obsidian is offline")

    monkeypatch.setattr("app.services.document_upload_service.ObsidianService", FakeObsidianService)
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(
        "/documents/upload",
        files={"file": ("sample.txt", b"hello obsidian", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert enqueued == [(payload["document_id"], payload["parse_job_id"])]
    event = (
        db.query(DocumentEvent)
        .filter(
            DocumentEvent.document_id == payload["document_id"],
            DocumentEvent.event_type == "obsidian_sync_failed",
        )
        .one()
    )
    assert "offline" in event.message


def test_upload_skips_obsidian_without_api_key(client, db, monkeypatch):
    enqueued: list[tuple[int, int]] = []
    requests: list[dict] = []

    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_SYNC_ENABLED", True)
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_API_KEY", "")
    monkeypatch.setattr("app.services.obsidian_service.httpx.put", lambda *args, **kwargs: requests.append(kwargs))
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(
        "/documents/upload",
        files={"file": ("sample.txt", b"hello obsidian", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert enqueued == [(payload["document_id"], payload["parse_job_id"])]
    assert requests == []
    event = (
        db.query(DocumentEvent)
        .filter(
            DocumentEvent.document_id == payload["document_id"],
            DocumentEvent.event_type == "obsidian_sync_skipped",
        )
        .one()
    )
    assert "not configured" in event.message.lower()


def test_obsidian_health_does_not_expose_secret(client, monkeypatch):
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_SYNC_ENABLED", True)
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_API_KEY", "test-api-key")
    monkeypatch.setattr("app.services.obsidian_service.config.OBSIDIAN_API_URL", "http://127.0.0.1:27123")
    monkeypatch.setattr("app.services.obsidian_service.httpx.get", lambda *args, **kwargs: FakeResponse())

    response = client.get("/obsidian/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["configured"] is True
    assert "test-api-key" not in response.text
    assert "127.0.0.1" not in response.text


def test_retry_parse_allows_failed_documents(client, db, storage, user, monkeypatch):
    document = create_document(db, storage, user, status="failed")
    enqueued: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(f"/documents/{document.id}/retry-parse")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["latest_parse_job"]["status"] == "queued"
    assert enqueued == [(document.id, payload["latest_parse_job"]["id"])]


@pytest.mark.parametrize("initial_status", ["pending", "processing"])
def test_retry_parse_rejects_active_documents(client, db, storage, user, initial_status):
    document = create_document(db, storage, user, status=initial_status)
    active_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(active_job)
    db.commit()

    response = client.post(f"/documents/{document.id}/retry-parse")

    assert response.status_code == 409
    assert db.query(JobRun).filter(JobRun.document_id == document.id).count() == 1


@pytest.mark.parametrize("initial_status", ["completed", "done"])
def test_retry_parse_rejects_completed_documents(client, db, storage, user, initial_status):
    document = create_document(db, storage, user, status=initial_status)

    response = client.post(f"/documents/{document.id}/retry-parse")

    assert response.status_code == 400
    assert db.query(JobRun).filter(JobRun.document_id == document.id).count() == 0


def test_pipeline_uses_existing_job_and_marks_success(db_session_factory, db, storage, user):
    document = create_document(db, storage, user)
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)
    parsed_document = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(job)
    assert parsed_document.status == "done"
    assert job.status == "succeeded"
    assert db.query(JobRun).filter(JobRun.document_id == document.id).count() == 1


def test_pipeline_failure_marks_job_and_document_failed(db_session_factory, db, storage, user, monkeypatch):
    document = create_document(db, storage, user)
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)
    monkeypatch.setattr(pipeline.parser, "parse", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    assert result.status == "failed"
    assert document.status == "failed"
    assert document.error_message == "boom"
    assert job.status == "failed"
    assert job.error_message == "boom"


def test_upload_empty_file_is_rejected_without_creating_document(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
    assert db.query(Document).count() == 0
    assert db.query(JobRun).count() == 0


def test_processing_failure_details_are_visible_in_detail_and_list(client, db, storage, user):
    document = create_document(db, storage, user, status="failed", filename="spaces.txt", content=b"   \n\t")
    document.error_message = "文件内容为空"
    document.fail_reason = "文件内容为空"
    db.commit()

    detail_response = client.get(f"/documents/{document.id}")
    list_response = client.get("/documents")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["processing_status"] == "failed"
    assert detail_payload["processing_error"] == "文件内容为空"
    assert detail_payload["updated_at"]

    assert list_response.status_code == 200
    item = next(item for item in list_response.json()["items"] if item["id"] == document.id)
    assert item["processing_status"] == "failed"
    assert item["processing_error"] == "文件内容为空"
    assert item["updated_at"]


@pytest.mark.parametrize(
    ("filename", "content", "source_type", "mime_type", "expected_reason"),
    [
        ("broken.pdf", b"%PDF-1.4\nnot actually a readable pdf", "pdf", "application/pdf", "PDF 文件损坏，无法解析"),
        ("broken.png", PNG_BYTES, "image", "image/png", "图片文件无法打开"),
        ("spaces.txt", b"   \n\t", "txt", "text/plain", "文件内容为空"),
    ],
)
def test_pipeline_marks_bad_files_failed_with_clear_reason(
    db_session_factory,
    db,
    storage,
    user,
    monkeypatch,
    filename,
    content,
    source_type,
    mime_type,
    expected_reason,
):
    document = create_document(db, storage, user, filename=filename, content=content)
    document.source_type = source_type
    document.mime_type = mime_type
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    monkeypatch.setattr(
        "app.services.document_parse_pipeline.DocumentEmbeddingService.embed_document",
        lambda *_args, **_kwargs: 0,
    )
    if source_type == "image":
        class FailingOcr:
            def ocr_image(self, _file_path):
                raise RuntimeError("cannot identify image file")

        pipeline = DocumentParsePipeline(
            session_factory=db_session_factory,
            file_storage=storage,
            ocr_service=FailingOcr(),
        )
    else:
        pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)

    result = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    assert result.status == "failed"
    assert document.status == "failed"
    assert document.error_message == expected_reason
    assert document.fail_reason == expected_reason
    assert job.status == "failed"
    assert job.error_message == expected_reason
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).count() == 0


def test_pipeline_timeout_marks_document_failed(db_session_factory, db, storage, user, monkeypatch):
    document = create_document(db, storage, user, filename="slow.txt", content=b"slow text")
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)

    def slow_extract(_document_id):
        raise TimeoutError("parse deadline exceeded")

    monkeypatch.setattr(pipeline, "_extract_document", slow_extract)

    result = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    assert result.status == "failed"
    assert document.error_message == "文件解析超时"
    assert document.fail_reason == "文件解析超时"
    assert job.status == "failed"
    assert job.error_message == "文件解析超时"


def test_pipeline_missing_source_file_marks_document_failed(db_session_factory, db, storage, user):
    document = create_document(db, storage, user, filename="missing.txt", content=b"gone")
    storage.get_file_path(document.original_file_path).unlink()
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)

    result = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    event_record = (
        db.query(DocumentEvent)
        .filter(DocumentEvent.document_id == document.id, DocumentEvent.event_type == "parse_failed")
        .one()
    )
    assert result.status == "failed"
    assert document.status == "failed"
    assert document.error_message == "源文件不存在，无法解析"
    assert document.fail_reason == "源文件不存在，无法解析"
    assert job.status == "failed"
    assert job.error_message == "源文件不存在，无法解析"
    assert "missing_source_file" in event_record.event_metadata


def test_one_failed_document_does_not_block_later_document_processing(db_session_factory, db, storage, user):
    failed_document = create_document(db, storage, user, filename="bad.txt", content=b"    ")
    failed_job = JobRun(kind="document_parse", document_id=failed_document.id, user_id=user.id, status="queued")
    ok_document = create_document(db, storage, user, filename="ok.txt", content=b"hello reliable processing")
    ok_job = JobRun(kind="document_parse", document_id=ok_document.id, user_id=user.id, status="queued")
    db.add_all([failed_job, ok_job])
    db.commit()
    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)

    first = pipeline.run(failed_document.id, parse_job_id=failed_job.id)
    second = pipeline.run(ok_document.id, parse_job_id=ok_job.id)

    db.refresh(failed_document)
    db.refresh(ok_document)
    db.refresh(failed_job)
    db.refresh(ok_job)
    assert first.status == "failed"
    assert failed_document.error_message == "文件内容为空"
    assert failed_job.status == "failed"
    assert second.status == "done"
    assert ok_document.status == "done"
    assert ok_job.status == "succeeded"


def test_pipeline_skips_deleted_document(db_session_factory, db, storage, user):
    document = create_document(db, storage, user, status="deleted")
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)
    pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(job)
    assert job.status == "failed"
    assert "deleted" in (job.error_message or "").lower()
    event = db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id).one()
    assert event.event_type == "parse_skipped"


def test_embedding_failure_marks_document_failed(db_session_factory, db, storage, user, monkeypatch):
    document = create_document(db, storage, user)
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)
    monkeypatch.setattr(
        "app.services.document_parse_pipeline.DocumentEmbeddingService.embed_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("embed unavailable")),
    )

    result = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    event_types = {event.event_type for event in db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)}
    assert result.status == "done"
    assert document.status == "done"
    assert job.status == "succeeded"
    assert "embedding_failed" in event_types


def test_search_defaults_to_parsed_documents(client, db, storage, user):
    parsed = create_document(db, storage, user, status="completed", filename="parsed.txt")
    parsed.cleaned_text = "needle searchable text"
    queued = create_document(db, storage, user, status="pending", filename="queued.txt")
    queued.cleaned_text = "needle queued text"
    db.commit()

    response = client.get("/documents/search?q=needle")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [parsed.id]


def test_chunk_search_falls_back_to_keyword_when_vector_search_is_unavailable(client, db, storage, user, monkeypatch):
    document = create_document(db, storage, user, status="completed", filename="parsed.txt")
    chunk = DocumentChunk(
        document_id=document.id,
        parse_job_id=None,
        chunk_index=0,
        chunk_type="body",
        text="Needle chunk text",
        cleaned_text="Needle chunk text",
    )
    db.add(chunk)
    db.commit()

    def fail_semantic_search(*_args, **_kwargs):
        raise RuntimeError("sqlite-vec unavailable")

    monkeypatch.setattr(
        "app.services.document_search_service.DocumentSearchService._semantic_chunk_search",
        fail_semantic_search,
    )

    response = client.get("/documents/search/chunks?q=needle")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["chunk_id"] == chunk.id
    assert payload["items"][0]["document_title"] == document.title


def test_chunk_search_uses_stored_embedding_json(client, db, storage, user, monkeypatch):
    class QueryEmbeddingProvider:
        model_name = "test-embedding"

        def embed(self, texts):
            return [[1.0, *([0.0] * (EMBEDDING_DIM - 1))] for _text in texts]

    monkeypatch.setattr(
        "app.services.document_search_service.resolve_embedding_provider",
        lambda: QueryEmbeddingProvider(),
    )
    document = create_document(db, storage, user, status="completed", filename="semantic.txt")
    matching_chunk = DocumentChunk(
        document_id=document.id,
        parse_job_id=None,
        chunk_index=0,
        chunk_type="body",
        text="Semantic match",
        cleaned_text="Semantic match",
        embedding_json=json.dumps([1.0, *([0.0] * (EMBEDDING_DIM - 1))]),
    )
    unrelated_chunk = DocumentChunk(
        document_id=document.id,
        parse_job_id=None,
        chunk_index=1,
        chunk_type="body",
        text="Unrelated vector",
        cleaned_text="Unrelated vector",
        embedding_json=json.dumps([0.0, 1.0, *([0.0] * (EMBEDDING_DIM - 2))]),
    )
    db.add_all([matching_chunk, unrelated_chunk])
    db.commit()

    response = client.get("/documents/search/chunks?q=semantic&threshold=0.5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["chunk_id"] == matching_chunk.id
    assert payload["items"][0]["score"] == 1.0


def test_get_document_chunks_returns_parsed_chunks(client, db, storage, user):
    document = create_document(db, storage, user, status="completed")
    chunk = DocumentChunk(
        document_id=document.id,
        parse_job_id=None,
        chunk_index=0,
        chunk_type="body",
        text="Chunk text",
        cleaned_text="Chunk text",
        token_count=2,
        metadata_json='{"source":"body","section_path":["Intro"]}',
    )
    db.add(chunk)
    db.commit()

    response = client.get(f"/documents/{document.id}/chunks")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["chunk_index"] == 0
    assert payload[0]["token_count"] == 2
    assert payload[0]["metadata_json"] == '{"source":"body","section_path":["Intro"]}'


def test_search_chunks_uses_bookmark_source_url_as_source(client, db, user):
    document = Document(
        user_id=user.id,
        title="Example Article",
        original_filename="example.com",
        stored_filename="bookmark",
        original_file_path="bookmark:https://example.com/article",
        file_size=128,
        mime_type="text/html",
        source_type="bookmark",
        source_url="https://example.com/article",
        site_name="example.com",
        status="done",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            chunk_type="web",
            text="Alpha bookmark body",
            cleaned_text="Alpha bookmark body",
            metadata_json=json.dumps({"url": "https://example.com/article"}),
        )
    )
    db.commit()

    response = client.get("/documents/search/chunks?q=Alpha")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source"] == "https://example.com/article"


def test_get_document_chunks_pending_document_returns_empty(client, db, storage, user):
    document = create_document(db, storage, user, status="pending")

    response = client.get(f"/documents/{document.id}/chunks")

    assert response.status_code == 200
    assert response.json() == []


def test_get_document_chunks_rejects_other_user(client, db, storage, user):
    other = User(email="other@example.com", username="other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = create_document(db, storage, other, status="completed")

    response = client.get(f"/documents/{document.id}/chunks")

    assert response.status_code == 403


def test_tasks_returns_document_parse_jobs_for_current_user(client, db, storage, user):
    statuses = [
        ("queued", "queued"),
        ("running", "running"),
        ("succeeded", "succeeded"),
        ("failed", "failed"),
    ]
    for index, (job_status, _) in enumerate(statuses):
        document = create_document(db, storage, user, status="completed", filename=f"task-{index}.txt")
        db.add(JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status=job_status, error_message="bad" if job_status == "failed" else None))
    db.commit()

    response = client.get("/tasks/search")

    assert response.status_code == 200
    payload = response.json()["items"]
    returned_statuses = {item["file_name"]: item["status"] for item in payload if item["task_kind"] == "document_parse"}
    assert returned_statuses == {f"task-{index}.txt": expected for index, (_, expected) in enumerate(statuses)}
    assert all(item["document_id"] for item in payload if item["task_kind"] == "document_parse")


def test_tasks_returns_unified_basic_file_and_parse_tasks(client, db, storage, user):
    basic_file_task = JobRun(
        kind="basic_file_processing",
        job_id="basic-1",
        user_id=user.id,
        file_name="basic.pdf",
        file_size=123,
        file_type="pdf",
        status="queued",
        metadata_json=json.dumps({"storage_path": "/tmp/basic.pdf"}),
    )
    document = create_document(db, storage, user, status="completed", filename="parse.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded")
    db.add_all([basic_file_task, parse_job])
    db.commit()

    response = client.get("/tasks/search")

    assert response.status_code == 200
    payload = response.json()["items"]
    by_id = {item["task_id"]: item for item in payload}
    assert by_id["basic-1"]["task_kind"] == "basic_file_processing"
    assert by_id[parse_job.job_id]["task_kind"] == "document_parse"
    assert by_id[parse_job.job_id]["status"] == "succeeded"


def test_tasks_status_filter_uses_unified_status(client, db, storage, user):
    parsed_document = create_document(db, storage, user, status="completed", filename="parsed.txt")
    queued_document = create_document(db, storage, user, status="pending", filename="queued.txt")
    db.add_all(
        [
            JobRun(kind="document_parse", document_id=parsed_document.id, user_id=user.id, status="succeeded"),
            JobRun(kind="document_parse", document_id=queued_document.id, user_id=user.id, status="queued"),
        ]
    )
    db.commit()

    response = client.get("/tasks/search?status=succeeded")

    assert response.status_code == 200
    payload = response.json()["items"]
    assert [item["file_name"] for item in payload] == ["parsed.txt"]
    assert all(item["status"] == "succeeded" for item in payload)


def test_tasks_search_endpoint_supports_pagination_search_filter_and_sort(client, db, storage, user):
    own_alpha = create_document(db, storage, user, status="completed", filename="alpha-report.txt")
    own_beta = create_document(db, storage, user, status="completed", filename="beta-report.txt")
    other = User(email="search-other@example.com", username="search-other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    other_alpha = create_document(db, storage, other, status="completed", filename="alpha-other.txt")
    db.add_all(
        [
            JobRun(
                kind="document_parse",
                job_id="job-alpha",
                document_id=own_alpha.id,
                user_id=user.id,
                status="succeeded",
                progress=100,
            ),
            JobRun(
                kind="document_parse",
                job_id="job-beta",
                document_id=own_beta.id,
                user_id=user.id,
                status="failed",
                progress=100,
                error_message="parse failed",
            ),
            JobRun(
                kind="document_parse",
                job_id="job-alpha-other",
                document_id=other_alpha.id,
                user_id=other.id,
                status="succeeded",
                progress=100,
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/tasks/search?page=1&size=1&q=report&status=succeeded&kind=document_parse&sort_by=file_name&sort_order=asc"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 1
    assert [item["task_id"] for item in payload["items"]] == ["job-alpha"]
    assert payload["items"][0]["file_name"] == "alpha-report.txt"


def test_legacy_tasks_list_endpoint_is_removed_after_search_migration(client):
    response = client.get("/tasks")

    assert response.status_code == 405


@pytest.mark.parametrize(
    ("job_status", "expected_status", "expected_progress"),
    [
        ("queued", "queued", 0),
        ("running", "running", 50),
        ("succeeded", "succeeded", 100),
        ("failed", "failed", 100),
    ],
)
def test_task_detail_returns_parse_job_mapping(client, db, storage, user, job_status, expected_status, expected_progress):
    document = create_document(db, storage, user, status=job_status, filename=f"{job_status}.txt")
    parse_job = JobRun(kind="document_parse",
        document_id=document.id,
        user_id=user.id,
        status=job_status,
        progress=expected_progress,
        error_message="parse failed" if job_status == "failed" else None,
    )
    db.add(parse_job)
    db.commit()
    db.refresh(parse_job)

    response = client.get(f"/tasks/{parse_job.job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == parse_job.job_id
    assert payload["task_kind"] == "document_parse"
    assert payload["status"] == expected_status
    assert payload["progress"] == expected_progress
    assert payload["error"] == ("parse failed" if job_status == "failed" else None)
    assert payload["metadata_json"] is None or isinstance(payload["metadata_json"], str)


def test_task_detail_rejects_other_users_parse_job(client, db, storage, user):
    other = User(email="detail-other@example.com", username="detail-other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = create_document(db, storage, other, status="completed", filename="other-detail.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=other.id, status="succeeded")
    db.add(parse_job)
    db.commit()
    db.refresh(parse_job)

    response = client.get(f"/tasks/{parse_job.job_id}")

    assert response.status_code == 404


def test_task_detail_rejects_invalid_parse_task_id(client):
    response = client.get("/tasks/parse-invalid")

    assert response.status_code == 404


def test_parse_task_result_endpoint_returns_conflict(client, db, storage, user):
    document = create_document(db, storage, user, status="completed", filename="result.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded")
    db.add(parse_job)
    db.commit()
    db.refresh(parse_job)

    response = client.get(f"/tasks/{parse_job.job_id}/result")

    assert response.status_code == 409
    assert "Document parse tasks" in response.json()["detail"]


def test_clear_tasks_only_clears_basic_file_tasks_and_explains_parse_jobs_retained(client, db, storage, user):
    db.add(
        JobRun(
            kind="basic_file_processing",
            job_id="basic-clear",
            user_id=user.id,
            file_name="clear.pdf",
            file_size=10,
            file_type="pdf",
            status="queued",
            metadata_json=json.dumps({"storage_path": "/tmp/clear.pdf"}),
        )
    )
    document = create_document(db, storage, user, status="completed", filename="retained.txt")
    db.add(JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded"))
    db.commit()

    response = client.delete("/tasks")

    assert response.status_code == 200
    assert "Cleared 2 task records" in response.json()["message"]
    assert db.query(JobRun).filter(JobRun.user_id == user.id).count() == 2
    assert db.query(JobRun).filter(JobRun.user_id == user.id, JobRun.is_visible.is_(True)).count() == 0


def test_tasks_handles_parse_job_without_updated_at(client, db, storage, user):
    document = create_document(db, storage, user, status="completed", filename="no-updated.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded")
    db.add(parse_job)
    db.commit()
    response = client.get("/tasks/search")

    assert response.status_code == 200
    assert any(item["task_id"] == parse_job.job_id for item in response.json()["items"])


def test_tasks_handles_parse_job_without_document(client, db, user):
    parse_job = JobRun(kind="document_parse", document_id=999_999, user_id=user.id, status="queued", created_at=datetime.now(timezone.utc))
    db.add(parse_job)
    db.commit()
    db.refresh(parse_job)

    response = client.get("/tasks/search")

    assert response.status_code == 200
    payload = response.json()["items"]
    orphan = next(item for item in payload if item["task_id"] == parse_job.job_id)
    assert orphan["document_id"] == 999999
    assert orphan["file_name"] == "Document 999999"


def test_tasks_only_returns_current_users_parse_jobs(client, db, storage, user):
    own_document = create_document(db, storage, user, status="completed", filename="own.txt")
    other = User(email="task-other@example.com", username="task-other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    other_document = create_document(db, storage, other, status="completed", filename="other.txt")
    db.add(JobRun(kind="document_parse", document_id=own_document.id, user_id=user.id, status="succeeded"))
    db.add(JobRun(kind="document_parse", document_id=other_document.id, user_id=other.id, status="succeeded"))
    db.commit()

    response = client.get("/tasks/search")

    assert response.status_code == 200
    filenames = {item["file_name"] for item in response.json()["items"]}
    assert "own.txt" in filenames
    assert "other.txt" not in filenames


def test_tasks_requires_authentication(db_session_factory):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as anonymous_client:
            response = anonymous_client.get("/tasks/search")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def upload_document_with_mode(client, filename: str, content: bytes, mime_type: str, processing_mode: str = "auto"):
    return client.post(
        "/documents/upload",
        data={"processing_mode": processing_mode},
        files={"file": (filename, content, mime_type)},
    )


def test_processing_mode_defaults_to_auto(client, db):
    response = client.post(
        "/documents/upload",
        files={"file": ("default.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 202
    document = db.get(Document, response.json()["document_id"])
    job = db.get(JobRun, response.json()["parse_job_id"])
    assert document.processing_mode == DocumentProcessingMode.AUTO.value
    assert json.loads(job.input_json)["processing_mode"] == DocumentProcessingMode.AUTO.value


def test_invalid_processing_mode_returns_422(client):
    response = upload_document_with_mode(client, "bad.txt", b"hello", "text/plain", "freeform")

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("filename", "mime_type", "processing_mode"),
    [
        ("plain.txt", "text/plain", "plain_text"),
        ("paper.pdf", "application/pdf", "pdf_text"),
        ("scan.pdf", "application/pdf", "scanned_pdf_ocr"),
        ("photo.png", "image/png", "image_ocr"),
        ("notes.md", "text/markdown", "markdown_notes"),
        ("table.png", "image/png", "table_image_ocr"),
    ],
)
def test_compatible_processing_mode_uploads_succeed(client, db, filename, mime_type, processing_mode):
    content = PNG_BYTES if filename.endswith(".png") else PDF_BYTES if filename.endswith(".pdf") else b"content"
    response = upload_document_with_mode(client, filename, content, mime_type, processing_mode)

    assert response.status_code == 202
    document = db.get(Document, response.json()["document_id"])
    job = db.get(JobRun, response.json()["parse_job_id"])
    assert document.processing_mode == processing_mode
    assert json.loads(job.input_json)["processing_mode"] == processing_mode


@pytest.mark.parametrize(
    ("filename", "mime_type", "processing_mode", "message"),
    [
        ("image.png", "image/png", "pdf_text", "not compatible with image files"),
        ("plain.txt", "text/plain", "image_ocr", "requires an image file"),
        ("paper.pdf", "application/pdf", "image_ocr", "requires an image file"),
        ("notes.md", "text/markdown", "scanned_pdf_ocr", "requires a PDF file"),
    ],
)
def test_incompatible_processing_mode_uploads_fail(client, filename, mime_type, processing_mode, message):
    content = PNG_BYTES if filename.endswith(".png") else PDF_BYTES if filename.endswith(".pdf") else b"content"
    response = upload_document_with_mode(client, filename, content, mime_type, processing_mode)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_documents_responses_include_processing_mode(client, db):
    upload_response = upload_document_with_mode(client, "mode.txt", b"hello", "text/plain", "plain_text")
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document_id"]

    list_response = client.get("/documents")
    detail_response = client.get(f"/documents/{document_id}")

    assert list_response.status_code == 200
    item = next(item for item in list_response.json()["items"] if item["id"] == document_id)
    assert item["processing_mode"] == "plain_text"
    assert item["processing_strategy"] == "plain_text"
    assert detail_response.status_code == 200
    assert detail_response.json()["processing_mode"] == "plain_text"
    assert detail_response.json()["processing_strategy"] == "plain_text"


def test_retry_parse_preserves_processing_mode(client, db):
    upload_response = upload_document_with_mode(client, "retry.pdf", b"%PDF-1.4", "application/pdf", "scanned_pdf_ocr")
    document_id = upload_response.json()["document_id"]
    document = db.get(Document, document_id)
    job = db.get(JobRun, upload_response.json()["parse_job_id"])
    document.status = "failed"
    job.status = "failed"
    db.commit()

    response = client.post(f"/documents/{document_id}/retry-parse")

    assert response.status_code == 200
    db.refresh(document)
    assert document.processing_mode == "scanned_pdf_ocr"
    assert response.json()["processing_mode"] == "scanned_pdf_ocr"


@pytest.mark.parametrize(
    ("processing_mode", "source_type", "expected_strategy"),
    [
        ("auto", "pdf", "pdf_text_with_ocr_fallback"),
        ("scanned_pdf_ocr", "pdf", "ocr_first_pdf"),
        ("image_ocr", "image", "image_ocr"),
        ("markdown_notes", "markdown", "markdown_structure"),
        ("table_image_ocr", "image", "table_image_ocr"),
    ],
)
def test_pipeline_selects_processing_strategy(db, storage, user, processing_mode, source_type, expected_strategy):
    extension = "png" if source_type == "image" else "md" if source_type == "markdown" else source_type
    document = create_document(db, storage, user, filename=f"strategy.{extension}")
    document.source_type = source_type
    document.processing_mode = processing_mode
    db.commit()

    strategy = DocumentParsePipeline.select_parser_strategy(document.processing_mode, document.source_type)

    assert strategy.name == expected_strategy
