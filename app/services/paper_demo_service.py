from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, DocumentAsset, DocumentEvent, PaperTable
from app.services.file_storage import FileStorageService

try:  # pdfplumber is preferred for table extraction, but the demo must degrade safely.
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency guard for old deployments
    pdfplumber = None  # type: ignore[assignment]


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str


class PaperDemoService:
    """Paper-specific enhancement built on the existing Document model.

    This service intentionally does not create a separate papers table and does
    not own the core upload/parse lifecycle. The normal document pipeline keeps
    using documents.status = pending/processing/done/failed. This service only
    enriches an already uploaded PDF document with demo-ready figures/snapshots
    and table candidates for Agent extraction.
    """

    def __init__(self, db: Session, file_storage: FileStorageService | None = None) -> None:
        self.db = db
        self.file_storage = file_storage or FileStorageService()

    def parse(self, paper: Document) -> Document:
        if paper.source_type != "pdf":
            raise ValueError("仅支持 PDF 文档进行论文增强解析")
        if paper.status != "done":
            raise ValueError("文档解析完成后才能进行论文增强解析")

        source_path = self.file_storage.get_file_path(paper.original_file_path)
        if not source_path.exists():
            raise FileNotFoundError("源 PDF 文件不存在")

        try:
            pages = self._extract_pages(source_path)
            text = "\n\n".join(page.text for page in pages if page.text.strip()).strip()
            if text.strip():
                paper.parsed_text = paper.parsed_text or text
                paper.cleaned_text = paper.cleaned_text or text
            elif not (paper.cleaned_text or paper.parsed_text):
                paper.parsed_text = "当前 PDF 未解析到可抽取正文。"
                paper.cleaned_text = paper.parsed_text

            self.db.query(DocumentAsset).filter(
                DocumentAsset.document_id == paper.id,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            ).delete(synchronize_session=False)
            self.db.query(PaperTable).filter(PaperTable.paper_id == paper.id).delete(synchronize_session=False)

            figure_assets = self._extract_figures(source_path, paper, pages)
            if not figure_assets:
                image_path = self._save_first_page_snapshot(source_path, paper)
                figure_assets.append(
                    DocumentAsset(
                        document_id=paper.id,
                        asset_type="page_snapshot",
                        page_number=1,
                        file_path=image_path,
                        mime_type="image/png",
                        metadata_json=json.dumps(
                            {
                                "figure_label": "Page 1 Snapshot",
                                "caption": "Fallback page snapshot",
                                "context": "Fallback page snapshot generated for paper Agent extraction.",
                                "source": "fallback_snapshot",
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            for asset in figure_assets:
                self.db.add(asset)

            table_candidates = self._extract_tables_with_pdfplumber(paper.id, source_path)
            if not table_candidates:
                table_candidates = self._table_candidates(paper.id, pages, paper.cleaned_text or paper.parsed_text or "")
            for table in table_candidates:
                self.db.add(table)

            paper.fail_reason = None
            paper.error_message = None
            paper.parsed_at = paper.parsed_at or app_now()
            paper.updated_at = app_now()
            self._log_event(
                paper,
                "paper_assets_extracted",
                f"论文增强解析完成：图片/截图 {len(figure_assets)} 个，表格候选 {len(table_candidates)} 个。",
                {"figures": len(figure_assets), "tables": len(table_candidates)},
            )
            self.db.commit()
            self.db.refresh(paper)
            return paper
        except Exception as exc:
            self.db.rollback()
            paper = self.db.get(Document, paper.id)
            if paper is not None:
                self._log_event(paper, "paper_parse_enhanced_failed", str(exc), {"error": str(exc)})
                self.db.commit()
            raise

    def _extract_pages(self, source_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        with fitz.open(source_path) as pdf:
            for page in pdf:
                page_text = page.get_text("text", sort=True).strip()
                if page_text:
                    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in page_text.splitlines()]
                    cleaned = "\n".join(line for line in cleaned_lines if line)
                    pages.append(ParsedPage(page_number=page.number + 1, text=cleaned))
        return pages

    def _extract_figures(self, source_path: Path, paper: Document, pages: list[ParsedPage]) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        with fitz.open(source_path) as pdf:
            for page in pdf:
                for image_index, image in enumerate(page.get_images(full=True), start=1):
                    if len(assets) >= 3:
                        return assets
                    xref = image[0]
                    try:
                        pix = fitz.Pixmap(pdf, xref)
                        if pix.width < 120 or pix.height < 120:
                            continue
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        filename = f"page-{page.number + 1}-figure-{image_index}.png"
                        image_path = asset_dir / filename
                        pix.save(image_path)
                    except Exception:
                        continue
                    caption = self._caption_for_page(pages, page.number + 1, image_index)
                    label = self._figure_label(caption, len(assets) + 1)
                    assets.append(
                        DocumentAsset(
                            document_id=paper.id,
                            asset_type="figure",
                            page_number=page.number + 1,
                            file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
                            mime_type="image/png",
                            metadata_json=json.dumps(
                                {
                                    "figure_label": label,
                                    "caption": caption,
                                    "context": caption,
                                    "source": "extracted_image",
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
        return assets

    def _save_first_page_snapshot(self, source_path: Path, paper: Document) -> str:
        asset_dir = self._asset_dir(paper)
        image_path = asset_dir / "page-1.png"
        with fitz.open(source_path) as pdf:
            if pdf.page_count == 0:
                raise ValueError("PDF 没有页面")
            pix = pdf[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(image_path)
        return image_path.relative_to(self.file_storage.upload_dir).as_posix()

    def _asset_dir(self, paper: Document) -> Path:
        asset_dir = self.file_storage.upload_dir / str(paper.user_id) / "paper_agent" / str(paper.id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        try:
            asset_dir.resolve().relative_to(self.file_storage.upload_dir.resolve())
        except ValueError as exc:
            raise ValueError("Asset path must stay inside upload directory.") from exc
        return asset_dir

    def _caption_for_page(self, pages: list[ParsedPage], page_number: int, image_index: int) -> str:
        page_text = next((page.text for page in pages if page.page_number == page_number), "")
        caption_pattern = r"(?im)^((?:fig(?:ure)?\.?\s*\d+[a-z]?|图\s*\d+)[^\n]*(?:\n(?!\s*(?:fig|table|表)\b).{0,180})?)"
        matches = [match.group(1).strip() for match in re.finditer(caption_pattern, page_text)]
        if image_index - 1 < len(matches):
            return re.sub(r"\s+", " ", matches[image_index - 1])[:500]
        if matches:
            return re.sub(r"\s+", " ", matches[0])[:500]
        return f"Image extracted from page {page_number}"

    def _figure_label(self, caption: str, fallback_index: int) -> str:
        match = re.search(r"(fig(?:ure)?\.?\s*\d+[a-z]?|图\s*\d+)", caption, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return f"Figure {fallback_index}"

    def _extract_tables_with_pdfplumber(self, paper_id: int, source_path: Path) -> list[PaperTable]:
        """Extract real PDF tables with pdfplumber and store them as Markdown.

        Complex tables are intentionally normalized to Markdown TEXT instead of
        a rigid JSON schema so the front end and Agent can consume them safely.
        Any failure returns an empty list and lets the text-candidate fallback run.
        """
        if pdfplumber is None:
            return []
        tables: list[PaperTable] = []
        try:
            with pdfplumber.open(source_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    extracted_tables = page.extract_tables() or []
                    for table_index, rows in enumerate(extracted_tables, start=1):
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
        body = normalized[1:]
        markdown_rows = [header, separator, *body]
        return "\n".join("| " + " | ".join(self._escape_markdown_cell(cell[:160]) for cell in row) + " |" for row in markdown_rows)[:4000]

    def _clean_cell(self, cell: Any) -> str:
        if cell is None:
            return ""
        return re.sub(r"\s+", " ", str(cell)).strip()

    def _escape_markdown_cell(self, cell: str) -> str:
        return cell.replace("|", "\\|")

    def _table_candidates(self, paper_id: int, pages: list[ParsedPage], existing_text: str) -> list[PaperTable]:
        candidates: list[tuple[int, str]] = []
        for page in pages:
            blocks = self._candidate_blocks(page.text)
            for block in blocks:
                candidates.append((page.page_number, block))
        if not candidates:
            fallback_text = pages[0].text[:1200] if pages else existing_text[:1200]
            if not fallback_text.strip():
                fallback_text = "Table fallback: 当前论文正文中未识别到明确表格，使用兜底文本作为表格候选。"
            candidates.append((pages[0].page_number if pages else 1, fallback_text))
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
            body = normalized[1:]
            markdown_rows = [header, separator, *body]
            return "\n".join("| " + " | ".join(cell[:80] for cell in row) + " |" for row in markdown_rows)[:1600]
        return "\n".join(lines[:10])[:1600]

    def _log_event(self, paper: Document, event_type: str, message: str, metadata: dict | None = None) -> None:
        self.db.add(
            DocumentEvent(
                document_id=paper.id,
                user_id=paper.user_id,
                event_type=event_type,
                message=message[:500],
                event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
            )
        )
