from __future__ import annotations

import numpy as np

from app.services.chart_extraction.axis_calibration import (
    apply_transform,
    dedupe_ticks,
    linear_transform_from_ticks,
    ocr_numeric_tokens,
)
from app.services.chart_extraction.chart_recipes import BIPHASIC_TIME_SERIES_RECIPES, biphasic_time_series_recipe
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import component_points
from app.services.chart_extraction.models import ImageRecord


class StackedTimeSeriesExtractor:
    image_type = "biphasic_time_series"
    calibration_method = "stacked_time_series_x_ocr"
    known_xy_method = "stacked_time_series_xy_known"

    @staticmethod
    def matches(record: ImageRecord) -> bool:
        return biphasic_time_series_recipe(record) is not None

    def matches_context(self, context: ExtractorContext) -> bool:
        return self.matches(context.record)

    def extract(self, context: ExtractorContext, points: list[dict] | None = None) -> ExtractorResult:
        source_points = points if points is not None else component_points(context.image, context.plot_area)
        calibrated = [dict(point) for point in source_points]
        self.apply_axis_values(calibrated, context.image, context.record)
        return ExtractorResult(image_type=self.image_type, points=calibrated)

    def apply_axis_values(self, points: list[dict], image: np.ndarray, record: ImageRecord | None = None) -> None:
        height = image.shape[0]
        x_ticks = [
            (float(token["cx"]), float(token["value"]))
            for token in ocr_numeric_tokens(image)
            if float(token["cy"]) > height * 0.86 and 0 <= float(token["value"]) <= 500
        ]
        x_transform = linear_transform_from_ticks(dedupe_ticks(x_ticks, "x"))
        recipe = biphasic_time_series_recipe(record) or BIPHASIC_TIME_SERIES_RECIPES[0]
        for point in points:
            px = float(point["pixel_x"])
            py = float(point["pixel_y"])
            panel = recipe.panel_for_y(py)
            point["recipe_id"] = recipe.recipe_id if self._has_known_y_template(record) else ""
            point["x_axis_label"] = recipe.x_axis_label
            point["x_axis_unit"] = recipe.x_axis_unit
            point["x_axis_type"] = "linear" if x_transform else "normalized"
            point["x_value"] = round(apply_transform(x_transform, px), 5) if x_transform else point["x_coordinate"]
            point["panel_id"] = panel.panel_id
            point["y_axis_label"] = panel.y_axis_label
            point["y_axis_unit"] = panel.y_axis_unit
            known_y = self._known_log_y_value(record, py)
            if known_y is not None:
                point["y_axis_type"] = "log10"
                point["y_value"] = known_y
            else:
                point["y_axis_type"] = "panel_normalized"
                point["y_value"] = panel.normalized_y(py)
            point["axis_calibration_method"] = self.known_xy_method if self._has_known_y_template(record) else self.calibration_method

    def _has_known_y_template(self, record: ImageRecord | None) -> bool:
        return bool(record and (recipe := biphasic_time_series_recipe(record)) and recipe.y_log_a is not None and recipe.y_log_b is not None)

    def _known_log_y_value(self, record: ImageRecord | None, pixel_y: float) -> float | None:
        if not record:
            return None
        recipe = biphasic_time_series_recipe(record)
        if not recipe:
            return None
        return recipe.calibrated_y(pixel_y)
