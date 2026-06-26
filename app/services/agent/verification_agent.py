"""
VerificationAgent: CSV提取结果验证代理

功能:
1. 读取提取的CSV结果，重新绘制图表
2. 与原图进行视觉和数值对比
3. 检测常见错误（双Y轴混淆、标记映射错误、数值范围异常）
4. 生成修正提示词，触发二次提取（可选）
5. 输出验证报告和质量评分
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.agent.llm_client import LLMClient


@dataclass
class VerificationIssue:
    """验证发现的问题"""

    type: str  # 问题类型
    severity: str  # CRITICAL | WARNING | INFO
    description: str  # 问题描述
    affected_series: str  # 受影响的系列
    suggestion: str  # 修正建议
    evidence: dict[str, Any] | None = None  # 证据数据


@dataclass
class VerificationResult:
    """验证结果"""

    passed: bool  # 是否通过验证
    quality_score: float  # 质量评分 0-1
    issues: list[VerificationIssue]  # 发现的问题列表
    summary: str  # 摘要
    correction_prompt: str | None = None  # 修正提示词（如果有问题）


class CSVVerificationAgent:
    """CSV提取结果验证代理"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client

    def verify_extraction(
        self,
        csv_path: str,
        original_image_path: str,
        image_type: str | None = None,
        caption: str | None = None,
    ) -> VerificationResult:
        """
        验证CSV提取结果

        Args:
            csv_path: 提取的CSV文件路径
            original_image_path: 原始图像路径
            image_type: 图表类型（可选）
            caption: 图注（可选）

        Returns:
            VerificationResult: 验证结果
        """
        # 1. 加载CSV数据
        csv_data = self._load_csv(csv_path)
        if not csv_data:
            return VerificationResult(
                passed=False,
                quality_score=0.0,
                issues=[
                    VerificationIssue(
                        type="empty_csv",
                        severity="CRITICAL",
                        description="CSV文件为空或无法读取",
                        affected_series="all",
                        suggestion="检查提取流程是否正常运行",
                    )
                ],
                summary="CSV文件无效",
            )

        # 2. 数值范围检查
        issues = []
        issues.extend(self._check_value_ranges(csv_data))

        # 3. 双Y轴绑定检查（如果是双Y轴图）
        if self._has_dual_y_axis(csv_data):
            issues.extend(self._check_dual_y_axis_binding(csv_data))

        # 4. 数据完整性检查
        issues.extend(self._check_data_completeness(csv_data))

        # 5. 趋势一致性检查（可选，需要LLM）
        if self.client and original_image_path:
            issues.extend(self._check_visual_consistency(csv_data, original_image_path, caption))

        # 6. 计算质量评分
        quality_score = self._calculate_quality_score(issues)

        # 7. 判断是否通过
        critical_issues = [issue for issue in issues if issue.severity == "CRITICAL"]
        passed = len(critical_issues) == 0

        # 8. 生成修正提示词（如果有问题）
        correction_prompt = None
        if not passed:
            correction_prompt = self._generate_correction_prompt(issues, csv_data, image_type)

        # 9. 生成摘要
        summary = self._generate_summary(passed, quality_score, issues)

        return VerificationResult(
            passed=passed,
            quality_score=quality_score,
            issues=issues,
            summary=summary,
            correction_prompt=correction_prompt,
        )

    def _load_csv(self, csv_path: str) -> list[dict[str, Any]]:
        """加载CSV文件"""
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception:
            return []

    def _check_value_ranges(self, csv_data: list[dict]) -> list[VerificationIssue]:
        """检查数值范围的合理性"""
        issues = []

        # 按系列分组
        series_data = defaultdict(lambda: {"x": [], "y": [], "y_right": []})
        for row in csv_data:
            series_name = row.get("series_name", "")
            if not series_name:
                continue

            try:
                x_val = float(row.get("x_value") or row.get("Time (hours)") or 0)
                y_val = float(row.get("y_value") or row.get("Bacteria OD600") or 0)
                y_right = row.get("y_right_value", "")

                series_data[series_name]["x"].append(x_val)
                series_data[series_name]["y"].append(y_val)
                if y_right:
                    try:
                        series_data[series_name]["y_right"].append(float(y_right))
                    except (ValueError, TypeError):
                        pass
            except (ValueError, TypeError):
                continue

        # 检查每个系列的数值范围
        for series_name, data in series_data.items():
            y_values = data["y"]
            if not y_values:
                continue

            y_min = min(y_values)
            y_max = max(y_values)

            # 规则1: OD600 应该在 0-3 范围内（通常 <1）
            if "OD600" in series_name or "OD" in series_name:
                if y_max > 5:
                    issues.append(
                        VerificationIssue(
                            type="dual_y_axis_confusion",
                            severity="CRITICAL",
                            description=f"{series_name} 的最大值是 {y_max:.2f}，远超生物学合理范围（OD600 通常<3）。"
                            f"可能被错误映射到右Y轴的数值范围。",
                            affected_series=series_name,
                            suggestion="该系列应该使用左Y轴，检查颜色-轴映射规则",
                            evidence={"y_max": y_max, "y_min": y_min, "expected_max": 3.0},
                        )
                    )

            # 规则2: 百分比应该在 0-100 范围内
            if "%" in series_name or "percent" in series_name.lower():
                if y_max < 1 and y_max > 0:
                    # 可能是0-1的小数形式，但通常百分比用0-100
                    issues.append(
                        VerificationIssue(
                            type="legend_mapping_error",
                            severity="CRITICAL",
                            description=f"{series_name} 的最大值是 {y_max:.3f}，应该在0-100范围内（百分比）。"
                            f"可能与其他系列的图例映射错误。",
                            affected_series=series_name,
                            suggestion="检查图例文本与标记（颜色+形状）的绑定关系",
                            evidence={"y_max": y_max, "y_min": y_min, "expected_range": [0, 100]},
                        )
                    )
                elif y_max > 100:
                    issues.append(
                        VerificationIssue(
                            type="value_out_of_range",
                            severity="WARNING",
                            description=f"{series_name} 的最大值是 {y_max:.2f}，超过100%。可能是数值读取错误。",
                            affected_series=series_name,
                            suggestion="检查Y轴刻度的OCR准确性",
                            evidence={"y_max": y_max, "expected_max": 100},
                        )
                    )

            # 规则3: 负值检查（大多数科研图表不应该有负值）
            if y_min < 0:
                issues.append(
                    VerificationIssue(
                        type="negative_value",
                        severity="WARNING",
                        description=f"{series_name} 存在负值 {y_min:.2f}。如果不是误差棒或相对变化，可能是提取错误。",
                        affected_series=series_name,
                        suggestion="检查Y轴刻度读取和坐标映射",
                        evidence={"y_min": y_min},
                    )
                )

        return issues

    def _check_dual_y_axis_binding(self, csv_data: list[dict]) -> list[VerificationIssue]:
        """检查双Y轴的系列绑定是否正确"""
        issues = []

        # 统计左Y轴和右Y轴的系列
        left_axis_series = set()
        right_axis_series = set()

        for row in csv_data:
            series_name = row.get("series_name", "")
            y_axis_side = row.get("y_axis_side", "")
            has_y_right = row.get("y_right_value", "") not in ("", None)

            if y_axis_side == "left" or not has_y_right:
                left_axis_series.add(series_name)
            if y_axis_side == "right" or has_y_right:
                right_axis_series.add(series_name)

        # 检查是否有系列同时出现在左右两侧
        overlapping = left_axis_series & right_axis_series
        if overlapping:
            issues.append(
                VerificationIssue(
                    type="axis_binding_conflict",
                    severity="CRITICAL",
                    description=f"以下系列同时被分配到左Y轴和右Y轴: {', '.join(overlapping)}",
                    affected_series=", ".join(overlapping),
                    suggestion="明确每个系列应该绑定到哪个Y轴，通常根据标记的颜色判断",
                    evidence={"overlapping_series": list(overlapping)},
                )
            )

        return issues

    def _check_data_completeness(self, csv_data: list[dict]) -> list[VerificationIssue]:
        """检查数据完整性"""
        issues = []

        # 按系列统计数据点数量
        series_counts = defaultdict(int)
        for row in csv_data:
            series_name = row.get("series_name", "")
            if series_name:
                series_counts[series_name] += 1

        # 检查数据点数量是否过少
        for series_name, count in series_counts.items():
            if count < 5:
                issues.append(
                    VerificationIssue(
                        type="insufficient_data_points",
                        severity="WARNING",
                        description=f"{series_name} 只有 {count} 个数据点，可能遗漏了部分数据",
                        affected_series=series_name,
                        suggestion="检查是否在快速变化区域或平台期遗漏了数据点",
                        evidence={"point_count": count, "expected_min": 5},
                    )
                )

        return issues

    def _check_visual_consistency(
        self, csv_data: list[dict], original_image_path: str, caption: str | None
    ) -> list[VerificationIssue]:
        """使用LLM检查视觉一致性"""
        issues = []

        if not self.client:
            return issues

        try:
            # 生成数据摘要
            series_summary = self._summarize_series_data(csv_data)

            # 构建提示词
            prompt = f"""你是科研图表验证专家。请对比原始图像和提取的CSV数据，判断提取是否准确。

图注: {caption or '无'}

提取的数据摘要:
{json.dumps(series_summary, indent=2, ensure_ascii=False)}

请检查:
1. 数据系列的数量是否匹配
2. 每个系列的趋势是否一致（上升/下降/平台期）
3. 峰值和拐点的位置是否对应
4. 数值范围是否合理

如果发现不一致，请指出具体问题。输出JSON格式:
{{
  "consistent": true/false,
  "issues": [
    {{
      "type": "问题类型",
      "description": "问题描述",
      "affected_series": "受影响的系列名"
    }}
  ]
}}
"""

            image_data_url = self.client.image_data_url(original_image_path)
            if not image_data_url:
                return issues

            result = self.client.chat_json(
                [
                    {"role": "system", "content": "你是科研图表验证专家。"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="visual_consistency_check",
            )

            if not result.get("consistent", True):
                for issue_data in result.get("issues", []):
                    issues.append(
                        VerificationIssue(
                            type=issue_data.get("type", "visual_inconsistency"),
                            severity="WARNING",
                            description=issue_data.get("description", "视觉不一致"),
                            affected_series=issue_data.get("affected_series", "unknown"),
                            suggestion="使用修正后的提示词重新提取",
                        )
                    )

        except Exception as e:
            # LLM检查失败不影响其他检查
            print(f"Visual consistency check failed: {e}")

        return issues

    def _has_dual_y_axis(self, csv_data: list[dict]) -> bool:
        """判断是否为双Y轴图表"""
        # 检查是否有 y_right_value 或 y_axis_side 字段
        for row in csv_data:
            if row.get("y_right_value") or row.get("y_axis_side"):
                return True

        # 检查是否有多个不同的 y_axis_label
        y_labels = {row.get("y_axis_label", "") for row in csv_data if row.get("y_axis_label")}
        return len(y_labels) > 1

    def _summarize_series_data(self, csv_data: list[dict]) -> dict:
        """生成数据摘要"""
        series_data = defaultdict(lambda: {"x": [], "y": [], "count": 0})

        for row in csv_data:
            series_name = row.get("series_name", "")
            if not series_name:
                continue

            try:
                x_val = float(row.get("x_value") or row.get("Time (hours)") or 0)
                y_val = float(row.get("y_value") or row.get("Bacteria OD600") or 0)

                series_data[series_name]["x"].append(x_val)
                series_data[series_name]["y"].append(y_val)
                series_data[series_name]["count"] += 1
            except (ValueError, TypeError):
                continue

        # 生成摘要
        summary = {}
        for series_name, data in series_data.items():
            x_vals = data["x"]
            y_vals = data["y"]

            summary[series_name] = {
                "point_count": data["count"],
                "x_range": [min(x_vals), max(x_vals)] if x_vals else [0, 0],
                "y_range": [min(y_vals), max(y_vals)] if y_vals else [0, 0],
                "trend": self._detect_trend(y_vals),
            }

        return summary

    def _detect_trend(self, y_values: list[float]) -> str:
        """检测趋势"""
        if len(y_values) < 3:
            return "insufficient_data"

        # 简单趋势判断
        first_third = sum(y_values[: len(y_values) // 3]) / (len(y_values) // 3)
        last_third = sum(y_values[-len(y_values) // 3 :]) / (len(y_values) // 3)

        diff = last_third - first_third
        threshold = (max(y_values) - min(y_values)) * 0.2

        if abs(diff) < threshold:
            return "flat"
        elif diff > 0:
            return "increasing"
        else:
            return "decreasing"

    def _calculate_quality_score(self, issues: list[VerificationIssue]) -> float:
        """计算质量评分"""
        if not issues:
            return 1.0

        # 根据问题严重性扣分
        penalty = 0.0
        for issue in issues:
            if issue.severity == "CRITICAL":
                penalty += 0.3
            elif issue.severity == "WARNING":
                penalty += 0.1
            else:  # INFO
                penalty += 0.05

        return max(0.0, 1.0 - penalty)

    def _generate_correction_prompt(
        self, issues: list[VerificationIssue], csv_data: list[dict], image_type: str | None
    ) -> str:
        """生成修正提示词"""
        prompt_parts = ["# 数据提取修正提示词\n", "基于原图与提取结果对比分析，发现以下问题需要修正:\n"]

        # 列出所有问题
        for i, issue in enumerate(issues, 1):
            prompt_parts.append(f"\n## 问题 {i}: {issue.type} [{issue.severity}]")
            prompt_parts.append(f"- 描述: {issue.description}")
            prompt_parts.append(f"- 影响系列: {issue.affected_series}")
            prompt_parts.append(f"- 修正建议: {issue.suggestion}\n")

        # 生成具体的修正指令
        prompt_parts.append("\n## 修正指令\n")

        # 根据问题类型生成针对性的指令
        has_dual_y_issue = any("dual_y" in issue.type or "axis" in issue.type for issue in issues)
        has_legend_issue = any("legend" in issue.type or "mapping" in issue.type for issue in issues)

        if has_dual_y_issue:
            prompt_parts.append(
                """
### 双Y轴识别规则
请严格遵循以下规则重新提取:

1. **颜色-轴映射**:
   - 黑色/灰色标记 → 左Y轴
   - 橙色/红色/彩色标记 → 右Y轴
   - 优先根据**颜色**判断，而非标记形状

2. **数值范围核验**:
   - 提取每个点后，检查数值是否在对应Y轴的刻度范围内
   - 如果 OD600 系列出现 >5 的值，说明映射错误

3. **CSV输出要求**:
   - 必须包含 `y_axis_side` 字段: "left" 或 "right"
   - 左Y轴系列和右Y轴系列分别使用不同的列，或标注 `y_axis_side`
"""
            )

        if has_legend_issue:
            prompt_parts.append(
                """
### 图例-标记绑定规则
请严格遵循以下规则:

1. **标记识别优先级**:
   - 首先识别标记的**颜色**（黑/橙/红/蓝等）
   - 其次识别标记的**形状**（圆/三角/方形，实心/空心）
   - 颜色 > 形状，同颜色不同形状的标记应该属于相关系列

2. **图例文本绑定**:
   - OCR提取图例文本后，与图像中的标记进行精确匹配
   - 通过颜色+形状的组合唯一确定每个系列

3. **交叉验证**:
   - 提取完成后，检查每个系列的名称、颜色、形状是否一致
   - 检查数值范围是否符合系列名称的含义（如 OD600 vs Phenol %）
"""
            )

        prompt_parts.append(
            """
### 数据完整性要求
- 注意快速变化区域（如下降阶段）的多个数据点
- 注意平台期的平稳趋势，不要遗漏
- 不要过度平滑，保留原始数据点的特征
"""
        )

        return "\n".join(prompt_parts)

    def _generate_summary(self, passed: bool, quality_score: float, issues: list[VerificationIssue]) -> str:
        """生成验证摘要"""
        if passed:
            return f"✓ 验证通过 (质量评分: {quality_score:.2f})"

        critical_count = sum(1 for issue in issues if issue.severity == "CRITICAL")
        warning_count = sum(1 for issue in issues if issue.severity == "WARNING")

        return (
            f"✗ 验证失败 (质量评分: {quality_score:.2f})\n"
            f"发现 {critical_count} 个严重问题, {warning_count} 个警告"
        )


def verify_csv_extraction(
    csv_path: str,
    original_image_path: str,
    image_type: str | None = None,
    caption: str | None = None,
    client: LLMClient | None = None,
) -> VerificationResult:
    """
    便捷函数: 验证CSV提取结果

    Args:
        csv_path: CSV文件路径
        original_image_path: 原始图像路径
        image_type: 图表类型
        caption: 图注
        client: LLM客户端（可选，用于视觉一致性检查）

    Returns:
        VerificationResult: 验证结果
    """
    agent = CSVVerificationAgent(client=client)
    return agent.verify_extraction(csv_path, original_image_path, image_type, caption)
