from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models import DocumentAsset
from app.schemas.paper import CoordinatePreviewRead
from app.services.chart_extraction import process_mineru_image_batch
from app.services.extraction.csv_exporter import _semantic_axis_field
from app.services.file_storage import FileStorageService
from app.services.paper.evidence import normalize_evidence_type


CHART_TYPE_HINTS = {
    "rheology_strain_sweep": "strain sweep G' G'' storage modulus loss modulus Pa %",
    "rheology_flow_curve": "flow curve viscosity shear rate steady-state flow s^-1 mPa*s",
    "rheology_step_time_sweep": "time sweep viscosity shear rate recovery time s Pa mPa*s",
    "biphasic_time_series": "phase I phase II biphasic time series viscosity shear rate",
    "line_plot": "line chart time series",
    "multi_line_plot": "multi line multiple curves legend groups",
    "bar_chart": "bar chart grouped bar yield modulus toughness",
    "bar_or_line_with_errorbar": "error bar mean SD significance n=3",
    "scatter_plot": "scatter plot correlation calibration curve fit",
    "heatmap_matrix": "heatmap matrix colorbar fluorescence expression",
    "spectrum_curve": "spectrum FTIR XRD EDS UV-vis wavenumber 2theta",
    "2d_field_map": "2d field map concentration diffusion energy colorbar",
    "microscopy_quant": "microscopy SEM TEM fluorescence scale bar cells pores",
    "multi_panel_composite": "combined figure multi-panel parent figure",
}

COORDINATE_ASSET_IMAGE_TYPES = {
    "2d_field_map",
    "bar",
    "bar_chart",
    "bar_or_line_with_errorbar",
    "biphasic_time_series",
    "coordinate_plot",
    "dual_axis_plot",
    "generic_coordinate_plot",
    "grouped_bar",
    "heatmap_matrix",
    "line",
    "line_chart",
    "line_plot",
    "multi_line_plot",
    "rheology_flow_curve",
    "rheology_step_time_sweep",
    "rheology_strain_sweep",
    "scatter",
    "scatter_plot",
    "spectrum_curve",
}

NON_COORDINATE_ASSET_IMAGE_TYPES = {
    "flowchart",
    "material_image",
    "microscope_image",
    "microscopy_quant",
    "molecular_structure",
    "multi_panel_composite",
    "natural_image",
    "non_data_image",
    "page_or_figure",
    "photo",
    "schematic",
    "schematic_or_photo",
    "text_image",
}
NON_COORDINATE_MINERU_SUB_TYPES = {
    "flowchart",
    "natural_image",
    "photo",
    "schematic",
    "text_image",
}

NON_COORDINATE_SOURCES = {"fallback_snapshot", "page_visual_snapshot"}
NON_COORDINATE_TEXT_HINTS = {
    "组合图",
    "复合",
    "示意",
    "流程",
    "结构",
    "照片",
    "显微",
    "无坐标",
    "molecular",
    "trajectory",
    "schematic",
    "photo",
    "microscopy",
    "micrograph",
}
NON_COORDINATE_PREVIEW_TYPES = {"multi_panel_composite", "schematic_or_photo", "microscopy_quant"}


def is_coordinate_asset(asset: DocumentAsset, metadata: dict[str, Any]) -> bool:
    if not asset.file_path or asset.asset_type != "figure":
        return False

    source = str(metadata.get("source") or "")
    if source in NON_COORDINATE_SOURCES:
        return False
    if _has_non_coordinate_type(metadata):
        return False
    if source == "extracted_image":
        return _truthy(metadata.get("data_extraction_possible"))

    image_type = _metadata_image_type(metadata)
    if _looks_like_non_coordinate_asset(metadata):
        return False
    if image_type in COORDINATE_ASSET_IMAGE_TYPES:
        return True

    evidence_type = normalize_evidence_type(asset=asset, metadata=metadata)
    if evidence_type != "chart":
        return False

    if _truthy(metadata.get("data_extraction_possible")):
        return True

    return source in {"mineru_chart", "rendered_figure_region"} and str(metadata.get("visual_role") or "") in {"chart", "chart_candidate"}


