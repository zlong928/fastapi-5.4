from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from app.models import Document, DocumentAsset
from app.services.file_storage import FileStorageService
from app.services.paper.models import FigureExtractionReport, ParsedPage

CAPTION_BLOCK_RE = re.compile(r"(?i)^\s*((?:fig(?:ure)?\.?|图)\s*\d+[a-z]?)\b")
CAPTION_ANY_RE = re.compile(r"(?i)\b((?:fig(?:ure)?\.?|图)\s*\d+[a-z]?)\b")


class FigureExtractor:
    """Extract paper figures or create a fallback page snapshot.

    This extractor creates files and unsaved DocumentAsset instances only.
    It does not attach objects to a SQLAlchemy session and never commits.
    """

    def __init__(self, file_storage: FileStorageService | None = None, max_figures: int = 20) -> None:
        self.file_storage = file_storage or FileStorageService()
        self.max_figures = max_figures

    def extract(self, *, source_path: Path, paper: Document, pages: list[ParsedPage]) -> FigureExtractionReport:
        try:
            rendered_assets = self._extract_rendered_figure_regions(source_path, paper, pages)

            # Do not blindly skip rendered pages forever. In practice, rendered
            # crops are preferred, while image objects remain a backup source
            # for pages without rendered figure regions.
            rendered_pages = {asset.page_number for asset in rendered_assets if asset.page_number is not None}
            image_assets = self._extract_image_objects(source_path, paper, pages, skip_pages=rendered_pages)

            assets = self._dedupe_sort_limit([*rendered_assets, *image_assets])

            if assets:
                return FigureExtractionReport(
                    assets=assets,
                    status="success",
                    message=f"Extracted {len(assets)} paper figure assets.",
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

    def _extract_rendered_figure_regions(
        self,
        source_path: Path,
        paper: Document,
        pages: list[ParsedPage],
    ) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        seen_labels: set[str] = set()
        page_text_map = {page.page_number: page.text for page in pages}

        with fitz.open(source_path) as pdf:
            for page in pdf:
                page_number = page.number + 1
                page_text = page_text_map.get(page_number, "")

                caption_candidates = self._caption_candidates_from_text(page_text)
                if not caption_candidates:
                    caption_candidates = self._caption_candidates_from_blocks(page)

                if not caption_candidates:
                    continue

                visual_rects = self._visual_rects(page)

                for label, caption in caption_candidates:
                    label_key = self._normalize_label(label)
                    if label_key in seen_labels:
                        continue

                    caption_rect = self._find_caption_rect(page, label, caption)
                    if caption_rect is None:
                        continue

                    figure_rect = self._figure_rect_from_caption(page, caption_rect, visual_rects)
                    if figure_rect is None:
                        continue

                    filename = f"page-{page_number}-{self._safe_filename(label)}-rendered.png"
                    image_path = asset_dir / filename

                    try:
                        pix = page.get_pixmap(
                            matrix=fitz.Matrix(2, 2),
                            clip=figure_rect,
                            alpha=False,
                        )
                        pix.save(image_path)
                    except Exception:
                        continue

                    assets.append(
                        self._figure_asset(
                            paper=paper,
                            page_number=page_number,
                            image_path=image_path,
                            label=label,
                            caption=caption,
                            source="rendered_figure_region",
                        )
                    )
                    seen_labels.add(label_key)

        return assets

    def _extract_image_objects(
        self,
        source_path: Path,
        paper: Document,
        pages: list[ParsedPage],
        skip_pages: set[int] | None = None,
    ) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        seen_xrefs: set[int] = set()
        skip_pages = skip_pages or set()

        with fitz.open(source_path) as pdf:
            for page in pdf:
                page_number = page.number + 1
                if page_number in skip_pages:
                    continue

                caption = self._first_caption_for_page(pages, page_number) or f"Image extracted from page {page_number}"

                for image_index, image in enumerate(page.get_images(full=True), start=1):
                    xref = image[0]
                    if xref in seen_xrefs:
                        continue

                    try:
                        pix = fitz.Pixmap(pdf, xref)
                        if pix.width < 160 or pix.height < 160:
                            continue
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)

                        filename = f"page-{page_number}-image-{image_index}.png"
                        image_path = asset_dir / filename
                        pix.save(image_path)
                    except Exception:
                        continue

                    label = self._figure_label(caption, len(assets) + 1)
                    assets.append(
                        self._figure_asset(
                            paper=paper,
                            page_number=page_number,
                            image_path=image_path,
                            label=label,
                            caption=caption,
                            source="extracted_image",
                        )
                    )
                    seen_xrefs.add(xref)

        return assets

    def _snapshot_asset(self, source_path: Path, paper: Document) -> DocumentAsset:
        asset_dir = self._asset_dir(paper)
        image_path = asset_dir / "page-1-snapshot.png"

        with fitz.open(source_path) as pdf:
            if pdf.page_count == 0:
                raise ValueError("PDF has no pages")
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

    def _figure_asset(
        self,
        *,
        paper: Document,
        page_number: int,
        image_path: Path,
        label: str,
        caption: str,
        source: str,
    ) -> DocumentAsset:
        return DocumentAsset(
            document_id=paper.id,
            asset_type="figure",
            page_number=page_number,
            file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
            mime_type="image/png",
            metadata_json=json.dumps(
                {
                    "figure_label": label,
                    "caption": caption,
                    "context": caption,
                    "source": source,
                    "fallback": False,
                },
                ensure_ascii=False,
            ),
        )

    def _caption_blocks(self, page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
        captions: list[tuple[fitz.Rect, str]] = []

        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue

            text = self._clean_text(str(block[4]))
            if CAPTION_BLOCK_RE.match(text):
                captions.append((fitz.Rect(block[:4]), text[:1200]))

        return captions

    def _caption_candidates_from_text(self, page_text: str) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if not page_text:
            return candidates

        pattern = re.compile(
            r"(?ims)\b((?:fig(?:ure)?\.?|图)\s*\d+[a-z]?)\s*[|.]?\s+"
            r"(.{20,1200}?)(?=\n\s*(?:fig(?:ure)?\.?|图)\s*\d+|\n\s*(?:table|表)\s*\d+|\Z)"
        )

        for match in pattern.finditer(page_text):
            label = self._clean_text(match.group(1)).rstrip(".")
            caption = self._clean_text(f"{label} {match.group(2)}")[:1200]
            if label and caption:
                candidates.append((label, caption))

        return self._dedupe_caption_candidates(candidates)

    def _caption_candidates_from_blocks(self, page: fitz.Page) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []

        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue

            text = self._clean_text(str(block[4]))
            match = CAPTION_ANY_RE.search(text)
            if not match:
                continue

            label = self._clean_text(match.group(1)).rstrip(".")
            caption = text[match.start() :][:1200]
            if label and len(caption) >= 20:
                candidates.append((label, caption))

        return self._dedupe_caption_candidates(candidates)

    def _find_caption_rect(self, page: fitz.Page, label: str, caption: str) -> fitz.Rect | None:
        search_terms = [
            label,
            label.replace("Fig.", "Fig"),
            label.replace("Fig", "Fig."),
        ]

        for term in search_terms:
            try:
                rects = page.search_for(term)
            except Exception:
                rects = []

            if rects:
                rect = fitz.Rect(rects[0])
                for extra in rects[1:]:
                    if abs(extra.y0 - rect.y0) < 8:
                        rect |= extra
                return rect

        label_key = self._normalize_label(label)
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            text = self._clean_text(str(block[4]))
            if label_key in self._normalize_label(text):
                return fitz.Rect(block[:4])

        return None

    def _visual_rects(self, page: fitz.Page) -> list[fitz.Rect]:
        rects: list[fitz.Rect] = []

        try:
            for info in page.get_image_info(xrefs=True):
                bbox = info.get("bbox")
                if bbox:
                    rect = fitz.Rect(bbox)
                    if self._large_enough(rect, min_width=30, min_height=30):
                        rects.append(rect)
        except Exception:
            pass

        try:
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if rect is not None:
                    draw_rect = fitz.Rect(rect)
                    if self._large_enough(draw_rect, min_width=8, min_height=8):
                        rects.append(draw_rect)
        except Exception:
            pass

        return rects

    def _figure_rect_from_caption(
        self,
        page: fitz.Page,
        caption_rect: fitz.Rect,
        visual_rects: list[fitz.Rect],
    ) -> fitz.Rect | None:
        page_rect = page.rect
        top_margin = page_rect.y0 + 48
        left_margin = page_rect.x0 + 24
        right_margin = page_rect.x1 - 24
        bottom = max(top_margin + 20, caption_rect.y0 - 3)

        nearby: list[fitz.Rect] = []
        max_gap = page_rect.height * 0.62

        for rect in visual_rects:
            if rect.y1 > caption_rect.y0 + 2:
                continue
            if caption_rect.y0 - rect.y1 > max_gap:
                continue
            if rect.x1 < left_margin or rect.x0 > right_margin:
                continue
            nearby.append(rect)

        if nearby:
            union = fitz.Rect(nearby[0])
            for rect in nearby[1:]:
                union |= rect
            out = fitz.Rect(
                max(left_margin, union.x0 - 10),
                max(top_margin, union.y0 - 10),
                min(right_margin, union.x1 + 10),
                min(bottom, union.y1 + 10),
            )
        else:
            out = fitz.Rect(
                left_margin,
                max(top_margin, caption_rect.y0 - page_rect.height * 0.62),
                right_margin,
                bottom,
            )

        out &= page_rect
        return out if self._large_enough(out) else None

    def _dedupe_sort_limit(self, assets: list[DocumentAsset]) -> list[DocumentAsset]:
        unique: list[DocumentAsset] = []
        seen: set[tuple[int | None, str]] = set()

        for asset in assets:
            label = self._metadata_label(asset)
            key = (asset.page_number, self._normalize_label(label) or str(asset.file_path))
            if key in seen:
                continue

            seen.add(key)
            unique.append(asset)

        unique.sort(key=lambda asset: (asset.page_number or 0, self._normalize_label(self._metadata_label(asset))))
        return unique[: self.max_figures]

    def _asset_dir(self, paper: Document) -> Path:
        asset_dir = self.file_storage.upload_dir / str(paper.user_id) / "paper_agent" / str(paper.id)
        asset_dir.mkdir(parents=True, exist_ok=True)

        try:
            asset_dir.resolve().relative_to(self.file_storage.upload_dir.resolve())
        except ValueError as exc:
            raise ValueError("Asset path must stay inside upload directory.") from exc

        return asset_dir

    def _first_caption_for_page(self, pages: list[ParsedPage], page_number: int) -> str:
        page_text = next((page.text for page in pages if page.page_number == page_number), "")

        match = re.search(
            r"(?im)^((?:fig(?:ure)?\.?\s*\d+[a-z]?|图\s*\d+)[^\n]*(?:\n(?!\s*(?:fig|table|表)\b).{0,180})?)",
            page_text,
        )

        return self._clean_text(match.group(1))[:500] if match else ""

    def _metadata_label(self, asset: DocumentAsset) -> str:
        if not asset.metadata_json:
            return ""

        try:
            return str(json.loads(asset.metadata_json).get("figure_label") or "")
        except Exception:
            return ""

    def _figure_label(self, caption: str, fallback_index: int) -> str:
        match = CAPTION_ANY_RE.search(caption)

        if match:
            return self._clean_text(match.group(1)).rstrip(".")

        return f"Figure {fallback_index}"

    def _dedupe_caption_candidates(self, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()

        for label, caption in candidates:
            key = self._normalize_label(label)
            if key in seen:
                continue

            seen.add(key)
            unique.append((label, caption))

        return unique

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _normalize_label(self, label: str) -> str:
        return re.sub(r"\s+", "", label.lower().rstrip("."))

    def _safe_filename(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-") or "figure"

    def _large_enough(self, rect: fitz.Rect, *, min_width: float = 90, min_height: float = 70) -> bool:
        return rect.width >= min_width and rect.height >= min_height