from __future__ import annotations

from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.colorbar import build_colorbar_mapping
from app.services.chart_extraction.extractors.color_sampling import grid_color_samples
from app.services.chart_extraction.image_routing import is_2d_field_map


class Field2DMapExtractor:
    image_type = "2d_field_map"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_2d_field_map(context.record)

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        x0, y0, x1, y1 = context.plot_area
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        rows = min(6, max(3, height // 45))
        cols = min(6, max(3, width // 45))
        colorbar_mapping = build_colorbar_mapping(context.image, context.plot_area)
        points = grid_color_samples(
            context.image,
            context.plot_area,
            rows=rows,
            cols=cols,
            panel_id="field",
            x_axis_label="field_x",
            y_axis_label="field_y",
            axis_type="field_grid_index",
            calibration_method="field_color_grid_sample",
            colorbar_mapping=colorbar_mapping,
        )
        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="2d_field_map_grid_review_sample",
        )
