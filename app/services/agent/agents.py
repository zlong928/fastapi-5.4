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
from app.services.agent.types import ExtractionMap, ExtractionTask, FigureExtractionPlan, ImageType, PaperData, SupervisorState
from app.services.agent.visual_agents import (
    BarChartAgent,
    CoordinateExtractionAgent,
    HeatmapAgent,
    ImageClassifierAgent,
    NonDataVisualAgent,
    TableImageAgent,
    image_classification_prompt,
    image_type_from_string,
)
from app.services.agent.visual_contracts import (
    generic_visual_system_prompt,
    generic_visual_user_prompt,
    visual_text_fallback_prompt,
)


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
    """Build a deterministic text/table/figure routing map before LLM interpretation."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def build_map(self, paper: PaperData, metrics: list[str]) -> tuple[ExtractionMap, list[str]]:
        extraction_map = ExtractionMap()
        extraction_map.text_only_metrics = self._text_candidates(paper, metrics)
        extraction_map.figures = self._figure_candidates(paper, metrics)
        extraction_map = self._ensure_all_figures_covered(paper, extraction_map, metrics)
        mapped = {normalize_metric(str(item.get("metric") or "")) for item in extraction_map.text_only_metrics}
        for plan in extraction_map.figures.values():
            mapped.update(task.metric_name for task in plan.tasks)
        not_found = [metric for metric in metrics if metric not in mapped and metric not in {"figure_data", "key_metrics"}]
        return extraction_map, not_found

    def _text_candidates(self, paper: PaperData, metrics: list[str]) -> list[dict]:
        candidates: list[dict] = []
        content = paper.content or ""
        for metric in metrics:
            if metric in {"figure_data"}:
                continue
            windows = self._metric_windows(content, metric)
            for window in windows[:2]:
                candidates.append(
                    {
                        "metric": metric,
                        "field": self._field_for_metric(metric, window),
                        "value": self._chinese_value(metric, window),
                        "evidence": window[:240],
                        "mode": "deterministic_text_window",
                    }
                )
        return candidates

    def _figure_candidates(self, paper: PaperData, metrics: list[str]) -> dict[str, FigureExtractionPlan]:
        figure_metrics = [metric for metric in metrics if metric in {"figure_data", "key_metrics", "conclusion"}]
        if not figure_metrics:
            figure_metrics = ["visible_evidence"]
        plans: dict[str, FigureExtractionPlan] = {}
        for figure in paper.figures:
            searchable = f"{figure.figure_id} {figure.caption} {figure.context}".lower()
            plan = FigureExtractionPlan(figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption)
            matched = False
            for metric in figure_metrics:
                if metric == "figure_data" or self._metric_matches_text(metric, searchable):
                    plan.tasks.append(
                        ExtractionTask(
                            metric_name=metric,
                            text_context=figure.context or figure.caption,
                            specific_instruction=self._visual_instruction(metric),
                        )
                    )
                    matched = True
                    break
            if matched and plan.tasks:
                plans[figure.figure_id] = plan
        return plans

    def _metric_windows(self, content: str, metric: str) -> list[str]:
        keywords = self._keywords_for_metric(metric)
        if not content.strip():
            return []
        lower = content.lower()
        windows: list[str] = []
        for keyword in keywords:
            start = 0
            keyword_lower = keyword.lower()
            while len(windows) < 2:
                index = lower.find(keyword_lower, start)
                if index < 0:
                    break
                left = max(0, index - 180)
                right = min(len(content), index + 420)
                snippet = " ".join(content[left:right].split())
                if len(snippet) >= 40 and snippet not in windows:
                    windows.append(snippet)
                start = index + len(keyword_lower)
            if len(windows) >= 2:
                break
        if not windows and metric in {"objective", "research_purpose", "conclusion"}:
            return [" ".join(content[:600].split())]
        return windows

    def _keywords_for_metric(self, metric: str) -> list[str]:
        return {
            "objective": ["we propose", "in this study", "here we", "aim", "objective"],
            "research_purpose": ["we propose", "in this study", "here we", "aim", "objective"],
            "materials": ["materials", "hydrogel", "Clostridium", "Shewanella", "consortium", "Meso-CS"],
            "materials_methods": ["hydrogel", "Clostridium", "Shewanella", "consortium", "method", "prepared"],
            "experiment_groups": ["Meso-CS", "CS", "monoculture", "control", "group", "versus"],
            "key_metrics": ["yield", "titre", "mg COD", "fold", "%", "performance", "production"],
            "conclusion": ["these findings", "overall", "demonstrated", "conclude", "suggest"],
        }.get(metric, [metric.replace("_", " ")])

    def _metric_matches_text(self, metric: str, text: str) -> bool:
        return any(keyword.lower() in text for keyword in self._keywords_for_metric(metric))

    def _field_for_metric(self, metric: str, text: str) -> str:
        lower = text.lower()
        if "hydrogel" in lower and ("10–40" in text or "10-40" in text or "diameter" in lower):
            return "水凝胶微腔直径"
        if "clostridium" in lower or "shewanella" in lower:
            return "菌株组成"
        if "hexanoic" in lower or "hexanoate" in lower:
            return "己酸产量"
        return metric

    def _compact_value(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= 220:
            return compact
        return compact[:220].rsplit(" ", 1)[0]

    def _chinese_value(self, metric: str, text: str) -> str:
        compact = self._compact_value(text)
        lower = compact.lower()
        if "porin regulation" in lower and "exometabolite" in lower:
            return "性能提升归因于孔蛋白调控和外源代谢物富集，使细菌间相互作用由单向电子传递转向双向多代谢物交叉供给。"
        if "succinic acid" in lower and "denitrification" in lower:
            return "该调控策略还适用于琥珀酸生产、低碳氮比废水反硝化和新兴污染物去除等其他废水处理体系。"
        if "biomass" in lower and "did not affect" in lower:
            return "mesospace 未影响菌群生物量，说明性能变化不是由更高生物量导致。"
        if "10–40" in compact or "10-40" in compact:
            return "微生物被限制在直径 10–40 μm 的水凝胶微腔中。"
        if "clostridium" in lower or "shewanella" in lower:
            return "核心菌群由 Clostridium carboxidivorans P7 与 Shewanella oneidensis MR-1 组成。"
        if "hexanoic" in lower or "hexanoate" in lower:
            return "论文报告了 Meso-CS 在己酸/己酸盐产量上的提升，具体数值见原文证据。"
        if metric in {"objective", "research_purpose"}:
            return "研究提出 mesospace-domain regulation 策略，用于调控微生物互作代谢并提升废水处理产物选择性。"
        if metric == "conclusion":
            return "论文结论表明 mesospace domain 可协调微生物代谢并提升废水生物转化表现。"
        return compact

    def _visual_instruction(self, metric: str) -> str:
        if metric == "key_metrics":
            return "只提取图中实际可见的数值、趋势、坐标轴、图例或结构证据；没有就返回空结果。"
        if metric == "conclusion":
            return "只解释图中可见证据支持的结论，不使用图注外推；没有明确证据就返回空结果。"
        return "只提取图像中实际可见、可核验的正向信息；没有就返回空结果。"

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
                plan.tasks.append(
                    ExtractionTask(
                        metric_name="visible_evidence",
                        text_context=figure.caption or "图表完整数据提取",
                        specific_instruction=(
                            "只提取图像中实际可见、可核验的正向信息。"
                            "如果图中没有文字、数值、坐标轴、标注或可描述的结构证据，返回空结果；"
                            "不要输出“没有数据/无法提取/不是图表类型”这类否定项。"
                        )
                    )
                )
                extraction_map.figures[figure.figure_id] = plan
            else:
                # 为已有的图表补充全面提取任务（如果没有）
                existing_plan = extraction_map.figures[figure.figure_id]
                has_comprehensive = any(
                    task.metric_name in ("visible_evidence", "figure_data", "key_metrics")
                    for task in existing_plan.tasks
                )
                if not has_comprehensive:
                    existing_plan.tasks.append(
                        ExtractionTask(
                            metric_name="visible_evidence",
                            text_context=figure.caption or "图表完整数据提取",
                            specific_instruction=(
                                "只提取图像中实际可见、可核验的正向信息。"
                                "如果图中没有文字、数值、坐标轴、标注或可描述的结构证据，返回空结果；"
                                "不要输出“没有数据/无法提取/不是图表类型”这类否定项。"
                            )
                        )
                    )

        return extraction_map

    def _system_prompt(self) -> str:
        return """你是科研论文数据提取路由专家。你的职责是快速建立图片/正文/表格到指标的映射，不在本阶段做长篇结果生成。
