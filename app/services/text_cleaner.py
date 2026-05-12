from __future__ import annotations

import re
from dataclasses import dataclass, field


LIGATURES = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}


@dataclass(slots=True)
class CleanedDocument:
    raw_text: str
    cleaned_text: str
    references_text: str | None
    captions: list[str]
    quality: dict[str, int | bool]


class TextCleaner:
    def clean_pages(self, pages: list[str]) -> CleanedDocument:
        raw_text = "\n\n".join(page.strip() for page in pages if page.strip())
        page_lines = [self._strip_repeated_edges(page.splitlines(), pages) for page in pages]
        text = "\n\n".join("\n".join(lines) for lines in page_lines)
        text = self._repair_text(text)
        body_text, references_text = self._split_references(text)
        body_text, captions = self._extract_captions(body_text)
        cleaned_text = self._normalize_paragraphs(body_text)
        references_text = self._normalize_paragraphs(references_text) if references_text else None

        return CleanedDocument(
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            references_text=references_text,
            captions=captions,
            quality={
                "raw_chars": len(raw_text),
                "cleaned_chars": len(cleaned_text),
                "page_count": len(pages),
                "caption_count": len(captions),
                "has_references": bool(references_text),
                "ocr_used": False,
            },
        )

    def _repair_text(self, text: str) -> str:
        for source, replacement in LIGATURES.items():
            text = text.replace(source, replacement)
        text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
        return text

    def _normalize_paragraphs(self, text: str) -> str:
        paragraphs = []
        for paragraph in re.split(r"\n\s*\n", text):
            normalized = re.sub(r"\s*\n\s*", " ", paragraph)
            normalized = re.sub(r"[ \t]+", " ", normalized).strip()
            if normalized:
                paragraphs.append(normalized)
        return "\n\n".join(paragraphs)

    def _split_references(self, text: str) -> tuple[str, str | None]:
        match = re.search(r"(?im)^\s*(references|bibliography|参考文献)\s*$", text)
        if not match:
            return text, None
        return text[: match.start()].strip(), text[match.end() :].strip() or None

    def _extract_captions(self, text: str) -> tuple[str, list[str]]:
        captions: list[str] = []
        body_lines: list[str] = []
        caption_pattern = re.compile(r"^\s*((fig\.|figure|table)\s+\d+[\w.:-]*\s+.+)$", re.IGNORECASE)
        for line in text.splitlines():
            match = caption_pattern.match(line.strip())
            if match:
                captions.append(match.group(1).strip())
            else:
                body_lines.append(line)
        return "\n".join(body_lines), captions

    def _strip_repeated_edges(self, lines: list[str], pages: list[str]) -> list[str]:
        stripped = [line.strip() for line in lines if line.strip()]
        if len(pages) < 2 or not stripped:
            return stripped
        headers = self._repeated_edge_values(pages, edge="head")
        footers = self._repeated_edge_values(pages, edge="tail")
        return [line for line in stripped if line not in headers and line not in footers]

    def _repeated_edge_values(self, pages: list[str], edge: str) -> set[str]:
        counts: dict[str, int] = {}
        for page in pages:
            lines = [line.strip() for line in page.splitlines() if line.strip()]
            candidates = lines[:2] if edge == "head" else lines[-2:]
            for line in candidates:
                normalized = re.sub(r"\d+", "", line).strip()
                if normalized:
                    counts[normalized] = counts.get(normalized, 0) + 1
        threshold = max(2, int(len(pages) * 0.6))
        repeated = {line for line, count in counts.items() if count >= threshold}
        values: set[str] = set()
        for page in pages:
            lines = [line.strip() for line in page.splitlines() if line.strip()]
            candidates = lines[:2] if edge == "head" else lines[-2:]
            for line in candidates:
                if re.sub(r"\d+", "", line).strip() in repeated:
                    values.add(line)
        return values
