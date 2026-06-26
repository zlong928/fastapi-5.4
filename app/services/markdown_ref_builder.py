"""Markdown Reference Builder (MRFBuilder).

Parses MinerU-generated Markdown into a structured representation that the
classification and extraction pipelines can consume:

- **Sections**: heading hierarchy with associated text content.
- **Image references**: from ``![...](path)`` syntax, with caption, alt text,
  nearby text context, and parent section.
- **Tables**: Markdown tables detected in the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Regex for markdown image references: ![alt](path)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Regex for markdown headings
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# Regex for figure/table label patterns: "Figure 1", "Fig. 2a", "Table 3"
_LABEL_RE = re.compile(r"(?i)\b((?:fig(?:ure)?|table)\.?\s*\d+[a-z]?)\b")

# Regex for page markers in MinerU output
_PAGE_MARKER_RE = re.compile(
    r"^(?:#{1,3}\s*)?(?:page\s*(\d+)|\[page\s*(\d+)\])", re.IGNORECASE
)


@dataclass
class MarkdownSection:
    """A section of the markdown document (heading + body)."""

    level: int  # heading level (1-6)
    heading: str  # heading text without #
    body: str  # all text under this heading until the next same-or-higher heading
    start_line: int
    end_line: int
    subsections: list[MarkdownSection] = field(default_factory=list)


@dataclass
class MarkdownImageRef:
    """An image reference found in the markdown."""

    alt_text: str  # text inside [...]
    image_path: str  # path inside (...)
    caption: str  # cleaned caption (alt text without label prefix)
    label: str | None  # "Figure 1", "Fig. 2a", etc.
    page_number: int | None  # derived from page markers
    section_heading: str  # parent section heading
    nearby_text: str  # text from surrounding lines
    line_index: int  # line number in the original markdown
    context_before: str  # text before the image (up to 300 chars)
    context_after: str  # text after the image (up to 300 chars)


@dataclass
class MarkdownTable:
    """A markdown table extracted from the text."""

    headers: list[str]
    rows: list[list[str]]
    caption: str | None  # text immediately before/after the table
    label: str | None  # "Table 1", etc.
    page_number: int | None
    section_heading: str
    line_start: int
    line_end: int


@dataclass
class MarkdownDocument:
    """Structured representation of a MinerU Markdown document."""

    sections: list[MarkdownSection]
    images: list[MarkdownImageRef]
    tables: list[MarkdownTable]
    full_text: str
    page_count: int | None

    def text_by_section(self, heading: str) -> str:
        """Return all text under a given section heading."""
        for section in self.sections:
            if section.heading == heading:
                return section.body
            for sub in section.subsections:
                if sub.heading == heading:
                    return sub.body
        return ""

    def images_by_section(self, heading: str) -> list[MarkdownImageRef]:
        """Return images that belong to a given section."""
        return [img for img in self.images if img.section_heading == heading]

    def images_by_label(self) -> dict[str, MarkdownImageRef]:
        """Return a mapping from figure label to image ref."""
        result: dict[str, MarkdownImageRef] = {}
        for img in self.images:
            if img.label:
                result[img.label] = img
        return result

    def tables_by_label(self) -> dict[str, MarkdownTable]:
        """Return a mapping from table label to table."""
        result: dict[str, MarkdownTable] = {}
        for tbl in self.tables:
            if tbl.label:
                result[tbl.label] = tbl
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for LLM prompts."""
        return {
            "sections": [
                {
                    "heading": s.heading,
                    "level": s.level,
                    "body_preview": s.body[:500],
                    "body_length": len(s.body),
                    "image_count": len(self.images_by_section(s.heading)),
                    "table_count": len(
                        [t for t in self.tables if t.section_heading == s.heading]
                    ),
                }
                for s in self.sections
            ],
            "images": [
                {
                    "label": img.label,
                    "caption": img.caption,
                    "alt_text": img.alt_text,
                    "image_path": img.image_path,
                    "page_number": img.page_number,
                    "section": img.section_heading,
                    "nearby_text": img.nearby_text[:300],
                }
                for img in self.images
            ],
            "tables": [
                {
                    "label": tbl.label,
                    "caption": tbl.caption,
                    "headers": tbl.headers,
                    "row_count": len(tbl.rows),
                    "page_number": tbl.page_number,
                    "section": tbl.section_heading,
                    "sample_rows": tbl.rows[:5],
                }
                for tbl in self.tables
            ],
            "page_count": self.page_count,
        }


