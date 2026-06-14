from app.services.chart_extraction.extractors.bar_chart import BarChartExtractor
from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult, ImageExtractor
from app.services.chart_extraction.extractors.chart_table import ChartTableExtractor
from app.services.chart_extraction.extractors.coordinate_plot import CoordinatePlotExtractor
from app.services.chart_extraction.extractors.field_2d_map import Field2DMapExtractor
from app.services.chart_extraction.extractors.heatmap_matrix import HeatmapMatrixExtractor
from app.services.chart_extraction.extractors.line_plot import LinePlotExtractor
from app.services.chart_extraction.extractors.microscopy_quant import MicroscopyQuantExtractor
from app.services.chart_extraction.extractors.multi_line_plot import MultiLinePlotExtractor
from app.services.chart_extraction.extractors.registry import default_extractors, extractor_matches, select_extractor
from app.services.chart_extraction.extractors.scatter_plot import ScatterPlotExtractor
from app.services.chart_extraction.extractors.spectrum_curve import SpectrumCurveExtractor
from app.services.chart_extraction.extractors.stacked_time_series import StackedTimeSeriesExtractor
from app.services.chart_extraction.extractors.visual_marks import (
    classify_mark_color,
    colored_curve_points,
    component_points,
    data_mask,
    merge_marker_components,
)

__all__ = [
    "ExtractorContext",
    "ExtractorResult",
    "BarChartExtractor",
    "ChartTableExtractor",
    "Field2DMapExtractor",
    "ImageExtractor",
    "CoordinatePlotExtractor",
    "HeatmapMatrixExtractor",
    "LinePlotExtractor",
    "MicroscopyQuantExtractor",
    "MultiLinePlotExtractor",
    "ScatterPlotExtractor",
    "SpectrumCurveExtractor",
    "StackedTimeSeriesExtractor",
    "classify_mark_color",
    "colored_curve_points",
    "component_points",
    "data_mask",
    "default_extractors",
    "extractor_matches",
    "merge_marker_components",
    "select_extractor",
]
