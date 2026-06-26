"""
FigureTypeClassifierAgent: 增强版分类器

输出：
- image_type（带 enum）
- panel_count（从可视布局或 caption 推断）
- route_family（data_chart | microscopy | protein_assay | non_data_visual）
- confidence
- fallback_reason
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import (
    FigureExtractionPlan,
    ImageType,
    VisualCategory,
)


CATEGORY_MAP: dict[ImageType, VisualCategory] = {
    ImageType.LINE_PLOT: VisualCategory.DATA_CHART,
    ImageType.BIPHASIC_TIME_SERIES: VisualCategory.DATA_CHART,
    ImageType.MULTI_LINE_PLOT: VisualCategory.DATA_CHART,
    ImageType.RHEOLOGY_FLOW_CURVE: VisualCategory.DATA_CHART,
    ImageType.RHEOLOGY_STRAIN_SWEEP: VisualCategory.DATA_CHART,
    ImageType.RHEOLOGY_STEP_TIME_SWEEP: VisualCategory.DATA_CHART,
    ImageType.SCATTER_PLOT: VisualCategory.DATA_CHART,
    ImageType.BAR_CHART: VisualCategory.DATA_CHART,
    ImageType.GROUPED_BAR: VisualCategory.DATA_CHART,
    ImageType.BAR_OR_LINE_WITH_ERRORBAR: VisualCategory.DATA_CHART,
    ImageType.BOX_PLOT: VisualCategory.DATA_CHART,
    ImageType.DUAL_AXIS_PLOT: VisualCategory.DATA_CHART,
    ImageType.HEATMAP: VisualCategory.DATA_CHART,
    ImageType.HEATMAP_MATRIX: VisualCategory.DATA_CHART,
    ImageType.SPECTRUM_CURVE: VisualCategory.DATA_CHART,
    ImageType.FIELD_2D_MAP: VisualCategory.DATA_CHART,
    ImageType.TABLE_IMAGE: VisualCategory.DATA_CHART,
    ImageType.GENERIC_COORDINATE_PLOT: VisualCategory.DATA_CHART,
    ImageType.MULTI_PANEL_COMPOSITE: VisualCategory.DATA_CHART,
    ImageType.WESTERN_BLOT: VisualCategory.PROTEIN_ASSAY,
    ImageType.GEL_IMAGE: VisualCategory.PROTEIN_ASSAY,
    ImageType.MICROSCOPY_QUANT: VisualCategory.MICROSCOPY,
    ImageType.FLUORESCENCE_MICROSCOPY: VisualCategory.MICROSCOPY,
    ImageType.SEM_TEM: VisualCategory.MICROSCOPY,
    ImageType.MULTI_CHANNEL_MICROSCOPY: VisualCategory.MICROSCOPY,
    ImageType.NON_DATA_IMAGE: VisualCategory.NON_DATA_VISUAL,
    ImageType.SCHEMATIC: VisualCategory.NON_DATA_VISUAL,
    ImageType.SCHEMATIC_OR_PHOTO: VisualCategory.NON_DATA_VISUAL,
    ImageType.UNKNOWN: VisualCategory.UNKNOWN,
}


def image_type_to_visual_category(image_type: ImageType) -> VisualCategory:
    return CATEGORY_MAP.get(image_type, VisualCategory.UNKNOWN)


_CLASSIFICATION_PROMPT = """你是科研图片类型识别专家。识别图片类型并输出JSON：
{
  "image_type": "line_plot/multi_line_plot/scatter_plot/bar_chart/grouped_bar/bar_or_line_with_errorbar/box_plot/dual_axis_plot/heatmap/heatmap_matrix/spectrum_curve/2d_field_map/rheology_flow_curve/rheology_strain_sweep/rheology_step_time_sweep/biphasic_time_series/generic_coordinate_plot/table_image/multi_panel_composite/western_blot/gel_image/microscopy_quant/sem_tem/fluorescence_microscopy/multi_channel_microscopy/non_data_image/schematic/schematic_or_photo/unknown",
  "panel_count": 1,
  "has_x_axis": true/false,
  "has_y_axis": true/false,
  "axis_type": "linear/log/time_series/spectrum_frequency/none",
  "has_dual_y_axis": true/false,
  "route_family": "data_chart/microscopy/protein_assay/non_data_visual/unknown",
  "confidence": 0.0-1.0,
  "fallback_reason": "判断理由"
}

分类规则：
- line_plot: 折线图/曲线图/时序图
- multi_line_plot: 多条曲线需图例辨认
- bar_chart: 柱状图
- grouped_bar: 分组柱状图
- heatmap_matrix: 热图/矩阵图
- spectrum_curve: 光谱图（FTIR, XRD, UV-Vis等）
- scatter_plot: 散点图
- rheology_flow_curve: 流变稳态流动曲线
- rheology_strain_sweep: 流变振幅扫描
- rheology_step_time_sweep: 流变阶跃时间扫描
- biphasic_time_series: 双相时序图
- western_blot: Western blot / 免疫印迹
- gel_image: 琼脂糖凝胶/PAGE/DNA胶
- microscopy_quant: 显微镜/SEM/TEM（有scale bar）
- sem_tem: SEM/TEM（无荧光）
- fluorescence_microscopy: 荧光显微镜（DAPI, FITC, Cy5等通道）
- multi_channel_microscopy: 多通道叠加显微
- non_data_image: 照片/无数据图像
- schematic: 流程图/示意图/结构图
- table_image: 栅格化表格

