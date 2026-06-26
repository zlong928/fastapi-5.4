from __future__ import annotations

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import FigureExtractionPlan, ImageType
from app.services.agent.visual_contracts import visual_extraction_prompt


_SUPPLEMENTAL_IMAGE_TYPE_RULES = {
    ImageType.GROUPED_BAR.value: "Grouped bar chart with side-by-side bars for different groups or materials",
    ImageType.BOX_PLOT.value: "Box plot or violin plot",
    ImageType.DUAL_AXIS_PLOT.value: "Dual Y-axis plot (left and right y axes)",
    ImageType.TABLE_IMAGE.value: "Rasterized table image",
    ImageType.GENERIC_COORDINATE_PLOT.value: "Complex or rare coordinate chart",
    ImageType.NON_DATA_IMAGE.value: "Photo, fluorescence image, SEM, microscopy image etc. (non-coordinate data)",
    ImageType.SCHEMATIC.value: "Flowchart, schematic diagram, structural diagram",
}

_IMAGE_TYPE_ALIASES = {
    "coordinate_plot": ImageType.GENERIC_COORDINATE_PLOT,
    "image_evidence": ImageType.NON_DATA_IMAGE,
}


def image_type_from_string(value: object) -> ImageType:
    type_str = str(value or "unknown").strip().lower()
    if type_str in _IMAGE_TYPE_ALIASES:
        return _IMAGE_TYPE_ALIASES[type_str]
    for image_type in ImageType:
        if image_type.value == type_str:
            return image_type
    return ImageType.UNKNOWN


def image_classification_prompt() -> str:
    rules = _SUPPLEMENTAL_IMAGE_TYPE_RULES
    allowed_types = [image_type.value for image_type in ImageType]
    rule_lines = "\n".join(f"- {image_type}: {rules[image_type]}" for image_type in allowed_types if image_type in rules)
    allowed_type_text = "/".join(allowed_types)
    return f"""You are a scientific figure type classifier. Identify the image type and output JSON:
{{
  "image_type": "{allowed_type_text}",
  "has_x_axis": true/false,
  "has_y_axis": true/false,
  "axis_type": "linear/log/time_series/none",
  "has_dual_y_axis": true/false,
  "reason": "classification reason"
}}

Classification rules:
{rule_lines}

Use the most specific type; only use generic_coordinate_plot or unknown when truly uncertain."""


class ImageClassifierAgent:
    """Classify image type and route to appropriate processing chain."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(self, plan: FigureExtractionPlan) -> ImageType:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return ImageType.UNKNOWN
        try:
            payload = self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": image_classification_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\nPlease classify this image."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="image_classification",
            )
            return image_type_from_string(payload.get("image_type", "unknown"))
        except Exception:
            return ImageType.UNKNOWN


class CoordinateExtractionAgent:
    """Extract coordinate data from chart images via LLM."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_coordinates(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "Image unreadable"}
        route_key = plan.image_type.value if plan.image_type else "generic_coordinate_plot"
        try:
            return self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": visual_extraction_prompt("coordinate", route_key),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\n\nExtract all data point coordinates."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="coordinate_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class BarChartAgent:
    """Extract bar chart / column chart data."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_bars(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "Image unreadable"}
        route_key = plan.image_type.value if plan.image_type else "bar_chart"
        try:
            return self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": visual_extraction_prompt("bar_chart", route_key),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\n\nExtract bar chart data."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="bar_chart_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class HeatmapAgent:
    """Extract heatmap data."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_heatmap(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "Image unreadable"}
        route_key = plan.image_type.value if plan.image_type else "heatmap_matrix"
        try:
            return self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": visual_extraction_prompt("heatmap", route_key),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\n\nExtract heatmap data."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="heatmap_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class TableImageAgent:
    """Extract rasterized table data."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_table_image(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "Image unreadable"}
        try:
            return self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": visual_extraction_prompt("table_image", "table_image"),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\n\nExtract table data."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="table_image_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class NonDataVisualAgent:
    """Handle non-data visual evidence (photos, microscopy, etc.)"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def describe_visual(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "Image unreadable"}
        route_key = plan.image_type.value if plan.image_type else "non_data_image"
        try:
            return self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": visual_extraction_prompt("non_data_visual", route_key),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Figure ID: {plan.figure_id}\nCaption: {plan.caption}\n\nDescribe this image."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="non_data_visual_description",
            )
        except Exception as exc:
            return {"error": str(exc)}
