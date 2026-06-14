from __future__ import annotations

import re

import cv2
import numpy as np

from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import classify_mark_color
from app.services.chart_extraction.image_routing import is_microscopy_quant


def _parse_scale_bar_value(text: str) -> tuple[float, str] | None:
    unit_pattern = r"(?:um|µm|μm|nm|mm)"
    patterns = [
        rf"scale\s*bar[^0-9]{{0,12}}([0-9]+(?:\.[0-9]+)?)\s*({unit_pattern})",
        rf"([0-9]+(?:\.[0-9]+)?)\s*({unit_pattern})[^.;,\n]{{0,24}}scale\s*bar",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            unit = match.group(2).replace("μ", "µ")
            return float(match.group(1)), unit
    return None


def _detect_horizontal_scale_bar(crop: np.ndarray) -> dict | None:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    bottom = gray[int(height * 0.55) :, :]
    dark = bottom < 45
    bright = bottom > 235
    masks = [dark.astype("uint8") * 255, bright.astype("uint8") * 255]
    candidates: list[dict] = []
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
        num, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        for label in range(1, num):
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP]) + int(height * 0.55)
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            if w < max(18, int(width * 0.06)) or h < 2 or h > max(18, int(height * 0.08)):
                continue
            if w / max(1, h) < 5:
                continue
            if area < w * h * 0.55:
                continue
            cx, cy = centroids[label]
            candidates.append(
                {
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "cx": float(cx),
                    "cy": float(cy + int(height * 0.55)),
                    "score": w * (1 + y / max(1, height)),
                }
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["score"])


def detect_scale_bar(crop: np.ndarray, caption: str) -> dict | None:
    value = _parse_scale_bar_value(caption)
    bar = _detect_horizontal_scale_bar(crop)
    if not value or not bar:
        return None
    physical_value, unit = value
    if bar["w"] <= 0:
        return None
    return {
        "length_px": float(bar["w"]),
        "value": physical_value,
        "unit": unit,
        "pixel_size": physical_value / float(bar["w"]),
        "bbox": (bar["x"], bar["y"], bar["x"] + bar["w"], bar["y"] + bar["h"]),
        "binding_status": "scale_bar_caption_and_segment_bound_review",
        "binding_method": "caption_value_horizontal_segment",
    }


def _object_class_from_caption(caption: str) -> str:
    text = caption.lower()
    if "pore" in text:
        return "pore"
    if "cell" in text or "bacteria" in text:
        return "cell"
    if "carbonate" in text:
        return "carbonate_deposit"
    if "element" in text or "eds" in text or "mapping" in text:
        return "element_region"
    return "unclassified_object_review"


