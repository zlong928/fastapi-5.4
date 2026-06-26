from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualExtractionContract:
    key: str
    role: str
    schema_template: str
    requirements: tuple[str, ...]
    csv_fields: tuple[str, ...] = ()

    def render(self, route_key: str) -> str:
        requirements = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(self.requirements))
        schema = self.schema_template.format(route_key=route_key)
        return f"""{self.role} Current route: {route_key}. Output JSON:
{schema}

Key requirements:
{requirements}"""


VISUAL_EXTRACTION_CONTRACTS: dict[str, VisualExtractionContract] = {
    "coordinate": VisualExtractionContract(
        key="coordinate",
        role="You are a coordinate data extraction expert. Extract all data point coordinates from charts.",
        schema_template="""{{
  "figure": "figure_label",
  "chart_type": "{route_key}",
  "panels": [
    {{
      "panel": "panel_id (e.g. A/B/left/right)",
      "source_page": "page_number",
      "x_axis": {{"label": "X axis label", "unit": "unit", "type": "linear/log/time_series/spectrum_frequency"}},
      "y_axis": {{"label": "Y axis label", "unit": "unit", "type": "linear/log"}},
      "has_dual_y_axis": false,
      "right_y_axis": null,
      "phases": [
        {{"phase_name": "phase I/phase II", "x_start": null, "x_end": null, "boundary_note": "boundary description"}}
      ],
      "series": [
        {{
          "series_name": "series name",
          "color": "color",
          "marker": "marker type",
          "data_points": [
            {{"x": value, "y": value, "phase": null, "y_error": null}},
            {{"x": value, "y": value, "phase": null, "y_error": null}}
          ]
        }}
      ],
      "extraction_method": "vector/image_digitization",
      "notes": "notes"
    }}
  ]
}}""",
        requirements=(
            "Extract every visible data point's x,y coordinates",
            "Distinguish different data series by color and marker",
            "Identify axis type (linear/log)",
            "Check for dual y-axis",
            "For biphasic/phase time series, extract phases and bind each point to its phase",
            "For multi-curve charts, bind series_name to color/marker via legend",
            "For error bar charts, read y_error, mean+/-SD, significance markers",
            "For spectrum/frequency charts, use spectrum_frequency for x_axis.type and preserve peaks",
            "All quantifiable values must be numbers, not strings",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "series_name",
            "x_value",
            "y_value",
            "x_axis_label",
            "x_axis_unit",
            "x_axis_type",
            "y_axis_label",
            "y_axis_unit",
            "y_axis_type",
            "y_right_value",
            "y_right_axis_type",
            "legend_label",
            "legend_binding_status",
            "errorbar_height_px",
            "extraction_method",
            "axis_calibration_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "bar_chart": VisualExtractionContract(
        key="bar_chart",
        role="You are a bar chart / column chart data extraction expert.",
        schema_template="""{{
  "figure": "figure_label",
  "panel": "panel_id",
  "chart_type": "{route_key}",
  "x_axis": {{"label": "X axis label", "categories": ["category1", "category2"]}},
  "y_axis": {{"label": "Y axis label", "unit": "unit"}},
  "series": [
    {{
      "series_name": "series name",
      "bars": [
        {{"category": "category1", "value": number, "error_bar": null, "significance": null}}
      ]
    }}
  ],
  "extraction_method": "vector/raster_digitization/llm_assisted_reading",
  "confidence": 0.85,
  "notes": "notes"
}}""",
        requirements=(
            "Identify each bar's height and convert to numerical value",
            "Extract error bar values",
            "Distinguish different series in grouped bar charts",
            "Record significance markers (*, **, p-value, letter groups) in bars significance field or notes",
            "All values must be numbers",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "series_name",
            "x_axis_label",
            "y_axis_label",
            "y_axis_unit",
            "category_index",
            "category_label",
            "category_binding_status",
            "bar_left_px",
            "bar_right_px",
            "bar_top_px",
            "bar_bottom_px",
            "bar_height_px",
            "errorbar_top_px",
            "errorbar_bottom_px",
            "errorbar_height_px",
            "bar_geometry_status",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "heatmap": VisualExtractionContract(
        key="heatmap",
        role="You are a heatmap / 2D color field data extraction expert.",
        schema_template="""{{
  "figure": "figure_label",
  "panel": "panel_id",
  "chart_type": "{route_key}",
  "x_axis": {{"label": "X axis label", "values": ["col1", "col2"]}},
  "y_axis": {{"label": "Y axis label", "categories": ["row1", "row2"]}},
  "matrix": [[0.5, 0.8], [0.3, 0.9]],
  "colorbar": {{"min": 0, "max": 1, "label": "colorbar label", "unit": "unit or null"}},
  "extraction_method": "llm_assisted_reading",
  "confidence": 0.6,
  "notes": "Colorbar values approximate due to gradient"
}}""",
        requirements=(
            "Extract heatmap row and column labels",
            "Estimate matrix values from colors (mark as approximate if uncertain)",
            "Extract colorbar range, unit, and meaning",
            "For 2D color fields, export as grid rows/columns/matrix, not as scatter points",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "x_coordinate",
            "y_coordinate",
            "z_value",
            "z_axis_label",
            "z_axis_unit",
            "z_axis_type",
            "colorbar_min_value",
            "colorbar_max_value",
            "colorbar_unit",
            "colorbar_binding_status",
            "pixel_x",
            "pixel_y",
            "extraction_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "table_image": VisualExtractionContract(
        key="table_image",
        role="You are a table image OCR expert.",
        schema_template="""{{
  "figure": "figure_label",
  "panel": null,
  "chart_type": "{route_key}",
  "table_data": {{
    "headers": ["col1", "col2", "col3"],
    "rows": [
      ["A1", "85.3", "99.2"],
      ["A2", "90.1", "98.5"]
    ]
  }},
  "extraction_method": "llm_assisted_reading",
  "confidence": 0.7,
  "notes": "OCR quality high"
}}""",
        requirements=(
            "Read all cell contents from the table",
            "Keep header and data rows separated",
            "Maintain relative cell positions",
        ),
        csv_fields=(),
    ),
    "non_data_visual": VisualExtractionContract(
        key="non_data_visual",
        role="You are a non-coordinate image analysis expert, handling microscopy, SEM, fluorescence, EDS mapping, photos, schematics, and structural renders.",
        schema_template="""{{
  "figure": "figure_label",
  "panel": "panel_id",
  "chart_type": "{route_key}",
  "description": "detailed image description",
  "visible_elements": ["scale bar: 10 um", "cracks", "particles"],
  "quantitative_observations": [
    {{"name": "pore size/area/cell count/element distribution", "value": null, "unit": null, "method": "scale_bar/visual_count/qualitative"}}
  ],
  "extraction_method": "descriptive",
  "unsupported_reason": "No numerical data to extract"
}}""",
        requirements=(
            "Describe the main content and visible elements of the image",
            "Extract scale bar, ruler, and other metadata",
            "For microscopy_quant, prioritize reading scale bar and extract area, pore size, cell count, element distribution",
            "For schematic_or_photo, typically no CSV export, just preserve caption and structural description",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "scale_bar_length_px",
            "scale_bar_value",
            "scale_bar_unit",
            "pixel_size",
            "physical_area_value",
            "physical_area_unit",
            "component_area_px",
            "extraction_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
}


def visual_extraction_prompt(contract_key: str, route_key: str) -> str:
    contract = VISUAL_EXTRACTION_CONTRACTS[contract_key]
    return contract.render(route_key)


def visual_contract_csv_fields(contract_key: str) -> tuple[str, ...]:
    return VISUAL_EXTRACTION_CONTRACTS[contract_key].csv_fields


def generic_visual_system_prompt() -> str:
    return """You are a top scientific chart data extraction expert. Your task is to extract all visible data and information from images and explain in detail.

## Analysis Steps:

### Step 1: Identify chart type and structure
- Chart type: bar/line/scatter/microscopy/schematic/table/composite/other
- Axis info: X axis label, unit, scale values; Y axis label, unit, scale values
- Legend info: all series names, colors, markers
- Title and annotations: main title, subtitles, all text labels in figure

### Step 2: Extract all data points
- Bar chart: height value of each bar
- Line chart: X,Y coordinates of each data point
- Scatter plot: position of each point
- Microscopy/schematic: key dimensions, annotated values
- Table: all cell data

If values are clearly readable: record exact values.
If values are blurry: estimate range, e.g. "approximately 50-60".
If unreadable: note "value not readable" but describe approximate position and trend.

### Step 3: Extract text annotations
Record all text in figure: data labels, statistical significance markers, arrow annotations, error bar values, percentages, fold changes.

### Step 4: Summarize key findings
Summarize in detail: max values, min values, inter-group comparisons, trends, statistical significance, and key data points.

## Output JSON format:
{
  "figure_type": "specific chart type",
  "title": "chart title",
  "axes": {
    "x_axis": {"label": "X axis label", "unit": "unit", "visible_values": ["scale1", "scale2"]},
    "y_axis": {"label": "Y axis label", "unit": "unit", "range": "range (e.g. 0-100)"}
  },
  "legend": [
    {"name": "series name", "color": "color description", "marker": "marker type"}
  ],
  "data_points": [
    {
      "series": "series name",
      "x": "X value or category",
      "y": "Y value",
      "value_label": "data label",
      "error_bar": "error value if any",
      "significance": "significance marker if any"
    }
  ],
  "annotations": ["all text annotations in figure"],
  "statistics": {
    "max_value": {"value": number, "condition": "condition"},
    "min_value": {"value": number, "condition": "condition"},
    "comparisons": ["comparison 1: A is 50% higher than B", "comparison 2: C significantly lower than D (p<0.05)"]
  },
  "overall_description": "complete description including what the chart shows, main data points, key trends, important comparisons",
  "extractions": [{
    "metric": "extracted metric name",
    "success": true,
    "data": {"specific value fields": number},
    "qualitative": "detailed description of the metric value, trend, comparisons",
    "confidence": "high/medium/low",
    "notes": "additional notes",
    "evidence": "visible evidence in figure (axis values, annotation text, etc.)"
  }],
  "key_findings": [
    "Finding 1: specific value + unit + comparison",
    "Finding 2: trend + magnitude + significance"
  ],
  "extraction_completeness": "completeness assessment"
}

## Strict requirements:
1. All descriptions, labels, conclusions must be in English.
2. Do not miss data: extract every visible data point in the figure.
3. Precision first: record exact values when readable, do not just say "higher" or "increased".
4. Structured: data must be stored in the data_points array.
5. Verifiable: all conclusions must be based on visible evidence in the figure.
6. Complete explanation: key_findings must include specific values and units.

If unable to output valid JSON consistently, do not return empty response; output a text evidence description instead."""


def generic_visual_user_prompt(figure_id: str, caption: str, tasks_desc: str, review_note: str = "") -> str:
    review = f"\nReview note: {review_note}" if review_note else ""
    return f"""# Chart Information
- Figure ID: {figure_id}
- Caption: {caption}

# Extraction Tasks
{tasks_desc}

# Analysis Requirements
Follow the system prompt steps carefully to completely extract all information from this chart:

1. Complete structure identification: chart type, axes (labels + scale values), legend (all series)
2. Extract all data points: exact values for each bar/point/line, do not miss any
3. Record all text: title, labels, data labels, statistical markers, annotations
4. Summarize key findings: main data, comparisons, significance, must include specific values

Key requirements:
- Extract every visible data point in the figure
- Values must be recorded precisely (record exact value when readable)
- Conclusions must be specific (e.g. "Group A 85%, 41.7% higher than Group B 60%", not "Group A is higher")
{review}"""


def visual_text_fallback_prompt() -> str:
    return (
        "Please describe this paper figure or page screenshot in English. Only list positive information "
        "that is actually visible and verifiable in the figure: readable values, trends, axes, legends, "
        "text annotations, significance markers, structural positions or morphology. "
        "If a certain type of information does not exist, do not write 'not present/cannot extract/does not contain'. "
        "Do not output JSON, do not explain the process, keep within 500 words."
    )
