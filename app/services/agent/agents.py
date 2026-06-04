"""
All extraction agents: TaskPlanner, GlobalMap, Reflection, VisualBatch.

Each agent receives an LLMClient and owns one phase of the pipeline.
VisualBatchAgent runs figures in parallel via ThreadPoolExecutor.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import ExtractionMap, ExtractionTask, FigureExtractionPlan, PaperData, SupervisorState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DEFAULT_METRICS = ["research_purpose", "materials", "experiment_groups", "key_metrics", "figure_data", "conclusion"]

_METRIC_ALIASES = {
    "材料组成": "materials",
    "实验分组": "experiment_groups",
    "关键指标": "key_metrics",
    "主要结论": "conclusion",
    "结论": "conclusion",
}


def normalize_metric(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_一-鿿]+", "_", value.strip()).strip("_").lower()
    return _METRIC_ALIASES.get(value.strip(), cleaned or "unknown")


def find_figure(paper: PaperData, figure_id: str):
    normalized = re.sub(r"[^a-z0-9]+", "", figure_id.lower())
    for figure in paper.figures:
        candidate = re.sub(r"[^a-z0-9]+", "", figure.figure_id.lower())
        if normalized in candidate or candidate in normalized:
            return figure
    return None


def _table_content(content: str) -> str:
    marker = "[Extracted Tables]"
    if marker not in content:
        return ""
    return content.split(marker, 1)[1].strip()


def _snippet(content: str, metric: str, limit: int = 700) -> str:
    if not content.strip():
        return "未在当前论文解析内容中找到明确证据"
    lower = content.lower()
    key = metric.lower()
    index = lower.find(key)
    if index < 0:
        index = 0
    return content[index:index + limit].strip()


# ---------------------------------------------------------------------------
# TaskPlannerAgent
# ---------------------------------------------------------------------------


class TaskPlannerAgent:
    """Parse user query into a list of extraction metrics."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def plan(self, user_query: str, paper_title: str) -> list[str]:
        payload = self.client.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是科研数据提取任务规划专家。输出 JSON："
                        '{"metrics":["materials","experiment_groups","key_metrics","conclusion"]}。'
                        "指标必须短、稳定、可用于数据库字段名。"
                    ),
                },
                {"role": "user", "content": f"论文标题：{paper_title}\n用户目标：{user_query}\n请拆解 3-6 个指标。"},
            ],
            phase="planning",
        )
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(metrics, list) or not metrics:
            return DEFAULT_METRICS
        normalized = [normalize_metric(str(m)) for m in metrics[:6] if str(m).strip()]
        return normalized or DEFAULT_METRICS


# ---------------------------------------------------------------------------
# GlobalMapAgent
# ---------------------------------------------------------------------------


