from __future__ import annotations

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import FigureExtractionPlan, ImageType
from app.services.agent.visual_contracts import visual_extraction_prompt
from app.services.chart_extraction import CHART_TYPE_CATALOG


_SUPPLEMENTAL_IMAGE_TYPE_RULES = {
    ImageType.GROUPED_BAR.value: "分组柱状图，不同组别或材料并列柱，需要绑定类别和系列",
    ImageType.BOX_PLOT.value: "箱线图/violin图",
    ImageType.DUAL_AXIS_PLOT.value: "双Y轴图（左右两个y轴）",
    ImageType.TABLE_IMAGE.value: "栅格化的表格图像",
    ImageType.GENERIC_COORDINATE_PLOT.value: "复杂或罕见的坐标图",
    ImageType.NON_DATA_IMAGE.value: "照片、荧光图、SEM、显微镜图等非普通坐标数据图",
    ImageType.SCHEMATIC.value: "流程图、示意图、结构图",
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
    catalog_rules = {
        spec.image_type: f"{spec.label}，例如 {', '.join(spec.typical_content)}"
        for spec in CHART_TYPE_CATALOG
    }
    rules = {**catalog_rules, **_SUPPLEMENTAL_IMAGE_TYPE_RULES}
    allowed_types = [image_type.value for image_type in ImageType]
    rule_lines = "\n".join(f"- {image_type}: {rules[image_type]}" for image_type in allowed_types if image_type in rules)
    allowed_type_text = "/".join(allowed_types)
    return f"""你是科研图片类型识别专家。识别图片类型并输出JSON：
{{
  "image_type": "{allowed_type_text}",
  "has_x_axis": true/false,
  "has_y_axis": true/false,
  "axis_type": "linear/log/time_series/none",
  "has_dual_y_axis": true/false,
  "reason": "判断理由"
}}

分类规则：
{rule_lines}

优先使用最具体的类型；只有无法判断时才使用 generic_coordinate_plot 或 unknown。"""


class ImageClassifierAgent:
    """识别图片类型，并把图片送入稳定的专用处理链路。"""

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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n请识别图片类型。"},
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
    """专门提取坐标图中的数据点"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_coordinates(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "图片不可读"}
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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n\n请提取所有数据点坐标。"},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="coordinate_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class BarChartAgent:
    """专门提取条形图/柱状图数据"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_bars(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "图片不可读"}
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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n\n请提取柱状图数据。"},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="bar_chart_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class HeatmapAgent:
    """专门提取热图数据"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_heatmap(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "图片不可读"}
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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n\n请提取热图数据。"},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="heatmap_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class TableImageAgent:
    """专门提取栅格化表格数据"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract_table_image(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "图片不可读"}
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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n\n请提取表格中的数据。"},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="table_image_extraction",
            )
        except Exception as exc:
            return {"error": str(exc)}


class NonDataVisualAgent:
    """处理非数据视觉证据（照片、显微图等）"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def describe_visual(self, plan: FigureExtractionPlan) -> dict:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return {"error": "图片不可读"}
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
                            {"type": "text", "text": f"图号：{plan.figure_id}\n图注：{plan.caption}\n\n请描述这张图像。"},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="non_data_visual_description",
            )
        except Exception as exc:
            return {"error": str(exc)}
