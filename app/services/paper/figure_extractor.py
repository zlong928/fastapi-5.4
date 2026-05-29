from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import fitz

from app.models import Document, DocumentAsset
from app.services.paper.evidence import VISUAL_EVIDENCE_TYPES
from app.services.file_storage import FileStorageService
from app.services.paper.models import FigureExtractionReport, ParsedPage

CAPTION_BLOCK_RE = re.compile(r"(?i)^\s*((?:fig(?:ure)?\.?|图)\s*\d+[a-z]?)\b")
CAPTION_ANY_RE = re.compile(r"(?i)\b((?:fig(?:ure)?\.?|图)\s*\d+[a-z]?)\b")
CAPTION_REFERENCE_PREFIXES = (
    "as shown in",
    "as seen in",
    "shown in",
    "seen in",
    "see",
    "from",
    "in",
)
CAPTION_REFERENCE_VERBS = re.compile(r"(?i)^(shows?|showed|demonstrates?|illustrates?|depicts?|presents?|reports?|indicates?)\b")


class FigureExtractor:
    """Extract paper figures or create a fallback page snapshot.

    This extractor creates files and unsaved DocumentAsset instances only.
    It does not attach objects to a SQLAlchemy session and never commits.
    """

    def __init__(self, file_storage: FileStorageService | None = None, max_figures: int = 20, max_page_visual_snapshots: int = 6) -> None:
        self.file_storage = file_storage or FileStorageService()
        self.max_figures = max_figures
        self.max_page_visual_snapshots = max_page_visual_snapshots

    def extract(self, *, source_path: Path, paper: Document, pages: list[ParsedPage]) -> FigureExtractionReport:
        try:
            rendered_assets = self._extract_rendered_figure_regions(source_path, paper, pages)
            image_assets = self._extract_image_objects(source_path, paper, pages)
            page_visual_assets = self._extract_visual_page_snapshots(
                source_path=source_path,
                paper=paper,
                pages=pages,
                existing_assets=[*rendered_assets, *image_assets],
            )

            assets = self._dedupe_sort_limit([*rendered_assets, *image_assets, *page_visual_assets])
            figure_count = self._figure_count(assets)
            snapshot_count = self._snapshot_count(assets)

            if assets:
                status = "success" if figure_count > 0 else "partial"
                return FigureExtractionReport(
                    assets=assets,
                    status=status,
                    message=f"Extracted {figure_count} paper figures and {snapshot_count} page visual evidence assets.",
                    figure_count=figure_count,
                    snapshot_count=snapshot_count,
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
                    classification = self._classify_region(page, figure_rect, caption_rect, caption, visual_rects)
                    if classification["evidence_type"] not in VISUAL_EVIDENCE_TYPES:
                        continue
                    if not self._trusted_figure_rect(page, figure_rect, caption_rect):
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
                            evidence_type=str(classification["evidence_type"]),
                            bbox=[float(figure_rect.x0), float(figure_rect.y0), float(figure_rect.x1), float(figure_rect.y1)],
                            classification=classification,
                        )
                    )
                    seen_labels.add(label_key)

        return assets

    def _extract_image_objects(
        self,
        source_path: Path,
        paper: Document,
        pages: list[ParsedPage],
    ) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        seen_xrefs: set[int] = set()

        with fitz.open(source_path) as pdf:
            for page in pdf:
                page_number = page.number + 1
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
                            evidence_type="figure",
                            bbox=None,
                            classification={
                                "evidence_type": "figure",
                                "text_density": 0.0,
                                "image_density": 1.0,
                                "has_caption": bool(caption),
                                "has_axis_or_chart_shapes": False,
                                "is_table": False,
                                "confidence": 0.68,
                            },
                        )
                    )
                    seen_xrefs.add(xref)

        return assets

    def _extract_visual_page_snapshots(
        self,
        *,
        source_path: Path,
        paper: Document,
        pages: list[ParsedPage],
        existing_assets: list[DocumentAsset],
    ) -> list[DocumentAsset]:
        asset_dir = self._asset_dir(paper)
        assets: list[DocumentAsset] = []
        page_text_map = {page.page_number: page.text for page in pages}
        existing_pages = {asset.page_number for asset in existing_assets if asset.page_number is not None}

        with fitz.open(source_path) as pdf:
            snapshot_candidates: list[tuple[int, int, str]] = []
            for page in pdf:
                page_number = page.number + 1
                page_text = page_text_map.get(page_number, "")
                visual_rects = self._visual_rects(page)
                caption_candidates = self._caption_candidates_from_text(page_text)
                if not caption_candidates:
                    caption_candidates = self._caption_candidates_from_blocks(page)

                priority = self._page_visual_snapshot_priority(page, caption_candidates, visual_rects, page_number in existing_pages)
                if priority is None:
                    continue

                context = caption_candidates[0][1] if caption_candidates else "Page contains figure-like visual content."
                snapshot_candidates.append((priority, page_number, context))

            for _priority, page_number, context in sorted(snapshot_candidates, key=lambda item: (item[0], item[1]))[: self.max_page_visual_snapshots]:
                filename = f"page-{page_number}-visual-snapshot.png"
                image_path = asset_dir / filename
                try:
                    page = pdf[page_number - 1]
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                    pix.save(image_path)
                except Exception:
                    continue

                assets.append(
                    DocumentAsset(
                        document_id=paper.id,
                        asset_type="page_snapshot",
                        page_number=page_number,
                        file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
                        mime_type="image/png",
                        metadata_json=json.dumps(
                            {
                                "figure_label": f"Page {page_number} Visual Evidence",
                                "caption": "Page-level visual evidence generated from a page containing figure-like content.",
                                "context": context,
                                "source": "page_visual_snapshot",
                                "fallback": False,
                                "visual_role": "page_evidence",
                                "evidence_type": "page_region",
                                "confidence": 0.45,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )

        return assets

    def _page_visual_snapshot_priority(
        self,
        page: fitz.Page,
        caption_candidates: list[tuple[str, str]],
        visual_rects: list[fitz.Rect],
        has_existing_asset: bool,
    ) -> int | None:
        if caption_candidates:
            return 0
        if has_existing_asset:
            return 1
        page_area = max(1.0, page.rect.width * page.rect.height)
        for rect in visual_rects:
            area_ratio = (rect.width * rect.height) / page_area
            if self._large_enough(rect, min_width=80, min_height=70) and area_ratio >= 0.01:
                return 2
        return None

    def _should_create_page_visual_snapshot(
        self,
        page: fitz.Page,
        caption_candidates: list[tuple[str, str]],
        visual_rects: list[fitz.Rect],
        has_existing_asset: bool,
    ) -> bool:
        return self._page_visual_snapshot_priority(page, caption_candidates, visual_rects, has_existing_asset) is not None

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
                    "visual_role": "page_evidence",
                    "evidence_type": "page_region",
                    "confidence": 0.25,
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
        evidence_type: str,
        bbox: list[float] | None,
        classification: dict[str, Any],
    ) -> DocumentAsset:
        visual_role = "image_object" if source == "extracted_image" else "figure_candidate"
        metadata = {
            "figure_label": label,
            "caption": caption,
            "context": caption,
            "source": source,
            "fallback": False,
            "visual_role": visual_role,
            "evidence_type": evidence_type,
            "bbox": bbox,
            "text_density": classification.get("text_density", 0.0),
            "image_density": classification.get("image_density", 0.0),
            "has_caption": classification.get("has_caption", bool(caption)),
            "has_axis_or_chart_shapes": classification.get("has_axis_or_chart_shapes", False),
            "is_table": classification.get("is_table", False),
            "confidence": classification.get("confidence", 0.65),
        }
        return DocumentAsset(
            document_id=paper.id,
            asset_type="figure",
            page_number=page_number,
            file_path=image_path.relative_to(self.file_storage.upload_dir).as_posix(),
            mime_type="image/png",
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )

    def _caption_blocks(self, page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
        captions: list[tuple[fitz.Rect, str]] = []

        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue

            text = self._clean_text(str(block[4]))
            match = CAPTION_ANY_RE.search(text)
            if match and self._looks_like_caption_text(text, match):
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
        label_key = self._normalize_label(label)
        block_matches: list[tuple[float, fitz.Rect]] = []

        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue

            text = self._clean_text(str(block[4]))
            match = CAPTION_ANY_RE.search(text)
            if not match or self._normalize_label(match.group(1)) != label_key:
                continue
            if not self._looks_like_caption_text(text, match):
                continue

            block_matches.append((self._caption_block_score(page, text, match), fitz.Rect(block[:4])))

        if block_matches:
            block_matches.sort(key=lambda item: item[0], reverse=True)
            return block_matches[0][1]

        search_terms = self._label_search_terms(label)

        for term in search_terms:
            try:
                rects = page.search_for(term)
            except Exception:
                rects = []

            if rects:
                grouped = self._group_line_rects([fitz.Rect(rect) for rect in rects])
                if grouped:
                    grouped.sort(key=lambda rect: rect.y0, reverse=True)
                    return grouped[0]

        return None

    def _looks_like_caption_text(self, text: str, match: re.Match[str]) -> bool:
        before = text[: match.start()].strip()
        after = text[match.end() :].strip()
        before_lower = before.lower().rstrip(":：-")

        if len(after) < 15:
            return False
        if match.start() > 80:
            return False
        if before and len(before) > 50:
            return False
        if before and any(before_lower.endswith(prefix) or before_lower == prefix for prefix in CAPTION_REFERENCE_PREFIXES):
            return False
        if match.start() > 0 and text[match.start() - 1] in "([":
            return False
        if after[:1] in {")", "]", ",", ";"}:
            return False
        if before and CAPTION_REFERENCE_VERBS.match(after):
            return False

        return True

    def _caption_block_score(self, page: fitz.Page, text: str, match: re.Match[str]) -> float:
        score = 0.0
        if match.start() == 0:
            score += 4
        elif match.start() <= 30:
            score += 2
        if text[match.end() : match.end() + 1] in {".", ":", "：", "|", "-"}:
            score += 1
        if len(text) >= 35:
            score += 1
        if page.rect.height and match.start() <= 40:
            score += 0.5
        return score

    def _label_search_terms(self, label: str) -> list[str]:
        terms = [label]
        if "." in label:
            terms.append(label.replace(".", ""))
        match = re.match(r"(?i)^(fig(?:ure)?)(\.?)(\s*\d+[a-z]?)$", label.strip())
        if match:
            number = match.group(3)
            terms.extend([f"Fig. {number.strip()}", f"Fig {number.strip()}", f"Figure {number.strip()}"])
        unique: list[str] = []
        for term in terms:
            clean = self._clean_text(term)
            if clean and clean not in unique:
                unique.append(clean)
        return unique

    def _group_line_rects(self, rects: list[fitz.Rect]) -> list[fitz.Rect]:
        lines: list[fitz.Rect] = []
        for rect in sorted(rects, key=lambda item: (item.y0, item.x0)):
            if lines and abs(lines[-1].y0 - rect.y0) < 8:
                lines[-1] |= rect
            else:
                lines.append(fitz.Rect(rect))
        return lines

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
        left_margin, right_margin = self._column_bounds(page, caption_rect)
        bottom = max(top_margin + 20, caption_rect.y0 - 3)

        nearby: list[fitz.Rect] = []
        max_gap = page_rect.height * 0.34

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
                max(top_margin, caption_rect.y0 - page_rect.height * 0.28),
                right_margin,
                bottom,
            )

        out &= page_rect
        return out if self._large_enough(out) else None

    def _column_bounds(self, page: fitz.Page, caption_rect: fitz.Rect) -> tuple[float, float]:
        page_rect = page.rect
        left_margin = page_rect.x0 + 24
        right_margin = page_rect.x1 - 24
        page_width = page_rect.width
        if caption_rect.width >= page_width * 0.45:
            return left_margin, right_margin

        middle = page_rect.x0 + page_width / 2
        gutter = min(24.0, page_width * 0.04)
        caption_center = (caption_rect.x0 + caption_rect.x1) / 2
        if caption_center < middle:
            return left_margin, max(left_margin + 120, middle - gutter)
        return min(right_margin - 120, middle + gutter), right_margin

    def _trusted_figure_rect(self, page: fitz.Page, figure_rect: fitz.Rect, caption_rect: fitz.Rect) -> bool:
        page_area = max(1.0, page.rect.width * page.rect.height)
        rect_area = max(1.0, figure_rect.width * figure_rect.height)
        if rect_area / page_area > 0.45:
            return False
        return self._text_pollution_score(page, figure_rect, caption_rect) <= 0.35

    def _classify_region(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        caption_rect: fitz.Rect | None,
        caption: str,
        visual_rects: list[fitz.Rect],
    ) -> dict[str, Any]:
        text_density = self._text_pollution_score(page, rect, caption_rect) if caption_rect is not None else self._text_density(page, rect)
        image_density = self._image_density(rect, visual_rects)
        drawing_stats = self._drawing_stats(page, rect)
        has_caption = bool(caption.strip())
        caption_lower = caption.lower()
        has_chart_words = any(word in caption_lower for word in ("chart", "plot", "axis", "axes", "curve", "graph", "trend", "time-series", "time series"))
        has_axis_or_chart_shapes = drawing_stats["line_like_count"] >= 2 or has_chart_words
        is_table = drawing_stats["grid_like_count"] >= 6 or bool(re.search(r"(?i)\btable\b|表\s*\d+", caption))

        if text_density > 0.35 and image_density < 0.04 and not has_axis_or_chart_shapes:
            evidence_type = "text"
            confidence = 0.78
        elif is_table:
            evidence_type = "table"
            confidence = 0.72
        elif has_axis_or_chart_shapes and (image_density >= 0.005 or drawing_stats["drawing_count"] >= 3):
            evidence_type = "chart"
            confidence = 0.82
        elif image_density >= 0.01 or drawing_stats["drawing_count"] > 0:
            evidence_type = "figure"
            confidence = 0.72
        else:
            evidence_type = "page_region"
            confidence = 0.4

        return {
            "evidence_type": evidence_type,
            "text_density": round(float(max(0.0, min(1.0, text_density))), 4),
            "image_density": round(float(max(0.0, min(1.0, image_density))), 4),
            "has_caption": has_caption,
            "has_axis_or_chart_shapes": has_axis_or_chart_shapes,
            "is_table": is_table,
            "confidence": confidence,
        }

    def _text_density(self, page: fitz.Page, rect: fitz.Rect) -> float:
        chars = 0
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            block_rect = fitz.Rect(block[:4])
            if block_rect.get_area() <= 0 or not block_rect.intersects(rect):
                continue
            chars += len(self._clean_text(str(block[4])))
        if chars == 0:
            return 0.0
        estimated_text_capacity = max(80.0, rect.width * rect.height / 180.0)
        return min(1.0, chars / estimated_text_capacity)

    def _image_density(self, rect: fitz.Rect, visual_rects: list[fitz.Rect]) -> float:
        rect_area = max(1.0, rect.get_area())
        covered = 0.0
        for visual_rect in visual_rects:
            if not visual_rect.intersects(rect):
                continue
            intersection = fitz.Rect(visual_rect)
            intersection &= rect
            covered += max(0.0, intersection.get_area())
        return min(1.0, covered / rect_area)

    def _drawing_stats(self, page: fitz.Page, rect: fitz.Rect) -> dict[str, int]:
        drawing_count = 0
        line_like_count = 0
        grid_like_count = 0
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []
        for drawing in drawings:
            raw_rect = drawing.get("rect")
            if raw_rect is None:
                continue
            drawing_rect = fitz.Rect(raw_rect)
            if not drawing_rect.intersects(rect):
                continue
            drawing_count += 1
            width = abs(drawing_rect.width)
            height = abs(drawing_rect.height)
            if max(width, height) >= 24:
                line_like_count += 1
            if min(width, height) <= 4 and max(width, height) >= 24:
                grid_like_count += 1
        return {"drawing_count": drawing_count, "line_like_count": line_like_count, "grid_like_count": grid_like_count}

    def _text_pollution_score(self, page: fitz.Page, rect: fitz.Rect, caption_rect: fitz.Rect) -> float:
        non_caption_chars = 0
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            block_rect = fitz.Rect(block[:4])
            if block_rect.get_area() <= 0 or not block_rect.intersects(rect):
                continue
            if block_rect.intersects(caption_rect):
                continue
            text = self._clean_text(str(block[4]))
            if text:
                non_caption_chars += len(text)

        if non_caption_chars == 0:
            return 0.0

        estimated_text_capacity = max(80.0, rect.width * rect.height / 180.0)
        return min(1.0, non_caption_chars / estimated_text_capacity)

    def _dedupe_sort_limit(self, assets: list[DocumentAsset]) -> list[DocumentAsset]:
        unique: list[DocumentAsset] = []
        seen: set[tuple[int | None, str, str, str]] = set()

        for asset in assets:
            label = self._metadata_label(asset)
            source = self._metadata_source(asset)
            key = (
                asset.page_number,
                asset.asset_type,
                source,
                self._normalize_label(label) or str(asset.file_path),
            )
            if key in seen:
                continue

            seen.add(key)
            unique.append(asset)

        unique.sort(
            key=lambda asset: (
                asset.page_number or 0,
                self._source_priority(self._metadata_source(asset)),
                self._normalize_label(self._metadata_label(asset)),
            )
        )
        return unique[: self.max_figures]

    def _figure_count(self, assets: list[DocumentAsset]) -> int:
        return sum(1 for asset in assets if asset.asset_type == "figure" and not self._metadata_fallback(asset))

    def _snapshot_count(self, assets: list[DocumentAsset]) -> int:
        return sum(1 for asset in assets if asset.asset_type == "page_snapshot")

    def _source_priority(self, source: str) -> int:
        order = {
            "rendered_figure_region": 0,
            "extracted_image": 1,
            "page_visual_snapshot": 2,
            "fallback_snapshot": 3,
        }
        return order.get(source, 9)

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

    def _metadata_source(self, asset: DocumentAsset) -> str:
        if not asset.metadata_json:
            return ""

        try:
            return str(json.loads(asset.metadata_json).get("source") or "")
        except Exception:
            return ""

    def _metadata_fallback(self, asset: DocumentAsset) -> bool:
        if not asset.metadata_json:
            return asset.asset_type == "page_snapshot"

        try:
            metadata = json.loads(asset.metadata_json)
        except Exception:
            return asset.asset_type == "page_snapshot"

        raw_fallback = metadata.get("fallback") if isinstance(metadata, dict) else None
        if isinstance(raw_fallback, bool):
            return raw_fallback
        if raw_fallback is not None:
            return str(raw_fallback).lower() == "true"
        return asset.asset_type == "page_snapshot"

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
