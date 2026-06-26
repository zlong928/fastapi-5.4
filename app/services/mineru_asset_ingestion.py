from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.models import Document, DocumentAsset
from app.services.chart_extraction import process_mineru_image_batch
from app.services.file_storage import FileStorageService

# Regex to find markdown image references: ![alt text](path)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Page marker patterns in MinerU markdown output
_PAGE_MARKER_RE = re.compile(r"^(?:#{1,3}\s*)?(?:page\s*(\d+)|\[page\s*(\d+)\])", re.IGNORECASE)

# Keywords suggesting a chart/diagram rather than a photo/micrograph
_CHART_KEYWORDS = (
    "figure", "fig.", "chart", "plot", "graph", "curve",
    "schematic", "diagram", "illustration", "图谱",
    "示意图", "曲线", "趋势", "关系",
)

# Keywords suggesting microscopy/photo rather than data chart
_PHOTO_KEYWORDS = (
    "sem", "tem", "afm", "micrograph", "microscopy", "photo",
    "image of", "photograph", "显微", "照片", "sem图像",
)


class MinerUVisualAssetIngestion:
    """Ingest visual assets from MinerU's Markdown output.

    Instead of relying on content_list.json, this reads the MinerU Markdown file,
    finds all image references (``![...](path)``), matches them against the
    extracted image files on disk, and creates ``DocumentAsset`` records.

    The Markdown must be the same one produced by ``MinerUParserService`` and
    saved at ``document.cleaned_text`` (the MinerU Markdown content).
    """

    def __init__(self, file_storage: FileStorageService | None = None) -> None:
        self.file_storage = file_storage or FileStorageService()

    def ingest(
        self,
        *,
        document: Document,
        parse_job_id: int,
        markdown_text: str,
        extract_dir: str | None,
        generate_coordinate_preview: bool = False,
    ) -> list[DocumentAsset]:
        """Ingest visual assets by scanning the MinerU Markdown for image references.

        Args:
            document: The ``Document`` record.
            parse_job_id: The ``JobRun.id`` that triggered this parse.
            markdown_text: The full MinerU Markdown content (typically from
                ``document.cleaned_text``).
            extract_dir: The directory where MinerU extracted all files (the
                ``extract_dir`` from ``_save_result_artifacts``).
            generate_coordinate_preview: If ``True``, attempt coordinate extraction
                on the first chart asset found.

        Returns:
            A list of persisted ``DocumentAsset`` instances (not yet added to the
            session — the caller is responsible for that).
        """
        if not markdown_text or not extract_dir:
            return []
        root = Path(extract_dir)
        if not root.is_dir():
            return []

        # Parse markdown to find all image references and their context
        image_refs = self._parse_image_refs(markdown_text)
        if not image_refs:
            return []

        # Match image refs to actual files on disk
        assets: list[DocumentAsset] = []
        for i, ref in enumerate(image_refs):
            image_path = self._resolve_image_path(root, ref["path"])
            if image_path is None:
                continue

            relative_image_path = self._copy_image(
                document=document, source_path=image_path, index=len(assets)
            )
            if relative_image_path is None:
                continue

            evidence_type = self._classify_evidence_type(ref)
            metadata = {
                "source": "mineru_markdown",
                "evidence_type": evidence_type,
                "visual_role": "chart" if evidence_type == "chart" else "figure_candidate",
                "chart_type": self._infer_chart_type(ref),
                "mineru_img_path": ref["path"],
                "mineru_alt_text": ref["alt"][:200] if ref["alt"] else "",
                "mineru_nearby_text": ref.get("nearby_text", "")[:500],
                "mineru_section": ref.get("section", ""),
                "page_idx": ref.get("page_number"),
                "data_extraction_possible": evidence_type == "chart",
                "precise_values_extracted": False,
                "warnings": [],
            }

            asset = DocumentAsset(
                document_id=document.id,
                parse_job_id=parse_job_id,
                asset_type="figure",
                asset_index=len(assets),
                label=ref.get("label") or f"MinerU Figure {i + 1}",
                caption=ref.get("caption") or ref["alt"] or "",
                page_number=ref.get("page_number"),
                file_path=relative_image_path,
                mime_type=self._mime_type(relative_image_path),
                ocr_text=ref.get("nearby_text") or None,
                text_content=ref.get("caption") or ref.get("nearby_text") or ref["alt"] or "",
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
            assets.append(asset)

        unique_assets = self._dedupe(assets)
        if generate_coordinate_preview:
            self._attach_first_coordinate_preview(
                document=document,
                assets=unique_assets,
                extract_dir=root,
            )
        return unique_assets

    # ------------------------------------------------------------------
    # Markdown parsing
    # ------------------------------------------------------------------

    def _parse_image_refs(self, markdown: str) -> list[dict[str, Any]]:
        """Extract all image references from the Markdown with surrounding context."""
        lines = markdown.splitlines()
        # Build page number map: for each line index, what page are we on
        page_map = self._build_page_map(lines)
        # Build section map: for each line, what heading section are we in
        section_map = self._build_section_map(lines)

        refs: list[dict[str, Any]] = []
        for line_idx, line in enumerate(lines):
            for match in _MARKDOWN_IMAGE_RE.finditer(line):
                alt_text = match.group(1).strip()
                img_path = match.group(2).strip()

                # Extract figure label from alt text (e.g., "Figure 1: ...")
                label = self._extract_label(alt_text)

                # Build caption from alt text, stripping the label prefix
                caption = self._build_caption(alt_text, label)

                # Collect nearby text context (lines before and after the image ref)
                nearby_lines: list[str] = []
                for offset in range(-3, 4):
                    if offset == 0:
                        continue
                    neighbor_idx = line_idx + offset
                    if 0 <= neighbor_idx < len(lines):
                        neighbor = lines[neighbor_idx].strip()
                        if neighbor and not _MARKDOWN_IMAGE_RE.search(neighbor):
                            nearby_lines.append(neighbor)
                nearby_text = " ".join(nearby_lines)

                refs.append({
                    "line_idx": line_idx,
                    "alt": alt_text,
                    "path": img_path,
                    "label": label,
                    "caption": caption,
                    "nearby_text": nearby_text[:500],
                    "page_number": page_map.get(line_idx),
                    "section": section_map.get(line_idx, ""),
                })
        return refs

    def _build_page_map(self, lines: list[str]) -> dict[int, int | None]:
        """Map line indices to page numbers based on page markers in the markdown."""
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

    def _build_section_map(self, lines: list[str]) -> dict[int, str]:
        """Map line indices to the current heading section."""
        section_map: dict[int, str] = {}
        current_section = ""
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                if heading:
                    current_section = heading
            section_map[i] = current_section
        return section_map

    # ------------------------------------------------------------------
    # Label / caption extraction
    # ------------------------------------------------------------------

    def _extract_label(self, alt_text: str) -> str | None:
        """Extract a figure label like 'Figure 3' or 'Fig. 2a' from alt text."""
        match = re.search(r"(?i)\b(fig(?:ure)?\.?\s*\d+[a-z]?)\b", alt_text)
        if match:
            return match.group(1)
        # Try to match just a number at the beginning
        match = re.match(r"^\s*(\d+[a-z]?)[\.\)]", alt_text)
        if match:
            return f"Figure {match.group(1)}"
        return None

    def _build_caption(self, alt_text: str, label: str | None) -> str:
        """Build a clean caption from alt text, stripping the label prefix."""
        if not alt_text:
            return ""
        if label:
            # Remove the label prefix: "Figure 1: " or "Figure 1. " etc.
            pattern = re.compile(
                r"^" + re.escape(label) + r"[:\s.\-—]+\s*",
                re.IGNORECASE,
            )
            cleaned = pattern.sub("", alt_text).strip()
            return cleaned if cleaned else alt_text
        return alt_text

    # ------------------------------------------------------------------
    # File resolution & copying
    # ------------------------------------------------------------------

    def _resolve_image_path(self, root: Path, img_path: str) -> Path | None:
        """Resolve a markdown image reference to an actual file on disk."""
        # Clean the path - MinerU may use "images/filename.png" or just "filename.png"
        clean = img_path.strip().lstrip("./")
        # Try exact match under extract_dir
        candidate = root / clean
        if candidate.is_file():
            return candidate
        # Try just the filename (search recursively under extract_dir)
        filename = Path(clean).name
        for found in root.rglob(filename):
            if found.is_file():
                return found
        return None

    def _copy_image(self, *, document: Document, source_path: Path, index: int) -> str | None:
        """Copy an image file into application storage.

        Returns the path relative to the upload directory.
        """
        extension = source_path.suffix.lower() or ".png"
        asset_dir = (
            self.file_storage.upload_dir
            / str(document.user_id)
            / "mineru-assets"
            / str(document.id)
        )
        asset_dir.mkdir(parents=True, exist_ok=True)
        filename = f"mineru-{index + 1}{extension}"
        destination = asset_dir / filename
        try:
            shutil.copyfile(source_path, destination)
            return destination.relative_to(self.file_storage.upload_dir).as_posix()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _classify_evidence_type(self, ref: dict[str, Any]) -> str:
        """Classify an image reference as 'chart' or 'figure' based on context."""
        text = " ".join([
            ref.get("caption", ""),
            ref.get("alt", ""),
            ref.get("nearby_text", ""),
        ]).lower()

        photo_score = sum(1 for kw in _PHOTO_KEYWORDS if kw in text)
        chart_score = sum(1 for kw in _CHART_KEYWORDS if kw in text)

        if chart_score > photo_score:
            return "chart"
        if photo_score > chart_score:
            return "figure"
        # Default: if there's a label, likely a chart; otherwise figure
        if ref.get("label"):
            return "chart"
        return "figure"

    def _infer_chart_type(self, ref: dict[str, Any]) -> str:
        """Infer a rough chart type from caption/alt text keywords."""
        text = " ".join([
            ref.get("caption", ""),
            ref.get("alt", ""),
            ref.get("nearby_text", ""),
        ]).lower()
        if any(kw in text for kw in ("bar", "histogram", "柱状")):
            return "bar"
        if any(kw in text for kw in ("scatter", "散点")):
            return "scatter"
        if any(kw in text for kw in ("heatmap", "heat map", "热图")):
            return "heatmap"
        if any(kw in text for kw in ("line", "curve", "折线", "曲线", "trend")):
            return "line"
        if any(kw in text for kw in ("viscosity", "modulus", "rheolog", "流变", "g'", "g''")):
            return "rheology"
        if any(kw in text for kw in ("spectrum", "spectra", "光谱", "ir ", "ftir", "raman")):
            return "spectrum"
        return "unknown"

    # ------------------------------------------------------------------
    # Deduplication & coordinate preview
    # ------------------------------------------------------------------

    def _dedupe(self, assets: list[DocumentAsset]) -> list[DocumentAsset]:
        seen: set[tuple[int | None, str, str]] = set()
        unique: list[DocumentAsset] = []
        for asset in assets:
            metadata = json.loads(asset.metadata_json or "{}")
            key = (
                asset.page_number,
                str(metadata.get("mineru_img_path")),
                asset.caption or asset.label or "",
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(asset)
        return unique

    def _attach_first_coordinate_preview(
        self,
        *,
        document: Document,
        assets: list[DocumentAsset],
        extract_dir: Path,
    ) -> None:
        """Try extracting coordinate data from the first chart asset."""
        chart_assets = [
            asset
            for asset in assets
            if self._metadata(asset).get("evidence_type") == "chart"
        ]
        if not chart_assets:
            return

        out_dir = (
            self.file_storage.upload_dir
            / str(document.user_id)
            / "mineru-coordinate-csv"
            / str(document.id)
        )
        first_failure: tuple[DocumentAsset, str] | None = None

        for chart_asset in chart_assets:
            metadata = self._metadata(chart_asset)
            raw_img_path = metadata.get("mineru_img_path")
            if not raw_img_path:
                continue
            image_path = extract_dir / str(raw_img_path)
            try:
                image_path.resolve().relative_to(extract_dir.resolve())
            except ValueError:
                continue
            if not image_path.is_file():
                continue

            try:
                result = process_mineru_image_batch(
                    images_dir=image_path.parent,
                    content_list_path=None,  # No longer using content_list.json
                    out_dir=out_dir,
                    sample_limit=15,
                    image_path=image_path,
                )
            except Exception:
                if first_failure is None:
                    first_failure = (
                        chart_asset,
                        f"coordinate_preview_failed",
                    )
                continue

            processed = result.processed[0] if result.processed else {}
            if not processed.get("csv_path"):
                if first_failure is None:
                    reason = str(
                        processed.get("reason")
                        or processed.get("status")
                        or "no_coordinate_csv"
                    )
                    first_failure = (chart_asset, f"coordinate_preview_skipped:{reason}")
                continue
            self._write_coordinate_preview_metadata(chart_asset, result, processed)
            return

        if first_failure is not None:
            chart_asset, warning = first_failure
            metadata = self._metadata(chart_asset)
            metadata.setdefault("warnings", []).append(warning)
            chart_asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _write_coordinate_preview_metadata(
        self, asset: DocumentAsset, result: Any, processed: dict
    ) -> None:
        metadata = self._metadata(asset)
        csv_path = str(processed.get("csv_path") or "")
        preview = {
            "image_type": processed.get("image_type") or "",
            "status": processed.get("status") or "",
            "row_count": processed.get("row_count") or 0,
            "data_quality": processed.get("data_quality") or "",
            "coordinate_csv_path": self._relative_upload_path(csv_path),
            "sample_limit": 15,
        }
        metadata["coordinate_preview"] = preview
        metadata["chart_data_csv_path"] = preview["coordinate_csv_path"]
        metadata["chart_data_quality"] = preview["data_quality"]
        metadata["chart_data_row_count"] = preview["row_count"]
        metadata["coordinate_samples_extracted"] = bool(preview["coordinate_csv_path"])
        metadata["precise_values_extracted"] = processed.get("status") == "accepted"
        if processed.get("status") != "accepted":
            metadata.setdefault("warnings", []).append(
                "coordinate_preview_requires_review"
            )
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    @staticmethod
    def _metadata(asset: DocumentAsset) -> dict[str, Any]:
        try:
            parsed = json.loads(asset.metadata_json or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _relative_upload_path(self, path: str) -> str:
        if not path:
            return ""
        candidate = Path(path)
        try:
            return (
                candidate.resolve()
                .relative_to(self.file_storage.upload_dir.resolve())
                .as_posix()
            )
        except ValueError:
            return path

    @staticmethod
    def _mime_type(path: str) -> str:
        extension = Path(path).suffix.lower()
        if extension in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if extension == ".webp":
            return "image/webp"
        return "image/png"
