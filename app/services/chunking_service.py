from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChunkInput:
    chunk_type: str
    text: str
    cleaned_text: str
    chunk_index: int
    char_start: int | None = None
    char_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None


class ChunkingService:
    def chunk_document(
        self,
        cleaned_text: str,
        captions: list[str],
        references_text: str | None,
        chunk_size: int = 1200,
        overlap: int = 150,
    ) -> list[ChunkInput]:
        chunks = self._chunk_body(cleaned_text, chunk_size, overlap)
        for caption in captions:
            chunks.append(ChunkInput("caption", caption, caption, len(chunks)))
        if references_text:
            for reference in self._split_references(references_text):
                chunks.append(ChunkInput("reference", reference, reference, len(chunks)))
        return chunks

    def build_ocr_chunk(self, text: str, chunk_index: int, page_number: int | None = None) -> ChunkInput:
        return ChunkInput(
            chunk_type="ocr",
            text=text,
            cleaned_text=text,
            chunk_index=chunk_index,
            char_start=0,
            char_end=len(text),
            page_start=page_number,
            page_end=page_number,
        )

    def _chunk_body(self, text: str, chunk_size: int, overlap: int) -> list[ChunkInput]:
        chunks: list[ChunkInput] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            boundary = text.rfind("\n\n", start, end)
            if boundary > start + 400:
                end = boundary
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(ChunkInput("body", chunk_text, chunk_text, len(chunks), start, end))
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    def _split_references(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines or [text.strip()]