class GlobalMapAgent:
    """Read the full paper and build a figure/text/table-to-metric mapping."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def build_map(self, paper: PaperData, metrics: list[str]) -> tuple[ExtractionMap, list[str]]:
        figures_summary = "\n".join(f"- {fig.figure_id}: {fig.caption[:240]}" for fig in paper.figures)
        payload = self.client.chat_json(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(paper, metrics, figures_summary)},
            ],
            phase="mapping",
        )
        extraction_map = self._parse_map(paper, payload)
        not_found = [normalize_metric(str(item)) for item in (payload.get("not_found_metrics") or [])]

        # 关键改进：确保每个图表都有提取任务
        extraction_map = self._ensure_all_figures_covered(paper, extraction_map, metrics)

        if not extraction_map.figures and paper.figures:
            extraction_map, not_found = self._fallback_map(paper, metrics)
        return extraction_map, not_found

    def _ensure_all_figures_covered(self, paper: PaperData, extraction_map: ExtractionMap, metrics: list[str]) -> ExtractionMap:
        """确保每个图表都有提取任务，即使用户没有明确查询"""
        for figure in paper.figures:
            if figure.figure_id not in extraction_map.figures:
                # 为未覆盖的图表添加通用提取任务
                plan = FigureExtractionPlan(
                    figure_id=figure.figure_id,
                    image_path=figure.image_path,
                    caption=figure.caption
                )
                # 添加全面的数据提取任务
                plan.tasks.append(
                    ExtractionTask(
                        metric_name="comprehensive_data_extraction",
                        text_context=figure.caption or "图表完整数据提取",
                        specific_instruction="提取图表中所有可见的数据点、数值、关键指标和对比关系，用中文详细说明"
                    )
                )
                extraction_map.figures[figure.figure_id] = plan
            else:
                # 为已有的图表补充全面提取任务（如果没有）
                existing_plan = extraction_map.figures[figure.figure_id]
                has_comprehensive = any(
                    task.metric_name in ("comprehensive_data_extraction", "figure_data", "key_metrics")
                    for task in existing_plan.tasks
                )
                if not has_comprehensive:
                    existing_plan.tasks.append(
                        ExtractionTask(
                            metric_name="comprehensive_data_extraction",
                            text_context=figure.caption or "图表完整数据提取",
                            specific_instruction="提取图表中所有可见的数据点、数值、关键指标和对比关系，用中文详细说明"
                        )
                    )

        return extraction_map

    def _system_prompt(self) -> str:
        return """你是科研论文数据分析专家。一次阅读全文，建立图片/正文/表格到指标的映射。
输出 JSON：
{
  "figure_mappings": {"Figure 1": {"tasks": [{"metric": "key_metrics", "context": "为什么看这张图", "instruction": "提取什么"}]}},
  "text_only_metrics": [{"metric": "materials", "value": "提取值", "evidence": "原文证据（必须是论文中的原句或数据）"}],
  "not_found_metrics": []
}
规则：
1. text_only_metrics 的 evidence 必须是论文原文片段，不能是你的概括
2. 表格内容会出现在 [Extracted Tables] 区块；如果证据来自表格，请放在 text_only_metrics 并复制简短表格证据
3. 每个指标的 value 应该是具体的、可核对的信息，不是泛泛的总结"""

    def _user_prompt(self, paper: PaperData, metrics: list[str], figures_summary: str) -> str:
        parts = [
            f"论文标题：{paper.title}",
            f"指标：{json.dumps(metrics, ensure_ascii=False)}",
            f"图片：\n{figures_summary}",
        ]
        if paper.tables:
            table_lines = []
            for t in paper.tables:
                header_str = ", ".join(t.headers[:6]) if t.headers else "无表头"
                table_lines.append(f"- {t.label} (page {t.page_number}, {t.row_count} rows): [{header_str}]")
            parts.append(f"结构化表格：\n" + "\n".join(table_lines))
        parts.append(f"论文全文前 18000 字：\n{paper.content[:18000]}")
        return "\n".join(parts)

    def _parse_map(self, paper: PaperData, payload: dict) -> ExtractionMap:
        extraction_map = ExtractionMap()
        for fig_id, fig_data in (payload.get("figure_mappings") or {}).items():
            figure = find_figure(paper, str(fig_id))
            if not figure:
                continue
            plan = FigureExtractionPlan(figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption)
            for task in fig_data.get("tasks", []) or []:
                metric = normalize_metric(str(task.get("metric") or ""))
                if metric:
                    plan.tasks.append(
                        ExtractionTask(
                            metric_name=metric,
                            text_context=str(task.get("context") or ""),
                            specific_instruction=str(task.get("instruction") or ""),
                        )
                    )
            if plan.tasks:
                extraction_map.figures[plan.figure_id] = plan
        extraction_map.text_only_metrics = [item for item in (payload.get("text_only_metrics") or []) if isinstance(item, dict)]
        return extraction_map

    def _fallback_map(self, paper: PaperData, metrics: list[str]) -> tuple[ExtractionMap, list[str]]:
        extraction_map = ExtractionMap()
        content = paper.content
        table_content = _table_content(content)
        text_metrics: list[dict] = []
        figure_metrics = {"conclusion", "key_metrics", "figure_data"}
        for metric in metrics:
            if metric in figure_metrics and paper.figures:
                figure = paper.figures[0]
                plan = extraction_map.figures.setdefault(
                    figure.figure_id,
                    FigureExtractionPlan(figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption),
                )
                plan.tasks.append(ExtractionTask(metric_name=metric, text_context=figure.context or figure.caption, specific_instruction="fallback caption/context analysis"))
                if metric == "key_metrics" and table_content:
                    text_metrics.append({"metric": metric, "value": table_content[:700], "evidence": table_content[:240], "mode": "fallback_caption_only"})
            else:
                source = table_content if metric == "key_metrics" and table_content else content
                text_metrics.append({"metric": metric, "value": _snippet(source, metric), "evidence": _snippet(source, metric, limit=240), "mode": "fallback_caption_only"})
        extraction_map.text_only_metrics = text_metrics
        return extraction_map, []


# ---------------------------------------------------------------------------
# ReflectionAgent
# ---------------------------------------------------------------------------


class ReflectionAgent:
    """Review the extraction map for missed or mismatched metrics."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def review(
        self,
        paper: PaperData,
        metrics: list[str],
        extraction_map: ExtractionMap,
        not_found: list[str],
    ) -> dict:
        mapped_metrics = set()
        for plan in extraction_map.figures.values():
            for task in plan.tasks:
                mapped_metrics.add(task.metric_name)
        for item in extraction_map.text_only_metrics:
            mapped_metrics.add(str(item.get("metric", "")))

        unmapped = [m for m in metrics if m not in mapped_metrics and m not in not_found]

        if not unmapped and not not_found:
            return {
                "adjusted": False,
                "extraction_map": extraction_map,
                "not_found": not_found,
                "message": "映射复核通过，所有指标已覆盖",
                "notes": {"stage": "mapping", "approved": True, "notes": "all metrics covered", "suggestions": 0},
            }

        figure_ids = [plan.figure_id for plan in extraction_map.figures.values()]
        table_summary = ""
        if paper.tables:
            table_summary = "\n".join(
                f"- {t.label} (page {t.page_number}): columns={t.headers[:6]}, rows={t.row_count}"
                for t in paper.tables
            )

        try:
            payload = self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": """你是科研数据提取复核专家。检查提取映射是否有遗漏或错配。
