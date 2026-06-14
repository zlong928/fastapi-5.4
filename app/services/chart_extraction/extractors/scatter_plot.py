from __future__ import annotations

import cv2
import numpy as np

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import component_points
from app.services.chart_extraction.image_routing import is_scatter_plot


class ScatterPlotExtractor:
    image_type = "scatter_plot"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_scatter_plot(context.record)

    @staticmethod
    def _fit_line(image: np.ndarray, area: tuple[int, int, int, int]) -> dict | None:
        x0, y0, x1, y1 = area
        crop = image[y0 : y1 + 1, x0 : x1 + 1]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (((hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 45)) | (gray < 100)).astype("uint8") * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        height, width = mask.shape
        min_len = max(24, int(width * 0.28))
        lines = cv2.HoughLinesP(
            mask,
            rho=1,
            theta=np.pi / 180,
            threshold=max(12, int(min_len * 0.35)),
            minLineLength=min_len,
            maxLineGap=5,
        )
        if lines is None:
            return None
        candidates: list[dict] = []
        for line in lines[:, 0, :]:
            lx1, ly1, lx2, ly2 = [float(value) for value in line]
            dx = lx2 - lx1
            dy = ly2 - ly1
            length = float(np.hypot(dx, dy))
            if length < min_len or abs(dx) < 8:
                continue
            slope = dy / dx
            if abs(slope) < 0.05 or abs(slope) > 5:
                continue
            intercept = ly1 - slope * lx1
            candidates.append(
                {
                    "length": length,
                    "x1": lx1 + x0,
                    "y1": ly1 + y0,
                    "x2": lx2 + x0,
                    "y2": ly2 + y0,
                    "slope": slope,
                    "intercept": intercept + y0 - slope * x0,
                }
            )
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item["length"])
        px = (best["x1"] + best["x2"]) / 2
        py = (best["y1"] + best["y2"]) / 2
        return {
            "panel_id": "plot",
            "series_name": "fit_line",
            "scatter_role": "fit_line",
            "scatter_geometry_status": "fit_line_detected",
            "pixel_x": round(px, 1),
            "pixel_y": round(py, 1),
            "x_coordinate": round((px - x0) / max(1, x1 - x0), 5),
            "y_coordinate": round(1 - (py - y0) / max(1, y1 - y0), 5),
            "fit_line_x1_px": round(best["x1"], 1),
            "fit_line_y1_px": round(best["y1"], 1),
            "fit_line_x2_px": round(best["x2"], 1),
            "fit_line_y2_px": round(best["y2"], 1),
            "fit_line_slope_px": round(best["slope"], 6),
            "fit_line_intercept_px": round(best["intercept"], 3),
            "color_group": "fit_line",
            "component_area_px": int(round(best["length"])),
        }

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        points = component_points(context.image, context.plot_area)
        for point in points:
            point.setdefault("panel_id", "plot")
            point["scatter_role"] = "data_point"
            point["scatter_geometry_status"] = "scatter_points_detected"
            point.setdefault("series_name", point.get("color_group", "point"))
        fit_line = self._fit_line(context.image, context.plot_area)
        if fit_line:
            points.append(fit_line)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="scatter_plot_cv_review_sample",
        )
