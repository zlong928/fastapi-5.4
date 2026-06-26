"""
QualityReviewAgent: 增强版质量控制 agent。

相比现有 quality.py 增强：
1. 覆盖范围质量分数（轴覆盖比例、数据密度）
2. 按模态（data_chart / microscopy / protein_assay）区分规则
3. 弱检测的对象级置信度
4. 统一 quality_tags 列表
"""
from __future__ import annotations

from typing import Any

from app.services.agent.types import ExtractionPoint


# ---------------------------------------------------------------------------
# 按 route_family 的质检规则
# ---------------------------------------------------------------------------

def quality_check_data_chart(pt: ExtractionPoint) -> tuple[float, list[str]]:
    """数据图表质量检查"""
    tags: list[str] = []
    base_conf = max(0.5, pt.confidence * 1.2)

    # x_value 存在性
    if pt.x_value is None:
        base_conf *= 0.5
        tags.append("missing_x_value")
    # y_value 存在性
    if pt.y_value is None and not pt.band_intensity:
        base_conf *= 0.5
        tags.append("missing_y_value")
    # 单位
    if not pt.x_unit and not pt.x_label:
        base_conf *= 0.8
        tags.append("missing_x_axis_label")
    if not pt.y_unit and not pt.y_label:
        base_conf *= 0.8
        tags.append("missing_y_axis_label")
    # 轴类型缺失
    if pt.x_axis_type == "linear" and not pt.x_value:
        pass  # 线性且未赋值是合理的
    # 物理 vs 归一化
    if pt.x_axis_type in ("pixel", "normalized"):
        base_conf *= 0.85
        tags.append("normalized_axis_only")

    return min(1.0, max(0.1, base_conf)), tags


def quality_check_microscopy(pt: ExtractionPoint) -> tuple[float, list[str]]:
    """显微镜质量检查"""
    tags: list[str] = []
    base_conf = max(0.5, pt.confidence * 1.2)

    # scale bar 存在性
    if not pt.pixel_size:
        base_conf *= 0.6
        tags.append("no_scale_bar_calibration")
    # 对象计数合理性
    if pt.object_count == 0 and not pt.overall_description:
        base_conf *= 0.4
        tags.append("no_objects_detected")
    elif pt.object_count > 200:
        base_conf *= 0.7
        tags.append("high_object_count_needs_review")
    # channel 信息
    if not pt.channel:
        base_conf *= 0.9
        tags.append("channel_not_detected")
    # 直径存在
    if not pt.object_diameter_physical and pt.pixel_size:
        base_conf *= 0.8
        tags.append("object_diameter_not_computed")
    # 对象分类
    if pt.object_class in ("unclassified_object_review", ""):
        base_conf *= 0.8
        tags.append("object_class_unverified")

    return min(1.0, max(0.1, base_conf)), tags


def quality_check_protein_assay(pt: ExtractionPoint) -> tuple[float, list[str]]:
    """蛋白质分析质量检查"""
    tags: list[str] = []
    base_conf = max(0.5, pt.confidence * 1.2)

    # 条带强度
    if pt.band_intensity is None and not pt.qualitative:
        base_conf *= 0.5
        tags.append("missing_band_intensity")
    # 分子量
    if pt.molecular_weight_kda is None:
        base_conf *= 0.85
        tags.append("molecular_weight_not_detected")
    # 目标蛋白
    if not pt.target_protein:
        base_conf *= 0.8
        tags.append("target_protein_not_identified")
    # loading control
    if not pt.loading_control:
        base_conf *= 0.9
        tags.append("no_loading_control_detected")

    return min(1.0, max(0.1, base_conf)), tags


def quality_check_non_data_visual(pt: ExtractionPoint) -> tuple[float, list[str]]:
    """非数据视觉证据质量检查"""
    tags: list[str] = ["non_data_visual_descriptive"]
    base_conf = max(0.3, pt.confidence * 0.8)
    if not pt.overall_description and not pt.qualitative:
        base_conf = 0.1
        tags.append("empty_description")
    return base_conf, tags


_ROUTE_QUALITY_FN = {
    "data_chart": quality_check_data_chart,
    "microscopy": quality_check_microscopy,
    "protein_assay": quality_check_protein_assay,
    "non_data_visual": quality_check_non_data_visual,
}


def check_quality(pt: ExtractionPoint) -> ExtractionPoint:
    """对单个提取点执行模态感知的质检"""
    fn = _ROUTE_QUALITY_FN.get(pt.route_family, quality_check_data_chart)
    confidence, tags = fn(pt)
    pt.confidence = round(confidence, 3)
    pt.quality_tags = tags
    pt.needs_review = confidence < 0.4 or "no_scale_bar_calibration" in tags or "missing_x_value" in tags
    if pt.needs_review and not pt.review_reason:
        pt.review_reason = ";".join(tags[:3]) if tags else "quality_below_threshold"
    return pt


def check_batch_quality(points: list[ExtractionPoint]) -> list[ExtractionPoint]:
    """批量质检"""
    return [check_quality(pt) for pt in points]


def summarize_quality_from_points(points: list[ExtractionPoint]) -> dict[str, Any]:
    """对一批点生成质检摘要"""
    if not points:
        return {
            "total_points": 0,
            "accepted": 0,
            "review_required": 0,
            "avg_confidence": 0.0,
            "all_tags": [],
        }
    accepted = sum(1 for p in points if not p.needs_review)
    review = sum(1 for p in points if p.needs_review)
    avg_conf = round(sum(p.confidence for p in points) / len(points), 3)
    all_tags = []
    for p in points:
        all_tags.extend(p.quality_tags)
    from collections import Counter
    tag_counts = Counter(all_tags)
    return {
        "total_points": len(points),
        "accepted": accepted,
        "review_required": review,
        "avg_confidence": avg_conf,
        "tag_counts": dict(tag_counts.most_common(20)),
    }


def annotate_points_quality(points: list[ExtractionPoint]) -> list[ExtractionPoint]:
    """外部调用入口：对点列表执行完整质检"""
    return check_batch_quality(points)
