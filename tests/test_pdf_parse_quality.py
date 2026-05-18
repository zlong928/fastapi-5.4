from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import Document, DocumentChunk
from app.models import User
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services import document_parser
from app.services.document_parser import DocumentParserService, ParsedDocument, ParsedElement, ParsedPage, PdfPageProfile
from app.services.file_storage import FileStorageService
from app.core.config import EMBEDDING_DIM


class StubFileStorage:
    def get_file_path(self, _relative_path):
        return "/tmp/fake.pdf"


class StubEmbeddingProvider:
    model_name = "stub"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIM for _ in texts]


class StubOcrService:
    def __init__(self, pages: dict[int, str] | None = None, failures: set[int] | None = None):
        self.pages = pages or {}
        self.failures = failures or set()
        self.calls: list[int] = []

    def ocr_pdf_page(self, _file_path, page_number: int) -> str:
        self.calls.append(page_number)
        if page_number in self.failures:
            raise RuntimeError("ocr boom")
        return self.pages.get(page_number, "")

    def ocr_pdf_pages(self, _file_path):
        return [self.pages[index] for index in sorted(self.pages)]


class StubParser:
    def __init__(self, parsed_document: ParsedDocument):
        self.parsed_document = parsed_document

    def parse_pdf_document(self, _file_path):
        return self.parsed_document


class FakePymupdfDocument:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self.pages

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePymupdf:
    def __init__(self, pages):
        self.pages = pages

    def open(self, _file_path):
        return FakePymupdfDocument(self.pages)


