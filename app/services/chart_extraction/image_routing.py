from __future__ import annotations

import re
from typing import Any

import numpy as np
from app.services.chart_extraction.chart_recipes import line_plot_recipe
from app.services.chart_extraction.models import ImageRecord


FLOWCHART_HINTS = {"flowchart", "schematic", "photo", "natural_image"}
MULTI_LINE_HINTS = {
    "multi line",
    "multi-line",
    "multiple line",
    "multiple curve",
    "multiple curves",
    "different groups",
    "different materials",
    "legend",
}
BAR_HINTS = {"bar chart", "bar plot", "column chart", "column plot", "histogram", "grouped bar"}
ERRORBAR_HINTS = {"error bar", "errorbar", "mean ± sd", "mean±sd", "standard error", "n=3"}
FIELD_2D_HINTS = {
    "2d field",
    "2-d field",
    "field map",
    "simulation field",
    "diffusion field",
    "concentration field",
    "energy terrain",
    "energy landscape",
    "n2/h2",
    "n₂/h₂",
    "gradient map",
    "contour map",
}
HEATMAP_HINTS = {
    "heatmap",
    "heat map",
    "matrix",
    "colorbar",
    "color bar",
    "expression",
    "fluorescence intensity matrix",
    "concentration map",
    "metabolite",
    "clustered map",
}
SCATTER_HINTS = {
    "scatter",
    "scatter plot",
    "correlation",
    "linear fit",
    "fitting curve",
    "calibration curve",
    "standard curve",
    "r2",
    "r²",
    "pore size",
    "diameter",
    "intensity relationship",
}
SPECTRUM_HINTS = {
    "ftir",
    "xrd",
    "eds",
    "uv-vis",
    "uv vis",
    "uv/vis",
    "tga",
    "dsc",
    "raman",
    "xps",
    "spectrum",
    "spectra",
    "wavenumber",
    "2θ",
    "2theta",
    "frequency sweep",
    "frequency scan",
    "strain sweep",
    "strain scan",
    "storage modulus",
    "loss modulus",
}
STRONG_MICROSCOPY_HINTS = {
    "microscopy",
    "micrograph",
    "sem",
    "tem",
    "confocal",
    "fluorescence image",
    "eds mapping",
    "element mapping",
    "scale bar",
}
GENERIC_MICROSCOPY_HINTS = {
    "cell",
    "cells",
    "pore",
    "pores",
    "carbonate deposits",
    "element distribution",
}


def is_flowchart(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    return any(hint in subtype for hint in FLOWCHART_HINTS) or "schematic" in caption


def is_large_composite(record: ImageRecord, image: np.ndarray) -> bool:
    height, width = image.shape[:2]
    caption = record.caption.lower()
    return width >= 800 or height >= 800 or "(a and b)" in caption or "rheology and shape retention" in caption


def is_line_chart(record: ImageRecord, image: np.ndarray) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    if "line" in subtype or "line chart" in caption:
        return True
    return line_plot_recipe(record) is not None


def is_multi_line_plot(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    if any(hint in haystack for hint in MULTI_LINE_HINTS):
        return True
    return ("line" in subtype or "curve" in caption) and "legend" in caption


def is_bar_chart(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in BAR_HINTS)


def is_errorbar_chart(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in ERRORBAR_HINTS)


def is_2d_field_map(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in FIELD_2D_HINTS)


def is_heatmap_matrix(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in HEATMAP_HINTS)


def is_scatter_plot(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in SCATTER_HINTS)


def is_spectrum_curve(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    return any(hint in haystack for hint in SPECTRUM_HINTS)


def is_microscopy_quant(record: ImageRecord) -> bool:
    subtype = record.mineru_sub_type.lower()
    caption = record.caption.lower()
    haystack = f"{subtype} {caption}"
    if any(hint in haystack for hint in STRONG_MICROSCOPY_HINTS):
        return True
    if subtype in {"flowchart", "schematic", "text_image"}:
        return False
    return any(re.search(rf"\b{re.escape(hint)}\b", haystack) for hint in GENERIC_MICROSCOPY_HINTS)


def skip_reason(record: ImageRecord, image: np.ndarray) -> str | None:
    if is_microscopy_quant(record):
        return None
    if is_flowchart(record):
        return "schematic_or_photo_caption_only"
    if is_large_composite(record, image):
        return "multi_panel_composite_review_only"
    return None


def route_image_type(
    record: ImageRecord,
    image: np.ndarray,
    stacked_extractor: Any,
) -> str:
    if stacked_extractor.matches(record):
        return stacked_extractor.image_type
    if is_microscopy_quant(record):
        return "microscopy_quant"
    if is_2d_field_map(record):
        return "2d_field_map"
    if is_heatmap_matrix(record):
        return "heatmap_matrix"
    if is_errorbar_chart(record):
        return "bar_or_line_with_errorbar"
    if is_bar_chart(record):
        return "bar_chart"
    if is_scatter_plot(record):
        return "scatter_plot"
    if is_spectrum_curve(record):
        return "spectrum_curve"
    if is_multi_line_plot(record):
        return "multi_line_plot"
    if is_line_chart(record, image):
        return "line_plot"
    return "coordinate_plot"


def refine_image_type_from_extracted_axes(record: ImageRecord, image_type: str, points: list[dict]) -> str:
    if image_type != "coordinate_plot":
        return image_type

    axis_text = _axis_text(record, points)
    if any(str(point.get("panel_id") or "") in {"upper_panel", "lower_panel"} for point in points):
        return "line_plot"
    if _looks_like_spectrum_or_rheology(axis_text):
        return "spectrum_curve"
    if _looks_like_time_series(axis_text):
        return "line_plot"
    return image_type


def _axis_text(record: ImageRecord, points: list[dict]) -> str:
    parts = [record.mineru_sub_type, record.caption]
    for point in points[:8]:
        parts.extend(
            [
                str(point.get("x_axis_label") or ""),
                str(point.get("x_axis_unit") or ""),
                str(point.get("y_axis_label") or ""),
                str(point.get("y_axis_unit") or ""),
                str(point.get("z_axis_label") or ""),
                str(point.get("z_axis_unit") or ""),
            ]
        )
    return " ".join(parts).lower()


def _looks_like_spectrum_or_rheology(axis_text: str) -> bool:
    spectrum_axis_hints = {
        "wavenumber",
        "frequency",
        "2θ",
        "2theta",
        "binding energy",
        "raman shift",
        "strain",
        "storage modulus",
        "loss modulus",
        "g'",
        "g''",
        "modulus",
    }
    return any(hint in axis_text for hint in SPECTRUM_HINTS | spectrum_axis_hints)


def _looks_like_time_series(axis_text: str) -> bool:
    time_axis_hints = {"time", "day", "days", "hour", "hours", "min", "minute", "minutes", "s ", "sec"}
    return any(hint in axis_text for hint in time_axis_hints)
