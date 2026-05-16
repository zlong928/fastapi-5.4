from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentChunk, DocumentEvent, JobRun, User
from app.schemas.document import DocumentProcessingMode
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.file_storage import FileStorageService
from app.services.document_service import DocumentService


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
    status: str = "uploaded",
    filename: str = "sample.txt",
    content: bytes = b"DocumentParser uses Redis.",
) -> Document:
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename=filename,
        file_content=content,
        file_extension=filename.rsplit(".", 1)[1],
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
    assert payload["status"] == "queued"
    assert payload["parse_job_id"]

    document = db.get(Document, payload["document_id"])
    job = db.get(JobRun, payload["parse_job_id"])
    assert document is not None
    assert document.status == "queued"
    assert job is not None
    event_types = {
        event.event_type
        for event in db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)
    }
    assert "uploaded" in event_types
    assert enqueued == [(document.id, job.id)]


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

    written_paths = [unquote(request["url"].split("/vault/", 1)[1]) for request in requests]
    assert written_paths == [
        f"Uploads/2026/05/{payload['document_id']}-Unsafe - Title- 01/original/source bad-.txt",
        f"Uploads/2026/05/{payload['document_id']}-Unsafe - Title- 01/index.md",
    ]
    assert all(request["headers"]["Authorization"] == "Bearer test-api-key" for request in requests)
    assert all(request["url"].startswith("http://127.0.0.1:27123/vault/") for request in requests)

    index_request = requests[1]
    index_text = index_request["content"].decode("utf-8")
    assert "title: \"../Unsafe / Title: 01\"" in index_text
    assert 'original_file: "original/source bad-.txt"' in index_text
    assert "[[original/source bad-.txt]]" in index_text
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
        "directory_path": f"Uploads/2026/05/{payload['document_id']}-Unsafe - Title- 01",
        "original_file_path": f"Uploads/2026/05/{payload['document_id']}-Unsafe - Title- 01/original/source bad-.txt",
        "index_path": f"Uploads/2026/05/{payload['document_id']}-Unsafe - Title- 01/index.md",
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


@pytest.mark.parametrize("initial_status", ["parsed", "failed"])
def test_retry_parse_allowed_for_finished_states(client, db, storage, user, monkeypatch, initial_status):
    document = create_document(db, storage, user, status=initial_status)
    enqueued: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.document_service.enqueue_document_parse",
        lambda document_id, parse_job_id: enqueued.append((document_id, parse_job_id)),
    )

    response = client.post(f"/documents/{document.id}/retry-parse")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["latest_parse_job"]["status"] == "queued"
    assert enqueued == [(document.id, payload["latest_parse_job"]["id"])]


@pytest.mark.parametrize("initial_status", ["queued", "processing"])
def test_retry_parse_rejects_active_documents(client, db, storage, user, initial_status):
    document = create_document(db, storage, user, status=initial_status)
    active_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(active_job)
    db.commit()

    response = client.post(f"/documents/{document.id}/retry-parse")

    assert response.status_code == 409
    assert db.query(JobRun).filter(JobRun.document_id == document.id).count() == 1


def test_pipeline_uses_existing_job_and_marks_success(db_session_factory, db, storage, user):
    document = create_document(db, storage, user)
    job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    pipeline = DocumentParsePipeline(session_factory=db_session_factory, file_storage=storage)
    parsed_document = pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(job)
    assert parsed_document.status == "parsed"
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

    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    assert document.status == "failed"
    assert document.error_message == "boom"
    assert job.status == "failed"
    assert job.error_message == "boom"


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


def test_embedding_and_kg_failures_are_warning_events(db_session_factory, db, storage, user, monkeypatch):
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
    monkeypatch.setattr(
        "app.services.document_parse_pipeline.DocumentKgService.extract_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("kg unavailable")),
    )

    pipeline.run(document.id, parse_job_id=job.id)

    db.refresh(document)
    db.refresh(job)
    event_types = {event.event_type for event in db.query(DocumentEvent).filter(DocumentEvent.document_id == document.id)}
    assert document.status == "parsed"
    assert job.status == "succeeded"
    assert {"embedding_failed", "kg_failed"}.issubset(event_types)


def test_search_defaults_to_parsed_documents(client, db, storage, user):
    parsed = create_document(db, storage, user, status="parsed", filename="parsed.txt")
    parsed.cleaned_text = "needle searchable text"
    queued = create_document(db, storage, user, status="queued", filename="queued.txt")
    queued.cleaned_text = "needle queued text"
    db.commit()

    response = client.get("/documents/search?q=needle")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [parsed.id]