class MRFBuilder:
    """Build a structured ``MarkdownDocument`` from MinerU Markdown text."""

    def build(self, markdown_text: str) -> MarkdownDocument:
        """Parse MinerU Markdown into a structured document."""
        lines = markdown_text.splitlines()
        page_map = self._build_page_map(lines)
        section_map = self._build_section_map(lines)

        # Extract sections
        sections = self._extract_sections(lines)

        # Extract image references
        images = self._extract_images(lines, page_map, section_map)

        # Extract tables
        tables = self._extract_tables(lines, page_map, section_map)

        # Page count from page markers
        page_numbers = {v for v in page_map.values() if v is not None}
        page_count = max(page_numbers) if page_numbers else None

        return MarkdownDocument(
            sections=sections,
            images=images,
            tables=tables,
            full_text=markdown_text,
            page_count=page_count,
        )

    # ------------------------------------------------------------------
    # Section extraction
    # ------------------------------------------------------------------

    def _extract_sections(self, lines: list[str]) -> list[MarkdownSection]:
        """Extract heading hierarchy from markdown lines."""
        # Find all heading lines
        heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, text)
        for i, line in enumerate(lines):
            m = _MD_HEADING_RE.match(line.strip())
            if m:
                level = len(m.group(1))
                text = m.group(2).strip()
                heading_positions.append((i, level, text))

        if not heading_positions:
            # No headings — treat entire document as one section
            return [
                MarkdownSection(
                    level=1,
                    heading="",
                    body="\n".join(lines),
                    start_line=0,
                    end_line=len(lines) - 1,
                )
            ]

        sections: list[MarkdownSection] = []
        for idx, (line_idx, level, heading) in enumerate(heading_positions):
            # Body goes from this line+1 to the next heading line (or end)
            next_line = (
                heading_positions[idx + 1][0]
                if idx + 1 < len(heading_positions)
                else len(lines)
            )
            body_lines = lines[line_idx + 1 : next_line]
            body = "\n".join(body_lines).strip()

            section = MarkdownSection(
                level=level,
                heading=heading,
                body=body,
                start_line=line_idx,
                end_line=next_line - 1,
            )
            sections.append(section)

        return sections

    # ------------------------------------------------------------------
    # Image extraction
    # ------------------------------------------------------------------

    def _extract_images(
        self,
        lines: list[str],
        page_map: dict[int, int | None],
        section_map: dict[int, str],
    ) -> list[MarkdownImageRef]:
        """Extract all image references from markdown."""
        images: list[MarkdownImageRef] = []

        for line_idx, line in enumerate(lines):
            for match in _MD_IMAGE_RE.finditer(line):
                alt_text = match.group(1).strip()
                img_path = match.group(2).strip()

                label = self._extract_label(alt_text)
                caption = self._build_caption(alt_text, label)

                # Nearby text (surrounding non-image lines)
                nearby_parts: list[str] = []
                for offset in range(-3, 4):
                    if offset == 0:
                        continue
                    ni = line_idx + offset
                    if 0 <= ni < len(lines):
                        neighbor = lines[ni].strip()
                        if neighbor and not _MD_IMAGE_RE.search(neighbor):
                            nearby_parts.append(neighbor)
                nearby_text = " ".join(nearby_parts)

                # Context before/after
                context_before = "\n".join(
                    lines[max(0, line_idx - 8) : line_idx]
                ).strip()[:300]
                context_after = "\n".join(
                    lines[line_idx + 1 : min(len(lines), line_idx + 9)]
                ).strip()[:300]

                images.append(
                    MarkdownImageRef(
                        alt_text=alt_text,
                        image_path=img_path,
                        caption=caption,
                        label=label,
                        page_number=page_map.get(line_idx),
                        section_heading=section_map.get(line_idx, ""),
                        nearby_text=nearby_text[:500],
                        line_index=line_idx,
                        context_before=context_before,
                        context_after=context_after,
                    )
                )

        return images

    # ------------------------------------------------------------------
    # Table extraction
    # ------------------------------------------------------------------

    def _extract_tables(
        self,
        lines: list[str],
        page_map: dict[int, int | None],
        section_map: dict[int, str],
    ) -> list[MarkdownTable]:
        """Extract markdown tables."""
        tables: list[MarkdownTable] = []

        # Find table blocks: consecutive lines starting and ending with |
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("|") and line.endswith("|"):
                # Start of a table block
                start = i
                table_lines: list[str] = []
                while i < len(lines):
                    curr = lines[i].strip()
                    if not (curr.startswith("|") and curr.endswith("|")):
                        break
                    table_lines.append(curr)
                    i += 1
                end = i - 1

                if len(table_lines) >= 2:
                    headers, rows = self._parse_table_lines(table_lines)
                    if headers:
                        # Look for caption before or after the table
                        caption = self._find_table_caption(lines, start, end)
                        label = self._extract_label(caption or "")

                        tables.append(
                            MarkdownTable(
                                headers=headers,
                                rows=rows,
                                caption=caption,
                                label=label,
                                page_number=page_map.get(start),
                                section_heading=section_map.get(start, ""),
                                line_start=start,
                                line_end=end,
                            )
                        )
            i += 1

        return tables

    def _parse_table_lines(
        self, table_lines: list[str]
    ) -> tuple[list[str], list[list[str]]]:
        """Parse markdown table lines into headers and rows."""
        if len(table_lines) < 2:
            return [], []

        # First line is header
        headers = [
            cell.strip() for cell in table_lines[0].strip("|").split("|")
        ]

        # Skip separator line (|---|---|)
        data_start = 1
        if data_start < len(table_lines) and all(
            re.fullmatch(r":?-{3,}:?", cell.strip() or "")
            for cell in table_lines[data_start].strip("|").split("|")
        ):
            data_start = 2

        rows: list[list[str]] = []
        for line in table_lines[data_start:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells:
                rows.append(cells)

        return headers, rows

    def _find_table_caption(
        self, lines: list[str], table_start: int, table_end: int
    ) -> str | None:
        """Find a caption (like 'Table 1: ...') near the table block."""
        # Check line before
        if table_start > 0:
            before = lines[table_start - 1].strip()
            if before and not before.startswith("#") and "|" not in before:
                if re.search(r"(?i)\btable\b", before):
                    return before
        # Check line after
        if table_end + 1 < len(lines):
            after = lines[table_end + 1].strip()
            if after and not after.startswith("#") and "|" not in after:
                return after
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_label(text: str) -> str | None:
        """Extract 'Figure 3' or 'Table 2' from text."""
        match = _LABEL_RE.search(text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _build_caption(alt_text: str, label: str | None) -> str:
        """Build clean caption by stripping label prefix (case-insensitive)."""
        if not alt_text:
            return ""
        if label:
            pattern = re.compile(
                r"^" + re.escape(label) + r"[:\s.\-—]+\s*",
                re.IGNORECASE,
            )
            cleaned = pattern.sub("", alt_text).strip()
            return cleaned if cleaned else alt_text
        return alt_text

    @staticmethod
    def _build_page_map(lines: list[str]) -> dict[int, int | None]:
        """Map line indices to page numbers."""
        page_map: dict[int, int | None] = {}
        current_page: int | None = None
        for i, line in enumerate(lines):
            m = _PAGE_MARKER_RE.search(line.strip())
            if m:
                page_str = m.group(1) or m.group(2)
                try:
                    current_page = int(page_str)
                except (TypeError, ValueError):
                    pass
            page_map[i] = current_page
        return page_map

    @staticmethod
    def _build_section_map(lines: list[str]) -> dict[int, str]:
        """Map line indices to the current section heading."""
        section_map: dict[int, str] = {}
        current_section = ""
        for i, line in enumerate(lines):
            m = _MD_HEADING_RE.match(line.strip())
            if m:
                heading = m.group(2).strip()
                if heading:
                    current_section = heading
            section_map[i] = current_section
        return section_map
