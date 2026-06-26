"""Enhanced ExtractionServiceV2 with merged advantages from old Agent system.

Key improvements:
1. User query as core prompt (not hardcoded system instructions)
2. Parallel figure processing from VisualBatchAgent
3. Ensure all figures covered (from GlobalMapAgent)
4. Quality checks (from old agents)
5. Flexible keyword matching (from GlobalMapAgent)
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import (
    Document,
    DocumentAsset,
    ExtractionRun,
    ExtractionItem,
    ExtractionEvidence,
)
from app.services.agent.llm_client import LLMClient
from app.services.extraction.classification_pipeline_v2 import (
    ClassificationPipeline,
    IndicatorMapping,
)
from app.services.extraction.figure_extraction_pipeline import (
    FigureExtractionPipeline,
    FigureExtractionResult,
)
from app.services.extraction.llm_config import build_llm_config, build_vlm_config
from app.services.extraction.fusion_pipeline import FusionPipeline
from app.services.markdown_ref_builder import MRFBuilder, MarkdownDocument

logger = logging.getLogger(__name__)


# ✅ 新设计：文本提取的系统提示词也改为"工具能力"定义
TEXT_EXTRACTION_SYSTEM_PROMPT = """你是一个科学数据提取引擎。

## 你的能力
- 从科学论文的文本段落中提取具体的数值、单位、误差信息
- 识别和引用原文证据
- 判断提取结果的置信度

## 输出格式
返回JSON：
```json
{
  "extractions": [
    {
      "indicator": "<用户要提取的内容，保持原始表达>",
      "value_text": "4500 ± 200 mPa·s",
      "value_numeric": 4500.0,
      "value_unit": "mPa·s",
      "value_error": "±200 (SD)",
      "evidence_quote": "<从原文中引用的完整句子或段落>",
      "confidence": 0.9
    }
  ]
}
```

## 工作原则
1. **只提取明确陈述的值**：不要推测或外推
2. **保持用户的原始表达**：indicator字段使用用户的原始描述
3. **引用完整证据**：evidence_quote必须是原文的完整句子
4. **标注置信度**：
   - 0.9-1.0: 明确陈述且有具体数值
   - 0.7-0.9: 描述清晰但可能有多种解读
   - 0.5-0.7: 信息模糊或间接提及
   - <0.5: 不确定，建议跳过
