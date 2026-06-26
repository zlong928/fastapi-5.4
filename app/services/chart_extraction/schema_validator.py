from __future__ import annotations

import logging
import re

import numpy as np

from app.services.chart_extraction.agents.vlm_extractor import VlmExtractionResult
from app.services.chart_extraction.axis_calibration import (
    apply_transform,
    infer_axis_labels_from_ocr,
    infer_axis_transform,
    linear_transform_from_ticks,
    ocr_numeric_tokens,
)
from app.services.chart_extraction.contracts import AxisContract, Contract
from app.services.chart_extraction.cv import RawExtraction, RawPixel
from app.services.chart_extraction.cv.verifier import VerificationReport
from app.services.chart_extraction.models import ImageRecord

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Thin orchestration layer. Raw pixels + contract -> physical data points."""

    def vlm_to_points(self, vlm_result: VlmExtractionResult, record: ImageRecord) -> list[dict]:
        """Convert VLM structured output to CSV rows. No CV needed."""
        axes = vlm_result.axes or {}
        points: list[dict] = []
        for series_idx, series in enumerate(vlm_result.series):
            data_points = series.get("data_points", [])
            for point in data_points:
                x_val = point.get("x")
                y_val = point.get("y")
                if x_val is None or y_val is None:
                    continue
                series_name = series.get("name") or ""
                color_name = series.get("color_name") or ""
                row = {
                    "image_id": f"{record.ordinal:02d}_{record.path.stem}",
                    "image_file": record.path.name,
                    "image_type": vlm_result.chart_type,
                    "mineru_sub_type": record.mineru_sub_type,
                    "series_name": series_name if series_name.strip() else f"series_{series_idx}",
                    "x_value": float(x_val) if not isinstance(x_val, float) else x_val,
                    "y_value": float(y_val) if not isinstance(y_val, float) else y_val,
                    "x_unit": axes.get("x", {}).get("unit", ""),
                    "y_unit": axes.get("y", {}).get("unit", ""),
                    "x_axis_label": axes.get("x", {}).get("label", ""),
                    "y_axis_label": axes.get("y", {}).get("label", ""),
                    "x_axis_type": axes.get("x", {}).get("scale", "linear"),
                    "y_axis_type": axes.get("y", {}).get("scale", "linear"),
                    "color_group": color_name if color_name.strip() else "unknown",
                    "series_id": color_name if color_name.strip() else f"series_{series_idx}",
                    "extraction_method": "vlm",
                    "axis_calibration_method": "vlm_direct",
                    "confidence": vlm_result.confidence,
                    "quality_tags": "",
                    "chart_type": vlm_result.chart_type,
                    "component_area_px": 0,
                    "pixel_x": 0,
                    "pixel_y": 0,
                }
                if series.get("axis") == "y2":
                    row["y_right_value"] = row["y_value"]
                points.append(row)
        return points

    def calibrate(
        self,
        vlm_result: VlmExtractionResult,
        verification_report: VerificationReport,
        plot_area: tuple[int, int, int, int],
        record: ImageRecord,
    ) -> list[dict]:
        """Merge CV calibration into VLM values when available."""
        points = self.vlm_to_points(vlm_result, record)
        if not verification_report or not plot_area:
            return points

        x0, y0, x1, y1 = plot_area
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)

        axes = vlm_result.axes or {}
        calibrations = verification_report.calibrations or {}

        for pt in points:
            # X axis calibration
            x_cal = calibrations.get("x")
            x_ax = axes.get("x", {})
            if (x_cal and x_cal.r_squared > 0.95 and x_cal.tick_count >= 3
                    and x_cal.transform is not None
                    and x_ax.get("range_min") is not None and x_ax.get("range_max") is not None):
                x_val = pt.get("x_value")
                if x_val is not None:
                    x_min = x_ax["range_min"]
                    x_max = x_ax["range_max"]
                    if x_max > x_min:
                        x_scale = x_ax.get("scale", "linear")
                        if x_scale == "log10" and x_val > 0 and x_min > 0:
                            log_min = np.log10(float(x_min))
                            log_max = np.log10(float(x_max))
                            log_val = np.log10(float(x_val))
                            px = x0 + (log_val - log_min) / (log_max - log_min) * width
                        else:
                            px = x0 + (float(x_val) - float(x_min)) / (float(x_max) - float(x_min)) * width
                        cal_val = apply_transform(x_cal.transform, px)
                        if cal_val is not None:
                            pt["x_value"] = round(float(cal_val), 5)
                            pt["axis_calibration_method"] = "cv_calibrated"

            # Y axis calibration
            y_cal = calibrations.get("y")
            y_ax = axes.get("y", {})
            if (y_cal and y_cal.r_squared > 0.95 and y_cal.tick_count >= 3
                    and y_cal.transform is not None
                    and y_ax.get("range_min") is not None and y_ax.get("range_max") is not None):
                y_val = pt.get("y_value")
                if y_val is not None:
                    y_min = y_ax["range_min"]
                    y_max = y_ax["range_max"]
                    if y_max > y_min:
                        y_scale = y_ax.get("scale", "linear")
                        if y_scale == "log10" and y_val > 0 and y_min > 0:
                            log_min = np.log10(float(y_min))
                            log_max = np.log10(float(y_max))
                            log_val = np.log10(float(y_val))
                            py = y1 - (log_val - log_min) / (log_max - log_min) * height
                        else:
                            py = y1 - (float(y_val) - float(y_min)) / (float(y_max) - float(y_min)) * height
                        cal_val = apply_transform(y_cal.transform, py)
                        if cal_val is not None:
                            pt["y_value"] = round(float(cal_val), 5)
                            pt["axis_calibration_method"] = "cv_calibrated"

            # Y2 axis calibration
            y2_cal = calibrations.get("y2")
            y2_ax = axes.get("y2", {})
            y2_val = pt.get("y_right_value")
            if (y2_cal and y2_cal.r_squared > 0.95 and y2_cal.tick_count >= 3
                    and y2_cal.transform is not None
                    and y2_ax.get("range_min") is not None and y2_ax.get("range_max") is not None
                    and y2_val is not None):
                y2_min = y2_ax["range_min"]
                y2_max = y2_ax["range_max"]
                if y2_max > y2_min:
                    y2_scale = y2_ax.get("scale", "linear")
                    if y2_scale == "log10" and y2_val > 0 and y2_min > 0:
                        log_min = np.log10(float(y2_min))
                        log_max = np.log10(float(y2_max))
                        log_val = np.log10(float(y2_val))
                        py = y1 - (log_val - log_min) / (log_max - log_min) * height
                    else:
                        py = y1 - (float(y2_val) - float(y2_min)) / (float(y2_max) - float(y2_min)) * height
                    cal_val = apply_transform(y2_cal.transform, py)
                    if cal_val is not None:
                        pt["y_right_value"] = round(float(cal_val), 5)
                        pt["axis_calibration_method"] = "cv_calibrated"

        # Adjust overall confidence based on verification match score
        if verification_report.overall_match_score < 0.5:
            for pt in points:
                pt["confidence"] = round(pt.get("confidence", 0.5) * 0.8, 3)

        return points

    def transform(
        self,
        raw: RawExtraction,
        contract: Contract,
        image: np.ndarray,
        plot_area: tuple[int, int, int, int],
        record: ImageRecord | None = None,
    ) -> list[dict]:
        x0, y0, x1, y1 = plot_area
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)

        x_ticks = [t for t in raw.tick_values if t.get("axis") == "x"]
        y_ticks = [t for t in raw.tick_values if t.get("axis") == "y"]
        y_right_ticks = [t for t in raw.tick_values if t.get("axis") == "y_right"]

        x_transform = self._fit_transform(x_ticks, "x", contract.x_axis)
        y_transform = self._fit_transform(y_ticks, "y", contract.y_axis)
        y_right_transform = self._fit_transform(y_right_ticks, "y", contract.y_axis) if y_right_ticks else None

        x_transform, y_transform = self._tick_scale_check(
            x_transform, y_transform, raw.tick_values, contract,
        )

        mid_x = (x0 + x1) / 2
        points: list[dict] = []
        for pixel in raw.pixels:
            x_val = apply_transform(x_transform, pixel.px) if x_transform else None
            y_val = apply_transform(y_transform, pixel.py) if y_transform else None

            if x_val is None:
                x_val = round((pixel.px - x0) / width, 5)
                x_type = "normalized"
            else:
                x_type = x_transform.get("scale", "linear") if x_transform else "normalized"

            if y_val is None:
                y_val = round(1 - (pixel.py - y0) / height, 5)
                y_type = "normalized"
            else:
                y_type = y_transform.get("scale", "linear") if y_transform else "normalized"

            # Dual Y-axis: if pixel is on the right half of plot area, compute right-axis value
            y_right_val = None
            y_right_type = ""
            if y_right_transform and pixel.px >= mid_x:
                y_right_val = apply_transform(y_right_transform, pixel.py)
                if y_right_val is not None:
                    y_right_val = round(float(y_right_val), 5)
                    y_right_type = y_right_transform.get("scale", "linear")

            pt = {
                "pixel_x": round(pixel.px, 1),
                "pixel_y": round(pixel.py, 1),
                "x_value": round(float(x_val), 5),
                "y_value": round(float(y_val), 5),
                "y_right_value": y_right_val,
                "y_right_type": y_right_type,
                "x_unit": contract.x_axis.unit,
                "y_unit": contract.y_axis.unit,
                "x_axis_label": contract.x_axis.label,
                "y_axis_label": contract.y_axis.label,
                "x_axis_type": x_type,
                "y_axis_type": y_type,
                "color_group": pixel.color_group,
                "series_id": pixel.color_group,
                "extraction_method": "cv_" + raw.detection_method,
                "axis_calibration_method": "ocr_ticks" if (x_transform or y_transform) else "normalized_fallback",
                "component_area_px": 0,
            }
            points.append(pt)

        ocr_labels = infer_axis_labels_from_ocr(image, plot_area)
        self._apply_ocr_labels(points, ocr_labels, contract)

        return points

    def _fit_transform(
        self,
        ticks: list[dict],
        axis: str,
        contract_axis: AxisContract,
    ) -> dict | None:
        if not ticks:
            return None
        pairs = [(float(t["px"] if axis == "x" else t["py"]), float(t["value"])) for t in ticks]
        return infer_axis_transform(pairs, axis)

    def _tick_scale_check(
        self,
        x_transform: dict | None,
        y_transform: dict | None,
        ticks: list[dict],
        contract: Contract,
    ) -> tuple[dict | None, dict | None]:
        # Defense 3a: override x_transform when OCR ticks disagree with contract
        if x_transform and contract.x_axis.scale == "linear" and x_transform.get("scale") == "log10":
            logger.info("tick_scale_override axis=x contract=linear ocr=log10")
            x_ticks = [t for t in ticks if t.get("axis") == "x"]
            pairs = [(float(t["px"]), float(t["value"])) for t in x_ticks]
            log_transform = infer_axis_transform(pairs, "x")
            if log_transform and log_transform.get("scale") == "log10":
                x_transform = log_transform
        elif x_transform is None and contract.x_axis.scale == "log10":
            x_ticks = [t for t in ticks if t.get("axis") == "x"]
            if x_ticks:
                pairs = [(float(t["px"]), float(t["value"])) for t in x_ticks]
                positive = [v for _, v in pairs if v > 0]
                if len(positive) >= 2 and max(positive) / max(min(positive), 1e-12) >= 50:
                    log_transform = infer_axis_transform(pairs, "x")
                    if log_transform and log_transform.get("scale") == "log10":
                        x_transform = log_transform
                        logger.info("tick_scale_inferred image_type=%s axis=x scale=log10", contract.image_type)

        # Defense 3a: override y_transform when OCR ticks disagree with contract
        if y_transform and contract.y_axis.scale == "linear" and y_transform.get("scale") == "log10":
            logger.info("tick_scale_override axis=y contract=linear ocr=log10")
            y_ticks = [t for t in ticks if t.get("axis") == "y"]
            pairs = [(float(t["py"]), float(t["value"])) for t in y_ticks]
            log_transform = infer_axis_transform(pairs, "y")
            if log_transform and log_transform.get("scale") == "log10":
                y_transform = log_transform
        elif y_transform is None and contract.y_axis.scale == "log10":
            y_ticks = [t for t in ticks if t.get("axis") == "y"]
            if y_ticks:
                pairs = [(float(t["py"]), float(t["value"])) for t in y_ticks]
                positive = [v for _, v in pairs if v > 0]
                if len(positive) >= 2 and max(positive) / max(min(positive), 1e-12) >= 50:
                    log_transform = infer_axis_transform(pairs, "y")
                    if log_transform and log_transform.get("scale") == "log10":
                        y_transform = log_transform
                        logger.info("tick_scale_inferred image_type=%s axis=y scale=log10", contract.image_type)

        return x_transform, y_transform

    def _apply_ocr_labels(
        self,
        points: list[dict],
        ocr_labels: dict,
        contract: Contract,
    ) -> None:
        x_label = str(ocr_labels.get("x_axis_label") or "")
        y_label = str(ocr_labels.get("y_axis_label") or "")
        x_unit = str(ocr_labels.get("x_axis_unit") or "")
        y_unit = str(ocr_labels.get("y_axis_unit") or "")

        if not x_label and not y_label:
            return

        for pt in points:
            if x_label and not contract.x_axis.label:
                pt["x_axis_label"] = x_label
            if x_unit and not contract.x_axis.unit:
                pt["x_axis_unit"] = x_unit
            if y_label and not contract.y_axis.label:
                pt["y_axis_label"] = y_label
            if y_unit and not contract.y_axis.unit:
                pt["y_axis_unit"] = y_unit
