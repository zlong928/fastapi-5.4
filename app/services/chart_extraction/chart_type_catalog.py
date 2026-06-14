from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartTypeSpec:
    image_type: str
    label: str
    suitable_for_csv: bool
    processing_chain: str
    typical_content: tuple[str, ...]
    coordinate_output: str
    binding_requirements: tuple[str, ...] = tuple()
    requires_review: bool = False


CHART_TYPE_CATALOG: tuple[ChartTypeSpec, ...] = (
    ChartTypeSpec(
        image_type="line_plot",
        label="折线图 / 时间序列图",
        suitable_for_csv=True,
        processing_chain="line_plot",
        typical_content=("H2 generation over time", "NH4+ change", "quality over time", "fluorescence over time"),
        coordinate_output="xy_series_csv",
    ),
    ChartTypeSpec(
        image_type="biphasic_time_series",
        label="双相 / 分阶段时序图",
        suitable_for_csv=True,
        processing_chain="biphasic_time_series",
        typical_content=("phase I/phase II", "alternating high/low conditions", "two-stage kinetics"),
        coordinate_output="panel_xy_series_csv",
        binding_requirements=("panel_axis_binding",),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="multi_line_plot",
        label="多曲线图",
        suitable_for_csv=True,
        processing_chain="multi_line_plot",
        typical_content=("groups", "time points", "materials"),
        coordinate_output="xy_series_csv",
        binding_requirements=("legend_series_binding",),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="bar_chart",
        label="柱状图 / 分组柱状图",
        suitable_for_csv=True,
        processing_chain="bar_chart",
        typical_content=("yield", "modulus", "toughness", "degradation rate", "CO2 capture"),
        coordinate_output="category_value_csv",
        binding_requirements=("category_label_binding", "bar_geometry_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="bar_or_line_with_errorbar",
        label="带误差棒的统计图",
        suitable_for_csv=True,
        processing_chain="bar_or_line_with_errorbar",
        typical_content=("mean ± SD", "significance markers", "n=3"),
        coordinate_output="category_or_xy_value_error_csv",
        binding_requirements=("category_label_binding", "errorbar_geometry_binding", "significance_marker_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="scatter_plot",
        label="散点图 / 拟合图",
        suitable_for_csv=True,
        processing_chain="scatter_plot",
        typical_content=("correlation", "calibration curve", "pore size relationship"),
        coordinate_output="xy_point_csv",
        binding_requirements=("point_set_binding", "fit_line_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="heatmap_matrix",
        label="热图 / 矩阵图",
        suitable_for_csv=True,
        processing_chain="heatmap_matrix",
        typical_content=("gene expression", "metabolites", "fluorescence matrix", "concentration map"),
        coordinate_output="matrix_cell_csv",
        binding_requirements=("colorbar_value_binding", "cell_grid_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="spectrum_curve",
        label="光谱 / 谱图类曲线",
        suitable_for_csv=True,
        processing_chain="spectrum_curve",
        typical_content=("FTIR", "XRD", "EDS", "UV-vis", "TGA", "rheology frequency sweep"),
        coordinate_output="xy_spectrum_csv",
        binding_requirements=("scan_axis_binding", "peak_baseline_review"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="2d_field_map",
        label="二维颜色场 / 模拟场",
        suitable_for_csv=True,
        processing_chain="2d_field_map",
        typical_content=("N2/H2 concentration", "diffusion field", "energy terrain"),
        coordinate_output="grid_xyz_csv",
        binding_requirements=("colorbar_value_binding", "spatial_axis_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="microscopy_quant",
        label="显微图 / SEM / 荧光图 / EDS mapping",
        suitable_for_csv=False,
        processing_chain="microscopy_quant",
        typical_content=("cells", "pores", "carbonate deposits", "element distribution"),
        coordinate_output="object_quant_summary_csv",
        binding_requirements=("scale_bar_binding", "object_classification_binding"),
        requires_review=True,
    ),
    ChartTypeSpec(
        image_type="schematic_or_photo",
        label="示意图 / 流程图 / 照片 / 结构渲染",
        suitable_for_csv=False,
        processing_chain="schematic_or_photo",
        typical_content=("device structure", "metabolic pathway", "printing workflow", "material photo"),
        coordinate_output="caption_only",
    ),
)

CATALOG_BY_TYPE = {spec.image_type: spec for spec in CHART_TYPE_CATALOG}


def chart_type_spec(image_type: str) -> ChartTypeSpec | None:
    return CATALOG_BY_TYPE.get(image_type)
