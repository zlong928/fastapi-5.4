from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import httpx

from app.services.agent.fallback_agent import FallbackExtractionCoordinator
from app.services.agent.types import ExtractionMap, ExtractionTask, FigureExtractionPlan, PaperData, SupervisorState


class OpenAIExtractionCoordinator(FallbackExtractionCoordinator):
    """OpenAI-compatible coordinator that keeps the agent.py generator contract."""

    MAX_VISUAL_RETRIES = 2

    def __init__(self, config: dict) -> None:
        self.config = config
        self.base_url = str(config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = str(config.get("api_key") or "")
        self.model = str(config.get("model") or "gpt-4o-mini")
        self.timeout = float(config.get("timeout") or 60)
        self.token_stats = {"planning": {}, "mapping": {}, "reflection": {}, "visual": {}, "total": {}}

    def extract(self, paper: PaperData, user_query: str | None = None, preset_metrics: list[str] | None = None):
        self.token_stats = {"planning": {}, "mapping": {}, "reflection": {}, "visual": {}, "total": {}}
        supervisor_state = SupervisorState()

        yield {"phase": "PLANNING", "status": "start", "message": "阶段1: 解析用户指令，规划提取任务..."}
        metrics = preset_metrics or self._plan_metrics(user_query or "", paper.title)
        yield {"phase": "PLANNING", "status": "done", "message": f"识别出 {len(metrics)} 个待提取指标", "data": {"metrics": metrics}}

        yield {"phase": "MAPPING", "status": "start", "message": "阶段2: 阅读全文，构建提取地图..."}
        extraction_map, not_found = self._build_extraction_map(paper, metrics)
        yield {
            "phase": "MAPPING",
            "status": "done",
            "message": f"映射完成: {len(extraction_map.figures)} 张图片待分析",
            "data": {"figure_count": len(extraction_map.figures), "text_only_count": len(extraction_map.text_only_metrics), "not_found": not_found},
        }

        yield {"phase": "REFLECTION", "status": "mapping_review", "message": "阶段2.5: 复核提取地图，检查遗漏与错配..."}
        reflection_result = self._reflect_on_mapping(paper, metrics, extraction_map, not_found)
        if reflection_result["adjusted"]:
            extraction_map = reflection_result["extraction_map"]
            not_found = reflection_result["not_found"]
            supervisor_state.mapping_adjusted = True
        supervisor_state.reflection_notes.append(reflection_result["notes"])
        yield {"phase": "REFLECTION", "status": "done", "message": reflection_result["message"], "data": {"approved": not reflection_result["adjusted"], "adjusted": reflection_result["adjusted"], "remaining_not_found": not_found}}

        yield {"phase": "VISUAL_ANALYSIS", "status": "start", "message": f"阶段3: 分析 {len(extraction_map.figures)} 张图片..."}
        visual_results: list[dict] = []
        for plan in extraction_map.figures.values():
            result = self._analyze_figure_with_retry(plan, supervisor_state)
            visual_results.append(result)
            yield {"phase": "VISUAL_ANALYSIS", "status": "figure_done", "message": f"{plan.figure_id} 分析完成", "data": result}
        yield {"phase": "VISUAL_ANALYSIS", "status": "done", "message": f"图片分析完成: {len(visual_results)} 张"}

        yield {"phase": "AGGREGATION", "status": "start", "message": "阶段4: 汇总提取结果..."}
        final = self._aggregate_results(paper, metrics, extraction_map, visual_results, not_found, supervisor_state)
        final["token_usage"] = self.token_stats
        final["model_info"] = {"provider": "openai_compatible", "base_url": self.base_url, "model": self.model}
        yield {"phase": "AGGREGATION", "status": "done", "message": "提取完成！", "data": final}
        yield {"phase": "FINISH", "status": "done", "message": "所有任务完成", "results": final}

    def _plan_metrics(self, user_query: str, paper_title: str) -> list[str]:
        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": "你是科研数据提取任务规划专家。输出 JSON：{\"metrics\":[\"materials\",\"experiment_groups\",\"key_metrics\",\"conclusion\"]}。指标必须短、稳定、可用于数据库字段名。",
                },
                {"role": "user", "content": f"论文标题：{paper_title}\n用户目标：{user_query}\n请拆解 3-6 个指标。"},
            ],
            phase="planning",
        )
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(metrics, list) or not metrics:
            return self.DEFAULT_METRICS
        return [self._normalize_metric(str(metric)) for metric in metrics[:6] if str(metric).strip()] or self.DEFAULT_METRICS

    def _build_extraction_map(self, paper: PaperData, metrics: list[str]) -> tuple[ExtractionMap, list[str]]:
        figures_summary = "\n".join(f"- {fig.figure_id}: {fig.caption[:240]}" for fig in paper.figures)
        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": """你是科研论文数据分析专家。一次阅读全文，建立图片/正文/表格到指标的映射。