输出 JSON：
{
  "issues": [{"metric": "...", "problem": "unmapped/wrong_figure/missing_table", "fix": "描述修复方案"}],
  "new_figure_mappings": {"Figure X": {"tasks": [{"metric": "...", "context": "...", "instruction": "..."}]}},
  "new_text_metrics": [{"metric": "...", "value": "...", "evidence": "..."}],
  "resolved_not_found": []
}
如果映射已经合理，issues 为空数组。""",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"论文标题：{paper.title}\n"
                            f"待提取指标：{json.dumps(metrics, ensure_ascii=False)}\n"
                            f"当前映射到图片的指标：{json.dumps(list(mapped_metrics), ensure_ascii=False)}\n"
                            f"当前图片列表：{json.dumps(figure_ids, ensure_ascii=False)}\n"
                            f"未映射指标：{json.dumps(unmapped, ensure_ascii=False)}\n"
                            f"标记为未找到：{json.dumps(not_found, ensure_ascii=False)}\n"
                            f"表格概要：\n{table_summary or '无表格'}\n"
                            f"论文前 6000 字：\n{paper.content[:6000]}"
                        ),
                    },
                ],
                phase="reflection",
            )
        except Exception:
            return {
                "adjusted": False,
                "extraction_map": extraction_map,
                "not_found": not_found,
                "message": "映射复核调用失败，保持原映射",
                "notes": {"stage": "mapping", "approved": True, "notes": "reflection call failed, keeping original", "suggestions": 0},
            }

        adjusted = False
        issues = payload.get("issues") or []

        for fig_id, fig_data in (payload.get("new_figure_mappings") or {}).items():
            figure = find_figure(paper, str(fig_id))
            if not figure:
                continue
            plan = extraction_map.figures.get(figure.figure_id) or FigureExtractionPlan(
                figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption
            )
            existing_metrics = {task.metric_name for task in plan.tasks}
            for task in fig_data.get("tasks", []) or []:
                metric = normalize_metric(str(task.get("metric") or ""))
                if metric and metric not in existing_metrics:
                    plan.tasks.append(
                        ExtractionTask(
                            metric_name=metric,
                            text_context=str(task.get("context") or ""),
                            specific_instruction=str(task.get("instruction") or ""),
                        )
                    )
                    adjusted = True
            if plan.tasks:
                extraction_map.figures[plan.figure_id] = plan

        for item in payload.get("new_text_metrics") or []:
            if isinstance(item, dict) and item.get("metric"):
                extraction_map.text_only_metrics.append(item)
                adjusted = True

        resolved = [normalize_metric(str(m)) for m in (payload.get("resolved_not_found") or [])]
        if resolved:
            not_found = [m for m in not_found if m not in resolved]
            adjusted = True

        return {
            "adjusted": adjusted,
            "extraction_map": extraction_map,
            "not_found": not_found,
            "message": f"映射复核完成，发现 {len(issues)} 个问题，{'已修正' if adjusted else '无需调整'}",
            "notes": {"stage": "mapping", "approved": not adjusted, "notes": json.dumps(issues, ensure_ascii=False)[:500], "suggestions": len(issues)},
        }


# ---------------------------------------------------------------------------
# ResultReflectionAgent
# ---------------------------------------------------------------------------


class ResultReflectionAgent:
    """Review low-confidence extraction results and attempt to improve them."""

    CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def review_and_retry(self, paper: PaperData, final_results: dict) -> dict:
        low_confidence_text = [
            item for item in (final_results.get("text_only_data") or [])
            if isinstance(item, dict) and str(item.get("mode", "")).startswith("fallback")
        ]
        if not low_confidence_text:
            return final_results

        metrics_to_retry = [item.get("metric") for item in low_confidence_text if item.get("metric")][:4]
        if not metrics_to_retry:
            return final_results

        try:
            payload = self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": """你是科研数据提取复核专家。以下指标在首次提取中置信度较低或使用了 fallback 模式。
