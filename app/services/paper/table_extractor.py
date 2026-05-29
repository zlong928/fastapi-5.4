from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.models import PaperTable
from app.services.paper.models import ParsedPage, TableExtractionReport

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency guard for old deployments
    pdfplumber = None  # type: ignore[assignment]


TABLE_LABEL_RE = re.compile(
    r"(?i)\b((?:supplementary\s+)?table\s+(?:\d+[a-z]?|[ivxlcdm]+)|表\s*\d+[a-z]?)\b"
)
FIGURE_LABEL_RE = re.compile(r"(?i)\b(?:fig(?:ure)?\.?|图)\s*\d+[a-z]?\b")
METADATA_EXCLUSION_TERMS = (
    "received:",
    "accepted:",
    "check for updates",
    "nature communications",
    "correspondence",
    "author information",
    "doi",
    "https://doi.org",
    "www.",
    "downloaded",
    "research article",
    "science advances",
    "advancedsciencenews",
    "advmat.de",
    "nature communications",
    "abstract",
    "affiliations",
)
VALUE_OR_UNIT_RE = re.compile(
    r"(?i)(\d|%|mg|g/l|g\s*l-?1|ml|mmol|mol|µm|μm|um|nm|cm|mm|h\b|day|days|°c|kpa|mpa)"
)


