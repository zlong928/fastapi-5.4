from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import Document, DocumentAsset, DocumentChunk, User
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.file_storage import FileStorageService


class FakeOcrService:
    def ocr_image(self, file_path: Path) -> str:
        return f"OCR text from image {file_path.name}"

    def ocr_pdf_pages(self, file_path: Path) -> list[str]:
        return ["Scanned PDF page OCR text"]


class BlankPdfParser:
    def parse_pdf_pages(self, file_path: Path) -> list[str]:
        return ["", "   "]

    def parse(self, file_path: Path, source_type: str) -> str:
        return file_path.read_text(encoding="utf-8")


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
    user = User(email="ocr@example.com", username="ocr", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def create_document(session_factory, user_id: int, relative_path: str, stored_filename: str, source_type: str, mime_type: str) -> int:
    db = session_factory()
    document = Document(
        user_id=user_id,
        title=stored_filename,
        original_filename=stored_filename,
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=100,
        mime_type=mime_type,
        source_type=source_type,
        status="pending",
    )
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()
    return document_id


def test_image_upload_pipeline_writes_ocr_asset_and_chunk(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="scan.png",
        file_content=b"fake image bytes",
        file_extension="png",
    )
    document_id = create_document(session_factory, user.id, relative_path, stored_filename, "image", "image/png")

    DocumentParsePipeline(
        session_factory=session_factory,
        file_storage=storage,
        ocr_service=FakeOcrService(),
    ).run(document_id)

    db = session_factory()
    document = db.get(Document, document_id)
    assets = db.scalars(select(DocumentAsset).where(DocumentAsset.document_id == document_id)).all()
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()

    assert document is not None
    assert document.status == "parsed"
    assert document.cleaned_text == f"OCR text from image {stored_filename}"
    assert assets[0].asset_type == "uploaded_image"
    assert assets[0].ocr_text == f"OCR text from image {stored_filename}"
    assert chunks[0].chunk_type == "ocr"
    assert chunks[0].cleaned_text == f"OCR text from image {stored_filename}"
    db.close()


def test_scanned_pdf_falls_back_to_ocr_pages(tmp_path: Path):
    session_factory = make_session_factory()
    user = create_user(session_factory)
    storage = FileStorageService(upload_dir=str(tmp_path))
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename="scan.pdf",
        file_content=b"%PDF fake",
        file_extension="pdf",
    )
    document_id = create_document(session_factory, user.id, relative_path, stored_filename, "pdf", "application/pdf")

    pipeline = DocumentParsePipeline(
        session_factory=session_factory,
        file_storage=storage,
        ocr_service=FakeOcrService(),
    )
    pipeline.parser = BlankPdfParser()
    pipeline.run(document_id)

    db = session_factory()
    document = db.get(Document, document_id)
    assets = db.scalars(select(DocumentAsset).where(DocumentAsset.document_id == document_id)).all()
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()

    assert document is not None
    assert document.cleaned_text == "Scanned PDF page OCR text"
    assert assets[0].asset_type == "pdf_page_ocr"
    assert assets[0].page_number == 1
    assert chunks[0].chunk_type == "ocr"
    assert chunks[0].page_start == 1
    db.close()
