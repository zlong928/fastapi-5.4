from __future__ import annotations

from collections.abc import Sequence

from app.services.chart_extraction.extractors.base import ExtractorContext, ImageExtractor
from app.services.chart_extraction.extractors.bar_chart import BarChartExtractor
from app.services.chart_extraction.extractors.chart_table import ChartTableExtractor
from app.services.chart_extraction.extractors.coordinate_plot import CoordinatePlotExtractor
from app.services.chart_extraction.extractors.field_2d_map import Field2DMapExtractor
from app.services.chart_extraction.extractors.heatmap_matrix import HeatmapMatrixExtractor
from app.services.chart_extraction.extractors.line_plot import LinePlotExtractor
from app.services.chart_extraction.extractors.microscopy_quant import MicroscopyQuantExtractor
from app.services.chart_extraction.extractors.multi_line_plot import MultiLinePlotExtractor
from app.services.chart_extraction.extractors.scatter_plot import ScatterPlotExtractor
from app.services.chart_extraction.extractors.spectrum_curve import SpectrumCurveExtractor
from app.services.chart_extraction.extractors.stacked_time_series import StackedTimeSeriesExtractor


def default_extractors() -> list[ImageExtractor]:
    return [
        ChartTableExtractor(),
        StackedTimeSeriesExtractor(),
        Field2DMapExtractor(),
        HeatmapMatrixExtractor(),
        BarChartExtractor(),
        SpectrumCurveExtractor(),
        ScatterPlotExtractor(),
        MicroscopyQuantExtractor(),
        MultiLinePlotExtractor(),
        LinePlotExtractor(),
        CoordinatePlotExtractor(),
    ]


def extractor_matches(extractor: ImageExtractor, context: ExtractorContext) -> bool:
    if hasattr(extractor, "matches_context"):
        return bool(extractor.matches_context(context))  # type: ignore[attr-defined]
    return bool(extractor.matches(context))  # type: ignore[attr-defined]


def select_extractor(context: ExtractorContext, extractors: Sequence[ImageExtractor] | None = None) -> ImageExtractor:
    for extractor in extractors or default_extractors():
        if extractor_matches(extractor, context):
            return extractor
    return CoordinatePlotExtractor()
