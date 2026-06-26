"""
MorphologyAgent: 升级版显微镜分析 agent。

相比 MicroscopyQuantExtractor 新增：
1. 多通道荧光解析（DAPI/FITC/Cy5/overlay）
2. 分水岭分割（接触对象）
3. 粒径分布直方图（D10/D50/D90）
4. 密度测量（objects/µm²）
5. 对象级置信度
6. 垂直/水平刻度条检测
"""
from __future__ import annotations

import re
import time
from typing import Any

import cv2
import numpy as np

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import ExtractionPoint, FigureExtractionPlan, extraction_point_to_dict
from app.services.chart_extraction.visual_marks import classify_mark_color


# channel keywords for fluorescence microscopy
_CHANNEL_KEYWORDS: dict[str, list[str]] = {
    "DAPI": ["dapi", "hoechst", "dna stain", "nuclei", "nuclear"],
    "FITC": ["fitc", "gfp", "green", "alexa 488", "cy2"],
    "Cy5": ["cy5", "cy5.5", "far-red", "alexa 647", "deep red"],
    "Cy3": ["cy3", "alexa 555", "alexa 568", "red", "trtic"],
    "brightfield": ["brightfield", "bright field", "dic", "phase"],
    "overlay": ["overlay", "merge", "merged", "combined"],
}


