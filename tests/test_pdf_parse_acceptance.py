from __future__ import annotations

from pathlib import Path

from app.services.document_parser import ParsedDocument, ParsedElement, ParsedPage, PdfPageProfile
from scripts.pdf_parse_acceptance import build_acceptance_report


def test_acceptance_report_summarizes_real_parser_metadata():
    parsed = ParsedDocument(
        pages=[
            ParsedPage(
                page_number=1,
                profile=PdfPageProfile(
                    page_number=1,
                    text_length=120,
                    word_count=20,
                    block_count=3,
                    image_block_count=1,
                    image_count=1,
                    is_scanned=False,
                    bad_text_layer=False,
                    needs_ocr=False,
                    extraction_method="pdf_text",
                    warnings=[],
                ),
                elements=[
                    ParsedElement(
                        element_type="paragraph",
                        text="A useful paragraph",
                        page_number=1,
                        bbox=(1.0, 2.0, 3.0, 4.0),
                        extractor="pymupdf",
                    ),
                    ParsedElement(
                        element_type="image",
                        text="",
                        page_number=1,
                        bbox=(5.0, 6.0, 7.0, 8.0),
                        extractor="pymupdf",
                    ),
                ],
            ),
            ParsedPage(
                page_number=2,
                profile=PdfPageProfile(
                    page_number=2,
                    text_length=0,
                    word_count=0,
                    block_count=0,
                    image_block_count=1,
                    image_count=1,
                    is_scanned=True,
                    bad_text_layer=False,
                    needs_ocr=True,
                    extraction_method="ocr",
                    warnings=["empty_text", "suspected_scanned_page"],
                ),
                elements=[],
                warnings=["ocr_required"],
            ),
        ],
        source_type="pdf",
        parser_engine="pymupdf",
        pymupdf_available=True,
        table_extraction_enabled=False,
        table_extraction_reason="pdfplumber is not installed; table extraction is disabled.",
    )

    report = build_acceptance_report(parsed, Path("/samples/paper.pdf"))

    assert report["parser_engine"] == "pymupdf"
    assert report["pymupdf_available"] is True
    assert report["pages_total"] == 2
    assert report["pages_text_extracted"] == 1
    assert report["pages_needing_ocr"] == [2]
    assert report["scanned_pages"] == [2]
    assert report["image_block_count_total"] == 2
    assert report["pages_with_bbox"] == 1
    assert report["extraction_methods"] == {"pymupdf": 2}
    assert report["element_counts"] == {"paragraph": 1, "image": 1}
    assert "acceptance_many_pages_need_ocr" in report["warnings"]