输出 JSON：
{
  "figure_mappings": {"Figure 1": {"tasks": [{"metric": "key_metrics", "context": "为什么看这张图", "instruction": "提取什么"}]}},
  "text_only_metrics": [{"metric": "materials", "value": "提取值", "evidence": "原文证据（必须是论文中的原句或数据）"}],
  "not_found_metrics": []
}
规则：
1. text_only_metrics 的 evidence 必须是论文原文片段，不能是你的概括
2. 表格内容会出现在 [Extracted Tables] 区块；如果证据来自表格，请放在 text_only_metrics 并复制简短表格证据
3. 每个指标的 value 应该是具体的、可核对的信息，不是泛泛的总结""",
                },
                {
                    "role": "user",
                    "content": self._mapping_user_prompt(paper, metrics, figures_summary),
                },
            ],
            phase="mapping",
        )
        extraction_map = ExtractionMap()
        for fig_id, fig_data in (payload.get("figure_mappings") or {}).items():
            figure = self._find_figure(paper, str(fig_id))
            if not figure:
                continue
            plan = FigureExtractionPlan(figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption)
            for task in fig_data.get("tasks", []) or []:
                metric = self._normalize_metric(str(task.get("metric") or ""))
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
        not_found = [self._normalize_metric(str(item)) for item in (payload.get("not_found_metrics") or [])]
        if not extraction_map.figures and paper.figures:
            fallback_map, fallback_not_found = self._build_map(paper, metrics)
            extraction_map.figures = fallback_map.figures
            if not extraction_map.text_only_metrics:
                extraction_map.text_only_metrics = fallback_map.text_only_metrics
            not_found = not_found or fallback_not_found
        return extraction_map, not_found

    def _mapping_user_prompt(self, paper: PaperData, metrics: list[str], figures_summary: str) -> str:
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

    def _reflect_on_mapping(self, paper: PaperData, metrics: list[str], extraction_map: ExtractionMap, not_found: list[str]) -> dict:
        mapped_metrics = set()
        for plan in extraction_map.figures.values():
            for task in plan.tasks:
                mapped_metrics.add(task.metric_name)
        for item in extraction_map.text_only_metrics:
            mapped_metrics.add(str(item.get("metric", "")))

        unmapped = [m for m in metrics if m not in mapped_metrics and m not in not_found]
        figure_ids = [plan.figure_id for plan in extraction_map.figures.values()]
        table_summary = ""
        if paper.tables:
            table_summary = "\n".join(f"- {t.label} (page {t.page_number}): columns={t.headers[:6]}, rows={t.row_count}" for t in paper.tables)

        if not unmapped and not not_found:
            return {
                "adjusted": False,
                "extraction_map": extraction_map,
                "not_found": not_found,
                "message": "映射复核通过，所有指标已覆盖",
                "notes": {"stage": "mapping", "approved": True, "notes": "all metrics covered", "suggestions": 0},
            }

        try:
            payload = self._chat_json(
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
            figure = self._find_figure(paper, str(fig_id))
            if not figure:
                continue
            plan = extraction_map.figures.get(figure.figure_id) or FigureExtractionPlan(
                figure_id=figure.figure_id, image_path=figure.image_path, caption=figure.caption
            )
            existing_metrics = {task.metric_name for task in plan.tasks}
            for task in fig_data.get("tasks", []) or []:
                metric = self._normalize_metric(str(task.get("metric") or ""))
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

        resolved = [self._normalize_metric(str(m)) for m in (payload.get("resolved_not_found") or [])]
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

    def _analyze_figure_with_retry(self, plan: FigureExtractionPlan, supervisor_state: SupervisorState) -> dict:
        result = self._analyze_figure(plan)
        retry_count = 0
        while self._needs_retry(result) and retry_count < self.MAX_VISUAL_RETRIES:
            retry_count += 1
            supervisor_state.visual_retries[plan.figure_id] = retry_count
            failure_diagnosis = self._diagnose_failure(result)
            retry_plan = FigureExtractionPlan(
                figure_id=plan.figure_id,
                image_path=plan.image_path,
                caption=plan.caption,
                tasks=plan.tasks,
                review_notes=(
                    f"第{retry_count}次重试。上次失败原因：{failure_diagnosis['reason']}。"
                    f"建议策略：{failure_diagnosis['strategy']}"
                ),
            )
            result = self._analyze_figure(retry_plan)
            result["retry_count"] = retry_count
            result["failure_diagnosis"] = failure_diagnosis
        return result

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

    def _analyze_figure(self, plan: FigureExtractionPlan) -> dict:
        started = time.time()
        image_base64 = self._image_base64(plan.image_path)
        if not image_base64:
            return self._fallback_visual(plan, "图片文件不可读")
        tasks_description = "\n".join(f"{index + 1}. {task.metric_name}: {task.specific_instruction or task.text_context}" for index, task in enumerate(plan.tasks))
        review = f"\n复核提示：{plan.review_notes}" if plan.review_notes else ""
        try:
            payload = self._chat_json(
                [
                    {
                        "role": "system",
                        "content": """你是科研图表分析专家。必须结合图片可见内容和图注，输出 JSON：
{
  "figure_type": "bar_chart/line_chart/scatter_plot/microscopy/flowchart/architecture_diagram/table_snapshot/other",
  "overall_description": "图片整体描述，包括可见的坐标轴、图例、标注文字",
  "extractions": [{
    "metric": "指标名",
    "success": true/false,
    "data": {"key": "value"},
    "qualitative": "定性结论或数值描述",
    "confidence": "high/medium/low",
    "notes": "不确定性说明或补充信息",
    "evidence": "图中可见的支撑证据（坐标轴数字、图例文字、标注等）"
  }]
}
规则：
1. data 字段尽量填入从图中读取的具体数值（如柱状图高度、折线图数据点）
2. evidence 必须来自图片中可见的文字、数字或标注，不能编造
3. 如果无法读取精确数值，data 留空但 qualitative 给出保守描述
4. notes 说明不确定性来源（如分辨率不足、数据点重叠等）""",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"图片：{plan.figure_id}\n图注：{plan.caption}\n任务：\n{tasks_description}{review}"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        ],
                    },
                ],
                phase="visual",
            )
        except Exception as exc:
            return self._fallback_visual(plan, str(exc))
        payload["figure_id"] = plan.figure_id
        payload["image_path"] = plan.image_path
        payload["elapsed"] = round(time.time() - started, 2)
        if not payload.get("extractions"):
            return self._fallback_visual(plan, "模型未返回图片提取结果")
        return payload

    def _chat_json(self, messages: list[dict], *, phase: str) -> dict:
        request_body = {"model": self.model, "messages": messages, "temperature": 0.1, "response_format": {"type": "json_object"}}
        content = self._stream_chat_content({**request_body, "stream": True}, phase=phase)
        return self._parse_json_content(content)

    def _stream_chat_content(self, body: dict, *, phase: str) -> str:
        last_error: Exception | None = None
        for url in self._chat_urls():
            try:
                chunks: list[str] = []
                usage: dict = {}
                with httpx.stream(
                    "POST",
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                    timeout=self.timeout,
                ) as response:
                    response.raise_for_status()
                    if "text/event-stream" not in response.headers.get("content-type", "") and "application/json" not in response.headers.get("content-type", ""):
                        raise RuntimeError(f"stream endpoint returned {response.headers.get('content-type', '')}")
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[len("data:"):].strip()
                        if line == "[DONE]":
                            break
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if payload.get("usage"):
                            usage = payload["usage"]
                        choice = (payload.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            chunks.append(delta["content"])
                        message = choice.get("message") or {}
                        if message.get("content"):
                            chunks.append(message["content"])
                content = "".join(chunks).strip()
                if content:
                    self._merge_usage(phase, usage)
                    return content
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"模型流式调用失败 phase={phase} model={self.model}: {last_error}")

    def _chat_urls(self) -> list[str]:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return [f"{base}/chat/completions"]
        return [f"{base}/v1/chat/completions", f"{base}/chat/completions"]

    def _merge_usage(self, phase: str, usage: dict) -> None:
        phase_usage = self.token_stats.setdefault(phase, {})
        total_usage = self.token_stats.setdefault("total", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = int(usage.get(key) or 0)
            phase_usage[key] = int(phase_usage.get(key) or 0) + value
            total_usage[key] = int(total_usage.get(key) or 0) + value

    def _parse_json_content(self, content: str) -> dict:
        text = (content or "").strip()
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if match:
            text = match.group(1)
        elif "{" in text and "}" in text:
            text = text[text.find("{"): text.rfind("}") + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Model response is not a JSON object.")
        return parsed

    def _find_figure(self, paper: PaperData, figure_id: str):
        normalized = self._normalize_figure_id(figure_id)
        for figure in paper.figures:
            candidate = self._normalize_figure_id(figure.figure_id)
            if normalized in candidate or candidate in normalized:
                return figure
        return None

    def _normalize_figure_id(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _normalize_metric(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", value.strip()).strip("_").lower()
        aliases = {
            "材料组成": "materials",
            "实验分组": "experiment_groups",
            "关键指标": "key_metrics",
            "主要结论": "conclusion",
            "结论": "conclusion",
        }
        return aliases.get(value.strip(), cleaned or "unknown")

    def _image_base64(self, image_path: str) -> str | None:
        try:
            path = Path(image_path)
            if not path.exists():
                return None
            return base64.b64encode(path.read_bytes()).decode("utf-8")
        except Exception:
            return None

    def _fallback_visual(self, plan: FigureExtractionPlan, reason: str) -> dict:
        result = super()._analyze_figure(plan)
        result["overall_description"] = plan.caption or "Fallback figure analysis"
        for extraction in result.get("extractions", []):
            extraction["notes"] = f"视觉模型不可用或图片分析失败：{reason}"
        return result

    def _needs_retry(self, result: dict) -> bool:
        if result.get("error"):
            return True
        extractions = result.get("extractions") or []
        if not extractions:
            return True
        return any(
            str(item.get("confidence", "")).lower() == "low" or not (item.get("qualitative") or item.get("data"))
            for item in extractions
        )