def _detect_vertical_scale_bar(crop: np.ndarray) -> dict | None:
    """检测垂直刻条"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    right = gray[:, int(width * 0.55):]
    dark = right < 45
    bright = right > 235
    masks = [dark.astype("uint8") * 255, bright.astype("uint8") * 255]
    candidates: list[dict] = []
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 3), np.uint8))
        _num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        for label in range(1, _num):
            x = int(stats[label, cv2.CC_STAT_LEFT]) + int(width * 0.55)
            y = int(stats[label, cv2.CC_STAT_TOP])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            if h < max(18, int(height * 0.06)) or w < 2 or w > max(18, int(width * 0.08)):
                continue
            if h / max(1, w) < 5:
                continue
            if area < h * w * 0.55:
                continue
            cx, cy = centroids[label]
            candidates.append({
                "x": x, "y": y, "w": w, "h": h,
                "cx": float(cx + int(width * 0.55)),
                "cy": float(cy),
                "score": h * (1 + x / max(1, width)),
            })
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["score"])


def _detect_scale_bar_both(crop: np.ndarray, caption: str) -> dict | None:
    """检测水平或垂直刻度条"""
    value = _parse_scale_bar_value(caption)
    if not value:
        return None
    physical_value, unit = value
    # 尝试水平
    h_bar = _detect_horizontal_scale_bar(crop)
    if h_bar and h_bar["w"] > 0:
        return {
            "length_px": float(h_bar["w"]),
            "value": physical_value,
            "unit": unit,
            "pixel_size": physical_value / float(h_bar["w"]),
            "bbox": (h_bar["x"], h_bar["y"], h_bar["x"] + h_bar["w"], h_bar["y"] + h_bar["h"]),
            "binding_status": "scale_bar_caption_and_segment_bound_review",
            "binding_method": "horizontal_segment",
        }
    v_bar = _detect_vertical_scale_bar(crop)
    if v_bar and v_bar["h"] > 0:
        return {
            "length_px": float(v_bar["h"]),
            "value": physical_value,
            "unit": unit,
            "pixel_size": physical_value / float(v_bar["h"]),
            "bbox": (v_bar["x"], v_bar["y"], v_bar["x"] + v_bar["w"], v_bar["y"] + v_bar["h"]),
            "binding_status": "scale_bar_caption_and_segment_bound_review",
            "binding_method": "vertical_segment",
        }
    return None


def _detect_channels(crop: np.ndarray, caption: str) -> dict[str, np.ndarray]:
    """检测多通道荧光 —— 按通道分离图像"""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    caption_lower = caption.lower()

    channels: dict[str, np.ndarray] = {}
    channel_masks: dict[str, np.ndarray] = {}
    primary_channel = _identify_primary_channel(caption_lower)

    if primary_channel in ("overlay", ""):
        # 检测是否有多个荧光通道
        # DAPI-like (blue): H 100-130 or V通道低
        blue_mask = (hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 140) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 40)
        # FITC/GFP-like (green): H 35-85
        green_mask = (hsv[:, :, 0] > 35) & (hsv[:, :, 0] < 85) & (hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 40)
        # Cy5-like (red): H 0-10 or 160-180
        red_mask = ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 155)) & (hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 40)
        # Cy3-like (orange/red): H 0-20
        orange_mask = (hsv[:, :, 0] < 20) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 40)

        channel_masks = {}
        if np.sum(blue_mask) > 500:
            channel_masks["DAPI"] = blue_mask.astype(np.uint8) * 255
        if np.sum(green_mask) > 500:
            channel_masks["FITC"] = green_mask.astype(np.uint8) * 255
        if np.sum(red_mask) > 500:
            channel_masks["Cy5"] = red_mask.astype(np.uint8) * 255
        if np.sum(orange_mask) > 500:
            channel_masks["Cy3"] = orange_mask.astype(np.uint8) * 255

        if not channel_masks:
            channel_masks["brightfield"] = np.ones((crop.shape[0], crop.shape[1]), dtype=np.uint8) * 255
    else:
        # 单通道
        channel_masks = {primary_channel: np.ones((crop.shape[0], crop.shape[1]), dtype=np.uint8) * 255}

    for ch_name, mask in channel_masks.items():
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        channels[ch_name] = mask

    return channels


def _identify_primary_channel(caption: str) -> str:
    """从 caption 确定主通道"""
    for ch_name, keywords in _CHANNEL_KEYWORDS.items():
        for kw in keywords:
            if kw in caption:
                return ch_name
    return ""


def _watershed_split(mask: np.ndarray) -> np.ndarray:
    """分水岭分割接触对象"""
    # 距离变换
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    _, sure_fg = cv2.threshold(dist, 0.4 * dist.max(), 255, 0)
    sure_fg = np.uint8(sure_fg)
    # 背景
    kernel = np.ones((3, 3), np.uint8)
    sure_bg = cv2.dilate(mask, kernel, iterations=3)
    unknown = cv2.subtract(sure_bg, sure_fg)
    # 标记
    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0
    markers = cv2.watershed(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR) if len(mask.shape) == 2 else cv2.cvtColor((mask * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR), markers)
    return markers


def _compute_size_distribution(diameters_um: list[float]) -> dict[str, float]:
    """计算粒径分布统计"""
    if not diameters_um:
        return {"d10": 0, "d50": 0, "d90": 0, "mean": 0, "n": 0}
    arr = np.array(sorted(diameters_um))
    return {
        "d10": float(np.percentile(arr, 10)),
        "d50": float(np.percentile(arr, 50)),
        "d90": float(np.percentile(arr, 90)),
        "mean": float(arr.mean()),
        "n": len(arr),
    }


def _object_confidence_from_shape(area_px: int, circularity: float, image_area: int) -> float:
    """基于形状的特征计算对象级置信度"""
    score = 0.5
    # 排除非常小的对象（噪声）
    if area_px < 16:
        score -= 0.3
    elif area_px < 50:
        score -= 0.1
    elif area_px > image_area * 0.3:
        score -= 0.2  # 太大可能不是单个对象
    # 排除圆形度太低的（可能是线条/噪点）
    if circularity < 0.2:
        score -= 0.2
    elif circularity > 0.7:
        score += 0.1
    # 排除异常大的
    if area_px > image_area * 0.01:
        score -= 0.1
    return max(0.1, min(1.0, score))


class MorphologyAgent:
    """升级版显微镜分析 agent（通道解析 + 分割 + 粒径分布）"""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(self, plan: FigureExtractionPlan) -> dict[str, Any]:
        started = time.time()
        import cv2
        import numpy as np

        image = cv2.imread(str(plan.image_path))
        if image is None:
            return self._error_result(plan, "image_unreadable")

        x0, y0 = 0, 0
        x1, y1 = image.shape[1] - 1, image.shape[0] - 1
        crop = image  # 整图

        caption_lower = (plan.caption + " " + plan.nearby_text).lower()

        # 1. 检测通道
        channels = _detect_channels(crop, caption_lower)
        primary_channel = list(channels.keys())[0] if channels else "brightfield"

        # 2. 检测 scale bar（支持水平和垂直）
        scale_bar = _detect_scale_bar_both(crop, caption_lower)
        pixel_size = float(scale_bar["pixel_size"]) if scale_bar else None
        if pixel_size and pixel_size <= 0:
            pixel_size = None

        # 3. 逐通道分析
        all_points: list[ExtractionPoint] = []
        channel_object_counts: dict[str, int] = {}
        all_diameters: list[float] = []

        for ch_name, ch_mask in channels.items():
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

            # 改进的检测：结合纹理 + 饱和度 + 暗对象
            contrast = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 7))
            textured = contrast > max(12, int(np.percentile(contrast, 80)))
            saturated = (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 45)
            dark_objects = gray < max(80, int(np.percentile(gray, 35)))
            raw_mask = (textured | saturated | dark_objects).astype("uint8") * 255

            # 应用通道遮罩
            raw_mask = cv2.bitwise_and(raw_mask, ch_mask)
            raw_mask = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            # 移除 scale bar 区域
            if scale_bar:
                bx0, by0, bx1, by1 = scale_bar["bbox"]
                pad = 4
                raw_mask[max(0, by0 - pad):min(raw_mask.shape[0], by1 + pad),
                         max(0, bx0 - pad):min(raw_mask.shape[1], bx1 + pad)] = 0

            # 分水岭分割
            markers = _watershed_split(raw_mask)
            height, width = raw_mask.shape
            image_area = height * width
            max_component_area = int(image_area * 0.05)

            # 提取标记过的组件
            ch_points: list[ExtractionPoint] = []
            ch_diameters: list[float] = []
            label_max = int(markers.max())
            for label in range(2, label_max + 1):
                comp = (markers == label)
                area_px = int(np.sum(comp))
                if area_px < 20 or area_px > max_component_area:
                    continue
                ys, xs = np.where(comp)
                cx, cy = float(xs.mean()), float(ys.mean())
                # 颜色
                pix_bgr = crop[comp]
                mean_bgr = pix_bgr.mean(axis=0)
                rgb = np.array([mean_bgr[2], mean_bgr[1], mean_bgr[0]])
                # 形态学
                eq_diameter_px = float(2 * np.sqrt(area_px / np.pi))
                eq_diameter_um = round(eq_diameter_px * pixel_size, 4) if pixel_size else None
                perpendicular = cv2.arcLength(comp.astype(np.uint8), True)
                circularity = round(float(4 * np.pi * area_px / max(1e-9, perpendicular * perpendicular)), 4) if perpendicular else 0.0
                area_value = round(area_px * pixel_size * pixel_size, 4) if pixel_size else 0.0
                area_unit = f"{scale_bar['unit']}^2" if scale_bar else "px^2"
                obj_conf = _object_confidence_from_shape(area_px, circularity, image_area)
                obj_class = _classify_object(caption_lower, ch_name)

                pt = ExtractionPoint(
                    figure_id=plan.figure_id,
                    image_path=str(plan.image_path),
                    source_type="cv_extractor",
                    extraction_method="morphology_cv_v2",
                    route_family="microscopy",
                    image_type=plan.image_type.value if plan.image_type else "microscopy_quant",
                    channel=ch_name,
                    object_class=obj_class,
                    object_count=1,
                    object_area_physical=area_value,
                    object_diameter_physical=eq_diameter_um or round(eq_diameter_px, 4),
                    object_circularity=circularity,
                    object_area_fraction=round(area_px / image_area, 6),
                    scale_bar_value=float(scale_bar["value"]) if scale_bar else None,
                    scale_bar_unit=str(scale_bar["unit"]) if scale_bar else "",
                    pixel_size=pixel_size,
                    x_value=round(cx, 1),
                    y_value=round(cy, 1),
                    x_label="image_x",
                    y_label="image_y",
                    x_unit=scale_bar["unit"] if scale_bar else "px",
                    y_unit=scale_bar["unit"] if scale_bar else "px",
                    series_color=classify_mark_color(rgb),
                    confidence=obj_conf,
                    needs_review=obj_conf < 0.5,
                    review_reason="" if obj_conf >= 0.5 else f"low_confidence_object_{obj_class}_{ch_name}",
                )
                ch_points.append(pt)
                if eq_diameter_um:
                    ch_diameters.append(eq_diameter_um)

            ch_points.sort(key=lambda p: -(p.object_area_physical or 0))
            all_points.extend(ch_points[:60])  # 最多 60 个对象/通道
            channel_object_counts[ch_name] = len(ch_points)
            all_diameters.extend(ch_diameters)

        # 计算粒径分布
        size_dist = _compute_size_distribution(all_diameters)

        return {
            "figure_id": plan.figure_id,
            "image_path": str(plan.image_path),
            "figure_type": "microscopy",
            "image_type": plan.image_type.value if plan.image_type else "microscopy_quant",
            "primary_channel": primary_channel,
            "channels": list(channels.keys()),
            "channel_object_counts": channel_object_counts,
            "scale_bar": scale_bar,
            "size_distribution": size_dist,
            "overall_description": (
                f"Microscopy analysis: {len(all_points)} objects across {len(channels)} channels. "
                f"Mean diameter: {size_dist['mean']:.2f} µm, D50: {size_dist['d50']:.2f} µm"
            ),
            "extraction_points": [extraction_point_to_dict(p) for p in all_points],
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": {
                        "channel_object_counts": channel_object_counts,
                        "size_distribution": size_dist,
                        "total_objects": len(all_points),
                    },
                    "qualitative": f"{len(all_points)} objects in {', '.join(channels.keys())}. "
                                  f"D50={size_dist['d50']:.2f} µm, mean={size_dist['mean']:.2f} µm" if all_diameters else "No physical calibration available.",
                    "confidence": "high" if pixel_size else "medium",
                    "notes": f"channels={','.join(channels.keys())}; scale_bar={'yes' if scale_bar else 'no'}",
                    "mode": "morphology_cv_v2",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _error_result(self, plan: FigureExtractionPlan, reason: str) -> dict[str, Any]:
        return {
            "figure_id": plan.figure_id,
            "image_path": str(plan.image_path),
            "figure_type": "microscopy",
            "image_type": plan.image_type.value if plan.image_type else "microscopy_quant",
            "error": reason,
            "extraction_points": [],
            "extractions": [{"metric": t.metric_name, "success": False, "data": {}, "qualitative": f"分析失败：{reason}", "confidence": "none", "notes": reason} for t in plan.tasks],
            "elapsed": 0,
        }


def _classify_object(caption: str, channel: str) -> str:
    """基于 caption+channel 的对象分类"""
    text = caption.lower()
    if "pore" in text:
        return "pore"
    if "cell" in text or "cells" in text or "bacteria" in text or "nuclei" in text:
        return "cell"
    if "carbonate" in text:
        return "carbonate_deposit"
    if "particle" in text or "nanoparticle" in text or "bead" in text:
        return "particle"
    if "fiber" in text or "fibril" in text or "filament" in text:
        return "fiber"
    if channel in ("DAPI",):
        return "nucleus"
    if channel in ("FITC", "GFP"):
        return "target_signal"
    if channel in ("Cy5", "Cy3"):
        return "target_signal"
    if "element" in text or "eds" in text or "mapping" in text:
        return "element_region"
    return "unclassified_object_review"
