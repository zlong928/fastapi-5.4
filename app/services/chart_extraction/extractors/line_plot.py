from __future__ import annotations

from app.services.chart_extraction.axis_assignment import assign_axis_values
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.visual_marks import (
    colored_curve_points,
    component_points,
    merge_marker_components,
)
from app.services.chart_extraction.image_routing import is_line_chart


class LinePlotExtractor:
    image_type = "line_plot"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_line_chart(context.record, context.image)

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        points = merge_marker_components(
            colored_curve_points(context.image, context.plot_area),
            component_points(context.image, context.plot_area),
        )
        if len(points) < 3:
            points = component_points(context.image, context.plot_area)
        assign_axis_values(context.record, points, context.image, context.plot_area)
        return ExtractorResult(image_type=self.image_type, points=points)
