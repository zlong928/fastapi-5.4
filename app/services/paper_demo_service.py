from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from dataclasses import dataclass

import fitz
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import MAX_UPLOAD_SIZE_BYTES
from app.core.time import app_now
from app.models import Document, DocumentAsset, PaperTable, User
from app.services.file_storage import FileStorageService


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str


class PaperDemoService:
    """Small paper-demo workflow built on the existing document model."""

    def __init__(self, db: Session, file_storage: FileStorageService | None = None) -> None:
        self.db = db
        self.file_storage = file_storage or FileStorageService()

    async def upload_pdf(self, *, file: UploadFile, user: User) -> Document:
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError(f"File is too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES} bytes.")
        if not content.startswith(b"%PDF-"):
            raise ValueError("仅支持 PDF 文件")
        safe_name = self.file_storage.safe_original_filename(file.filename or "paper.pdf")
        title = Path(safe_name).stem
        file_hash = hashlib.sha256(content).hexdigest()
        existing = (
            self.db.query(Document)
            .filter(Document.user_id == user.id, Document.file_hash == file_hash, Document.status != "deleted")
            .one_or_none()
        )
        if existing is not None:
            return existing
        relative_path, stored_filename = self.file_storage.store_file(
            user_id=user.id,
            original_filename=safe_name,
            file_content=content,
            file_extension="pdf",
        )
        paper = Document(
            user_id=user.id,
            title=title,
            original_filename=safe_name,
            stored_filename=stored_filename,
            original_file_path=relative_path,
            file_size=len(content),
            file_hash=file_hash,
            mime_type="application/pdf",
            source_type="pdf",
            processing_mode="auto",
            status="uploaded",
            uploaded_at=app_now(),
        )
        self.db.add(paper)
        self.db.commit()
        self.db.refresh(paper)
        return paper

    def parse(self, paper: Document) -> Document:
        paper.status = "parsing"
        paper.error_message = None
        paper.fail_reason = None
        self.db.commit()
        try:
            source_path = self.file_storage.get_file_path(paper.original_file_path)
            if not source_path.exists():
                raise FileNotFoundError("源 PDF 文件不存在")
            pages = self._extract_pages(source_path)
            page_count = len(pages)
            text = "\n\n".join(page.text for page in pages if page.text.strip()).strip()
            if not text.strip():
                text = "当前 PDF 未解析到可抽取正文。"

            self.db.query(DocumentAsset).filter(
                DocumentAsset.document_id == paper.id,
                DocumentAsset.asset_type.in_(["paper_figure", "paper_page_snapshot"]),
            ).delete(synchronize_session=False)
            self.db.query(PaperTable).filter(PaperTable.paper_id == paper.id).delete(synchronize_session=False)

            figure_assets = self._extract_figures(source_path, paper, pages)
            if not figure_assets:
                image_path = self._save_first_page_snapshot(source_path, paper)
                figure_assets.append(
                    DocumentAsset(
                        document_id=paper.id,
                        asset_type="paper_page_snapshot",
                        page_number=1,
                        file_path=image_path,
                        mime_type="image/png",
                        metadata_json=json.dumps(
                            {
                                "figure_label": "Page 1 Snapshot",
                                "caption": "Fallback page snapshot",
                                "extraction_method": "page_snapshot",
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            for asset in figure_assets:
                self.db.add(asset)

            for table in self._table_candidates(paper.id, pages):
                self.db.add(table)
            paper.parsed_text = text
            paper.cleaned_text = text
            paper.status = "parsed"
            paper.parsed_at = app_now()
            paper.updated_at = app_now()
            self.db.commit()
            self.db.refresh(paper)
            return paper
        except Exception as exc:
            self.db.rollback()
            paper = self.db.get(Document, paper.id)
            if paper is not None:
                paper.status = "failed"
                paper.error_message = str(exc)
                paper.fail_reason = str(exc)
                paper.updated_at = app_now()
                self.db.commit()
            raise

    def _extract_pages(self, source_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        with fitz.open(source_path) as pdf:
            for page in pdf:
                page_text = page.get_text("text").strip()
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
                            asset_type="paper_figure",
                            page_number=page.number + 1,
                            file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
                            mime_type="image/png",
                            metadata_json=json.dumps(
                                {
                                    "figure_label": label,
                                    "caption": caption,
                                    "extraction_method": "embedded_pdf_image",
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
        except ValueError:
            raise ValueError("Asset path must stay inside upload directory.")
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

    def _table_candidates(self, paper_id: int, pages: list[ParsedPage]) -> list[PaperTable]:
        candidates: list[tuple[int, str]] = []
        for page in pages:
            blocks = self._candidate_blocks(page.text)
            for block in blocks:
                candidates.append((page.page_number, block))
        if not candidates:
            fallback_text = pages[0].text[:1200] if pages else "Table fallback: 当前论文正文中未识别到明确表格，使用正文片段作为表格候选文本。"
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