def test_get_document_chunks_returns_parsed_chunks(client, db, storage, user):
    document = create_document(db, storage, user, status="parsed")
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


def test_get_document_chunks_queued_document_returns_empty(client, db, storage, user):
    document = create_document(db, storage, user, status="queued")

    response = client.get(f"/documents/{document.id}/chunks")

    assert response.status_code == 200
    assert response.json() == []


def test_get_document_chunks_rejects_other_user(client, db, storage, user):
    other = User(email="other@example.com", username="other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    document = create_document(db, storage, other, status="parsed")

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
        document = create_document(db, storage, user, status="parsed", filename=f"task-{index}.txt")
        db.add(JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status=job_status, error_message="bad" if job_status == "failed" else None))
    db.commit()

    response = client.get("/tasks")

    assert response.status_code == 200
    payload = response.json()
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
    document = create_document(db, storage, user, status="parsed", filename="parse.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded")
    db.add_all([basic_file_task, parse_job])
    db.commit()

    response = client.get("/tasks")

    assert response.status_code == 200
    payload = response.json()
    by_id = {item["task_id"]: item for item in payload}
    assert by_id["basic-1"]["task_kind"] == "basic_file_processing"
    assert by_id[parse_job.job_id]["task_kind"] == "document_parse"
    assert by_id[parse_job.job_id]["status"] == "succeeded"


def test_tasks_status_filter_uses_unified_status(client, db, storage, user):
    parsed_document = create_document(db, storage, user, status="parsed", filename="parsed.txt")
    queued_document = create_document(db, storage, user, status="queued", filename="queued.txt")
    db.add_all(
        [
            JobRun(kind="document_parse", document_id=parsed_document.id, user_id=user.id, status="succeeded"),
            JobRun(kind="document_parse", document_id=queued_document.id, user_id=user.id, status="queued"),
        ]
    )
    db.commit()

    response = client.get("/tasks?status=succeeded")

    assert response.status_code == 200
    payload = response.json()
    assert [item["file_name"] for item in payload] == ["parsed.txt"]
    assert all(item["status"] == "succeeded" for item in payload)


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
    document = create_document(db, storage, other, status="parsed", filename="other-detail.txt")
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
    document = create_document(db, storage, user, status="parsed", filename="result.txt")
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
    document = create_document(db, storage, user, status="parsed", filename="retained.txt")
    db.add(JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded"))
    db.commit()

    response = client.delete("/tasks")

    assert response.status_code == 200
    assert "Cleared 2 task records" in response.json()["message"]
    assert db.query(JobRun).filter(JobRun.user_id == user.id).count() == 2
    assert db.query(JobRun).filter(JobRun.user_id == user.id, JobRun.is_visible.is_(True)).count() == 0


def test_tasks_handles_parse_job_without_updated_at(client, db, storage, user):
    document = create_document(db, storage, user, status="parsed", filename="no-updated.txt")
    parse_job = JobRun(kind="document_parse", document_id=document.id, user_id=user.id, status="succeeded")
    db.add(parse_job)
    db.commit()
    response = client.get("/tasks")

    assert response.status_code == 200
    assert any(item["task_id"] == parse_job.job_id for item in response.json())


def test_tasks_handles_parse_job_without_document(client, db, user):
    parse_job = JobRun(kind="document_parse", document_id=999_999, user_id=user.id, status="queued", created_at=datetime.now(timezone.utc))
    db.add(parse_job)
    db.commit()
    db.refresh(parse_job)

    response = client.get("/tasks")

    assert response.status_code == 200
    payload = response.json()
    orphan = next(item for item in payload if item["task_id"] == parse_job.job_id)
    assert orphan["document_id"] == 999999
    assert orphan["file_name"] == "Document 999999"


def test_tasks_only_returns_current_users_parse_jobs(client, db, storage, user):
    own_document = create_document(db, storage, user, status="parsed", filename="own.txt")
    other = User(email="task-other@example.com", username="task-other", hashed_password=None)
    db.add(other)
    db.commit()
    db.refresh(other)
    other_document = create_document(db, storage, other, status="parsed", filename="other.txt")
    db.add(JobRun(kind="document_parse", document_id=own_document.id, user_id=user.id, status="succeeded"))
    db.add(JobRun(kind="document_parse", document_id=other_document.id, user_id=other.id, status="succeeded"))
    db.commit()

    response = client.get("/tasks")

    assert response.status_code == 200
    filenames = {item["file_name"] for item in response.json()}
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
            response = anonymous_client.get("/tasks")
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
    response = upload_document_with_mode(client, filename, b"content", mime_type, processing_mode)

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
    response = upload_document_with_mode(client, filename, b"content", mime_type, processing_mode)

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
