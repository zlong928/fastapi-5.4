from __future__ import annotations

import re

import cv2
import numpy as np

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.chart_recipes import line_plot_recipe
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import (
    classify_mark_color,
    colored_curve_points,
    component_points,
    merge_marker_components,
)
from app.services.chart_extraction.image_routing import is_multi_line_plot
from app.services.chart_extraction.plot_geometry import detect_stacked_plot_panels

try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None


def _clean_legend_text(text: str) -> str:
    cleaned = " ".join(text.replace("|", " ").replace("_", " ").split())
    return cleaned.strip(" .,:;")


def legend_markers(image: np.ndarray, area: tuple[int, int, int, int]) -> list[dict]:
    x0, y0, x1, y1 = area
    crop = image[y0 : y1 + 1, x0 : x1 + 1]
    height, width = crop.shape[:2]
    if crop.size == 0:
        return []

    return _colored_marker_candidates(crop, x0, y0, max_area=max(500, int(width * height * 0.015)))


def _colored_marker_candidates(crop: np.ndarray, x0: int, y0: int, max_area: int) -> list[dict]:
    height, width = crop.shape[:2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 45)).astype("uint8") * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    markers: list[dict] = []
    for label in range(1, num):
        area_px = int(stats[label, cv2.CC_STAT_AREA])
        if not (8 <= area_px <= max_area):
            continue
        lx = int(stats[label, cv2.CC_STAT_LEFT])
        ly = int(stats[label, cv2.CC_STAT_TOP])
        lw = int(stats[label, cv2.CC_STAT_WIDTH])
        lh = int(stats[label, cv2.CC_STAT_HEIGHT])
        if lw > max(80, int(width * 0.22)) or lh > max(30, int(height * 0.12)):
            continue
        cx, cy = centroids[label]
        comp = labels == label
        pix_bgr = crop[comp]
        mean_bgr = pix_bgr.mean(axis=0)
        color = classify_mark_color(np.array([mean_bgr[2], mean_bgr[1], mean_bgr[0]]))
        markers.append(
            {
                "legend_label": color,
                "color_group": color,
                "legend_marker_x": round(float(cx + x0), 1),
                "legend_marker_y": round(float(cy + y0), 1),
                "legend_marker_area_px": area_px,
                "bbox": (lx + x0, ly + y0, lx + lw + x0, ly + lh + y0),
            }
        )
    markers.sort(key=lambda item: (float(item["legend_marker_y"]), float(item["legend_marker_x"])))
    return markers


def bind_legend_text(image: np.ndarray, area: tuple[int, int, int, int], markers: list[dict]) -> list[dict]:
    if pytesseract is None or not markers:
        return markers

    x0, y0, x1, y1 = area
    crop = image[y0 : y1 + 1, x0 : x1 + 1]
    height, width = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    try:
        data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return markers

    token_rows: list[dict] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = _clean_legend_text(str(raw_text))
        if not text or not any(ch.isalnum() for ch in text):
            continue
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        if confidence < 20:
            continue
        left = float(data["left"][index]) / 2 + x0
        top = float(data["top"][index]) / 2 + y0
        width_px = float(data["width"][index]) / 2
        height_px = float(data["height"][index]) / 2
        token_rows.append(
            {
                "text": text,
                "left": left,
                "right": left + width_px,
                "cy": top + height_px / 2,
                "confidence": confidence,
            }
        )

    for marker in markers:
        marker_x = float(marker["legend_marker_x"])
        marker_y = float(marker["legend_marker_y"])
        nearby = [
            token
            for token in token_rows
            if marker_x - 2 <= token["left"] <= marker_x + max(90, width * 0.45)
            and abs(float(token["cy"]) - marker_y) <= 16
        ]
        if not nearby:
            continue
        nearby.sort(key=lambda token: float(token["left"]))
        label = _clean_legend_text(" ".join(str(token["text"]) for token in nearby[:4]))
        if label:
            marker["legend_label"] = label
            marker["legend_text_confidence"] = round(
                sum(float(token["confidence"]) for token in nearby[:4]) / len(nearby[:4]),
                1,
            )
    return markers


