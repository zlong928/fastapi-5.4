from __future__ import annotations


def _truthy(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def _float_or_none(value: object) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def annotate_quality(rows: list[dict]) -> None:
    """Annotate quality metrics. Review logic is now handled by auto_refinement.py."""
    for row in rows:
        method = str(row.get("axis_calibration_method") or "")
        image_type = str(row.get("image_type") or "")
        
        # 设置置信度和数据质量（移除 needs_review 和 reasons）
        confidence = row.get("confidence", 0.35)
        data_quality = row.get("data_quality", "standard")
        
        # 根据方法和图表类型调整置信度
        if method == "mineru_chart_table":
            confidence = 0.86
            data_quality = "mineru_chart_table_bound"
        elif image_type == "multi_panel_composite":
            confidence = 0.9
        elif image_type == "rheology_flow_curve":
            confidence = _float_or_none(row.get("axis_confidence")) or 0.62
        elif method == "known_log_axis":
            confidence = 0.9
        elif method == "ocr_ticks":
            confidence = 0.72
        
        # 更新行数据（不再设置 needs_review 和 review_reason）
        row.update({
            "confidence": confidence,
            "data_quality": data_quality,
        })
def image_status_from_rows(rows: list[dict]) -> str:
    if not rows:
        return "empty"
    if any(_truthy(row.get("needs_review")) for row in rows):
        return "review_required"
    return "accepted"


def summarize_quality(rows: list[dict]) -> dict:
    total = len(rows)
    review_count = sum(1 for row in rows if _truthy(row.get("needs_review")))
    accepted_count = total - review_count
    qualities = sorted({str(row.get("data_quality") or "") for row in rows if row.get("data_quality")})
    recipe_ids = sorted({str(row.get("recipe_id") or "") for row in rows if row.get("recipe_id")})
    panel_ids = sorted({str(row.get("panel_id") or "") for row in rows if row.get("panel_id")})
    calibration_methods = sorted(
        {str(row.get("axis_calibration_method") or "") for row in rows if row.get("axis_calibration_method")}
    )
    review_reasons = sorted(
        {
            reason
            for row in rows
            for reason in str(row.get("review_reason") or "").split(";")
            if reason
        }
    )
    return {
        "accepted_row_count": accepted_count,
        "review_row_count": review_count,
        "data_quality": "|".join(qualities),
        "recipe_ids": "|".join(recipe_ids),
        "panel_ids": "|".join(panel_ids),
        "axis_calibration_methods": "|".join(calibration_methods),
        "review_reasons": "|".join(review_reasons),
    }