优先使用最具体的类型；只有无法判断时才使用 generic_coordinate_plot 或 unknown。"""


class FigureTypeClassifierAgent:
    """增强版分类器，输出 panel_count、route_family、confidence、fallback_reason"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(self, plan: FigureExtractionPlan) -> dict[str, Any]:
        """返回完整分类结果字典"""
        # 先从 caption 尝试判断
        caption_result = self._classify_from_caption(plan.caption or "", plan.nearby_text or "")
        if caption_result["confidence"] >= 0.7:
            return caption_result

        # LLM 视觉分类
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return self._default_result(ImageType.UNKNOWN, "image_unreadable")

        try:
            payload = self.client.chat_json(
                [
                    {"role": "system", "content": _CLASSIFICATION_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"图号：{plan.figure_id}\n图注：{plan.caption}\n"
                                    f"附近正文：{plan.nearby_text[:500]}\n"
                                    f"请识别图片类型、面板数量、路由家族。"
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="image_classification_v2",
            )
            result = self._parse_llm_output(payload, plan)
            return result
        except Exception as exc:
            fallback = self._classify_from_caption(plan.caption or "", plan.nearby_text or "")
            if fallback["confidence"] > 0:
                return fallback
            return self._default_result(ImageType.UNKNOWN, str(exc)[:120])

    def _classify_from_caption(self, caption: str, nearby_text: str) -> dict[str, Any]:
        """仅基于 caption + nearby text 的分类（高置信度时使用）"""
        blob = (caption + " " + nearby_text).lower()

        strong_matches: list[tuple[list[str], ImageType, float]] = [
            (["western blot", "immunoblot", "western blotting"], ImageType.WESTERN_BLOT, 0.85),
            (["sds-page", "gel electrophoresis", "sds page"], ImageType.GEL_IMAGE, 0.8),
            (["sem image", "sem micrograph", "sem microphotograph"], ImageType.SEM_TEM, 0.85),
            (["tem image", "tem micrograph", "tem microphotograph"], ImageType.SEM_TEM, 0.85),
            (["dapi", "fitc", "immunofluorescence", "confocal microscopy"], ImageType.FLUORESCENCE_MICROSCOPY, 0.8),
            (["scale bar", "scalebar", "µm", "μm"], ImageType.MICROSCOPY_QUANT, 0.6),
            (["schematic", "workflow diagram", "mechanism diagram", "示意", "流程"], ImageType.SCHEMATIC, 0.75),
            (["ftir", "xrd pattern", "uv-vis spectrum", "raman shift", "wavenumber"], ImageType.SPECTRUM_CURVE, 0.8),
            (["flow curve", "viscosity curve", "shear rate"], ImageType.RHEOLOGY_FLOW_CURVE, 0.7),
            (["strain sweep", "storage modulus", "loss modulus", "g'", "g''", "g′"], ImageType.RHEOLOGY_STRAIN_SWEEP, 0.75),
        ]
        for keywords, img_type, conf in strong_matches:
            if any(kw in blob for kw in keywords):
                return self._result_for(img_type, 1, conf, f"caption_match_{img_type.value}")

        return self._default_result(ImageType.UNKNOWN, "caption_insufficient")

    def _parse_llm_output(self, payload: dict, plan: FigureExtractionPlan) -> dict[str, Any]:
        image_type = self._parse_image_type(payload.get("image_type", "unknown"))
        panel_count = int(payload.get("panel_count", 1))
        confidence = float(payload.get("confidence", 0.5))
        fallback_reason = str(payload.get("fallback_reason", ""))
        route_family = str(payload.get("route_family", ""))
        if not route_family:
            route_family = image_type_to_visual_category(image_type).value

        return self._result_for(image_type, max(1, panel_count), min(1.0, max(0.0, confidence)), fallback_reason, route_family)

    def _result_for(
        self, image_type: ImageType, panel_count: int, confidence: float,
        fallback_reason: str, route_family: str | None = None,
    ) -> dict[str, Any]:
        if not route_family:
            route_family = image_type_to_visual_category(image_type).value
        return {
            "image_type": image_type.value,
            "image_type_enum": image_type,
            "panel_count": panel_count,
            "route_family": route_family,
            "confidence": confidence,
            "fallback_reason": fallback_reason,
        }

    def _default_result(self, image_type: ImageType, reason: str = "") -> dict[str, Any]:
        return self._result_for(
            image_type, 1, 0.0 if image_type == ImageType.UNKNOWN else 0.5,
            reason,
        )

    @staticmethod
    def _parse_image_type(value: str) -> ImageType:
        val = value.strip().lower()
        for it in ImageType:
            if it.value == val:
                return it
        aliases: dict[str, ImageType] = {
            "coordinate_plot": ImageType.GENERIC_COORDINATE_PLOT,
            "image_evidence": ImageType.NON_DATA_IMAGE,
            "gel": ImageType.GEL_IMAGE,
            "western": ImageType.WESTERN_BLOT,
            "blot": ImageType.WESTERN_BLOT,
            "microscopy": ImageType.MICROSCOPY_QUANT,
            "fluorescence": ImageType.FLUORESCENCE_MICROSCOPY,
            "confocal": ImageType.FLUORESCENCE_MICROSCOPY,
            "chromatogram": ImageType.SPECTRUM_CURVE,
            "boxplot": ImageType.BOX_PLOT,
            "violin": ImageType.BOX_PLOT,
        }
        if val in aliases:
            return aliases[val]
        return ImageType.UNKNOWN