请重新阅读论文内容，尝试找到更好的证据。输出 JSON：
{
  "improved": [{"metric": "...", "value": "改进后的提取值", "evidence": "论文原文证据", "confidence": "high/medium/low"}],
  "still_uncertain": ["无法改进的指标名"]
}
规则：evidence 必须是论文原文片段。如果确实找不到更好的证据，放入 still_uncertain。""",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"论文标题：{paper.title}\n"
                            f"需要复核的指标：{json.dumps(metrics_to_retry, ensure_ascii=False)}\n"
                            f"论文前 12000 字：\n{paper.content[:12000]}"
                        ),
                    },
                ],
                phase="result_reflection",
            )
        except Exception:
            final_results.setdefault("supervisor_trace", {})["result_reflection"] = "call_failed"
            return final_results

        improved = payload.get("improved") or []
        still_uncertain = payload.get("still_uncertain") or []

        text_data = final_results.get("text_only_data") or []
        improved_map = {item["metric"]: item for item in improved if isinstance(item, dict) and item.get("metric")}
        for i, item in enumerate(text_data):
            metric = item.get("metric", "")
            if metric in improved_map:
                better = improved_map[metric]
                text_data[i] = {
                    "metric": metric,
                    "value": better.get("value", item.get("value", "")),
                    "evidence": better.get("evidence", item.get("evidence", "")),
                    "mode": "reflection_improved",
                    "original_mode": item.get("mode", ""),
                    "reflection_confidence": better.get("confidence", "medium"),
                }
        final_results["text_only_data"] = text_data
        final_results.setdefault("supervisor_trace", {})["result_reflection"] = {
            "improved_count": len(improved),
            "still_uncertain": still_uncertain,
        }
        return final_results


class VisualBatchAgent:
    """Analyze multiple figures in parallel using ThreadPoolExecutor."""

    MAX_WORKERS = 4
    MAX_RETRIES = 3  # 从2增加到3，提高图表分析成功率

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.max_workers = max(1, int(os.getenv("VISUAL_LLM_MAX_WORKERS", str(self.MAX_WORKERS))))
        self.max_retries = max(0, int(os.getenv("VISUAL_LLM_MAX_RETRIES", "1")))

    def analyze_batch(
        self,
        plans: list[FigureExtractionPlan],
        supervisor_state: SupervisorState,
        on_figure_done: Callable[[dict], None] | None = None,
    ) -> list[dict]:
        if not plans:
            return []
        if len(plans) == 1:
            result = self._analyze_with_retry(plans[0], supervisor_state)
            if on_figure_done:
                on_figure_done(result)
            return [result]

        results: list[dict | None] = [None] * len(plans)
        workers = min(self.max_workers, len(plans))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(self._analyze_with_retry, plan, supervisor_state): idx
                for idx, plan in enumerate(plans)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = self._error_result(plans[idx], str(exc))
                results[idx] = result
                if on_figure_done:
                    on_figure_done(result)
        return results  # type: ignore[return-value]

    def _analyze_with_retry(self, plan: FigureExtractionPlan, supervisor_state: SupervisorState) -> dict:
        result = self._analyze_figure(plan)
        retry_count = 0
        while self._needs_retry(result) and retry_count < self.max_retries:
            retry_count += 1
            supervisor_state.visual_retries[plan.figure_id] = retry_count
            diagnosis = self._diagnose_failure(result)
            retry_plan = FigureExtractionPlan(
                figure_id=plan.figure_id,
                image_path=plan.image_path,
                caption=plan.caption,
                tasks=plan.tasks,
                review_notes=(
                    f"第{retry_count}次重试。上次失败原因：{diagnosis['reason']}。"
                    f"建议策略：{diagnosis['strategy']}"
                ),
            )
            result = self._analyze_figure(retry_plan)
            result["retry_count"] = retry_count
            result["failure_diagnosis"] = diagnosis
        return result

    def _analyze_figure(self, plan: FigureExtractionPlan) -> dict:
        started = time.time()
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return self._error_result(plan, "图片文件不可读")
        tasks_desc = "\n".join(
            f"{i + 1}. {t.metric_name}: {t.specific_instruction or t.text_context}"
            for i, t in enumerate(plan.tasks)
        )
        if self._prefer_text_fallback_first(plan):
            return self._text_visual_fallback(plan, image_data_url, tasks_desc, "page snapshot uses text-first visual analysis", started)
        review = f"\n复核提示：{plan.review_notes}" if plan.review_notes else ""
        try:
            payload = self.client.chat_json(
                [
                    {
                        "role": "system",
                        "content": """你是顶级科研图表数据提取专家。你的任务是从图片中提取**所有**可见的数据和信息，并用中文详细解释。