def coordinate_preview_read(asset: DocumentAsset, metadata: dict) -> CoordinatePreviewRead | None:
    preview = metadata.get("coordinate_preview")
    if not isinstance(preview, dict):
        return None
    csv_path = str(preview.get("coordinate_csv_path") or metadata.get("chart_data_csv_path") or "")
    if not csv_path:
        return None
    return CoordinatePreviewRead(
        image_type=str(preview.get("image_type") or ""),
        status=str(preview.get("status") or ""),
        row_count=int(preview.get("row_count") or 0),
        data_quality=str(preview.get("data_quality") or ""),
        sample_limit=int(preview.get("sample_limit") or 15),
        csv_url=f"/papers/assets/{asset.id}/coordinate-preview.csv",
        overlay_path=str(preview.get("overlay_path") or "") or None,
        summary_csv_path=str(preview.get("summary_csv_path") or "") or None,
        quality_audit_csv_path=str(preview.get("quality_audit_csv_path") or "") or None,
        run_manifest_path=str(preview.get("run_manifest_path") or "") or None,
        selected_extractor=str(preview.get("selected_extractor") or ""),
        reason=str(preview.get("reason") or ""),
        chart_type_hint=str(preview.get("chart_type_hint") or ""),
        targets=[str(item) for item in preview.get("targets", []) if item],
        request_id=str(preview.get("request_id") or ""),
        triggered_at=_parse_preview_datetime(preview.get("triggered_at")),
        semantic_binding=str(preview.get("semantic_binding") or ""),
        review_status=str(preview.get("review_status") or ""),
        review_notes=str(preview.get("review_notes") or ""),
        extraction_method=str(preview.get("extraction_method") or ""),
        text_evidence_refs=[str(item) for item in preview.get("text_evidence_refs", []) if item],
        semantic_columns=[str(item) for item in preview.get("semantic_columns", []) if item],
    )


