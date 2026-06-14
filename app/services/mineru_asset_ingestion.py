from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.models import Document, DocumentAsset
from app.services.chart_extraction import process_mineru_image_batch
from app.services.file_storage import FileStorageService


class MinerUVisualAssetIngestion:
    def __init__(self, file_storage: FileStorageService | None = None) -> None:
        self.file_storage = file_storage or FileStorageService()

    def ingest(
        self,
        *,
        document: Document,
        parse_job_id: int,
        content_list_path: str | None,
        extract_dir: str | None,
        generate_coordinate_preview: bool = False,
    ) -> list[DocumentAsset]:
        if not content_list_path or not extract_dir:
            return []
        content_path = Path(content_list_path)
        root = Path(extract_dir)
        if not content_path.is_file() or not root.is_dir():
            return []
        try:
            payload = json.loads(content_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []

        assets: list[DocumentAsset] = []
        for item in payload:
            if not isinstance(item, dict) or item.get("type") not in {"chart", "image"}:
                continue
            image_path = self._source_image_path(root, item)
            if image_path is None:
                continue
            relative_image_path = self._copy_image(document=document, source_path=image_path, index=len(assets))
            if relative_image_path is None:
                continue
            asset = self._asset_from_item(
                document=document,
                parse_job_id=parse_job_id,
                item=item,
                relative_image_path=relative_image_path,
                index=len(assets),
                content_list_path=content_path,
            )
            assets.append(asset)
        unique_assets = self._dedupe(assets)
        if generate_coordinate_preview:
            self._attach_first_coordinate_preview(
                document=document,
                assets=unique_assets,
                content_list_path=content_path,
                extract_dir=root,
            )
        return unique_assets

    def _source_image_path(self, root: Path, item: dict[str, Any]) -> Path | None:
        raw_path = item.get("img_path")
        if not raw_path:
            return None
        candidate = root / str(raw_path)
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _copy_image(self, *, document: Document, source_path: Path, index: int) -> str | None:
        extension = source_path.suffix.lower() or ".png"
        asset_dir = self.file_storage.upload_dir / str(document.user_id) / "mineru-assets" / str(document.id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        filename = f"mineru-{index + 1}{extension}"
        destination = asset_dir / filename
        try:
            shutil.copyfile(source_path, destination)
            return destination.relative_to(self.file_storage.upload_dir).as_posix()
        except Exception:
            return None

    def _asset_from_item(
        self,
        *,
        document: Document,
        parse_job_id: int,
        item: dict[str, Any],
        relative_image_path: str,
        index: int,
        content_list_path: Path,
    ) -> DocumentAsset:
        item_type = str(item.get("type") or "")
        subtype = str(item.get("sub_type") or "")
        evidence_type = "chart" if item_type == "chart" or "chart" in subtype.lower() else "figure"
        caption = self._caption(item)
        label = self._label(caption, item, index)
        metadata = {
            "source": "mineru_chart" if evidence_type == "chart" else "mineru_image",
            "evidence_type": evidence_type,
            "visual_role": "chart" if evidence_type == "chart" else "figure_candidate",
            "chart_type": self._chart_type(subtype),
            "mineru_type": item_type,
            "mineru_sub_type": subtype,
            "mineru_img_path": item.get("img_path"),
            "mineru_content": item.get("content") or "",
            "mineru_content_list_path": str(content_list_path),
            "bbox": item.get("bbox"),
            "page_idx": item.get("page_idx"),
            "data_extraction_possible": evidence_type == "chart",
            "precise_values_extracted": False,
            "warnings": [],
        }
        return DocumentAsset(
            document_id=document.id,
            parse_job_id=parse_job_id,
            asset_type="figure",
            asset_index=index,
            label=label,
            caption=caption,
            page_number=self._page_number(item),
            file_path=relative_image_path,
            mime_type=self._mime_type(relative_image_path),
            ocr_text=str(item.get("content") or "") if item_type == "image" and subtype == "text_image" else None,
            text_content=str(item.get("content") or caption or ""),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )

    def _caption(self, item: dict[str, Any]) -> str:
        for key in ("chart_caption", "image_caption"):
            value = item.get(key)
            if isinstance(value, list):
                return "\n".join(str(part) for part in value if str(part).strip()).strip()
            if isinstance(value, str):
                return value.strip()
        return ""

    def _label(self, caption: str, item: dict[str, Any], index: int) -> str:
        match = re.search(r"(?i)\b(fig(?:ure)?\.?\s*\d+[a-z]?)\b", caption)
        if match:
            return match.group(1)
        panel = str(item.get("image_caption") or item.get("chart_caption") or "").strip("[]'\" ")
        return panel[:80] if panel else f"MinerU Visual {index + 1}"

    def _page_number(self, item: dict[str, Any]) -> int | None:
        try:
            return int(item.get("page_idx")) + 1
        except (TypeError, ValueError):
            return None

    def _chart_type(self, subtype: str) -> str:
        lower = subtype.lower()
        if "line" in lower:
            return "line"
        if "scatter" in lower:
            return "scatter"
        if "bar" in lower or "histogram" in lower:
            return "bar"
        return "unknown"

    def _mime_type(self, path: str) -> str:
        extension = Path(path).suffix.lower()
        if extension in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if extension == ".webp":
            return "image/webp"
        return "image/png"

    def _dedupe(self, assets: list[DocumentAsset]) -> list[DocumentAsset]:
        seen: set[tuple[int | None, str, str]] = set()
        unique: list[DocumentAsset] = []
        for asset in assets:
            metadata = json.loads(asset.metadata_json or "{}")
            key = (asset.page_number, str(metadata.get("bbox")), asset.caption or asset.label or "")
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
        content_list_path: Path,
        extract_dir: Path,
    ) -> None:
        chart_assets = [asset for asset in assets if self._metadata(asset).get("evidence_type") == "chart"]
        if not chart_assets:
            return

        out_dir = self.file_storage.upload_dir / str(document.user_id) / "mineru-coordinate-csv" / str(document.id)
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
                    content_list_path=content_list_path,
                    out_dir=out_dir,
                    sample_limit=15,
                    image_path=image_path,
                )
            except Exception as exc:
                if first_failure is None:
                    first_failure = (chart_asset, f"coordinate_preview_failed:{type(exc).__name__}")
                continue

            processed = result.processed[0] if result.processed else {}
            if not processed.get("csv_path"):
                if first_failure is None:
                    reason = str(processed.get("reason") or processed.get("status") or "no_coordinate_csv")
                    first_failure = (chart_asset, f"coordinate_preview_skipped:{reason}")
                continue
            self._write_coordinate_preview_metadata(chart_asset, result, processed)
            return

        if first_failure is not None:
            chart_asset, warning = first_failure
            metadata = self._metadata(chart_asset)
            metadata.setdefault("warnings", []).append(warning)
            chart_asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _write_coordinate_preview_metadata(self, asset: DocumentAsset, result: Any, processed: dict) -> None:
        metadata = self._metadata(asset)
        csv_path = str(processed.get("csv_path") or "")
        overlay_path = str(processed.get("overlay_path") or "")
        preview = {
            "image_type": processed.get("image_type") or "",
            "status": processed.get("status") or "",
            "row_count": processed.get("row_count") or 0,
            "data_quality": processed.get("data_quality") or "",
            "coordinate_csv_path": self._relative_upload_path(csv_path),
            "overlay_path": self._relative_upload_path(overlay_path),
            "combined_csv_path": self._relative_upload_path(str(result.combined_csv_path)),
            "summary_csv_path": self._relative_upload_path(str(result.summary_path)),
            "quality_audit_csv_path": self._relative_upload_path(str(result.quality_audit_path)),
            "run_manifest_path": self._relative_upload_path(str(result.manifest_path)),
            "sample_limit": 15,
        }
        metadata["coordinate_preview"] = preview
        metadata["chart_data_csv_path"] = preview["coordinate_csv_path"]
        metadata["chart_data_overlay_path"] = preview["overlay_path"]
        metadata["chart_data_quality"] = preview["data_quality"]
        metadata["chart_data_row_count"] = preview["row_count"]
        metadata["coordinate_samples_extracted"] = bool(preview["coordinate_csv_path"])
        metadata["precise_values_extracted"] = processed.get("status") == "accepted"
        if processed.get("status") != "accepted":
            metadata.setdefault("warnings", []).append("coordinate_preview_requires_review")
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _metadata(self, asset: DocumentAsset) -> dict[str, Any]:
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
            return candidate.resolve().relative_to(self.file_storage.upload_dir.resolve()).as_posix()
        except ValueError:
            return path