class MicroscopyQuantExtractor:
    image_type = "microscopy_quant"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_microscopy_quant(context.record)

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        x0, y0, x1, y1 = context.plot_area
        crop = context.image[y0 : y1 + 1, x0 : x1 + 1]
        if crop.size == 0:
            return ExtractorResult(
                image_type=self.image_type,
                points=[],
                extraction_method="microscopy_quant_cv_review_sample",
            )

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        contrast = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 7))
        textured = contrast > max(12, int(np.percentile(contrast, 80)))
        saturated = (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 45)
        dark_objects = gray < max(80, int(np.percentile(gray, 35)))
        mask = (textured | saturated | dark_objects).astype("uint8") * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        scale_bar = detect_scale_bar(crop, context.record.caption)
        if scale_bar:
            bx0, by0, bx1, by1 = scale_bar["bbox"]
            pad = 4
            mask[max(0, by0 - pad) : min(mask.shape[0], by1 + pad), max(0, bx0 - pad) : min(mask.shape[1], bx1 + pad)] = 0

        height, width = mask.shape
        image_area = max(1, height * width)
        object_class = _object_class_from_caption(context.record.caption)
        object_method = "caption_keyword_hint_review" if object_class != "unclassified_object_review" else "unclassified_review"
        num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        components: list[dict] = []
        max_component_area = max(64, int(image_area * 0.25))
        for label in range(1, num):
            area_px = int(stats[label, cv2.CC_STAT_AREA])
            if not (16 <= area_px <= max_component_area):
                continue
            cx, cy = centroids[label]
            px = float(cx + x0)
            py = float(cy + y0)
            comp = labels == label
            pix_bgr = crop[comp]
            mean_bgr = pix_bgr.mean(axis=0)
            rgb = np.array([mean_bgr[2], mean_bgr[1], mean_bgr[0]])
            pixel_size = float(scale_bar["pixel_size"]) if scale_bar else None
            area_value = round(area_px * pixel_size * pixel_size, 4) if pixel_size else ""
            area_unit = f"{scale_bar['unit']}^2" if scale_bar else ""
            obj_left = float(x0 + int(stats[label, cv2.CC_STAT_LEFT]))
            obj_top = float(y0 + int(stats[label, cv2.CC_STAT_TOP]))
            obj_width = float(int(stats[label, cv2.CC_STAT_WIDTH]))
            obj_height = float(int(stats[label, cv2.CC_STAT_HEIGHT]))
            eq_diameter_px = float(2 * np.sqrt(area_px / np.pi))
            eq_diameter_value = round(eq_diameter_px * pixel_size, 4) if pixel_size else ""
            contours, _hierarchy = cv2.findContours(comp.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            perimeter = cv2.arcLength(contours[0], True) if contours else 0.0
            circularity = round(float(4 * np.pi * area_px / max(1e-9, perimeter * perimeter)), 4) if perimeter else ""
            components.append(
                {
                    "pixel_x": round(px, 1),
                    "pixel_y": round(py, 1),
                    "x_coordinate": round((px - x0) / max(1, x1 - x0), 5),
                    "y_coordinate": round(1 - (py - y0) / max(1, y1 - y0), 5),
                    "x_value": round((px - x0) * pixel_size, 4) if pixel_size else round(px - x0, 2),
                    "y_value": round((py - y0) * pixel_size, 4) if pixel_size else round(py - y0, 2),
                    "x_axis_label": "image_x",
                    "x_axis_unit": scale_bar["unit"] if scale_bar else "px",
                    "x_axis_type": "scaled_pixel" if scale_bar else "pixel",
                    "y_axis_label": "image_y",
                    "y_axis_unit": scale_bar["unit"] if scale_bar else "px",
                    "y_axis_type": "scaled_pixel" if scale_bar else "pixel",
                    "z_value": area_value if scale_bar else round(area_px / image_area, 6),
                    "z_axis_label": "object_area" if scale_bar else "object_area_fraction",
                    "z_axis_unit": area_unit if scale_bar else "fraction",
                    "z_axis_type": "area_physical" if scale_bar else "area_fraction",
                    "scale_bar_length_px": round(scale_bar["length_px"], 2) if scale_bar else "",
                    "scale_bar_value": scale_bar["value"] if scale_bar else "",
                    "scale_bar_unit": scale_bar["unit"] if scale_bar else "",
                    "scale_bar_binding_status": scale_bar.get("binding_status", "") if scale_bar else "",
                    "scale_bar_binding_method": scale_bar.get("binding_method", "") if scale_bar else "",
                    "scale_bar_left_px": round(float(scale_bar["bbox"][0] + x0), 1) if scale_bar else "",
                    "scale_bar_right_px": round(float(scale_bar["bbox"][2] + x0), 1) if scale_bar else "",
                    "scale_bar_top_px": round(float(scale_bar["bbox"][1] + y0), 1) if scale_bar else "",
                    "scale_bar_bottom_px": round(float(scale_bar["bbox"][3] + y0), 1) if scale_bar else "",
                    "pixel_size": round(pixel_size, 6) if pixel_size else "",
                    "physical_area_value": area_value,
                    "physical_area_unit": area_unit,
                    "object_class": object_class,
                    "object_classification_method": object_method,
                    "object_left_px": round(obj_left, 1),
                    "object_right_px": round(obj_left + obj_width - 1, 1),
                    "object_top_px": round(obj_top, 1),
                    "object_bottom_px": round(obj_top + obj_height - 1, 1),
                    "object_width_px": round(obj_width, 1),
                    "object_height_px": round(obj_height, 1),
                    "object_equivalent_diameter_px": round(eq_diameter_px, 4),
                    "object_equivalent_diameter_value": eq_diameter_value,
                    "object_circularity": circularity,
                    "color_group": classify_mark_color(rgb),
                    "component_area_px": area_px,
                    "axis_calibration_method": "microscopy_scale_bar_review" if scale_bar else "microscopy_pixel_measurement_review",
                }
            )
        components.sort(key=lambda item: int(item["component_area_px"]), reverse=True)
        return ExtractorResult(
            image_type=self.image_type,
            points=components[:40],
            extraction_method="microscopy_quant_cv_review_sample",
        )
