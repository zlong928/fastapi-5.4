from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models import PaperTable
from app.services.paper.models import ParsedPage, TableExtractionReport

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency guard for old deployments
    pdfplumber = None  # type: ignore[assignment]


class TableExtractor:
    """Extract structured tables first, then degrade to text candidates."""

    def extract(self, *, paper_id: int, source_path: Path, pages: list[ParsedPage], existing_text: str) -> TableExtractionReport:
        tables = self._extract_with_pdfplumber(paper_id, source_path)
        if tables:
            return TableExtractionReport(tables=tables, status="success", source="pdfplumber", message=f"Extracted {len(tables)} structured tables.")

        candidates = self._table_candidates(paper_id, pages)
        if candidates:
            return TableExtractionReport(
                tables=candidates,
                status="fallback",
                source="fallback_candidate",
                message=f"Generated {len(candidates)} table candidates from page text.",
            )

        text_candidate = self._text_candidate(paper_id, pages, existing_text)
        if text_candidate is not None:
            return TableExtractionReport(
                tables=[text_candidate],
                status="partial",
                source="text_candidate",
                message="No structured table-like block was found; generated a text candidate.",
            )
        return TableExtractionReport(status="failed", source="none", message="No table or text candidate could be generated.")

    def _extract_with_pdfplumber(self, paper_id: int, source_path: Path) -> list[PaperTable]:
        if pdfplumber is None:
            return []
        tables: list[PaperTable] = []
        try:
            with pdfplumber.open(source_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    extracted_tables = page.extract_tables() or []
                    for rows in extracted_tables:
                        markdown = self._rows_to_markdown(rows)
                        if not markdown:
                            continue
                        tables.append(
                            PaperTable(
                                paper_id=paper_id,
                                table_label=f"Table {len(tables) + 1}",
                                content=markdown,
                                page=page_index,
                            )
                        )
                        if len(tables) >= 3:
                            return tables
        except Exception:
            return []
        return tables

    def _rows_to_markdown(self, rows: list[list[Any]] | None) -> str:
        if not rows:
            return ""
        cleaned_rows: list[list[str]] = []
        width = 0
        for row in rows:
            cells = [self._clean_cell(cell) for cell in (row or [])]
            if not any(cells):
                continue
            cleaned_rows.append(cells)
            width = max(width, len(cells))
        if not cleaned_rows or width < 2:
            return ""
        normalized = [row + [""] * (width - len(row)) for row in cleaned_rows[:40]]
        header = normalized[0]
        separator = ["---"] * width
        markdown_rows = [header, separator, *normalized[1:]]
        return "\n".join("| " + " | ".join(self._escape_markdown_cell(cell[:160]) for cell in row) + " |" for row in markdown_rows)[:4000]

    def _clean_cell(self, cell: Any) -> str:
        if cell is None:
            return ""
        return re.sub(r"\s+", " ", str(cell)).strip()

    def _escape_markdown_cell(self, cell: str) -> str:
        return cell.replace("|", "\\|")

    def _table_candidates(self, paper_id: int, pages: list[ParsedPage]) -> list[PaperTable]:
        candidates: list[tuple[int, str]] = []
        for page in pages:
            for block in self._candidate_blocks(page.text):
                candidates.append((page.page_number, block))
        return [
            PaperTable(
                paper_id=paper_id,
                table_label=f"Table Candidate {index}",
                content=self._format_table_candidate(content),
                page=page_number,
            )
            for index, (page_number, content) in enumerate(candidates[:2], start=1)
        ]

    def _candidate_blocks(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        blocks: list[str] = []
        for index, line in enumerate(lines):
            lower = line.lower()
            digit_count = len(re.findall(r"\d", line))
            looks_tabular = digit_count >= 3 and len(re.split(r"\s{2,}|\t|,|;", line)) >= 2
            is_label = lower.startswith("table") or line.startswith("表")
            if is_label or looks_tabular:
                start = max(0, index - (0 if is_label else 2))
                end = min(len(lines), index + 8)
                block = "\n".join(lines[start:end])
                if len(block) >= 40:
                    blocks.append(block)
        unique: list[str] = []
        for block in blocks:
            if block not in unique:
                unique.append(block)
        return unique

    def _format_table_candidate(self, content: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) < 2:
            return content[:1200]
        split_rows = [re.split(r"\s{2,}|\t", line) for line in lines]
        if max(len(row) for row in split_rows) >= 2:
            width = max(len(row) for row in split_rows)
            normalized = [row + [""] * (width - len(row)) for row in split_rows[:8]]
            header = normalized[0]
            separator = ["---"] * width
            markdown_rows = [header, separator, *normalized[1:]]
            return "\n".join("| " + " | ".join(cell[:80] for cell in row) + " |" for row in markdown_rows)[:1600]
        return "\n".join(lines[:10])[:1600]

    def _text_candidate(self, paper_id: int, pages: list[ParsedPage], existing_text: str) -> PaperTable | None:
        fallback_text = pages[0].text[:1200] if pages and pages[0].text.strip() else existing_text[:1200]
        if not fallback_text.strip():
            return None
        return PaperTable(
            paper_id=paper_id,
            table_label="Text Candidate 1",
            content=fallback_text[:1200],
            page=pages[0].page_number if pages else 1,
        )
