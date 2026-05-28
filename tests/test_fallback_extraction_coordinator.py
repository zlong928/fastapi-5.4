from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, User
from app.services.agent.fallback_agent import FallbackExtractionCoordinator
from app.services.agent.types import FigureInfo, PaperData


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
    user = User(email="paper@example.com", username="paperuser", hashed_password=None)
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


def test_fallback_coordinator_aggregates_with_not_found_metrics_argument():
    paper = PaperData(
        paper_id="paper-1",
        title="Microbial wastewater treatment",
        content="materials include hydrogel chambers. key_metrics include hexanoic acid yield.",
        figures=[
            FigureInfo(
                figure_id="Figure 1 [asset:9]",
                image_path="",
                caption="Conceptual figure for microbial consortia.",
                context="Conceptual figure for microbial consortia.",
            )
        ],
    )

    events = list(FallbackExtractionCoordinator().extract(paper=paper, user_query="提取关键指标"))
    finish = events[-1]

    assert finish["phase"] == "FINISH"
    assert finish["results"]["paper_id"] == "paper-1"
    assert "by_metric" in finish["results"]


def test_run_extraction_returns_pending_job_for_polling(client, db, user, monkeypatch):
    scheduled_jobs: list[int] = []
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="sample paper",
        original_filename="sample.pdf",
        stored_filename="sample.pdf",
        original_file_path="1/2026/05/sample.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="hydrogel chambers improved hexanoic acid production.",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    monkeypatch.setattr(
        "app.api.routes.extractions._schedule_job",
        lambda _background_tasks, job_id: scheduled_jobs.append(job_id),
    )

    response = client.post("/extractions/run", json={"paperId": paper.id, "query": "提取关键指标"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["error_message"] is None
    assert scheduled_jobs == [payload["id"]]

    list_response = client.get(f"/extractions?paper_id={paper.id}")
    assert list_response.status_code == 200
    jobs = list_response.json()
    assert jobs[0]["id"] == payload["id"]
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["result_count"] == 0
