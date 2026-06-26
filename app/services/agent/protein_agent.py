"""
ProteinAgent: Western blot / gel / protein assay 专用 agent。

输出结构化的 lane、band intensity、molecular weight marker、loading control、normalization ratio。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import (
    ExtractionPoint,
    FigureExtractionPlan,
    extraction_point_to_dict,
)


_WB_SYSTEM_PROMPT = """你是Western blot / 凝胶电泳分析专家。识别图中所有条带并输出JSON：

{
  "figure": "图号",
  "experiment_type": "western_blot/gel_image/protein_assay",
  "lanes": [
    {
      "lane_number": 1,
      "lane_label": "样品名称（如Control/Treated/Marker）",
      "bands": [
        {
          "band_label": "条带标记（如target protein、loading control名称）",
          "target_protein": "目标蛋白名称",
          "molecular_weight_kda": 数值或null,
          "relative_intensity": 数值（相对band强度，0-100或任意相对比例）,
          "normalized_intensity": 数值或null（相对于loading control的归一化值）,
          "loading_control": "loading control名称（如GAPDH）",
          "has_phosphorylation": true/false,
          "phosphorylation_site": "磷酸化位点（如有）",
          "note": "备注"
        }
      ]
    }
  ],
  "mw_marker": {
    "description": "分子量标记描述",
    "bands_kda": [170, 130, 95, 72, 55, 43, 34, 26, 17, 10]
  },
  "overall_description": "整体描述",
  "confidence": 0.0-1.0,
  "notes": "备注"
}

关键要求：
1. 识别每条泳道（lane）的样品名称
2. 识别每个条带对应的目标蛋白和分子量 (kDa)
3. 读取或估算相对条带强度（quantitative或semi-quantitative）
4. 如果有loading control（如GAPDH, β-actin, Tubulin），提取并记录
5. 识别分子量标记（MW marker）的条带位置
6. 所有数值必须是数字（强度可以是相对值0-100的范围）
7. 如果无法精确读数，给出合理范围如"40-50 kDa"
"""

_PROTEIN_ASSAY_PROMPT = """你是凝胶电泳（琼脂糖凝胶、PAGE）分析专家。识别图中所有泳道和条带并输出JSON：

{
  "figure": "图号",
  "experiment_type": "agarose_gel/native_page/sds_page/dna_gel",
  "lanes": [
    {
      "lane_number": 1,
      "lane_label": "样本名称",
      "bands": [
        {
          "band_label": "条带名称",
          "molecular_weight_kda": 数值或null,
          "relative_intensity": 数值,
          "note": "备注"
        }
      ]
    }
  ],
  "overall_description": "整体描述",
  "confidence": 0.0-1.0,
  "notes": "备注"
}

关键要求：
- DNA凝胶：注意 marker 的碱基数（bp/kb），条带大小用kb值
- 蛋白质凝胶：用kDa值
- 条带强度用相对值（0-100）
- 同一gel的不同lane做相对定量时标注loading control"""


class ProteinAgent:
    """Western blot / gel 分析 agent"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(self, plan: FigureExtractionPlan) -> dict[str, Any]:
        """分析 Western blot 或凝胶图像"""
        started = time.time()
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return self._error_result(plan, "图片不可读")

        prompt = self._select_prompt(plan)
        caption_lower = (plan.caption + " " + plan.nearby_text).lower()

        try:
            payload = self.client.chat_json(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"图号：{plan.figure_id}\n图注：{plan.caption}\n"
                                    f"附近正文：{plan.nearby_text[:600]}\n\n"
                                    f"请提取所有泳道(lane)和条带(band)数据。"
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="protein_extraction",
            )
        except Exception as exc:
            return self._error_result(plan, str(exc))

        points = self._payload_to_points(payload, plan, caption_lower)
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "protein_assay",
            "image_type": plan.image_type.value if plan.image_type else "western_blot",
            "chart_data": payload,
            "overall_description": payload.get("overall_description", ""),
            "extraction_points": [extraction_point_to_dict(p) for p in points],
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": payload,
                    "qualitative": payload.get("overall_description", ""),
                    "confidence": "high" if payload.get("confidence", 0) >= 0.7 else "medium",
                    "notes": f"{len(points)} bands extracted",
                    "mode": "protein_assay_extraction",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _select_prompt(self, plan: FigureExtractionPlan) -> str:
        blob = (plan.caption + " " + plan.nearby_text).lower()
        if any(kw in blob for kw in ["western", "immunoblot", "blotting"]):
            return _WB_SYSTEM_PROMPT
        return _PROTEIN_ASSAY_PROMPT

    def _payload_to_points(
        self, payload: dict, plan: FigureExtractionPlan, caption_lower: str
    ) -> list[ExtractionPoint]:
        points: list[ExtractionPoint] = []
        lanes = payload.get("lanes") or []
        for lane in lanes:
            lane_num = int(lane.get("lane_number", 0))
            lane_label = str(lane.get("lane_label", f"Lane_{lane_num}"))
            for band in lane.get("bands") or []:
                pt = ExtractionPoint(
                    figure_id=plan.figure_id,
                    image_path=plan.image_path,
                    source_type="llm_agent",
                    extraction_method="protein_assay_llm",
                    route_family="protein_assay",
                    image_type=plan.image_type.value if plan.image_type else "western_blot",
                    series_name=lane_label,
                    lane_number=lane_num,
                    band_label=str(band.get("band_label", "")),
                    band_intensity=self._safe_float(band.get("relative_intensity")),
                    band_intensity_norm=self._safe_float(band.get("normalized_intensity")),
                    molecular_weight_kda=self._safe_float(band.get("molecular_weight_kda")),
                    target_protein=str(band.get("target_protein", "")),
                    loading_control=str(band.get("loading_control", "")),
                    overall_description=payload.get("overall_description", ""),
                    qualitative=f"lane {lane_num}: {lane_label} - {band.get('band_label', '')}",
                    confidence=float(payload.get("confidence", 0.5)),
                    needs_review=float(payload.get("confidence", 0)) < 0.6,
                    review_reason="" if float(payload.get("confidence", 0)) >= 0.6 else "low_confidence_protein_assay",
                )

                # 尝试从 caption 提取 loading control
                if not pt.loading_control:
                    for lc in ["gapdh", "β-actin", "beta-actin", "actin", "tubulin", "β-tubulin"]:
                        if lc in caption_lower:
                            pt.loading_control = lc.upper()
                            break

                points.append(pt)

        # 如果没有 lanes，但 payload 有整体描述
        if not points:
            pt = ExtractionPoint(
                figure_id=plan.figure_id,
                image_path=plan.image_path,
                source_type="llm_agent",
                extraction_method="protein_assay_llm",
                route_family="protein_assay",
                image_type=plan.image_type.value if plan.image_type else "western_blot",
                overall_description=payload.get("overall_description", ""),
                qualitative=payload.get("overall_description", ""),
                confidence=float(payload.get("confidence", 0.3)),
                needs_review=True,
                review_reason="no_structured_lanes_extracted",
            )
            points.append(pt)

        return points

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _error_result(self, plan: FigureExtractionPlan, reason: str) -> dict[str, Any]:
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "protein_assay",
            "image_type": plan.image_type.value if plan.image_type else "western_blot",
            "overall_description": plan.caption or "蛋白分析失败",
            "error": reason,
            "extraction_points": [],
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": False,
                    "data": {},
                    "qualitative": plan.caption or f"蛋白分析失败：{reason}",
                    "confidence": "none",
                    "notes": f"蛋白分析失败：{reason}",
                }
                for task in plan.tasks
            ],
            "elapsed": 0,
        }
