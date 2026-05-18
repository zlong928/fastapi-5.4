from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE
from app.db.session import Base
from app.models import Document, JobRun, User
from app.services.document_service import DocumentService
from app.services.job_run_service import JobRunService


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def create_user(db):
    user = User(email="job@example.com", username="jobuser", hashed_password=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_document(db, user):
    document = Document(
        user_id=user.id,
        title="Paper",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        original_file_path="documents/1/paper.pdf",
        file_size=123,
        mime_type="application/pdf",
        source_type="pdf",
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_job_run_service_lifecycle_and_filters():
    db = make_session()
    user = create_user(db)
    document = create_document(db, user)
    service = JobRunService(db)

    job_run = service.create_job(
        user_id=user.id,
        kind=JOB_KIND_DOCUMENT_PARSE,
        subject_type="document",
        subject_id=document.id,
        document_id=document.id,
        title="Parse paper.pdf",
        file_name="paper.pdf",
        file_size=123,
        file_type="pdf",
        input_data={"processing_mode": "auto"},
    )
    db.commit()

    assert service.get_job(job_run.job_id, user_id=user.id) is not None
    assert service.list_jobs(user_id=user.id, status_filter="queued") == [job_run]
    assert service.list_jobs(user_id=user.id, kind_filter=JOB_KIND_DOCUMENT_PARSE) == [job_run]
    assert service.list_jobs(user_id=user.id, document_id=document.id) == [job_run]

    service.mark_running(job_run, worker_name="test-worker")
    service.update_progress(job_run, 150, metadata={"stage": "extracting"})
    db.commit()
    assert job_run.status == "running"
    assert job_run.started_at is not None
    assert job_run.worker_name == "test-worker"
    assert job_run.progress == 100

    service.update_progress(job_run, -5)
    assert job_run.progress == 0

    service.mark_succeeded(job_run, output_data={"chunk_count": 3})
    db.commit()
    assert job_run.status == "succeeded"
    assert job_run.progress == 100
    assert job_run.finished_at is not None


def test_job_run_failure_and_hide_does_not_delete_document():
    db = make_session()
    user = create_user(db)
    document = create_document(db, user)
    service = JobRunService(db)
    job_run = service.create_job(
        user_id=user.id,
        kind=JOB_KIND_DOCUMENT_PARSE,
        document_id=document.id,
        subject_type="document",
        subject_id=document.id,
    )

    service.mark_failed(job_run, "boom", metadata={"error_type": "RuntimeError"})
    hidden_count = service.hide_jobs_for_user(user.id)
    db.commit()

    assert job_run.status == "failed"
    assert job_run.error_message == "boom"
    assert job_run.finished_at is not None
    assert hidden_count == 1
    assert db.get(Document, document.id) is not None
    assert db.query(JobRun).filter(JobRun.user_id == user.id).count() == 1


def test_retry_parse_creates_document_parse_job_run(monkeypatch):
    db = make_session()
    user = create_user(db)
    document = create_document(db, user)
    document.status = "failed"
    db.commit()
    enqueued: list[tuple[int, int]] = []
    monkeypatch.setattr("app.services.document_service.enqueue_document_parse", lambda document_id, job_run_id: enqueued.append((document_id, job_run_id)))

    retried_document, job_run = DocumentService(db).retry_parse(document.id)

    assert retried_document.status == "pending"
    assert job_run.kind == JOB_KIND_DOCUMENT_PARSE
    assert job_run.document_id == document.id
    assert job_run.status == "queued"
    assert enqueued == [(document.id, job_run.id)]
