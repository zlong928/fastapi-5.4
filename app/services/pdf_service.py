from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import perf_counter

from pypdf import PdfReader


@dataclass(slots=True)
class PdfAnalysis:
    file_name: str
    file_size: int
    file_type: str
    processing_time_ms: float
    title: str
    abstract: str
    body_preview: str


class PdfParseError(RuntimeError):
    pass


class PdfService:
    def analyze_pdf(self, path: Path) -> PdfAnalysis:
        started = perf_counter()
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF"):
            raise PdfParseError("Invalid PDF header.")

        text = self._extract_text(raw)
        if not text:
            raise PdfParseError("No extractable text found in PDF.")

        title = self._extract_title(text, path)
        abstract = self._extract_abstract(text)
        body_preview = self._preview(text)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        return PdfAnalysis(
            file_name=path.name,
            file_size=path.stat().st_size,
            file_type="pdf",
            processing_time_ms=elapsed_ms,
            title=title,
            abstract=abstract,
            body_preview=body_preview,
        )

    def _extract_text(self, raw: bytes) -> str:
        library_text = self._extract_with_pypdf(raw)
        if library_text:
            return library_text

        decoded = raw.decode("latin-1", errors="ignore")
        strings = re.findall(r"\(([^()]*)\)\s*Tj", decoded)
        arrays = re.findall(r"\[(.*?)\]\s*TJ", decoded, flags=re.DOTALL)
        for array in arrays:
            strings.extend(re.findall(r"\(([^()]*)\)", array))

        if strings:
            return self._normalize(" ".join(self._unescape_pdf_text(value) for value in strings))

        return ""

    def _extract_with_pypdf(self, raw: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(raw))
        except Exception:
            return ""

        page_text: list[str] = []
        for page in reader.pages:
            try:
                extracted = page.extract_text() or ""
            except Exception:
                extracted = ""
            if extracted:
                page_text.append(extracted)
        return self._normalize(" ".join(page_text))

    def _extract_title(self, text: str, path: Path) -> str:
        for line in self._sentences(text):
            cleaned = line.strip(" :-")
            if cleaned:
                return cleaned[:120]
        return path.stem

    def _extract_abstract(self, text: str) -> str:
        match = re.search(r"\babstract\b[:\s-]*(.*?)(?:\bintroduction\b|\n\n|$)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            abstract = self._normalize(match.group(1))
            if abstract:
                return abstract[:500]
        sentences = self._sentences(text)
        return " ".join(sentences[1:3])[:500] if len(sentences) > 1 else ""

    def _preview(self, text: str) -> str:
        return text[:500]

    def _sentences(self, text: str) -> list[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _unescape_pdf_text(self, text: str) -> str:
        return (
            text.replace(r"\(", "(")
            .replace(r"\)", ")")
            .replace(r"\\", "\\")
            .replace(r"\n", " ")
            .replace(r"\r", " ")
            .replace(r"\t", " ")
        )