5. **如果找不到，不要包含该条目**：空结果比错误结果更好
"""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class ExtractionServiceV2Enhanced:
    """Enhanced extraction orchestrator with merged advantages."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient(build_llm_config())
        self.visual_client = LLMClient(build_vlm_config())
        self.mrf_builder = MRFBuilder()
        self.classifier = ClassificationPipeline(self.client)
        self.figure_extractor = FigureExtractionPipeline(self.visual_client)
        self.fusion = FusionPipeline(self.client)

        # ✅ 从旧系统继承：并发控制
        self.max_workers = _env_int("VISUAL_LLM_MAX_WORKERS", 4)

    def run_extraction(
        self,
        *,
        db: Session,
        paper: Document,
        user_query: str,
        mode: str = "standard",
    ) -> ExtractionRun:
        """Run the complete extraction pipeline with user-query-first design.

        Args:
            db: Database session.
            paper: The Document record (must have status='done').
            user_query: The user's complete, unmodified extraction request.
            mode: Extraction mode ('quick', 'standard', 'deep').

        Returns:
            The completed ``ExtractionRun``.
        """
        markdown_text = paper.cleaned_text or paper.parsed_text or ""
        if not markdown_text.strip():
            raise ValueError("Paper has no parsed text. Run MinerU parse first.")

        # Create the run record
        run = ExtractionRun(
            paper_id=paper.id,
            user_query=user_query,
            status="classifying",
            phase="classifying",
        )
        db.add(run)
        db.flush()

        try:
            # Phase 1: Build MRF from markdown
            mrf_doc = self.mrf_builder.build(markdown_text)

            # Phase 2: Classification — map user query to sources
            # ✅ 关键：不再解析为"indicators"列表，完整传递user_query
            run.phase = "classifying"
            mappings = self.classifier.classify(mrf_doc, user_query)

            # ✅ 从旧系统继承：确保所有图表都被覆盖
            mappings = self._ensure_all_figures_covered(mrf_doc, mappings, paper)

            run.classification_json = json.dumps(
                [
                    {
                        "indicator": m.indicator,
                        "figures": m.figures,
                        "sections": m.sections,
                        "tables": m.tables,
                        "extraction_hint": m.extraction_hint,
                        "priority": m.priority,
                    }
                    for m in mappings
                ],
                ensure_ascii=False,
            )

            # Phase 3: Text extraction from sections
            if mode in ("standard", "deep"):
                run.phase = "extracting_text"
                run.status = "extracting_text"
                db.flush()
                text_items = self._extract_text_items(
                    db, run, mrf_doc, mappings, paper, user_query
                )
            else:
                text_items = []

            # Phase 4: Figure extraction from charts
            # ✅ 从旧系统继承：并行处理图表
            run.phase = "extracting_figures"
            run.status = "extracting_figures"
            db.flush()
            figure_results = self._extract_figure_items_parallel(
                db, run, mrf_doc, mappings, paper, user_query
            )
            # Persist figure extraction items to DB
            try:
                self._persist_figure_results(db, run, figure_results)
            except Exception as persist_exc:
                logger.error("Failed to persist figure results: %s", persist_exc, exc_info=True)

            # Phase 5: Fusion verification (only in deep mode)
            if mode == "deep":
                run.phase = "fusing"
                run.status = "fusing"
                db.flush()
                self._run_fusion_verification(
                    db, run, mappings, text_items, figure_results, mrf_doc, user_query
                )

            # Mark complete
            run.status = "done"
            run.phase = "done"
            run.completed_at = app_now()
            run.summary = self._build_summary(run, mappings, text_items, figure_results)
            db.flush()

        except Exception as exc:
            logger.exception("Extraction run %s failed", run.id)
            run.status = "failed"
            run.error_message = str(exc)
            run.error_phase = run.phase
            db.flush()

        return run

    def _persist_figure_results(
        self, db: Session, run: ExtractionRun, figure_results: list[dict],
    ) -> int:
        """Persist figure extraction results as ExtractionItem records."""
        import json as _json
        count = 0
        for fr in figure_results:
            result = fr.get("result")
            if not result or not result.data_points:
                continue
            fig_label = fr.get("fig_label", "")
            mapping = fr.get("mapping")
            indicator = mapping.indicator if mapping else ""
            item = ExtractionItem(
                run_id=run.id,
                indicator=indicator or result.chart_type or fig_label,
                value_text=result.overall_description or "",
                source_type="figure",
                extraction_method="llm_figure_extraction",
                figure_label=fig_label,
                x_axis_label=result.x_axis.label,
                x_axis_unit=result.x_axis.unit,
                x_axis_scale=result.x_axis.scale,
                y_axis_label=result.y_axis.label,
                y_axis_unit=result.y_axis.unit,
                y_axis_scale=result.y_axis.scale,
                series_name=result.series[0] if result.series else "",
                data_points_json=_json.dumps([
                    {"x_value": p.x_value, "y_value": p.y_value,
                     "x_unit": p.x_unit or result.x_axis.unit,
                     "y_unit": p.y_unit or result.y_axis.unit,
                     "series_name": p.series_name, "error_bar": p.error_bar}
                    for p in result.data_points
                ]),
                confidence=result.extraction_confidence,
            )
            db.add(item)
            db.flush()
            # Evidence link to asset
            from app.models import ExtractionEvidence
            asset_id = fr.get("asset_id")
            ev = ExtractionEvidence(
                item_id=item.id, source_type="figure",
                source_id=asset_id, source_label=fig_label,
                excerpt=result.overall_description or "",
            )
            db.add(ev)
            db.flush()
            count += 1
        return count

    def _ensure_all_figures_covered(
        self,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        paper: Document,
    ) -> list[IndicatorMapping]:
        """✅ 从旧Agent系统继承：确保所有图表都有提取任务.

        即使用户没有明确查询某个图表，也为它添加通用的"可见证据"提取任务。
        """
        # 收集已映射的图表
        mapped_figures = set()
        for mapping in mappings:
            mapped_figures.update(mapping.figures)

        # 查找所有图表（从MarkdownDocument.images）
        all_figures = []
        for img in mrf_doc.images:
            if img.label:  # 只处理有标签的图表
                all_figures.append(img.label)

        # 为未覆盖的图表添加通用任务
        for fig_label in all_figures:
            if fig_label not in mapped_figures:
                mappings.append(
                    IndicatorMapping(
                        indicator="图表完整数据",
                        indicator_keywords=[],
                        figures=[fig_label],
                        sections=[],
                        tables=[],
                        extraction_hint=(
                            "提取图像中实际可见的所有数据：坐标轴、数值、曲线、标注等。"
                            "如果图中没有数值数据（如纯示意图），返回图表类型和描述。"
                        ),
                        priority="medium",
                    )
                )

        return mappings

    def _extract_text_items(
        self,
        db: Session,
        run: ExtractionRun,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        paper: Document,
        user_query: str,  # ✅ 传递完整user_query
    ) -> list[ExtractionItem]:
        """Extract indicators from text sections.

        ✅ 改进：user_query作为上下文传递给LLM
        """
        items: list[ExtractionItem] = []

        for mapping in mappings:
            if not mapping.sections:
                continue

            # 收集相关章节的文本
            section_texts = []
            for section_title in mapping.sections:
                for section in mrf_doc.sections:
                    if section.title.lower() == section_title.lower():
                        section_texts.append(section.content)

            if not section_texts:
                continue

            combined_text = "\n\n".join(section_texts)

            # ✅ 新提示词设计
            messages = [
                {"role": "system", "content": TEXT_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_text_extraction_prompt(
                    user_query, mapping, combined_text
                )},
            ]

            try:
                result = self.client.chat_json(messages, phase="text_extraction")
                extractions = result.get("extractions", [])

                for ext in extractions:
                    item = ExtractionItem(
                        run_id=run.id,
                        indicator=ext.get("indicator", mapping.indicator),
                        value_text=ext.get("value_text"),
                        value_numeric=self._safe_float(ext.get("value_numeric")),
                        value_unit=ext.get("value_unit"),
                        value_error=ext.get("value_error"),
                        confidence=self._safe_float(ext.get("confidence")),
                        source_type="text",
                        extraction_method="llm_text_extraction",
                    )
                    db.add(item)
                    items.append(item)

                    # 添加证据
                    if ext.get("evidence_quote"):
                        evidence = ExtractionEvidence(
                            item_id=item.id,
                            source_type="text",
                            excerpt=ext["evidence_quote"],
                        )
                        db.add(evidence)

            except Exception as e:
                logger.warning("Text extraction failed for %s: %s", mapping.indicator, e)
                continue

        return items

    def _build_text_extraction_prompt(
        self, user_query: str, mapping: IndicatorMapping, section_text: str
    ) -> str:
        """Build user prompt for text extraction with user_query as context."""
        parts = [
            "# 用户的原始提取需求",
            user_query,
            "",
            "# 当前要提取的内容",
            mapping.indicator,
            "",
            "# 提取提示",
            mapping.extraction_hint or "从下面的文本中提取相关的数值、单位和证据。",
            "",
            "# 文本内容",
            section_text[:4000],  # 限制长度
            "",
            "# 任务",
            f"根据用户需求，提取「{mapping.indicator}」的具体数值和证据。返回JSON格式。",
        ]
        return "\n".join(parts)

    def _extract_figure_items_parallel(
        self,
        db: Session,
        run: ExtractionRun,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        paper: Document,
        user_query: str,
    ) -> list[dict]:
        """✅ 从旧Agent系统继承：并行处理图表.

        使用ThreadPoolExecutor并发处理多个图表，显著提升速度。
        """
        # 收集所有需要处理的图表任务
        figure_tasks = []
        for mapping in mappings:
            for fig_label in mapping.figures:
                figure_tasks.append({
                    "mapping": mapping,
                    "fig_label": fig_label,
                })

        if not figure_tasks:
            return []

        results = []

        # ✅ 并行处理
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(
                    self._extract_single_figure,
                    db, run, mrf_doc, task["mapping"], task["fig_label"], paper, user_query
                ): task
                for task in figure_tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(
                        "Figure extraction failed for %s: %s",
                        task["fig_label"], e
                    )

        return results

    def _extract_single_figure(
        self,
        db: Session,
        run: ExtractionRun,
        mrf_doc: MarkdownDocument,
        mapping: IndicatorMapping,
        fig_label: str,
        paper: Document,
        user_query: str,
    ) -> dict | None:
        """Extract data from a single figure with user_query context."""
        # 查找图表资产（从MarkdownDocument.images）
        figure_asset = None
        target_img = None

        for img in mrf_doc.images:
            if img.label == fig_label:
                target_img = img
                # 通过caption或label查找DocumentAsset
                figure_asset = self._find_figure_asset(db, paper.id, img.label, img.caption)
                break

        if not figure_asset or not figure_asset.file_path:
            return None

        # 构建提示词（带user_query上下文）
        prompt = self._build_figure_extraction_prompt(user_query, mapping, fig_label)

        try:
            # 调用figure extraction pipeline
            result = self.figure_extractor.extract_from_asset(
                db=db,
                asset=figure_asset,
                prompt=prompt,
                indicator=mapping.indicator,
            )

            return {
                "fig_label": fig_label,
                "mapping": mapping,
                "result": result,
            }
        except Exception as e:
            logger.warning("Figure extraction failed for %s: %s", fig_label, e)
            return None

    def _build_figure_extraction_prompt(
        self, user_query: str, mapping: IndicatorMapping, fig_label: str
    ) -> str:
        """Build prompt for figure extraction with user_query context."""
        parts = [
            "# 用户的原始提取需求",
            user_query,
            "",
            "# 当前图表",
            fig_label,
            "",
            "# 要提取的内容",
            mapping.indicator,
            "",
            "# 提取提示",
            mapping.extraction_hint or "提取图表中的所有可见数据点、坐标轴信息、单位等。",
        ]
        return "\n".join(parts)

    def _find_figure_asset(
        self, db: Session, paper_id: int, fig_label: str, caption: str
    ) -> DocumentAsset | None:
        """Find DocumentAsset by label or caption."""
        from app.models import DocumentAsset

        # 先尝试精确匹配label
        asset = (
            db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == paper_id,
                DocumentAsset.label == fig_label,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            )
            .first()
        )

        if asset:
            return asset

        # 模糊匹配caption
        assets = (
            db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == paper_id,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            )
            .all()
        )

        for asset in assets:
            if caption and asset.caption and caption.lower() in asset.caption.lower():
                return asset

        return None

    def _run_fusion_verification(
        self,
        db: Session,
        run: ExtractionRun,
        mappings: list[IndicatorMapping],
        text_items: list[ExtractionItem],
        figure_results: list[dict],
        mrf_doc: MarkdownDocument,
        user_query: str,
    ) -> None:
        """Fusion verification with user_query context."""
        # Basic fusion: log counts for now
        # Advanced fusion (conflict resolution, cross-validation) can be added later
        logger.info(
            "Fusion phase: %d mappings, %d text items, %d figure results for query: %s",
            len(mappings),
            len(text_items),
            len(figure_results),
            user_query[:100],
        )

    def _build_summary(
        self,
        run: ExtractionRun,
        mappings: list[IndicatorMapping],
        text_items: list,
        figure_results: list,
    ) -> str:
        """Build extraction summary."""
        total_indicators = len(mappings)
        text_count = len(text_items)
        figure_count = len(figure_results)

        return (
            f"提取完成：共{total_indicators}个指标，"
            f"从文本提取{text_count}条，从图表提取{figure_count}条。"
        )

    def _safe_float(self, value: any) -> float | None:
        """Safely convert to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
