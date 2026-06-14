from __future__ import annotations

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import (
    colored_curve_points,
    component_points,
    merge_marker_components,
)
from app.services.chart_extraction.image_routing import is_spectrum_curve


class SpectrumCurveExtractor:
    image_type = "spectrum_curve"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_spectrum_curve(context.record)

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        points = merge_marker_components(
            colored_curve_points(context.image, context.plot_area),
            component_points(context.image, context.plot_area),
        )
        if len(points) < 3:
            points = component_points(context.image, context.plot_area)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        for point in points:
            point.setdefault("panel_id", "spectrum")
        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="spectrum_curve_cv_review_sample",
        )