def run_coordinate_preview_for_asset(
    *,
    asset: DocumentAsset,
    storage: FileStorageService,
    chart_type: str = "auto",
    targets: list[str] | None = None,
    sample_limit: int = 120,
    force_regenerate: bool = False,
) -> CoordinatePreviewRead:
    if not asset.file_path:
        raise ValueError("Image asset has no file path.")

    image_path = storage.get_file_path(asset.file_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image asset file not found: {asset.file_path}")

    metadata = _metadata(asset)
    out_dir = storage.upload_dir / str(asset.document.user_id) / "asset-coordinate-csv" / str(asset.document_id) / str(asset.id)
    if force_regenerate and out_dir.exists():
        for path in out_dir.glob("*"):
            if path.is_file():
                path.unlink()
    content_list_path = _write_single_asset_content_list(
        asset=asset,
        metadata=metadata,
        image_path=image_path,
        out_dir=out_dir,
        chart_type=chart_type,
        targets=targets or [],
    )
    result = process_mineru_image_batch(
        images_dir=image_path.parent,
        content_list_path=content_list_path,
        out_dir=out_dir,
        sample_limit=sample_limit,
        image_path=image_path,
    )
    if not result.processed:
        raise ValueError(f"图片处理失败：未能加载或识别图片 {image_path.name}。请检查图片是否存在且格式正确。")
    processed = result.processed[0]
    if processed.get("image_type") in NON_COORDINATE_PREVIEW_TYPES or processed.get("selected_extractor") == "CompositeReviewExtractor":
        raise ValueError("该图片被识别为复合父图/非坐标图，不能生成坐标 CSV。请点击单个坐标图面板资产。")
    preview = _preview_payload(
        storage=storage,
        result=result,
        processed=processed,
        chart_type=chart_type,
        targets=targets or [],
        sample_limit=sample_limit,
    )
    metadata["coordinate_preview"] = preview
    metadata["chart_data_csv_path"] = preview["coordinate_csv_path"]
    metadata["chart_data_quality"] = preview["data_quality"]
    metadata["chart_data_row_count"] = preview["row_count"]
    metadata["coordinate_samples_extracted"] = bool(preview["coordinate_csv_path"])
    metadata["precise_values_extracted"] = processed.get("status") == "accepted"
    asset.metadata_json = json.dumps(metadata, ensure_ascii=False)
    return coordinate_preview_read(asset, metadata) or CoordinatePreviewRead(**preview)


def _write_single_asset_content_list(
    *,
    asset: DocumentAsset,
    metadata: dict[str, Any],
    image_path: Path,
    out_dir: Path,
    chart_type: str,
    targets: list[str],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    hint = _chart_type_hint(chart_type, targets)
    caption = _asset_caption(asset, metadata)
    content = _asset_chart_content(metadata) or " ".join(text for text in [caption, hint] if text)
    item = {
        "type": "chart",
        "sub_type": _sub_type_for(chart_type, metadata),
        "img_path": f"images/{image_path.name}",
        "chart_caption": [text for text in [caption, hint] if text],
        "content": content,
    }
    path = out_dir / "asset_content_list.json"
    path.write_text(json.dumps([item], ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _preview_payload(
    *,
    storage: FileStorageService,
    result: Any,
    processed: dict,
    chart_type: str,
    targets: list[str],
    sample_limit: int,
) -> dict:
    semantic_columns = _preview_semantic_columns(processed)
    return {
        "image_type": processed.get("image_type") or "",
        "status": processed.get("status") or "",
        "reason": processed.get("reason") or "",
        "row_count": processed.get("row_count") or 0,
        "data_quality": processed.get("data_quality") or "",
        "coordinate_csv_path": _relative_upload_path(storage, str(processed.get("csv_path") or "")),
        "summary_csv_path": _relative_upload_path(storage, str(result.summary_path)),
        "quality_audit_csv_path": _relative_upload_path(storage, str(result.quality_audit_path)),
        "run_manifest_path": _relative_upload_path(storage, str(result.manifest_path)),
        "sample_limit": sample_limit,
        "selected_extractor": processed.get("selected_extractor") or "",
        "chart_type_hint": "" if chart_type in {"", "auto"} else chart_type,
        "targets": targets,
        "request_id": uuid4().hex[:12],
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "semantic_binding": _semantic_binding_label(processed),
        "review_status": processed.get("review_status") or processed.get("status") or "",
        "review_notes": processed.get("review_notes") or "",
        "extraction_method": processed.get("extraction_method") or "",
        "text_evidence_refs": _preview_text_refs(processed),
        "semantic_columns": semantic_columns,
    }


def _semantic_binding_label(processed: dict) -> str:
    for key in ("axis_label_binding_method", "axis_calibration_method"):
        value = str(processed.get(key) or "").strip()
        if value:
            return value
    return ""


def _preview_text_refs(processed: dict) -> list[str]:
    raw = processed.get("text_evidence_refs")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _preview_semantic_columns(processed: dict) -> list[str]:
    x_label = _semantic_axis_field(
        processed.get("x_axis_label"),
        processed.get("x_unit"),
        processed.get("indicator"),
        processed.get("text_evidence_refs"),
        axis_name="x",
    )
    y_label = _semantic_axis_field(
        processed.get("y_axis_label"),
        processed.get("y_unit"),
        processed.get("indicator"),
        processed.get("text_evidence_refs"),
        axis_name="y",
    )
    return [label for label in [x_label, y_label] if label]


def _parse_preview_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata(asset: DocumentAsset) -> dict[str, Any]:
    try:
        parsed = json.loads(asset.metadata_json or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _asset_chart_content(metadata: dict[str, Any]) -> str:
    for key in ("mineru_content", "chart_content", "content"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_image_type(metadata: dict[str, Any]) -> str:
    preview = metadata.get("coordinate_preview")
    preview_type = preview.get("image_type") if isinstance(preview, dict) else None
    for value in (
        preview_type,
        metadata.get("image_type"),
        metadata.get("chart_type"),
        metadata.get("figure_type"),
        metadata.get("mineru_sub_type"),
    ):
        normalized = str(value or "").strip().lower()
        if normalized:
            return normalized
    return ""


def _has_non_coordinate_type(metadata: dict[str, Any]) -> bool:
    for key in ("image_type", "chart_type", "figure_type"):
        value = str(metadata.get(key) or "").strip().lower()
        if value in NON_COORDINATE_ASSET_IMAGE_TYPES:
            return True
    mineru_sub_type = str(metadata.get("mineru_sub_type") or "").strip().lower()
    return any(hint in mineru_sub_type for hint in NON_COORDINATE_MINERU_SUB_TYPES)


def _looks_like_non_coordinate_asset(metadata: dict[str, Any]) -> bool:
    text = " ".join(
        str(metadata.get(key) or "").lower()
        for key in ("figure_type", "caption", "agent_description", "context")
    )
    return any(hint in text for hint in NON_COORDINATE_TEXT_HINTS)


def _asset_caption(asset: DocumentAsset, metadata: dict[str, Any]) -> str:
    parts = [
        asset.label or "",
        asset.caption or "",
        str(metadata.get("figure_label") or ""),
        str(metadata.get("caption") or ""),
        str(metadata.get("figure_type") or ""),
        str(metadata.get("agent_description") or ""),
        str(metadata.get("context") or ""),
    ]
    text = " ".join(part for part in parts if part)
    return re.sub(r"\s+", " ", text).strip()[:1800]


def _chart_type_hint(chart_type: str, targets: list[str]) -> str:
    normalized = (chart_type or "auto").strip()
    target_text = " ".join(targets)
    if normalized in {"", "auto"}:
        return target_text
    return f"{normalized} {CHART_TYPE_HINTS.get(normalized, '')} {target_text}".strip()


def _sub_type_for(chart_type: str, metadata: dict[str, Any]) -> str:
    normalized = (chart_type or "auto").strip()
    if normalized not in {"", "auto"}:
        return normalized
    for key in ("chart_type", "image_type", "figure_type"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return "chart"


def _relative_upload_path(storage: FileStorageService, path: str) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(storage.upload_dir.resolve()).as_posix()
    except ValueError:
        return path


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}
