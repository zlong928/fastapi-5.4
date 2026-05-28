import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentAsset, ExtractionJob, ExtractionResult, PaperTable, User
from app.services.paper_demo_service import PaperDemoService
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


def test_parse_generates_page_snapshot_when_pdf_has_no_figures(db, user, tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    relative_path = "1/2026/05/nofig.pdf"
    pdf_path = tmp_path / relative_path
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A text-only PDF page for snapshot fallback.")
    pdf.save(str(pdf_path))
    pdf.close()

    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="text only paper",
        original_filename="nofig.pdf",
        stored_filename="nofig.pdf",
        original_file_path=relative_path,
        file_size=pdf_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="A text-only PDF page for snapshot fallback.",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    PaperDemoService(db).parse(paper)

    assets = db.query(DocumentAsset).filter(DocumentAsset.document_id == paper.id).all()
    assert len(assets) >= 1
    snapshot = next(asset for asset in assets if asset.asset_type == "page_snapshot")
    metadata = json.loads(snapshot.metadata_json)
    assert snapshot.page_number == 1
    assert snapshot.mime_type == "image/png"
    assert metadata == {
        "figure_label": "Page 1 Snapshot",
        "caption": "Fallback page snapshot",
        "source": "fallback_snapshot",
        "context": "Generated because no extractable PDF figure was found",
    }
    assert (tmp_path / snapshot.file_path).exists()


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


def test_paper_detail_returns_snapshot_asset_and_table_metadata(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="asset rich paper",
        original_filename="asset.pdf",
        stored_filename="asset.pdf",
        original_file_path="1/2026/05/asset.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        error_message="old extraction failure",
        cleaned_text="paper body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    db.add(
        DocumentAsset(
            document_id=paper.id,
            asset_type="page_snapshot",
            page_number=1,
            file_path="1/paper_agent/asset/page_1_snapshot.png",
            mime_type="image/png",
            metadata_json=(
                '{"figure_label":"Page 1 Snapshot","caption":"Fallback page snapshot",'
                '"source":"fallback_snapshot","context":"Generated because no extractable PDF figure was found"}'
            ),
        )
    )
    db.add_all(
        [
            PaperTable(
                paper_id=paper.id,
                table_label="Table 1",
                content="| A | B |\n| --- | --- |\n| 1 | 2 |",
                page=2,
            ),
            PaperTable(
                paper_id=paper.id,
                table_label="Table Candidate 1",
                content="| A | B |\n| --- | --- |\n| fallback | row |",
                page=3,
            ),
            PaperTable(
                paper_id=paper.id,
                table_label="Detected block",
                content="plain text candidate",
                page=4,
            ),
        ]
    )
    db.commit()

    response = client.get(f"/papers/{paper.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parse_error"] is None
    assert payload["figures"][0]["figure_label"] == "Page 1 Snapshot"
    assert payload["figures"][0]["caption"] == "Fallback page snapshot"
    assert payload["figures"][0]["source"] == "fallback_snapshot"
    assert payload["figures"][0]["notes"] == "Generated because no extractable PDF figure was found"
    assert payload["figures"][0]["image_path"].startswith("/papers/assets/")

    tables = {table["table_label"]: table for table in payload["tables"]}
    assert tables["Table 1"]["parse_status"] == "success"
    assert tables["Table 1"]["source"] == "pdfplumber"
    assert tables["Table Candidate 1"]["parse_status"] == "fallback"
    assert tables["Table Candidate 1"]["source"] == "fallback candidate"
    assert tables["Detected block"]["parse_status"] == "partial"
    assert tables["Detected block"]["source"] == "text candidate"


def test_list_extractions_without_paper_id_returns_all_user_jobs(client, db, user):
    now = datetime.now(timezone.utc)
    other_user = User(email="other@example.com", username="otheruser", hashed_password=None)
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    first_paper = Document(
        user_id=user.id,
        title="first paper",
        original_filename="first.pdf",
        stored_filename="first.pdf",
        original_file_path="1/2026/05/first.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="first",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    second_paper = Document(
        user_id=user.id,
        title="second paper",
        original_filename="second.pdf",
        stored_filename="second.pdf",
        original_file_path="1/2026/05/second.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="second",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    other_paper = Document(
        user_id=other_user.id,
        title="other paper",
        original_filename="other.pdf",
        stored_filename="other.pdf",
        original_file_path="2/2026/05/other.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="other",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add_all([first_paper, second_paper, other_paper])
    db.commit()
    db.refresh(first_paper)
    db.refresh(second_paper)
    db.refresh(other_paper)

    first_job = ExtractionJob(paper_id=first_paper.id, query="first query", status="done")
    second_job = ExtractionJob(paper_id=second_paper.id, query="second query", status="failed", error_message="bad extraction")
    other_job = ExtractionJob(paper_id=other_paper.id, query="other query", status="done")
    db.add_all([first_job, second_job, other_job])
    db.commit()
    db.refresh(first_job)
    db.refresh(second_job)
    db.add(
        ExtractionResult(
            job_id=first_job.id,
            source_type="text",
            source_id=None,
            field_name="key_metrics",
            content="result",
            evidence="evidence",
            confidence=0.7,
        )
    )
    db.commit()

    response = client.get("/extractions")

    assert response.status_code == 200
    payload = response.json()
    assert {job["paper_title"] for job in payload} == {"first paper", "second paper"}
    first_payload = next(job for job in payload if job["paper_title"] == "first paper")
    second_payload = next(job for job in payload if job["paper_title"] == "second paper")
    assert first_payload["query"] == "first query"
    assert first_payload["result_count"] == 1
    assert second_payload["status"] == "failed"
    assert second_payload["error_message"] == "bad extraction"
