from __future__ import annotations

import math

import numpy as np

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import component_points
from app.services.chart_extraction.plot_geometry import detect_stacked_plot_panels


class CoordinatePlotExtractor:
    image_type = "coordinate_plot"

    @staticmethod
    def matches(_context: ExtractorContext) -> bool:
        return True

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        panels = detect_stacked_plot_panels(context.image, context.plot_area)
        if panels:
            return self._extract_stacked_panels(context, panels)
        points = component_points(context.image, context.plot_area)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        return ExtractorResult(image_type=self.image_type, points=points)

    def _extract_stacked_panels(
        self,
        context: ExtractorContext,
        panels: list[tuple[str, tuple[int, int, int, int]]],
    ) -> ExtractorResult:
        panel_points: list[dict] = []
        for panel_id, area in panels:
            points = component_points(context.image, area)
            assign_axis_values(context.record, points, context.image, area)
            for point in points:
                point["panel_id"] = panel_id
            panel_points.extend(points)
        self._propagate_shared_x_axis(panel_points)
        return ExtractorResult(
            image_type=self.image_type,
            points=panel_points,
            extraction_method="local_cv_stacked_panel_review_sample",
        )

    @staticmethod
    def _propagate_shared_x_axis(points: list[dict]) -> None:
        shared_label = next(
            (
                (point.get("x_axis_label"), point.get("x_axis_unit"))
                for point in points
                if point.get("panel_id") == "lower_panel"
                and point.get("x_axis_label") not in {"", None, "normalized_x"}
            ),
            None,
        )
        if not shared_label:
            shared_label = next(
                (
                    (point.get("x_axis_label"), point.get("x_axis_unit"))
                    for point in reversed(points)
                    if point.get("x_axis_label") not in {"", None, "normalized_x"}
                ),
                None,
            )
        if not shared_label:
            return
        x_label, x_unit = shared_label
        shared_transform = CoordinatePlotExtractor._shared_x_transform(points)
        for point in points:
            if point.get("x_axis_label") in {"", None, "normalized_x"} or point.get("panel_id") == "upper_panel":
                was_different_axis = point.get("x_axis_label") not in {x_label, "", None, "normalized_x"}
                point["x_axis_label"] = x_label
                point["x_axis_unit"] = x_unit or ""
                point["axis_label_binding_method"] = point.get("axis_label_binding_method") or "shared_panel_x_axis"
                if point.get("panel_id") == "upper_panel" and shared_transform:
                    point["x_axis_type"] = shared_transform["scale"]
                    point["x_value"] = round(CoordinatePlotExtractor._apply_shared_x_transform(shared_transform, point), 5)
                    point["axis_label_binding_method"] = "shared_panel_x_axis"
                elif point.get("panel_id") == "upper_panel" and was_different_axis:
                    point["x_axis_type"] = "shared_normalized"
                    point["x_value"] = point.get("x_coordinate", "")

    @staticmethod
    def _shared_x_transform(points: list[dict]) -> dict | None:
        lower_points = [
            point
            for point in points
            if point.get("panel_id") == "lower_panel"
            and point.get("x_axis_type") in {"linear", "log10"}
            and point.get("x_value") not in {"", None}
            and point.get("pixel_x") not in {"", None}
        ]
        if len(lower_points) < 2:
            return None
        scale = str(lower_points[0].get("x_axis_type") or "linear")
        pairs: list[tuple[float, float]] = []
        seen_pixels: set[float] = set()
        for point in lower_points:
            try:
                pixel = float(point["pixel_x"])
                value = float(point["x_value"])
            except (TypeError, ValueError):
                continue
            if pixel in seen_pixels or (scale == "log10" and value <= 0):
                continue
            seen_pixels.add(pixel)
            pairs.append((pixel, math.log10(value) if scale == "log10" else value))
        if len(pairs) < 2:
            return None
        pixels = np.array([pixel for pixel, _value in pairs], dtype=float)
        values = np.array([value for _pixel, value in pairs], dtype=float)
        if len(set(float(pixel) for pixel in pixels)) < 2:
            return None
        coef = np.polyfit(pixels, values, 1)
        return {"scale": scale, "a": float(coef[0]), "b": float(coef[1])}

    @staticmethod
    def _apply_shared_x_transform(transform: dict, point: dict) -> float:
        value = float(transform["a"]) * float(point["pixel_x"]) + float(transform["b"])
        if transform["scale"] == "log10":
            return 10**value
        return value
