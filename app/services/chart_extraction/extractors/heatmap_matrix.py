from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult
from app.services.chart_extraction.extractors.colorbar import build_colorbar_mapping
from app.services.chart_extraction.extractors.color_sampling import grid_color_samples
from app.services.chart_extraction.image_routing import is_heatmap_matrix


class HeatmapMatrixExtractor:
    image_type = "heatmap_matrix"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        return is_heatmap_matrix(context.record)

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        x0, y0, x1, y1 = context.plot_area
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        rows = min(5, max(2, height // 35))
        cols = min(5, max(2, width // 35))
        colorbar_mapping = build_colorbar_mapping(context.image, context.plot_area)
        points = grid_color_samples(
            context.image,
            context.plot_area,
            rows=rows,
            cols=cols,
            panel_id="heatmap",
            x_axis_label="matrix_column",
            y_axis_label="matrix_row",
            axis_type="grid_index",
            calibration_method="heatmap_color_grid_sample",
            colorbar_mapping=colorbar_mapping,
        )
        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="heatmap_matrix_grid_review_sample",
        )
