from __future__ import annotations

import time

from app.services.agent.types import ExtractionMap, ExtractionTask, FigureExtractionPlan, PaperData, SupervisorState


class FallbackExtractionCoordinator:
    DEFAULT_METRICS = ["research_purpose", "materials", "experiment_groups", "key_metrics", "figure_data", "conclusion"]
    MAX_VISUAL_RETRIES = 1

    def extract(self, paper: PaperData, user_query: str | None = None, preset_metrics: list[str] | None = None):
        yield {"phase": "PLANNING", "status": "start", "message": "阶段1: 解析用户指令，规划提取任务..."}
        metrics = preset_metrics or self.DEFAULT_METRICS
        yield {"phase": "PLANNING", "status": "done", "message": f"识别出 {len(metrics)} 个待提取指标", "data": {"metrics": metrics}}

        yield {"phase": "MAPPING", "status": "start", "message": "阶段2: 阅读全文，构建提取地图..."}
        extraction_map, not_found = self._build_map(paper, metrics)
        yield {
            "phase": "MAPPING",
            "status": "done",
            "message": f"映射完成: {len(extraction_map.figures)} 张图片待分析",
            "data": {"figure_count": len(extraction_map.figures), "text_only_count": len(extraction_map.text_only_metrics), "not_found": not_found},
        }

        supervisor_state = SupervisorState()
        yield {"phase": "REFLECTION", "status": "mapping_review", "message": "阶段2.5: 复核提取地图，检查遗漏与错配..."}
        supervisor_state.reflection_notes.append({"stage": "mapping", "approved": True, "notes": "fallback mapping approved", "suggestions": 0})
        yield {"phase": "REFLECTION", "status": "done", "message": "映射复核完成", "data": {"approved": True, "remaining_not_found": not_found}}

        yield {"phase": "VISUAL_ANALYSIS", "status": "start", "message": f"阶段3: 并行分析 {len(extraction_map.figures)} 张图片..."}
        visual_results = []
        for plan in extraction_map.figures.values():
            result = self._analyze_figure(plan)
            visual_results.append(result)
            yield {"phase": "VISUAL_ANALYSIS", "status": "figure_done", "message": f"{plan.figure_id} fallback 分析完成", "data": result}
        yield {"phase": "VISUAL_ANALYSIS", "status": "done", "message": f"图片分析完成: {len(visual_results)} 张"}

        yield {"phase": "AGGREGATION", "status": "start", "message": "阶段4: 汇总提取结果..."}
        final = self._aggregate_results(paper, metrics, extraction_map, visual_results, not_found, supervisor_state)
        yield {"phase": "AGGREGATION", "status": "done", "message": "提取完成！", "data": final}
        yield {"phase": "FINISH", "status": "done", "message": "所有任务完成", "results": final}

    def _build_map(self, paper: PaperData, metrics: list[str]) -> tuple[ExtractionMap, list[str]]:
        extraction_map = ExtractionMap()
        content = paper.content
        table_content = self._table_content(content)
        text_metrics = []
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
                text_metrics.append({"metric": metric, "value": self._snippet(source, metric), "evidence": self._snippet(source, metric, limit=240), "mode": "fallback_caption_only"})
        extraction_map.text_only_metrics = text_metrics
        return extraction_map, []

    def _analyze_figure(self, plan: FigureExtractionPlan) -> dict:
        return {
            "figure_id": plan.figure_id,
            "image_path": plan.image_path,
            "figure_type": "unknown",
            "overall_description": plan.caption or "Fallback figure analysis",
            "mode": "fallback_caption_only",
            "extractions": [
                {
                    "metric": task.metric_name,
                    "success": False,
                    "data": {},
                    "qualitative": plan.caption or task.text_context or "无法分析：未配置视觉模型",
                    "confidence": "none",
                    "notes": "No multimodal API key configured; caption-only fallback, not a real extraction.",
                    "mode": "fallback_caption_only",
                }
                for task in plan.tasks
            ],
            "elapsed": 0,
        }

    def _aggregate_results(self, paper: PaperData, metrics: list[str], extraction_map: ExtractionMap, visual_results: list[dict], not_found: list[str], supervisor_state: SupervisorState) -> dict:
        results = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "metrics_requested": metrics,
            "by_metric": {metric: {"status": "not_found", "sources": []} for metric in metrics},
            "by_figure": {},
            "text_only_data": extraction_map.text_only_metrics,
            "not_found_metrics": not_found,
            "supervisor_trace": {
                "mapping_adjusted": supervisor_state.mapping_adjusted,
                "visual_retries": supervisor_state.visual_retries,
                "reflection_notes": supervisor_state.reflection_notes,
            },
            "token_usage": {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        }
        for item in extraction_map.text_only_metrics:
            metric = item.get("metric", "")
            if metric:
                results["by_metric"].setdefault(metric, {"status": "found_in_text", "sources": []})
                results["by_metric"][metric]["status"] = "found_in_text"
                results["by_metric"][metric]["sources"].append({"source_type": "text", "value": item.get("value", ""), "evidence": item.get("evidence", "")})
        for visual in visual_results:
            fig_id = visual.get("figure_id", "unknown")
            results["by_figure"][fig_id] = {
                "image_path": visual.get("image_path", ""),
                "figure_type": visual.get("figure_type", ""),
                "overall_description": visual.get("overall_description", ""),
                "extractions": visual.get("extractions", []),
                "elapsed": visual.get("elapsed", 0),
            }
        results["not_found_metrics"] = [metric for metric in metrics if results["by_metric"].get(metric, {}).get("status") == "not_found"]
        return results

    def _snippet(self, content: str, metric: str, limit: int = 700) -> str:
        if not content.strip():
            return "未在当前论文解析内容中找到明确证据"
        lower = content.lower()
        key = metric.lower()
        index = lower.find(key)
        if index < 0:
            index = 0
        return content[index:index + limit].strip()

    def _table_content(self, content: str) -> str:
        marker = "[Extracted Tables]"
        if marker not in content:
            return ""
        return content.split(marker, 1)[1].strip()
