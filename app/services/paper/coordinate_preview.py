from __future__ import annotations

from app.models import DocumentAsset
from app.schemas.paper import CoordinatePreviewRead


def coordinate_preview_read(asset: DocumentAsset, metadata: dict) -> CoordinatePreviewRead | None:
    preview = metadata.get("coordinate_preview")
    if not isinstance(preview, dict):
        return None
    csv_path = str(preview.get("coordinate_csv_path") or metadata.get("chart_data_csv_path") or "")
    if not csv_path:
        return None
    return CoordinatePreviewRead(
        status=str(preview.get("status") or ""),
        row_count=int(preview.get("row_count") or 0),
        data_quality=str(preview.get("data_quality") or ""),
        sample_limit=int(preview.get("sample_limit") or 15),
        csv_url=f"/papers/assets/{asset.id}/coordinate-preview.csv",
        overlay_path=str(preview.get("overlay_path") or "") or None,
        summary_csv_path=str(preview.get("summary_csv_path") or "") or None,
        quality_audit_csv_path=str(preview.get("quality_audit_csv_path") or "") or None,
        run_manifest_path=str(preview.get("run_manifest_path") or "") or None,
    )