## 分析步骤（必须逐步完成）：

### 第一步：识别图表类型和结构
- 图表类型：柱状图/折线图/散点图/显微镜图/流程图/结构示意图/表格/组合图/其他
- 坐标轴信息：X轴标签、单位、刻度值；Y轴标签、单位、刻度值
- 图例信息：所有系列的名称、颜色、标记符号
- 标题和注释：主标题、子标题、图中所有文字标注

### 第二步：提取所有数据点（关键！）
**必须提取图中每个可见的数据点**：
- 柱状图：每个柱子的高度数值
- 折线图：每个数据点的X、Y坐标
- 散点图：每个点的位置
- 显微镜图/示意图：关键尺寸、标注的数值
- 表格：所有单元格的数据

如果数值清晰可读：记录精确数值
如果数值模糊：估算范围（如"约50-60"）
如果无法读取：标注"数值不可读"但描述大致位置和趋势

### 第三步：提取文本标注
记录图中所有文字：
- 数据标签（如柱子上的数字）
- 统计显著性标记（*, **, ***, p<0.05, p<0.01等）
- 箭头指向的说明文字
- 误差线的数值
- 百分比、倍数关系

### 第四步：总结关键发现
用中文总结：
- 最大值和最小值及其对应的条件
- 各组之间的对比关系（谁比谁高/低多少，倍数关系）
- 变化趋势（上升/下降/先升后降等）
- 统计显著性结论
- 关键数据点的具体数值

