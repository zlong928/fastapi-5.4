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
    for row in rows:
        method = str(row.get("axis_calibration_method") or "")
        image_type = str(row.get("image_type") or "")
        x_axis_type = str(row.get("x_axis_type") or "")
        y_axis_type = str(row.get("y_axis_type") or "")
        y_right_value = row.get("y_right_value")
        reasons: list[str] = []
        confidence = 0.35
        data_quality = "review_only"
        needs_review = True

        if method == "mineru_chart_table":
            data_quality = "mineru_chart_table_bound"
            confidence = 0.86
            needs_review = False
        elif image_type == "multi_line_plot":
            data_quality = "multi_line_legend_review_sample"
            legend_status = str(row.get("legend_binding_status") or "")
            text_confidence = _float_or_none(row.get("legend_text_confidence"))
            confidence = (
                0.72
                if legend_status == "text_bound_review" and text_confidence is not None and text_confidence >= 80
                else 0.68
                if legend_status == "text_bound_review"
                else 0.6
                if legend_status == "color_bound_review"
                else 0.5
            )
            needs_review = True
            if legend_status == "text_bound_review":
                reasons.append("legend_text_ocr_bound_requires_review")
            elif legend_status == "color_bound_review":
                reasons.append("legend_color_bound_but_text_label_requires_review")
            else:
                reasons.append("legend_series_binding_requires_review")
        elif method == "known_log_axis":
            data_quality = "known_axis_calibrated"
            confidence = 0.9
            needs_review = False
        elif method == "stacked_time_series_xy_known":
            data_quality = "known_panel_axis_calibrated"
            confidence = 0.82
            needs_review = False
        elif image_type in {"bar_chart", "bar_or_line_with_errorbar"}:
            data_quality = "bar_chart_review_sample"
            geometry_status = str(row.get("bar_geometry_status") or "")
            category_status = str(row.get("category_binding_status") or "")
            category_confidence = _float_or_none(row.get("category_text_confidence"))
            errorbar_status = str(row.get("errorbar_binding_status") or "")
            confidence = (
                0.72
                if (
                    geometry_status == "bar_body_and_errorbar_detected"
                    and category_status == "text_bound_review"
                    and category_confidence is not None
                    and category_confidence >= 80
                    and errorbar_status == "vertical_errorbar_detected_review"
                )
                else 0.7
                if geometry_status == "bar_body_and_errorbar_detected" and category_status == "text_bound_review"
                else 0.64
                if geometry_status == "bar_body_detected" and category_status == "text_bound_review"
                else
                0.62
                if geometry_status == "bar_body_and_errorbar_detected"
                else 0.56
                if geometry_status == "bar_body_detected"
                else 0.45
            )
            needs_review = True
            if category_status == "text_bound_review" and geometry_status == "bar_body_and_errorbar_detected":
                reasons.append("bar_category_text_and_errorbar_bound_require_review")
            elif category_status == "text_bound_review":
                reasons.append("bar_category_text_bound_requires_review")
            elif geometry_status == "bar_body_and_errorbar_detected":
                reasons.append("bar_body_and_errorbar_detected_but_category_labels_require_review")
            elif geometry_status == "bar_body_detected":
                reasons.append("bar_body_detected_but_category_labels_require_review")
            else:
                reasons.append("bar_category_binding_and_errorbar_geometry_require_review")
        elif image_type == "spectrum_curve":
            data_quality = "spectrum_curve_review_sample"
            confidence = 0.5
            needs_review = True
            reasons.append("spectrum_peak_baseline_and_scan_axis_require_review")
        elif image_type == "scatter_plot":
            data_quality = "scatter_plot_review_sample"
            scatter_status = str(row.get("scatter_geometry_status") or "")
            confidence = 0.62 if scatter_status == "fit_line_detected" else 0.52
            needs_review = True
            if scatter_status == "fit_line_detected":
                reasons.append("scatter_fit_line_detected_but_point_set_requires_review")
            else:
                reasons.append("scatter_series_binding_and_fit_curve_require_review")
        elif image_type == "heatmap_matrix":
            data_quality = "heatmap_color_grid_review_sample"
            colorbar_status = str(row.get("colorbar_binding_status") or "")
            colorbar_confidence = _float_or_none(row.get("colorbar_tick_confidence"))
            confidence = (
                0.66
                if colorbar_status == "colorbar_ticks_bound_review"
                and colorbar_confidence is not None
                and colorbar_confidence >= 80
                else 0.62
                if colorbar_status == "colorbar_ticks_bound_review"
                else 0.48
            )
            needs_review = True
            if colorbar_status == "colorbar_ticks_bound_review":
                reasons.append("heatmap_colorbar_ticks_bound_but_cell_labels_require_review")
            else:
                reasons.append("heatmap_colorbar_mapping_and_cell_labels_require_review")
        elif image_type == "2d_field_map":
            data_quality = "2d_field_map_grid_review_sample"
            colorbar_status = str(row.get("colorbar_binding_status") or "")
            colorbar_confidence = _float_or_none(row.get("colorbar_tick_confidence"))
            confidence = (
                0.64
                if colorbar_status == "colorbar_ticks_bound_review"
                and colorbar_confidence is not None
                and colorbar_confidence >= 80
                else 0.6
                if colorbar_status == "colorbar_ticks_bound_review"
                else 0.46
            )
            needs_review = True
            if colorbar_status == "colorbar_ticks_bound_review":
                reasons.append("field_colorbar_ticks_bound_but_spatial_scale_requires_review")
            else:
                reasons.append("field_colorbar_mapping_and_spatial_scale_require_review")
        elif image_type == "microscopy_quant":
            data_quality = "microscopy_quant_review_sample"
            object_method = str(row.get("object_classification_method") or "")
            scale_bar_status = str(row.get("scale_bar_binding_status") or "")
            confidence = (
                0.62
                if method == "microscopy_scale_bar_review"
                and scale_bar_status == "scale_bar_caption_and_segment_bound_review"
                and object_method == "caption_keyword_hint_review"
                else 0.56
                if method == "microscopy_scale_bar_review"
                else 0.42
            )
            needs_review = True
            if method == "microscopy_scale_bar_review":
                reasons.append("scale_bar_detected_but_object_classification_requires_review")
            else:
                reasons.append("scale_bar_and_object_classification_require_review")
        elif method == "ocr_ticks":
            data_quality = "ocr_axis_calibrated"
            confidence = 0.72
            if str(row.get("extraction_method") or "") == "local_cv_stacked_panel_review_sample":
                data_quality = "ocr_axis_title_bound_review"
                confidence = min(confidence, 0.68)
                reasons.append("stacked_panel_axis_title_bound_but_panel_calibration_requires_review")
            elif str(row.get("x_axis_label")) == "normalized_x" or str(row.get("y_axis_label")) == "normalized_y":
                data_quality = "ocr_axis_unlabeled"
                confidence = min(confidence, 0.65)
                reasons.append("axis_label_not_extracted")
            elif row.get("axis_label_binding_method") == "ocr_axis_title" and (
                image_type == "coordinate_plot"
                or row.get("raw_image_type") == "coordinate_plot"
                or row.get("selected_extractor") == "CoordinatePlotExtractor"
            ):
                data_quality = "ocr_axis_title_bound_review"
                confidence = min(confidence, 0.68)
                if str(row.get("extraction_method") or "") == "local_cv_stacked_panel_review_sample":
                    reasons.append("stacked_panel_axis_title_bound_but_panel_calibration_requires_review")
                else:
                    reasons.append("axis_title_bound_but_tick_calibration_requires_review")
            if image_type == "line_plot" and y_right_value not in {"", None}:
                data_quality = "ocr_axis_unbound"
                confidence = min(confidence, 0.62)
                reasons.append("series_to_left_or_right_y_axis_not_bound")
            needs_review = bool(reasons)
        elif image_type in {"biphasic_time_series", "stacked_time_series"} or method == "stacked_time_series_x_ocr":
            data_quality = "partial_panel_normalized"
            confidence = 0.55
            needs_review = True
            reasons.append("x_axis_calibrated_but_panel_y_axis_is_normalized")
        elif method == "known_log_y_axis":
            data_quality = "partial_axis_calibrated"
            confidence = 0.58
            needs_review = True
            reasons.append("y_axis_calibrated_but_x_axis_is_normalized")
        elif method == "normalized_fallback" or x_axis_type == "normalized" or y_axis_type == "normalized":
            data_quality = "pixel_or_normalized_only"
            confidence = 0.35
            needs_review = True
            reasons.append("axis_ticks_not_reliably_calibrated")

        try:
            if y_right_value not in {"", None} and float(y_right_value) < 0:
                reasons.append("right_y_value_outside_axis_range")
                confidence = min(confidence, 0.5)
                needs_review = True
        except ValueError:
            pass

        if method not in {"known_log_axis", "stacked_time_series_xy_known"} and int(row.get("component_area_px") or 0) < 12:
            reasons.append("small_detected_component")
            confidence = min(confidence, 0.5)
            needs_review = True

        row["data_quality"] = data_quality
        row["extraction_confidence"] = round(confidence, 2)
        row["needs_review"] = "true" if needs_review else "false"
        row["review_reason"] = ";".join(dict.fromkeys(reasons))


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