def _series_metadata_from_label(label: str) -> dict:
    cleaned = _clean_legend_text(label)
    metadata = {"series_label_raw": cleaned}
    wt_match = re.search(r"(?P<value>\d+(?:\.\d+)?)\s*(?:w|wt)\s*%?", cleaned, flags=re.IGNORECASE)
    if wt_match:
        value = wt_match.group("value")
        metadata.update(
            {
                "series_variable": "Flink loading",
                "series_value": value,
                "series_unit": "wt %",
                "series_role": "formulation_level",
            }
        )
    lowered = cleaned.lower()
    has_storage = "g'" in lowered or "g’" in lowered
    has_loss = "g''" in lowered or 'g"' in lowered or "g’’" in lowered
    if has_storage and has_loss:
        metadata.setdefault("series_role", "modulus_pair_review")
        metadata.setdefault("series_variable", "G'/G''")
    elif has_storage:
        metadata.setdefault("series_role", "storage_modulus")
        metadata.setdefault("series_variable", "G'")
    elif has_loss:
        metadata.setdefault("series_role", "loss_modulus")
        metadata.setdefault("series_variable", "G''")
    return metadata


def _is_useful_legend_label(label: str) -> bool:
    cleaned = _clean_legend_text(label)
    if cleaned.lower() in {"blue", "green", "orange", "brown", "dark brown", "dark_brown", "gray", "red"}:
        return False
    if re.search(r"\d+\s*(?:w|wt)\s*%?", cleaned, flags=re.IGNORECASE):
        return True
    if any(token in cleaned.lower() for token in {"flink", "control", "treated"}):
        return True
    if "g'" in cleaned.lower() or 'g"' in cleaned.lower():
        return True
    return len(cleaned) >= 4 and sum(ch.isalpha() for ch in cleaned) >= 3


def apply_legend_binding(points: list[dict], markers: list[dict]) -> None:
    markers_by_color: dict[str, dict] = {}
    for marker in markers:
        color = str(marker["color_group"])
        existing = markers_by_color.get(color)
        marker_text_bound = str(marker.get("legend_label") or "") != color
        existing_text_bound = existing is not None and str(existing.get("legend_label") or "") != color
        if existing is None or (marker_text_bound and not existing_text_bound):
            markers_by_color[color] = marker
    for point in points:
        color = str(point.get("color_group") or "")
        marker = markers_by_color.get(color)
        if marker:
            text_bound = str(marker.get("legend_label") or "") != str(marker.get("color_group") or "")
            label = str(marker["legend_label"])
            if text_bound and not _is_useful_legend_label(label):
                label = str(marker["color_group"])
                text_bound = False
            point["series_name"] = label
            point["legend_label"] = label
            point.update(_series_metadata_from_label(label))
            point["legend_binding_status"] = (
                "text_bound_review"
                if text_bound
                else "color_bound_review"
            )
            point["legend_binding_method"] = "ocr_text_near_marker" if text_bound else "color_marker_match"
            point["legend_text_confidence"] = marker.get("legend_text_confidence", "")
            point["legend_marker_x"] = marker["legend_marker_x"]
            point["legend_marker_y"] = marker["legend_marker_y"]
            point["legend_marker_area_px"] = marker.get("legend_marker_area_px", "")
        else:
            point["series_name"] = color or "series"
            point["series_label_raw"] = color or "series"
            point["legend_binding_status"] = "review_required"
            point["legend_binding_method"] = "unbound"


class MultiLinePlotExtractor:
    image_type = "multi_line_plot"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_multi_line_plot(context.record)

    @staticmethod
    def matches_context(context: ExtractorContext) -> bool:
        if MultiLinePlotExtractor.matches(context):
            return True
        if detect_stacked_plot_panels(context.image, context.plot_area):
            return False
        recipe = line_plot_recipe(context.record)
        if (
            recipe is not None
            and recipe.x_axis_type == "linear"
            and recipe.y_axis_type == "linear"
            and recipe.x_axis_label != "normalized_x"
        ):
            return False
        points = merge_marker_components(
            colored_curve_points(context.image, context.plot_area),
            component_points(context.image, context.plot_area),
        )
        color_groups = {str(point.get("color_group") or "") for point in points}
        color_groups.discard("")
        color_groups.discard("gray")
        return len(color_groups) >= 2 and len(points) >= 2

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        points = merge_marker_components(
            colored_curve_points(context.image, context.plot_area),
            component_points(context.image, context.plot_area),
        )
        if len(points) < 3:
            points = component_points(context.image, context.plot_area)
        markers = bind_legend_text(context.image, context.plot_area, legend_markers(context.image, context.plot_area))
        apply_legend_binding(points, markers)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="multi_line_plot_cv_review_sample",
        )