## 输出JSON格式：
{
  "figure_type": "具体图表类型",
  "title": "图表标题（中文）",
  "axes": {
    "x_axis": {"label": "X轴标签（中文）", "unit": "单位", "visible_values": ["刻度1", "刻度2"]},
    "y_axis": {"label": "Y轴标签（中文）", "unit": "单位", "range": "范围（如0-100）"}
  },
  "legend": [
    {"name": "系列名（中文）", "color": "颜色描述", "marker": "标记类型"}
  ],
  "data_points": [
    {
      "series": "所属系列（中文）",
      "x": "X值或分类",
      "y": "Y值",
      "value_label": "数据标签",
      "error_bar": "误差值（如有）",
      "significance": "显著性标记（如有）"
    }
  ],
  "annotations": ["图中所有文字标注（中文）"],
  "statistics": {
    "max_value": {"value": 数值, "condition": "条件（中文）"},
    "min_value": {"value": 数值, "condition": "条件（中文）"},
    "comparisons": ["对比1：A比B高50%", "对比2：C显著低于D (p<0.05)"]
  },
  "overall_description": "完整的中文描述，包括：图表展示了什么、主要数据点、关键趋势、重要对比",
  "extractions": [{
    "metric": "提取的指标名",
    "success": true,
    "data": {"具体数值字段": 数值},
    "qualitative": "用中文详细描述该指标的数值、趋势、对比关系",
    "confidence": "high/medium/low",
    "notes": "补充说明（中文）",
    "evidence": "图中可见的证据（坐标轴数值、标注文字等）"
  }],
  "key_findings": [
    "关键发现1：具体数值+单位+对比（中文）",
    "关键发现2：趋势+幅度+显著性（中文）"
  ],
  "extraction_completeness": "完整度评估（如：已提取所有可见数据点/部分数据点模糊）"
}

## 严格要求：
1. **全部中文**：所有描述、标签、结论必须用中文，包括overall_description、qualitative、notes、evidence、key_findings
2. **不遗漏数据**：提取图中**每一个**可见的数据点，不要只提取部分
3. **精确优先**：能看清数值就记录精确数值，不要只说"较高"、"增加"等模糊描述
4. **结构化**：数据必须结构化存储在data_points数组中
5. **可验证**：所有结论必须基于图中可见的证据
6. **完整解释**：key_findings必须包含具体数值和单位，如"A组的转化率为85%，比B组(60%)高出41.7%"
7. **中文图例**：如果图例是英文，翻译成中文""",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"""# 图表信息
- 图表编号：{plan.figure_id}
- 图注：{plan.caption}

# 提取任务
{tasks_desc}

# 分析要求
请严格按照系统提示的步骤，**完整提取**这个图表中的所有信息：

1. **完整识别结构**：图表类型、坐标轴（标签+刻度值）、图例（所有系列）
2. **提取所有数据点**：图中每个柱/点/线的具体数值，不要遗漏
3. **记录所有文字**：标题、标签、数据标签、统计标记、注释
4. **总结关键发现**：用中文说明主要数据、对比关系、显著性，必须包含具体数值

