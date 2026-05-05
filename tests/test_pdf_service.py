from pathlib import Path

import pytest

from app.services.pdf_service import PdfParseError, PdfService


def _write_pdf(path: Path, lines: list[str]) -> Path:
    body = "\n".join(f"({line}) Tj" for line in lines)
    path.write_bytes(f"%PDF-1.4\nBT\n{body}\nET\n%%EOF\n".encode("latin-1"))
    return path


def test_analyze_pdf_extracts_required_fields(tmp_path):
    pdf_path = _write_pdf(
        tmp_path / "paper.pdf",
        [
            "Research Title.",
            "Abstract: This abstract explains the paper.",
            "The body starts here and should appear in the preview.",
        ],
    )

    result = PdfService().analyze_pdf(pdf_path)

    assert result.file_name == "paper.pdf"
    assert result.file_type == "pdf"
    assert result.title == "Research Title."
    assert result.abstract == "This abstract explains the paper. The body starts here and should appear in the preview."
    assert "The body starts here" in result.body_preview


def test_analyze_pdf_rejects_corrupt_pdf(tmp_path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not actually a pdf")

    with pytest.raises(PdfParseError, match="Invalid PDF header"):
        PdfService().analyze_pdf(corrupt)


def test_analyze_pdf_rejects_header_only_pdf(tmp_path):
    corrupt = tmp_path / "header-only.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nthis is not a readable document")

    with pytest.raises(PdfParseError, match="No extractable text"):
        PdfService().analyze_pdf(corrupt)