class FakePymupdfPage:
    def __init__(self, blocks=None, words=None, images=None):
        self.blocks = blocks or []
        self.words = words or []
        self.images = images or []

    def get_text(self, kind, sort=False):
        assert sort is True
        if kind == "blocks":
            return self.blocks
        if kind == "words":
            return self.words
        if kind == "dict":
            return {"blocks": []}
        raise AssertionError(kind)

    def get_images(self, full=True):
        assert full is True
        return self.images


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
    user = User(email="pdf@example.com", username="pdfuser", hashed_password=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def storage(tmp_path):
    return FileStorageService(upload_dir=str(tmp_path / "uploads"))


def profile(page_number: int, text: str, *, image_count: int = 0, needs_ocr: bool = False, bad_text: bool = False):
    warnings = []
    if needs_ocr:
        warnings.append("empty_text" if not text else "very_short_text")
    if bad_text:
        warnings.append("suspected_bad_text_layer")
    return PdfPageProfile(
        page_number=page_number,
        text_length=len(text),
        word_count=len(text.split()),
        block_count=1 if text else 0,
        image_block_count=image_count,
        image_count=image_count,
        is_scanned=needs_ocr and image_count > 0,
        bad_text_layer=bad_text,
        needs_ocr=needs_ocr,
        extraction_method="ocr" if needs_ocr else "pdf_text",
        warnings=warnings,
    )


def parsed_pdf(pages: list[ParsedPage]) -> ParsedDocument:
    return ParsedDocument(
        pages=pages,
        source_type="pdf",
        parser_engine="pymupdf",
        pymupdf_available=True,
        table_extraction_enabled=False,
        table_extraction_reason="not installed",
    )


def test_pymupdf_path_builds_elements_with_bbox_and_profile(monkeypatch):
    fake_page = FakePymupdfPage(
        blocks=[
            (100, 100, 180, 120, "Second block text has enough words.", 1, 0),
            (10, 10, 80, 30, "First block text has enough words.", 0, 0),
            (20, 40, 90, 80, "<image>", 2, 1),
        ],
        images=[("xref",)],
    )
    monkeypatch.setattr(document_parser, "fitz", FakePymupdf([fake_page]))

    parsed = DocumentParserService().parse_pdf_document("/tmp/fake.pdf")

    text_elements = [element for element in parsed.pages[0].elements if element.text]
    image_elements = [element for element in parsed.pages[0].elements if element.element_type == "image"]
    assert parsed.parser_engine == "pymupdf"
    assert parsed.pymupdf_available is True
    assert [element.text for element in text_elements] == [
        "First block text has enough words.",
        "Second block text has enough words.",
    ]
    assert text_elements[0].bbox == (10.0, 10.0, 80.0, 30.0)
    assert text_elements[0].extractor == "pymupdf"
    assert image_elements[0].bbox == (20.0, 40.0, 90.0, 80.0)
    assert parsed.pages[0].profile.image_block_count == 1


def test_pymupdf_words_fallback_when_blocks_have_no_text(monkeypatch):
    fake_page = FakePymupdfPage(
        blocks=[],
        words=[
            (10, 10, 25, 20, "Hello", 0, 0, 0),
            (30, 10, 60, 20, "world", 0, 0, 1),
        ],
    )
    monkeypatch.setattr(document_parser, "fitz", FakePymupdf([fake_page]))

    parsed = DocumentParserService().parse_pdf_document("/tmp/fake.pdf")

    assert parsed.pages[0].elements[0].text == "Hello world"
    assert parsed.pages[0].elements[0].bbox == (10.0, 10.0, 60.0, 20.0)


def test_pymupdf_unavailable_falls_back_to_pypdf(monkeypatch):
    class FakePypdfPage:
        def extract_text(self):
            return "Fallback text from pypdf with enough words."

        def get(self, _key, default=None):
            return default or {}

    class FakePypdfReader:
        pages = [FakePypdfPage()]

    monkeypatch.setattr(document_parser, "fitz", None)
    monkeypatch.setattr(document_parser.pypdf, "PdfReader", lambda _file: FakePypdfReader())

    parsed = DocumentParserService().parse_pdf_document(__file__)

    assert parsed.parser_engine == "pypdf"
    assert parsed.pymupdf_available is False
    assert parsed.pages[0].elements[0].extractor == "pypdf"
    assert any("pymupdf_unavailable" in warning for warning in parsed.warnings)


def create_pdf_document(db, storage, user, *, filename: str = "paper.pdf") -> Document:
    relative_path, stored_filename = storage.store_file(
        user_id=user.id,
        original_filename=filename,
        file_content=b"%PDF-1.4\nstub",
        file_extension="pdf",
    )
    document = Document(
        user_id=user.id,
        title="paper",
        original_filename=filename,
        stored_filename=stored_filename,
        original_file_path=relative_path,
        file_size=13,
        mime_type="application/pdf",
        source_type="pdf",
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, ocr_service):
    pipeline = DocumentParsePipeline(
        session_factory=db_session_factory,
        file_storage=storage,
        ocr_service=ocr_service,
        embedding_provider=StubEmbeddingProvider(),
    )
    pipeline.parser = StubParser(parsed_document)
    return pipeline.run(document.id)


def test_digital_pdf_page_chunks_with_pdf_text_metadata(db_session_factory, db, storage, user):
    document = create_pdf_document(db, storage, user)
    parsed_document = parsed_pdf(
        [
            ParsedPage(
                page_number=1,
                profile=profile(1, "Digital PDF text has enough words for extraction."),
                elements=[
                    ParsedElement(
                        element_type="paragraph",
                        text="Digital PDF text has enough words for extraction.",
                        page_number=1,
                        extractor="pymupdf",
                        bbox=(1, 2, 3, 4),
                        metadata={"source_type": "pdf"},
                    )
                ],
            )
        ]
    )

    run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, StubOcrService())

    chunk = db.query(DocumentChunk).filter_by(document_id=document.id).one()
    metadata = json.loads(chunk.metadata_json)
    assert chunk.chunk_type == "body"
    assert chunk.page_start == 1
    assert chunk.page_end == 1
    assert metadata["extractor"] == "pymupdf"
    assert metadata["bbox"] == [1, 2, 3, 4]
    assert metadata["ocr_used"] is False
    assert metadata["source_type"] == "pdf"


