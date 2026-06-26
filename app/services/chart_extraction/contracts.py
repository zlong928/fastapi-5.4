from __future__ import annotations

from pydantic import BaseModel, Field


class AxisContract(BaseModel):
    label: str = ""
    unit: str = ""
    scale: str = "linear"
    range_hint_min: float | None = None
    range_hint_max: float | None = None


class SeriesContract(BaseModel):
    name: str = ""
    color_hint: str = ""
    marker_hint: str = ""


class Contract(BaseModel):
    image_type: str
    x_axis: AxisContract = Field(default_factory=AxisContract)
    y_axis: AxisContract = Field(default_factory=AxisContract)
    series: list[SeriesContract] = Field(default_factory=list)
    numerical_constraints: list[str] = Field(default_factory=list)
    csv_columns: list[str] = Field(default_factory=list)


CONTRACT_REGISTRY: dict[str, Contract] = {}


def register(contract: Contract) -> None:
    CONTRACT_REGISTRY[contract.image_type] = contract


def get_contract(image_type: str) -> Contract:
    return CONTRACT_REGISTRY.get(image_type, CONTRACT_REGISTRY.get("generic_coordinate_plot"))


_DEFAULT_CSV = [
    "image_file", "image_type", "panel_id", "series_name",
    "x_value", "y_value", "x_unit", "y_unit",
    "x_axis_label", "y_axis_label", "x_axis_type", "y_axis_type",
    "extraction_method", "axis_calibration_method", "confidence",
]

_EXTRA_CSV = "__extra__"  # sentinel

_CONTRACT_SPECS: dict[str, dict] = {
    "line_plot":              {},
    "multi_line_plot":        {},
    "scatter_plot":           {},
    "spectrum_curve":         {},
    "generic_coordinate_plot": {},

    "rheology_flow_curve": {
        "x_axis": dict(label="Shear rate", unit="s⁻¹", scale="log10", range_hint_min=0.001),
        "y_axis": dict(label="Viscosity", unit="mPa·s", scale="log10", range_hint_min=0.001),
        "numerical_constraints": ["x_value > 0", "y_value > 0"],
    },
    "rheology_strain_sweep": {
        "x_axis": dict(label="Strain", unit="%", scale="log10", range_hint_min=0.001),
        "y_axis": dict(label="Modulus", unit="Pa", scale="log10", range_hint_min=0.001),
        "numerical_constraints": ["x_value > 0", "y_value > 0"],
    },
    "rheology_step_time_sweep": {
        "x_axis": dict(label="Time", unit="s", scale="linear"),
        "y_axis": dict(label="Viscosity", unit="mPa·s", scale="linear"),
        "numerical_constraints": ["x_value >= 0", "y_value > 0"],
    },
    "biphasic_time_series": {
        "x_axis": dict(label="Time", scale="linear"),
        "csv_columns": _DEFAULT_CSV + ["phase"],
    },

    "bar_chart": {
        "x_axis": dict(scale=""),
        "y_axis": dict(scale="linear"),
        "numerical_constraints": ["y_value >= 0"],
    },
    "grouped_bar": {
        "x_axis": dict(scale=""),
        "y_axis": dict(scale="linear"),
        "numerical_constraints": ["y_value >= 0"],
    },
    "bar_or_line_with_errorbar": {
        "x_axis": dict(scale=""),
        "y_axis": dict(scale="linear"),
        "numerical_constraints": ["y_value >= 0"],
        "csv_columns": _DEFAULT_CSV + ["error_bar", "significance"],
    },

    "heatmap_matrix": {
        "x_axis": dict(scale="grid"),
        "y_axis": dict(scale="grid"),
        "numerical_constraints": ["z_value within colorbar_range"],
        "csv_columns": _DEFAULT_CSV + ["z_value", "z_unit"],
    },
    "2d_field_map": {
        "x_axis": dict(scale="field"),
        "y_axis": dict(scale="field"),
        "csv_columns": _DEFAULT_CSV + ["z_value", "z_unit"],
    },

    "table_image": {
        "csv_columns": [],
    },
    "microscopy_quant": {
        "csv_columns": _DEFAULT_CSV + [
            "scale_bar_value", "scale_bar_unit", "pixel_size",
            "object_class", "object_area_physical", "object_diameter_physical",
        ],
    },
    "dual_axis_plot": {
        "csv_columns": _DEFAULT_CSV + ["y_right_value", "y_right_type"],
    },
}

for name, spec in _CONTRACT_SPECS.items():
    x_axis_args = spec.pop("x_axis", {})
    y_axis_args = spec.pop("y_axis", {})
    csv_cols = spec.pop("csv_columns", _DEFAULT_CSV)
    register(Contract(
        image_type=name,
        x_axis=AxisContract(**x_axis_args),
        y_axis=AxisContract(**y_axis_args),
        csv_columns=csv_cols,
        **spec,
    ))
