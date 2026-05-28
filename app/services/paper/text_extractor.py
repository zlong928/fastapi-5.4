from __future__ import annotations

import re
from pathlib import Path

import fitz

from app.services.paper.models import ParsedPage, TextExtractionReport


class TextExtractor:
    """Extract text and page-level text from a PDF without writing database state."""

    def extract(self, source_path: Path) -> TextExtractionReport:
        pages: list[ParsedPage] = []
        try:
            with fitz.open(source_path) as pdf:
                for page in pdf:
                    page_text = page.get_text("text", sort=True).strip()
                    pages.append(ParsedPage(page_number=page.number + 1, text=self._clean_text(page_text)))
        except Exception as exc:
            return TextExtractionReport(status="failed", message=str(exc))

        text = "\n\n".join(page.text for page in pages if page.text).strip()
        if text:
            return TextExtractionReport(pages=pages, text=text, status="success", message=f"Extracted text from {len(pages)} pages.")
        if pages:
            return TextExtractionReport(pages=pages, text="", status="partial", message="PDF pages were readable but no embedded text was found.")
        return TextExtractionReport(status="failed", message="PDF has no pages.")

    def _clean_text(self, text: str) -> str:
        cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in cleaned_lines if line)