def test_low_text_pdf_page_uses_per_page_ocr_fallback(db_session_factory, db, storage, user):
    document = create_pdf_document(db, storage, user)
    ocr = StubOcrService({1: "OCR recovered text from scanned page."})
    parsed_document = parsed_pdf([ParsedPage(page_number=1, profile=profile(1, "", image_count=1, needs_ocr=True))])

    run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, ocr)

    chunk = db.query(DocumentChunk).filter_by(document_id=document.id).one()
    metadata = json.loads(chunk.metadata_json)
    db.refresh(document)
    quality = json.loads(document.parse_quality_json)
    assert ocr.calls == [1]
    assert chunk.chunk_type == "ocr_text"
    assert metadata["extractor"] == "ocr"
    assert metadata["ocr_used"] is True
    assert quality["pages_ocr_used"] == 1


def test_hybrid_pdf_uses_text_and_ocr_by_page(db_session_factory, db, storage, user):
    document = create_pdf_document(db, storage, user)
    ocr = StubOcrService({2: "OCR page two content."})
    parsed_document = parsed_pdf(
        [
            ParsedPage(
                page_number=1,
                profile=profile(1, "Page one has normal digital text."),
                elements=[
                    ParsedElement(
                        element_type="paragraph",
                        text="Page one has normal digital text.",
                        page_number=1,
                        extractor="pymupdf",
                        metadata={"source_type": "pdf"},
                    )
                ],
            ),
            ParsedPage(page_number=2, profile=profile(2, "", image_count=1, needs_ocr=True)),
        ]
    )

    run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, ocr)

    chunks = db.query(DocumentChunk).filter_by(document_id=document.id).order_by(DocumentChunk.chunk_index).all()
    db.refresh(document)
    quality = json.loads(document.parse_quality_json)
    assert [chunk.page_start for chunk in chunks] == [1, 2]
    assert [json.loads(chunk.metadata_json)["extractor"] for chunk in chunks] == ["pymupdf", "ocr"]
    assert quality["pages_total"] == 2
    assert quality["pages_ocr_used"] == 1
    assert quality["parser_engine"] == "pymupdf"
    assert quality["pymupdf_available"] is True
    assert quality["extraction_methods"]["pymupdf"] == 1
    assert quality["extraction_methods"]["ocr"] == 1


def test_table_element_is_written_as_table_chunk(db_session_factory, db, storage, user):
    document = create_pdf_document(db, storage, user)
    parsed_document = parsed_pdf(
        [
            ParsedPage(
                page_number=1,
                profile=profile(1, "Table page has normal text."),
                elements=[
                    ParsedElement(
                        element_type="table",
                        text="| A | B |\n| --- | --- |\n| 1 | 2 |",
                        page_number=1,
                        extractor="table",
                        metadata={"source_type": "pdf", "row_count": 2, "column_count": 2},
                    )
                ],
            )
        ]
    )

    run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, StubOcrService())

    chunk = db.query(DocumentChunk).filter_by(document_id=document.id).one()
    db.refresh(document)
    metadata = json.loads(chunk.metadata_json)
    quality = json.loads(document.parse_quality_json)
    assert chunk.chunk_type == "table"
    assert metadata["extractor"] == "table"
    assert metadata["row_count"] == 2
    assert metadata["column_count"] == 2
    assert quality["table_count"] == 1


def test_ocr_failure_records_warning_without_silent_loss(db_session_factory, db, storage, user):
    document = create_pdf_document(db, storage, user)
    parsed_document = parsed_pdf([ParsedPage(page_number=1, profile=profile(1, "", image_count=1, needs_ocr=True))])

    result = run_stubbed_pipeline(db_session_factory, storage, document, parsed_document, StubOcrService(failures={1}))

    db.refresh(document)
    assert result.status == "failed"
    assert document.status == "failed"
    assert document.error_message == "文件内容为空"
