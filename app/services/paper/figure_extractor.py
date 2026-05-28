from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from app.models import Document, DocumentAsset
from app.services.file_storage import FileStorageService
from app.services.paper.models import FigureExtractionReport, ParsedPage


class FigureExtractor:
    """Extract PDF image objects or create a fallback page snapshot.

    The extractor creates files and unsaved DocumentAsset instances only. It
    does not attach objects to a SQLAlchemy session and never commits.
    """

    def __init__(self, file_storage: FileStorageService | None = None, max_figures: int = 3) -> None:
        self.file_storage = file_storage or FileStorageService()
        self.max_figures = max_figures

    def extract(self, *, source_path: Path, paper: Document, pages: list[ParsedPage]) -> FigureExtractionReport:
        try:
            assets = self._extract_real_figures(source_path, paper, pages)
            if assets:
                return FigureExtractionReport(
                    assets=assets,
                    status="success",
                    message=f"Extracted {len(assets)} PDF image objects.",
                    figure_count=len(assets),
                    snapshot_count=0,
                )
            snapshot = self._snapshot_asset(source_path, paper)
            return FigureExtractionReport(
                assets=[snapshot],
                status="partial",
                message="No extractable PDF figure was found; generated page 1 snapshot.",
                figure_count=0,
                snapshot_count=1,
            )
        except Exception as exc:
            return FigureExtractionReport(status="failed", message=str(exc))

    def _extract_real_figures(self, source_path: Path, paper: Document, pages: list[ParsedPage]) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        with fitz.open(source_path) as pdf:
            for page in pdf:
                for image_index, image in enumerate(page.get_images(full=True), start=1):
                    if len(assets) >= self.max_figures:
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
                                    "fallback": False,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
        return assets

    def _snapshot_asset(self, source_path: Path, paper: Document) -> DocumentAsset:
        asset_dir = self._asset_dir(paper)
        image_path = asset_dir / "page-1-snapshot.png"
        with fitz.open(source_path) as pdf:
            if pdf.page_count == 0:
                raise ValueError("PDF 没有页面")
            pix = pdf[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(image_path)
        return DocumentAsset(
            document_id=paper.id,
            asset_type="page_snapshot",
            page_number=1,
            file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
            mime_type="image/png",
            metadata_json=json.dumps(
                {
                    "figure_label": "Page 1 Snapshot",
                    "caption": "Fallback page snapshot",
                    "source": "fallback_snapshot",
                    "fallback": True,
                    "context": "Generated because no extractable PDF figure was found",
                },
                ensure_ascii=False,
            ),
        )

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
