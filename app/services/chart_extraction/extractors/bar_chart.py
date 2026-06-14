from __future__ import annotations

import cv2
import numpy as np

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import component_points
from app.services.chart_extraction.image_routing import is_bar_chart, is_errorbar_chart

try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None


def _clean_label(text: str) -> str:
    cleaned = " ".join(text.replace("|", " ").replace("_", " ").split())
    return cleaned.strip(" .,:;")


class BarChartExtractor:
    image_type = "bar_chart"
    errorbar_image_type = "bar_or_line_with_errorbar"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_bar_chart(context.record) or is_errorbar_chart(context.record)

    @staticmethod
    def _bar_components(image: np.ndarray, area: tuple[int, int, int, int]) -> list[dict]:
        x0, y0, x1, y1 = area
        crop = image[y0 : y1 + 1, x0 : x1 + 1]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (((hsv[:, :, 1] > 35) & (hsv[:, :, 2] > 45)) | ((gray > 35) & (gray < 210))).astype("uint8") * 255
        height, width = mask.shape
        mask[: int(height * 0.08), :] = 0
        mask[int(height * 0.9) :, :] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 3), np.uint8))
        num, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        bars: list[dict] = []
        for label in range(1, num):
            area_px = int(stats[label, cv2.CC_STAT_AREA])
            bx = int(stats[label, cv2.CC_STAT_LEFT])
            by = int(stats[label, cv2.CC_STAT_TOP])
            bw = int(stats[label, cv2.CC_STAT_WIDTH])
            bh = int(stats[label, cv2.CC_STAT_HEIGHT])
            if bw < max(5, int(width * 0.025)) or bh < max(10, int(height * 0.08)):
                continue
            fill_ratio = area_px / max(1, bw * bh)
            if fill_ratio < 0.45 or bw / max(1, bh) > 2.8:
                continue
            cx, _cy = centroids[label]
            px_left = float(x0 + bx)
            px_right = float(x0 + bx + bw - 1)
            px_top = float(y0 + by)
            px_bottom = float(y0 + by + bh - 1)
            bars.append(
                {
                    "pixel_x": round(float(x0 + cx), 1),
                    "pixel_y": round(px_top, 1),
                    "x_coordinate": round((float(x0 + cx) - x0) / max(1, x1 - x0), 5),
                    "y_coordinate": round(1 - (px_top - y0) / max(1, y1 - y0), 5),
                    "bar_left_px": round(px_left, 1),
                    "bar_right_px": round(px_right, 1),
                    "bar_top_px": round(px_top, 1),
                    "bar_bottom_px": round(px_bottom, 1),
                    "bar_width_px": bw,
                    "bar_height_px": bh,
                    "component_area_px": area_px,
                    "color_group": "bar",
                    "bar_geometry_status": "bar_body_detected",
                }
            )
        bars.sort(key=lambda item: float(item["pixel_x"]))
        for index, bar in enumerate(bars):
            bar["category_index"] = index
            bar["series_name"] = f"category_{index}"
            bar["category_label"] = f"category_{index}"
            bar["category_binding_status"] = "index_only_review"
            bar["category_binding_method"] = "index_position_fallback"
        return bars

    @staticmethod
    def _attach_category_labels(image: np.ndarray, area: tuple[int, int, int, int], bars: list[dict]) -> None:
        if pytesseract is None or not bars:
            return
        x0, _y0, x1, y1 = area
        height, width = image.shape[:2]
        roi_y0 = min(height - 1, y1 + 1)
        roi_y1 = min(height - 1, y1 + 55)
        if roi_y1 <= roi_y0:
            return
        roi = image[roi_y0 : roi_y1 + 1, max(0, x0 - 8) : min(width, x1 + 9)]
        if roi.size == 0:
            return
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        try:
            data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=pytesseract.Output.DICT)
        except Exception:
            return
        tokens: list[dict] = []
        x_offset = max(0, x0 - 8)
        for index, raw_text in enumerate(data.get("text", [])):
            text = _clean_label(str(raw_text))
            if not text or not any(ch.isalnum() for ch in text):
                continue
            try:
                confidence = float(data["conf"][index])
            except Exception:
                confidence = -1.0
            if confidence < 20:
                continue
            left = float(data["left"][index]) / 2 + x_offset
            top = float(data["top"][index]) / 2 + roi_y0
            token_width = float(data["width"][index]) / 2
            token_height = float(data["height"][index]) / 2
            tokens.append(
                {
                    "text": text,
                    "cx": left + token_width / 2,
                    "cy": top + token_height / 2,
                    "left": left,
                    "right": left + token_width,
                    "confidence": confidence,
                }
            )
        if not tokens:
            return
        max_bar_width = max(float(bar.get("bar_width_px") or 12) for bar in bars)
        for bar in bars:
            center_x = float(bar["pixel_x"])
            candidates = [
                token
                for token in tokens
                if abs(float(token["cx"]) - center_x) <= max(max_bar_width * 0.9, 18)
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda token: (abs(float(token["cx"]) - center_x), float(token["cy"])))
            label = str(candidates[0]["text"])
            bar["category_label"] = label
            bar["series_name"] = label
            bar["category_binding_status"] = "text_bound_review"
            bar["category_binding_method"] = "ocr_text_near_bar"
            bar["category_text_confidence"] = round(float(candidates[0]["confidence"]), 1)
            bar["category_label_x"] = round(float(candidates[0]["cx"]), 1)
            bar["category_label_y"] = round(float(candidates[0]["cy"]), 1)

    @staticmethod
    def _attach_errorbars(image: np.ndarray, area: tuple[int, int, int, int], bars: list[dict]) -> None:
        x0, y0, _x1, _y1 = area
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for bar in bars:
            center_x = int(round(float(bar["pixel_x"])))
            bar_top = int(round(float(bar["bar_top_px"])))
            bar_width = int(round(float(bar["bar_width_px"])))
            search_half_width = max(3, int(bar_width * 0.35))
            left = max(x0, center_x - search_half_width)
            right = min(gray.shape[1] - 1, center_x + search_half_width)
            top = max(y0, bar_top - max(12, int((float(bar["bar_bottom_px"]) - bar_top) * 0.75)))
            bottom = max(y0, bar_top + 2)
            if bottom <= top or right <= left:
                continue
            crop = gray[top : bottom + 1, left : right + 1]
            dark = crop < 80
            ys, xs = np.where(dark)
            if len(xs) < 4:
                continue
            abs_y = ys + top
            abs_x = xs + left
            near_center = np.abs(abs_x - center_x) <= max(2, int(bar_width * 0.15))
            if near_center.sum() < 3:
                continue
            y_top = float(abs_y[near_center].min())
            y_bottom = float(abs_y[near_center].max())
            if y_bottom >= bar_top + 2 or bar_top - y_top < 3:
                continue
            bar["errorbar_top_px"] = round(y_top, 1)
            bar["errorbar_bottom_px"] = round(y_bottom, 1)
            bar["errorbar_height_px"] = round(max(0.0, float(bar["bar_top_px"]) - y_top), 1)
            bar["errorbar_center_x_px"] = round(float(center_x), 1)
            bar["errorbar_binding_status"] = "vertical_errorbar_detected_review"
            bar["errorbar_binding_method"] = "dark_vertical_line_near_bar_top"
            bar["bar_geometry_status"] = "bar_body_and_errorbar_detected"

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        points = self._bar_components(context.image, context.plot_area)
        if not points:
            points = component_points(context.image, context.plot_area)
            for index, point in enumerate(points):
                point["category_index"] = index
                point["bar_geometry_status"] = "component_fallback"
                point["category_label"] = f"category_{index}"
                point["category_binding_status"] = "index_only_review"
                point["category_binding_method"] = "index_position_fallback"
        self._attach_category_labels(context.image, context.plot_area, points)
        self._attach_errorbars(context.image, context.plot_area, points)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        image_type = self.errorbar_image_type if is_errorbar_chart(context.record) else self.image_type
        for point in points:
            point.setdefault("panel_id", "plot")
            point.setdefault("series_name", "bar")
        return ExtractorResult(
            image_type=image_type,
            points=points,
            extraction_method="bar_chart_cv_review_sample",
        )