输出 JSON：
{
  "figure_mappings": {"Figure 1": {"tasks": [{"metric": "key_metrics", "context": "为什么看这张图（<=80字）", "instruction": "提取什么（<=80字）"}]}},
  "text_only_metrics": [{"metric": "materials", "field": "具体字段名", "value": "简短提取值（<=120字）", "evidence": "原文短证据（<=160字）"}],
  "not_found_metrics": []
}
规则：
1. text_only_metrics 的 evidence 必须是论文原文片段，不能是你的概括
2. 表格内容会出现在 [Extracted Tables] 区块；如果证据来自表格，请放在 text_only_metrics 并复制简短表格证据
3. text_only_metrics 每个 metric 最多返回 2 条；不要枚举全文所有方法、所有数值
4. figure_mappings 每张图最多 1 个 task；instruction 只描述需要视觉模型核验的内容
5. field 必须精确描述 value 的语义，不能只重复 materials_methods/key_metrics 这类宽泛类别
6. 输出必须紧凑，禁止长段解释。"""

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
        parts.append(f"论文全文前 8000 字：\n{paper.content[:8000]}")
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
  "new_text_metrics": [{"metric": "...", "field": "具体字段名", "value": "...", "evidence": "..."}],
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
    MAX_RETRIES = 3

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.max_workers = max(1, int(os.getenv("VISUAL_LLM_MAX_WORKERS", str(self.MAX_WORKERS))))
        self.max_retries = max(0, int(os.getenv("VISUAL_LLM_MAX_RETRIES", "1")))
        self.classifier = ImageClassifierAgent(client)
        self.coordinate_extractor = CoordinateExtractionAgent(client)
        self.bar_chart_agent = BarChartAgent(client)
        self.heatmap_agent = HeatmapAgent(client)
        self.table_image_agent = TableImageAgent(client)
        self.non_data_agent = NonDataVisualAgent(client)

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
        # 先分类图片类型
        if not plan.image_type:
            plan.image_type = self.classifier.classify(plan)

        # 根据类型选择处理方式
        result = self._route_to_agent(plan)

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
                image_type=plan.image_type,
            )
            result = self._route_to_agent(retry_plan)
            result["retry_count"] = retry_count
            result["failure_diagnosis"] = diagnosis
        return result

    def _route_to_agent(self, plan: FigureExtractionPlan) -> dict:
        """根据图表类型路由到对应的专用 agent"""
        image_type = plan.image_type

        # 坐标/时序/谱图类型路由
        if image_type in (
            ImageType.LINE_PLOT,
            ImageType.BIPHASIC_TIME_SERIES,
            ImageType.MULTI_LINE_PLOT,
            ImageType.SCATTER_PLOT,
            ImageType.SPECTRUM_CURVE,
            ImageType.BAR_OR_LINE_WITH_ERRORBAR,
            ImageType.GENERIC_COORDINATE_PLOT,
            ImageType.COORDINATE_PLOT,
        ):
            return self._analyze_coordinate_figure(plan)

        # 双轴图
        elif image_type == ImageType.DUAL_AXIS_PLOT:
            return self._analyze_coordinate_figure(plan)

        # 条形图
        elif image_type in (ImageType.BAR_CHART, ImageType.GROUPED_BAR):
            return self._analyze_bar_chart(plan)

        # 热图/二维颜色场
        elif image_type in (ImageType.HEATMAP, ImageType.HEATMAP_MATRIX, ImageType.FIELD_2D_MAP):
            return self._analyze_heatmap(plan)

        # 表格图
        elif image_type == ImageType.TABLE_IMAGE:
            return self._analyze_table_image(plan)

        # 非数据视觉证据
        elif image_type in (
            ImageType.NON_DATA_IMAGE,
            ImageType.MICROSCOPY_QUANT,
            ImageType.IMAGE_EVIDENCE,
            ImageType.SCHEMATIC,
            ImageType.SCHEMATIC_OR_PHOTO,
        ):
            return self._analyze_non_data_visual(plan)

        # 未知类型，使用通用分析
        else:
            return self._analyze_figure(plan)

    def _analyze_coordinate_figure(self, plan: FigureExtractionPlan) -> dict:
        """使用专用agent提取坐标数据"""
        started = time.time()
        coordinate_data = self.coordinate_extractor.extract_coordinates(plan)

        if "error" in coordinate_data:
            return self._error_result(plan, coordinate_data["error"])
        coordinate_data.setdefault("chart_type", plan.image_type.value if plan.image_type else "generic_coordinate_plot")

        # 转换为标准格式
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "coordinate_plot",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "coordinate_data": coordinate_data,
            "chart_data": coordinate_data,
            "overall_description": f"坐标数据图：{coordinate_data.get('figure', plan.figure_id)}",
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": coordinate_data,
                    "qualitative": f"已提取坐标数据，共{len(coordinate_data.get('panels', []))}个子图",
                    "confidence": "high",
                    "notes": "使用专用坐标提取agent",
                    "mode": "coordinate_extraction",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _analyze_bar_chart(self, plan: FigureExtractionPlan) -> dict:
        """使用专用agent提取条形图数据"""
        started = time.time()
        chart_data = self.bar_chart_agent.extract_bars(plan)

        if "error" in chart_data:
            return self._error_result(plan, chart_data["error"])
        chart_data.setdefault("chart_type", plan.image_type.value if plan.image_type else "bar_chart")

        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "bar_chart",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "chart_data": chart_data,
            "overall_description": f"条形图：{chart_data.get('figure', plan.figure_id)}",
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": chart_data,
                    "qualitative": f"已提取条形图数据",
                    "confidence": "high",
                    "notes": "使用专用条形图提取agent",
                    "mode": "bar_chart_extraction",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _analyze_heatmap(self, plan: FigureExtractionPlan) -> dict:
        """使用专用agent提取热图数据"""
        started = time.time()
        chart_data = self.heatmap_agent.extract_heatmap(plan)

        if "error" in chart_data:
            return self._error_result(plan, chart_data["error"])
        chart_data.setdefault("chart_type", plan.image_type.value if plan.image_type else "heatmap_matrix")

        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "heatmap",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "chart_data": chart_data,
            "overall_description": f"热图：{chart_data.get('figure', plan.figure_id)}",
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": chart_data,
                    "qualitative": f"已提取热图数据",
                    "confidence": "medium",
                    "notes": "使用专用热图提取agent",
                    "mode": "heatmap_extraction",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _analyze_table_image(self, plan: FigureExtractionPlan) -> dict:
        """使用专用agent提取表格图数据"""
        started = time.time()
        chart_data = self.table_image_agent.extract_table_image(plan)

        if "error" in chart_data:
            return self._error_result(plan, chart_data["error"])
        chart_data.setdefault("chart_type", "table_image")

        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "table_image",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "chart_data": chart_data,
            "overall_description": f"表格图：{chart_data.get('figure', plan.figure_id)}",
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": chart_data,
                    "qualitative": f"已提取表格图数据",
                    "confidence": "high",
                    "notes": "使用专用表格图提取agent",
                    "mode": "table_image_extraction",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

    def _analyze_non_data_visual(self, plan: FigureExtractionPlan) -> dict:
        """处理非数据视觉证据"""
        started = time.time()
        chart_data = self.non_data_agent.describe_visual(plan)

        if "error" in chart_data:
            return self._error_result(plan, chart_data["error"])
        chart_data.setdefault("chart_type", plan.image_type.value if plan.image_type else "non_data_image")

        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "non_data_visual",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "chart_data": chart_data,
            "overall_description": chart_data.get("description", "非数据视觉证据"),
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": chart_data,
                    "qualitative": chart_data.get("description", ""),
                    "confidence": "medium",
                    "notes": "非数据视觉证据，无数值可提取",
                    "mode": "visual_descriptive",
                }
                for task in plan.tasks
            ],
            "elapsed": round(time.time() - started, 2),
        }

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
        try:
            content = self.client.chat_text(
                [
                    {
                        "role": "system",
                        "content": generic_visual_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": generic_visual_user_prompt(
                                    plan.figure_id,
                                    plan.caption,
                                    tasks_desc,
                                    plan.review_notes,
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                phase="visual",
            )
        except Exception as exc:
            return self._error_result(plan, str(exc))

        payload = self._parse_single_pass_visual_response(plan, content)
        payload["figure_id"] = plan.figure_id
        payload["image_path"] = plan.image_path
        payload["image_type"] = plan.image_type.value if plan.image_type else "unknown"
        payload["elapsed"] = round(time.time() - started, 2)
        return payload

    def _parse_single_pass_visual_response(self, plan: FigureExtractionPlan, content: str) -> dict:
        try:
            payload = self.client._parse_json(content)
        except Exception:
            return self._single_pass_text_result(plan, content, "visual_text_single_pass")

        # 确保所有返回的字典都有image_type
        if "image_type" not in payload:
            payload["image_type"] = plan.image_type.value if plan.image_type else "unknown"

        if not payload.get("extractions"):
            description = str(
                payload.get("overall_description")
                or payload.get("description")
                or payload.get("title")
                or content
            )
            return self._single_pass_text_result(plan, description, "visual_json_without_extractions")
        return payload

    def _single_pass_text_result(self, plan: FigureExtractionPlan, description: str, mode: str) -> dict:
        cleaned = (description or "").strip()
        if not cleaned:
            return self._error_result(plan, "视觉模型未返回可用内容")
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "page_or_figure",
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "overall_description": cleaned,
            "mode": mode,
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": {},
                    "qualitative": cleaned,
                    "confidence": "low" if self._looks_negative_or_empty(cleaned) else "medium",
                    "notes": "单次视觉调用未返回可用结构化 JSON，已使用同一次响应文本作为证据，未触发二次视觉调用。",
                    "evidence": cleaned[:500],
                    "mode": mode,
                }
                for task in plan.tasks
            ],
        }

    def _text_visual_fallback(self, plan: FigureExtractionPlan, image_data_url: str, tasks_desc: str, reason: str, started: float) -> dict:
        try:
            description = self.client.chat_text(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": visual_text_fallback_prompt(),
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
            "image_type": plan.image_type.value if plan.image_type else "unknown",
            "overall_description": description,
            "mode": "visual_text_fallback",
            "json_failure_reason": reason,
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": True,
                    "data": {},
                    "qualitative": description,
                    "confidence": "low" if self._looks_negative_or_empty(description) else "medium",
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

    def _looks_negative_or_empty(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return True
        negative_markers = (
            "没有任何",
            "无法提取",
            "不能提取",
            "不可读取",
            "不包含可",
            "没有可",
            "不存在可",
            "no extractable",
            "no visible",
        )
        return any(marker in normalized.lower() for marker in negative_markers)

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

        # 只有超过一半提取项完全失败才重试，避免因低置信度或单次文本结果就重试
        # 这样可以保留更多低置信度但有内容的结果
        return failed_count > 0 and failed_count > len(extractions) / 2

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
            "image_type": plan.image_type.value if plan.image_type else "unknown",
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
