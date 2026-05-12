from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import Document, DocumentChunk, ParseJob, User
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.document_search_service import DocumentSearchService
from app.services.file_storage import FileStorageService
from app.services.text_cleaner import TextCleaner


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
    user = User(email="reader@example.com", username="reader", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def test_text_cleaner_repairs_pdf_artifacts_and_splits_sections():
    pages = [
        "Paper Title\nThe ﬁrst trans-\nformer result.\nFigure 1. Model overview.\nFooter 1",
        "Paper Title\nMore body text.\nReferences\n[1] A paper.\nFooter 2",
    ]

    result = TextCleaner().clean_pages(pages)

    assert "first transformer" in result.cleaned_text
    assert "Paper Title" not in result.cleaned_text
    assert "Footer 1" not in result.cleaned_text
    assert "Figure 1. Model overview." not in result.cleaned_text
    assert result.captions == ["Figure 1. Model overview."]
    assert result.references_text == "[1] A paper."
    assert result.quality["caption_count"] == 1


def test_parse_pipeline_preserves_parsed_text_and_creates_chunks_and_job(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="sample.txt",
        file_content=(
            b"Header\nThe \xef\xac\x81rst trans-\nformer paragraph.\n"
            b"Figure 2. Architecture.\nReferences\n[1] Source.\nFooter\n"
        ),
        file_extension="txt",
    )

    db = session_factory()
    document = Document(
        user_id=user.id,
        title="Sample",
        original_filename="sample.txt",
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=100,
        mime_type="text/plain",
        source_type="txt",
        status="pending",
    )
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()

    pipeline = DocumentParsePipeline(session_factory=session_factory, file_storage=storage)
    pipeline.run(document_id)

    db = session_factory()
    parsed = db.get(Document, document_id)
    jobs = db.scalars(select(ParseJob).where(ParseJob.document_id == document_id)).all()
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()

    assert parsed is not None
    assert parsed.status == "parsed"
    assert parsed.parsed_text
    assert parsed.cleaned_text is not None
    assert "first transformer paragraph" in parsed.cleaned_text
    assert parsed.parse_quality_json is not None
    assert len(jobs) == 1
    assert jobs[0].status == "succeeded"
    assert {chunk.chunk_type for chunk in chunks} >= {"body", "caption", "reference"}
    db.close()


def test_document_search_matches_generated_chunks(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="searchable.txt",
        file_content=b"Knowledge graphs need grounded evidence chunks.",
        file_extension="txt",
    )

    db = session_factory()
    document = Document(
        user_id=user.id,
        title="Searchable",
        original_filename="searchable.txt",
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=47,
        mime_type="text/plain",
        source_type="txt",
        status="pending",
    )
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()

    DocumentParsePipeline(session_factory=session_factory, file_storage=storage).run(document_id)

    db = session_factory()
    hits = DocumentSearchService(db).search(user.id, "evidence chunks")

    assert len(hits) == 1
    assert hits[0].document.id == document_id
    assert hits[0].matched_field in {"cleaned_text", "chunk"}
    assert "evidence chunks" in hits[0].snippet
    db.close()
