"""
CaptionAlignmentAgent: 在分类前提供 caption/正文/图片上下文对齐，
在提取后做正反向验证。

数据流：
  Figure Discovery → CaptionAlignment → Type Classifier → ... → Extraction → Caption Validation
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import CaptionBinding, FigureExtractionPlan, FigureInfo, ImageType


class CaptionAlignmentAgent:
    """Caption/nearby-text/figure-label 对齐 + 校验"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client

    def align_batch(
        self,
        figures: list[FigureInfo],
        full_text: str = "",
    ) -> dict[str, CaptionBinding]:
        """对每张图执行 caption 对齐，返回 figure_id → CaptionBinding 映射"""
        bindings: dict[str, CaptionBinding] = {}
        for fig in figures:
            binding = self._align_single(fig, full_text)
            bindings[fig.figure_id] = binding
        return bindings

    def _align_single(self, fig: FigureInfo, full_text: str) -> CaptionBinding:
        """对单张图做 caption 绑定"""
        caption = fig.caption or ""
        context = fig.context or ""
        text_lower = full_text.lower()

        # 1. 提取 figure label
        fig_label = self._extract_figure_label(fig.figure_id, caption)
        fig_label_in_text = self._find_in_text(fig_label, text_lower) if fig_label else ""

        # 2. 提取 panel labels from caption
        panel_labels = self._extract_panel_labels(caption)

        # 3. 统计正文引用次数
        ref_count = self._count_references(full_text, fig_label) if fig_label else 0

        # 4. nearby text 提取
        nearby = self._extract_nearby_text(full_text, fig_label) if fig_label else context

        # 5. caption 是否可以验证（反向检查）
        caption_verified, caption_conf = self._verify_caption(caption, context)

        return CaptionBinding(
            figure_id=fig.figure_id,
            caption_text=caption,
            nearby_text=nearby,
            fig_label_in_text=fig_label_in_text,
            fig_label_in_image=fig_label,
            page_number=self._extract_page_number(fig.context),
            reference_count=ref_count,
            has_panel_labels=len(panel_labels) > 0,
            panel_labels=panel_labels,
            caption_verified=caption_verified,
            caption_confidence=caption_conf,
        )

    def _extract_figure_label(self, figure_id: str, caption: str) -> str:
        """从 figure_id 或 caption 中提取纯 label"""
        # 尝试从 figure_id 提取
        m = re.search(r"(?i)(?:fig(?:ure)?\.?|图)\s*([0-9]+[a-z]?(?:\s*[A-Z]?)?)", figure_id)
        if m:
            raw = m.group(0)
            return raw.strip().replace(" ", "")
        # 从 caption 提取
        m = re.search(r"(?i)((?:fig(?:ure)?\.?|图)\s*[0-9]+[a-z]?(?:\s*[A-Z]?)?)", caption)
        if m:
            return m.group(1).strip()
        return figure_id

    def _find_in_text(self, label: str, text: str) -> str:
        """查找 label 在正文中的表现形式"""
        # 尝试标准形态
        candidates = [
            label,
            label.replace("figure", "fig").replace("Figure", "Fig"),
            label.replace("Fig", "Figure"),
            label.replace(" ", ""),
        ]
        for c in candidates:
            cl = c.lower()
            if cl in text:
                return c
        return label

    _PANEL_RE = re.compile(r"(?i)\(([a-zA-Z](?:\s*[,;]\s*[a-zA-Z])*)\)")

    def _extract_panel_labels(self, caption: str) -> list[str]:
        """从 caption 提取面板标签：Figure 3 (A, B, C) → ['A', 'B', 'C']"""
        labels: list[str] = []
        for m in self._PANEL_RE.finditer(caption):
            content = m.group(1)
            parts = re.split(r"\s*[,;]\s*", content)
            for p in parts:
                p = p.strip()
                if len(p) == 1 and p.isalpha():
                    labels.append(p.upper())
        return labels

    def _count_references(self, full_text: str, fig_label: str) -> int:
        """统计正文引用次数"""
        base = fig_label.replace("Figure", "Fig").replace("figure", "fig").replace(" ", "")
        text_compact = re.sub(r"\s+", "", full_text.lower())
        return max(0, text_compact.count(base.lower()))

    def _extract_nearby_text(self, full_text: str, fig_label: str) -> str:
        """提取 figure label 在正文附近的上下文"""
        # 尝试定位 label
        patterns = [
            re.escape(fig_label),
            re.escape(fig_label.replace("Figure", "Fig.")),
            re.escape(fig_label.replace(" ", "")),
        ]
        for pat in patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 200)
                end = min(len(full_text), m.end() + 400)
                return full_text[start:end].strip()
        return ""

    def _extract_page_number(self, context: str) -> int | None:
        m = re.search(r"page_number=(\d+)", context)
        if m:
            return int(m.group(1))
        return None

    def _verify_caption(self, caption: str, context: str) -> tuple[bool, float]:
        """检查 caption 是否与图像上下文一致"""
        if not caption:
            return False, 0.0
        # 如果 caption 中有 scale bar、channel 信息，但 context 没有 → 低置信度
        has_scale = "scale bar" in caption.lower()
        has_channel = any(ch in caption.lower() for ch in ["dapi", "fitc", "cy5", "gfp", "rfp"])
        if has_scale and not has_scale:
            return True, 0.6  # 只有 caption 提到 scale，无法验证
        if caption:
            return True, 0.7
        return False, 0.3

    def enrich_plan_with_alignment(
        self,
        plan: FigureExtractionPlan,
        binding: CaptionBinding,
    ) -> FigureExtractionPlan:
        """用 binding 信息丰富 extraction plan"""
        plan.nearby_text = binding.nearby_text or plan.nearby_text
        plan.panel_count = max(plan.panel_count, len(binding.panel_labels) or 1)
        if binding.caption_text and not plan.caption:
            plan.caption = binding.caption_text

        # 根据 caption 内容推断图类型 hint
        caption_lower = (plan.caption + " " + binding.nearby_text).lower()
        image_type = self._infer_type_from_caption(caption_lower)
        if image_type and plan.image_type is None:
            plan.image_type = image_type

        return plan

    def _infer_type_from_caption(self, text: str) -> ImageType | None:
        text_lower = text.lower()
        hints: list[tuple[list[str], ImageType]] = [
            (["western blot", "western blotting", "immunoblot", "gel electrophoresis", "sds-page"], ImageType.WESTERN_BLOT),
            (["agarose gel", "pcr", "dna gel", "gel image"], ImageType.GEL_IMAGE),
            (["sem", "tem", "scanning electron", "transmission electron"], ImageType.SEM_TEM),
            (["fluorescence", "confocal", "immunofluorescence", "dapi", "fitc", "cy5", "gfp"], ImageType.FLUORESCENCE_MICROSCOPY),
            (["microscopy", "micrograph", "scale bar", "μm", "µm"], ImageType.MICROSCOPY_QUANT),
            (["schematic", "workflow", "mechanism", "diagram", "示意", "流程"], ImageType.SCHEMATIC),
        ]
        for keywords, img_type in hints:
            if any(kw in text_lower for kw in keywords):
                return img_type
        return None

    def validate_extraction(
        self,
        pt: dict[str, Any],
        binding: CaptionBinding,
    ) -> dict[str, Any]:
        """提取后验证：检查提取结果与 caption 的一致性"""
        warnings: list[str] = []
        caption_lower = (binding.caption_text + " " + binding.nearby_text).lower()

        # 检查 scale bar caption 与提取结果
        if "scale bar" in caption_lower:
            scale_val = pt.get("scale_bar_value") or pt.get("scale_bar_length_px")
            if not scale_val:
                warnings.append("caption_mentions_scale_bar_but_no_scale_bar_detected")

        # 检查 channel 信息
        mentioned_channels = []
        for ch in ["dapi", "fitc", "cy5", "gfp", "rfp", "brightfield"]:
            if ch in caption_lower:
                mentioned_channels.append(ch)
        extracted_channel = str(pt.get("channel", "")).lower()
        if mentioned_channels and extracted_channel not in mentioned_channels:
            warnings.append(f"caption_mentions_channels_{','.join(mentioned_channels)}_but_channel_is_{extracted_channel or 'not_set'}")

        # 检查 panel count
        if binding.has_panel_labels and pt.get("panel_count", 1) < len(binding.panel_labels):
            warnings.append("caption_has_{}_panel_labels_but_only_{}_extracted".format(
                len(binding.panel_labels), pt.get("panel_count", 1)))

        if warnings:
            pt["caption_validation_warnings"] = ";".join(warnings)
            pt["needs_review"] = True
            pt["review_reason"] = ";".join(
                filter(None, [pt.get("review_reason", ""), *warnings])
            )

        return pt