class TableExtractor:
    """Extract structured tables first, then use conservative table candidates."""

    def __init__(self, *, max_tables: int = 10) -> None:
        self.max_tables = max_tables

    def extract(self, *, paper_id: int, source_path: Path, pages: list[ParsedPage], existing_text: str) -> TableExtractionReport:
        tables = self._extract_with_pdfplumber(paper_id, source_path, pages)
        if tables:
            return TableExtractionReport(tables=tables, status="success", source="pdfplumber", message=f"Extracted {len(tables)} structured tables.")

        candidates = self._table_candidates(paper_id, pages)
        if candidates:
            return TableExtractionReport(
                tables=candidates,
                status="fallback",
                source="fallback_candidate",
                message=f"Generated {len(candidates)} table candidates from explicit table labels.",
            )

        weak_candidates = self._weak_table_candidates(paper_id, pages)
        if weak_candidates:
            return TableExtractionReport(
                tables=weak_candidates,
                status="partial",
                source="weak_table_candidate",
                message=f"Generated {len(weak_candidates)} weak table candidates from stable column text.",
            )

        return TableExtractionReport(tables=[], status="failed", source="none", message="No reliable table found in this PDF.")

    def _extract_with_pdfplumber(self, paper_id: int, source_path: Path, pages: list[ParsedPage]) -> list[PaperTable]:
        if pdfplumber is None:
            return []
        tables: list[PaperTable] = []
        seen_contents: set[str] = set()
        page_text_map = {page.page_number: page.text for page in pages}
        try:
            with pdfplumber.open(source_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    page_text = page_text_map.get(page_index, "")
                    if not page_text:
                        try:
                            page_text = page.extract_text() or ""
                        except Exception:
                            page_text = ""
                    for rows in self._pdfplumber_tables(page):
                        if not self._validate_structured_table(rows, page_text, page_index):
                            continue
                        markdown = self._rows_to_markdown(rows)
                        if not markdown or markdown in seen_contents:
                            continue
                        seen_contents.add(markdown)
                        table_label = self._table_label_for_page(page_text) or f"Table {len(tables) + 1}"
                        tables.append(
                            PaperTable(
                                paper_id=paper_id,
                                table_label=table_label,
                                content=markdown,
                                page=page_index,
                            )
                        )
                        if len(tables) >= self.max_tables:
                            return tables
        except Exception:
            return []
        return tables

    def _pdfplumber_tables(self, page: Any) -> list[list[list[Any]]]:
        strategies: list[dict[str, Any] | None] = [
            None,
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
            {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "intersection_tolerance": 3,
                "min_words_vertical": 2,
                "min_words_horizontal": 1,
            },
        ]
        extracted: list[list[list[Any]]] = []
        for settings in strategies:
            try:
                tables = page.extract_tables(table_settings=settings) if settings else page.extract_tables()
            except Exception:
                tables = []
            extracted.extend(tables or [])
        return extracted

    def _validate_structured_table(self, rows: list[list[Any]] | None, page_text: str, page_index: int) -> bool:
        cleaned_rows = self._clean_rows(rows)
        if len(cleaned_rows) < 3:
            return False

        widths = [len(row) for row in cleaned_rows]
        main_width, stable_count = Counter(widths).most_common(1)[0]
        if main_width < 2:
            return False

        stable_ratio = stable_count / max(1, len(widths))
        near_width_ratio = sum(1 for width in widths if abs(width - main_width) <= 1) / max(1, len(widths))
        if near_width_ratio < 0.6:
            return False

        table_text = " ".join(" ".join(row) for row in cleaned_rows)
        if self._metadata_term_count(table_text) >= 2:
            return False
        if self._looks_like_article_scaffold(table_text):
            return False
        if self._metadata_term_count(page_text) >= 4 and page_index == 1 and not self._page_has_table_caption(page_text):
            return False
        if self._broken_cell_ratio(rows) > 0.35:
            return False

        cells = [cell for row in cleaned_rows for cell in row if cell]
        if not cells:
            return False

        short_fragment_ratio = sum(1 for cell in cells if self._word_count(cell) <= 3) / len(cells)
        numeric_rows = sum(1 for row in cleaned_rows if VALUE_OR_UNIT_RE.search(" ".join(row)))
        numeric_cells = sum(1 for cell in cells if VALUE_OR_UNIT_RE.search(cell))
        numeric_cell_ratio = numeric_cells / len(cells)
        has_caption = self._page_has_table_caption(page_text)
        if not has_caption and self._looks_like_reference_fragment(cleaned_rows, table_text):
            return False

        if short_fragment_ratio > 0.75 and numeric_cell_ratio < 0.25 and not has_caption:
            return False

        if has_caption:
            return stable_ratio >= 0.5 or near_width_ratio >= 0.7

        if page_index == 1 and stable_ratio < 0.85:
            return False

        has_obvious_numeric_structure = numeric_rows >= 2 and (numeric_cells >= 3 or any(VALUE_OR_UNIT_RE.search(cell) for cell in cells))
        return near_width_ratio >= 0.8 and stable_ratio >= 0.6 and has_obvious_numeric_structure

    def _rows_to_markdown(self, rows: list[list[Any]] | None) -> str:
        cleaned_rows: list[list[str]] = []
        width = 0
        for cells in self._clean_rows(rows):
            cleaned_rows.append(cells)
            width = max(width, len(cells))
        if len(cleaned_rows) < 2 or width < 2:
            return ""
        populated_columns = 0
        for index in range(width):
            if any(index < len(row) and row[index] for row in cleaned_rows):
                populated_columns += 1
        if populated_columns < 2:
            return ""
        normalized = [row + [""] * (width - len(row)) for row in cleaned_rows[:40]]
        header = normalized[0]
        separator = ["---"] * width
        markdown_rows = [header, separator, *normalized[1:]]
        return "\n".join("| " + " | ".join(self._escape_markdown_cell(cell[:160]) for cell in row) + " |" for row in markdown_rows)[:4000]

    def _clean_rows(self, rows: list[list[Any]] | None) -> list[list[str]]:
        cleaned_rows: list[list[str]] = []
        if not rows:
            return cleaned_rows
        for row in rows:
            cells = [self._clean_cell(cell) for cell in (row or [])]
            while cells and not cells[-1]:
                cells.pop()
            if not any(cells):
                continue
            cleaned_rows.append(cells)
        return cleaned_rows

    def _clean_cell(self, cell: Any) -> str:
        if cell is None:
            return ""
        return re.sub(r"\s+", " ", str(cell)).strip()

    def _escape_markdown_cell(self, cell: str) -> str:
        return cell.replace("|", "\\|")

    def _table_candidates(self, paper_id: int, pages: list[ParsedPage]) -> list[PaperTable]:
        candidates: list[tuple[int, str, str]] = []
        for page in pages:
            for label, block in self._explicit_table_blocks(page.text):
                candidates.append((page.page_number, label, block))
        return [
            PaperTable(
                paper_id=paper_id,
                table_label=label,
                content=self._format_table_candidate(content),
                page=page_number,
            )
            for page_number, label, content in candidates[: self.max_tables]
        ]

    def _explicit_table_blocks(self, text: str) -> list[tuple[str, str]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        blocks: list[tuple[str, str]] = []
        for index, line in enumerate(lines):
            match = TABLE_LABEL_RE.search(line)
            if not match or not self._looks_like_table_caption_line(line, match):
                continue
            label = self._normalize_table_label(match.group(1))
            end = min(len(lines), index + 12)
            for cursor in range(index + 1, end):
                if cursor > index + 1 and (TABLE_LABEL_RE.search(lines[cursor]) or FIGURE_LABEL_RE.search(lines[cursor])):
                    end = cursor
                    break
            block_lines = lines[index:end]
            block = "\n".join(block_lines)
            if len(block) >= len(label):
                blocks.append((label, block))
        unique: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for label, block in blocks:
            key = (label.lower(), block)
            if key in seen:
                continue
            seen.add(key)
            unique.append((label, block))
        return unique

    def _format_table_candidate(self, content: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return "\n".join(lines[:12])[:1600] if lines else content[:1200]

    def _weak_table_candidates(self, paper_id: int, pages: list[ParsedPage]) -> list[PaperTable]:
        candidates: list[tuple[int, str]] = []
        for page in pages:
            for block in self._stable_table_blocks(page.text, page.page_number):
                candidates.append((page.page_number, block))
        return [
            PaperTable(
                paper_id=paper_id,
                table_label=f"Detected Table-like Block {index}",
                content=content,
                page=page_number,
            )
            for index, (page_number, content) in enumerate(candidates[: self.max_tables], start=1)
        ]

    def _stable_table_blocks(self, text: str, page_number: int) -> list[str]:
        if page_number == 1 and not self._page_has_table_caption(text):
            return []

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        blocks: list[str] = []
        current: list[str] = []

        for line in lines:
            if self._is_metadata_line(line) or TABLE_LABEL_RE.search(line) or FIGURE_LABEL_RE.search(line):
                if self._is_stable_table_block(current):
                    blocks.append("\n".join(current[:12])[:1600])
                current = []
                continue

            columns = self._split_columns(line)
            if len(columns) >= 2:
                current.append(line)
                continue

            if self._is_stable_table_block(current):
                blocks.append("\n".join(current[:12])[:1600])
            current = []

        if self._is_stable_table_block(current):
            blocks.append("\n".join(current[:12])[:1600])

        unique: list[str] = []
        for block in blocks:
            if block not in unique:
                unique.append(block)
        return unique

    def _is_stable_table_block(self, lines: list[str]) -> bool:
        if len(lines) < 3:
            return False
        if any(self._is_metadata_line(line) for line in lines):
            return False

        rows = [self._split_columns(line) for line in lines]
        if any(len(row) < 2 for row in rows):
            return False

        widths = [len(row) for row in rows]
        most_common_width, stable_count = Counter(widths).most_common(1)[0]
        if most_common_width < 2 or stable_count < 3:
            return False
        if stable_count / len(widths) < 0.75:
            return False

        numeric_rows = sum(1 for row in rows if VALUE_OR_UNIT_RE.search(" ".join(row)))
        return numeric_rows >= 2

    def _split_columns(self, line: str) -> list[str]:
        if "|" in line:
            return [part.strip() for part in line.strip("|").split("|") if part.strip()]
        return [part.strip() for part in re.split(r"\s{2,}|\t", line) if part.strip()]

    def _is_metadata_line(self, line: str) -> bool:
        lower = line.lower()
        return any(term in lower for term in METADATA_EXCLUSION_TERMS)

    def _metadata_term_count(self, text: str) -> int:
        lower = text.lower()
        return sum(1 for term in METADATA_EXCLUSION_TERMS if term in lower)

    def _looks_like_article_scaffold(self, text: str) -> bool:
        lower = text.lower()
        if FIGURE_LABEL_RE.search(text):
            return True
        scaffold_terms = ("article", "downloaded from", "https://doi.org", "www.", "research article")
        return sum(1 for term in scaffold_terms if term in lower) >= 2

    def _looks_like_reference_fragment(self, rows: list[list[str]], text: str) -> bool:
        citation_number_cells = sum(1 for row in rows for cell in row if re.match(r"^\s*\d{1,3}\.\s*$", cell))
        if citation_number_cells >= 2:
            return True

        lower = text.lower()
        reference_terms = (
            "references",
            "data availability",
            "supporting the findings",
            " et al",
            "adv.",
            "mater.",
            "nat.",
            "proc.",
            "journal",
        )
        return sum(1 for term in reference_terms if term in lower) >= 2

    def _broken_cell_ratio(self, rows: list[list[Any]] | None) -> float:
        cells = [str(cell) for row in (rows or []) for cell in (row or []) if cell is not None and str(cell).strip()]
        if not cells:
            return 0.0
        broken = 0
        for cell in cells:
            if cell.count("\n") >= 2 or re.search(r"[A-Za-z]-\s*\n\s*[a-z]", cell):
                broken += 1
        return broken / len(cells)

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"[\w%µμ°.-]+", text))

    def _page_has_table_caption(self, page_text: str) -> bool:
        return self._table_label_for_page(page_text) is not None

    def _table_label_for_page(self, page_text: str) -> str | None:
        for raw_line in (page_text or "").splitlines():
            line = raw_line.strip()
            if not line or self._is_metadata_line(line):
                continue
            match = TABLE_LABEL_RE.search(line)
            if not match or not self._looks_like_table_caption_line(line, match):
                continue
            return self._normalize_table_label(match.group(1))
        return None

    def _looks_like_table_caption_line(self, line: str, match: re.Match[str]) -> bool:
        if match.start() > 8:
            return False
        following = line[match.end() :].lstrip()
        if following.startswith((")", "]", ",", ";")):
            return False
        if following.lower().startswith(("and ", "or ", "in ", "for ", "with ")):
            return False
        return True

    def _normalize_table_label(self, label: str) -> str:
        return re.sub(r"\s+", " ", label).strip()