**关键要求**：
- 提取图中**每一个**可见的数据点
- 所有描述必须用**中文**
- 数值必须**精确记录**（能看清就记数值）
- 结论必须**具体**（如"A组85%，比B组60%高41.7%"，而不是"A组较高"）
{review}"""},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="visual",
            )
        except Exception as exc:
            return self._text_visual_fallback(plan, image_data_url, tasks_desc, str(exc), started)
        payload["figure_id"] = plan.figure_id
        payload["image_path"] = plan.image_path
        payload["elapsed"] = round(time.time() - started, 2)
        if not payload.get("extractions"):
            return self._text_visual_fallback(plan, image_data_url, tasks_desc, "模型未返回图片提取结果", started)
        return payload

    def _text_visual_fallback(self, plan: FigureExtractionPlan, image_data_url: str, tasks_desc: str, reason: str, started: float) -> dict:
        try:
            description = self.client.chat_text(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "请用中文描述这张论文图或页面截图，重点列出可见的关键数据、趋势、坐标轴、图例、"
                                    "显著性标记和结论。不要输出 JSON，不要解释过程，控制在500字以内。"
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    }
                ],
                phase="visual_text_fallback",
                max_tokens=1200,
            )
        except Exception as fallback_exc:
            return self._error_result(plan, f"{reason}; text fallback failed: {fallback_exc}")

        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "page_or_figure",
            "overall_description": description,
            "mode": "visual_text_fallback",
            "json_failure_reason": reason,
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": {},
                    "qualitative": description,
                    "confidence": "medium",
                    "notes": f"结构化视觉 JSON 失败后使用自然语言视觉理解降级。原始错误：{reason[:300]}",
                    "evidence": description[:500],
                    "mode": "visual_text_fallback",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _prefer_text_fallback_first(self, plan: FigureExtractionPlan) -> bool:
        if os.getenv("VISUAL_TEXT_FIRST_PAGE_SNAPSHOTS", "True").lower() not in ("true", "1", "t", "yes", "on"):
            return False
        marker = f"{plan.figure_id} {plan.caption}".lower()
        return "page" in marker and ("snapshot" in marker or "visual evidence" in marker)

    def _needs_retry(self, result: dict) -> bool:
        """判断是否需要重试图表分析。

        更宽松的重试策略：只重试严重失败的情况，避免过度重试导致低置信度结果丢失。
        """
        if result.get("error"):
            return True
        extractions = result.get("extractions") or []
        if not extractions:
            return True

        # 计算完全失败的提取项数量（既没有qualitative也没有data）
        failed_count = sum(
            1 for item in extractions
            if not item.get("success") and not item.get("qualitative") and not item.get("data")
        )

        # 只有超过一半提取项完全失败才重试，避免因低置信度就重试
        # 这样可以保留更多低置信度但有内容的结果
        return failed_count >= len(extractions) // 2

    def _diagnose_failure(self, result: dict) -> dict:
        if result.get("error"):
            return {"reason": f"模型调用错误: {result['error']}", "strategy": "检查图片是否可读，降低提取粒度，只描述可见内容"}
        extractions = result.get("extractions") or []
        if not extractions:
            return {"reason": "模型未返回任何提取结果", "strategy": "放宽要求，先描述图片整体内容，再尝试定位具体数据"}
        low_confidence = [e for e in extractions if str(e.get("confidence", "")).lower() == "low"]
        empty_results = [e for e in extractions if not (e.get("qualitative") or e.get("data"))]
        if empty_results:
            metrics = [e.get("metric", "unknown") for e in empty_results]
            return {"reason": f"指标 {metrics} 提取内容为空", "strategy": "聚焦图注、坐标轴标签、图例文字，给出定性描述即可"}
        if low_confidence:
            metrics = [e.get("metric", "unknown") for e in low_confidence]
            return {"reason": f"指标 {metrics} 置信度低", "strategy": "重点依据图中可见数字、趋势方向、对比关系给出保守结论，标注不确定性"}
        return {"reason": "结果质量不足", "strategy": "尝试更细致地描述图片可见内容，包括颜色、形状、文字标注"}

    def _error_result(self, plan: FigureExtractionPlan, reason: str) -> dict:
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "unknown",
            "overall_description": plan.caption or "图片分析失败",
            "error": reason,
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": False,
                    "data": {},
                    "qualitative": plan.caption or task.text_context or f"图片分析失败：{reason}",
                    "confidence": "none",
                    "notes": f"视觉模型不可用或图片分析失败：{reason}",
                }
                for task in plan.tasks
            ],
            "elapsed": 0,
        }
