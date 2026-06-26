"""Structured content extraction pipeline.

Pipeline goals:
- Default to ``auto`` mode.
- Use MRF parsing as base fact store.
- Planner -> evidence retrieval -> source router -> extractors -> fusion.
- Prefer section/table/caption. Call figure extractor only on upgrade conditions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, DocumentAsset, ExtractionRun, ExtractionItem, ExtractionEvidence
from app.services.agent.llm_client import LLMClient
from app.services.content_extraction.caption_extractor import CaptionExtractor
from app.services.content_extraction.figure_extractor import FigureExtractor
from app.services.content_extraction.fusion_engine import FusionEngine
from app.services.content_extraction.models import CandidateEvidence, ExtractionCandidate
from app.services.content_extraction.section_extractor import SectionExtractor
from app.services.content_extraction.table_extractor import TableExtractor
from app.services.extraction.classification_pipeline_v2 import (
    ClassificationPipeline,
    IndicatorMapping,
)
from app.services.extraction.llm_config import build_vlm_config
from app.services.document_search_service import DocumentSearchService
from app.services.markdown_ref_builder import MRFBuilder, MarkdownDocument

from app.services.content_extraction.models import DerivationType

logger = logging.getLogger(__name__)


STATUS_SUFFICIENT = "sufficient"
STATUS_INSUFFICIENT = "insufficient"
STATUS_CONFLICTED = "conflicted"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNRESOLVED = "unresolved"
SUPPORT_SUPPORTED = "supported"
SUPPORT_PARTIAL = "partially_supported"
SUPPORT_UNSUPPORTED = "unsupported"
MODE_ALIAS = {
    "auto": "auto",
    "default": "auto",
    "quick": "auto",
    "standard": "auto",
    "deep": "auto",
}

NUMERIC_PATTERN = re.compile(r"([-+]?(?:\d+\.\d+|\d+)(?:[eE][+-]?\d+)?)")
TOKEN_SEPARATOR = re.compile(r"[,;/，；\s]+")

UNIT_CANONICAL_MAP = {
    "pa*s": "Pa·s",
    "pas": "Pa·s",
    "mpa*s": "mPa·s",
    "pa s": "Pa·s",
    "mpa s": "mPa·s",
    "pa•s": "Pa·s",
    "mpa•s": "mPa·s",
    "pa s^-1": "Pa·s",
    "mpa s^-1": "mPa·s",
    "s^-1": "s⁻¹",
    "s-1": "s⁻¹",
    "min-1": "min⁻¹",
    "h-1": "h⁻¹",
}


@dataclass
class SchemaPlan:
    field_name: str
    entity: str
    required: bool
    priority: str
    allowed_derivation_types: list[DerivationType]
    unit_hints: list[str]
    keywords: list[str]
    mapping: IndicatorMapping
    requires_figure_dependency: bool = False


class ContentExtractionPipeline:
    def __init__(
        self,
        client: LLMClient | None = None,
        visual_client: LLMClient | None = None,
    ) -> None:
        # Content extraction should use the same MaaS/VLM provider as format extraction
        # so text planning, caption extraction, and figure extraction share one model config.
        self.client = client or LLMClient(build_vlm_config())
        self.visual_client = visual_client or LLMClient(build_vlm_config())
        self.mrf_builder = MRFBuilder()
        self.classifier = ClassificationPipeline(self.client)
        self.section_extractor = SectionExtractor(self.client)
        self.table_extractor = TableExtractor(self.client)
        self.caption_extractor = CaptionExtractor(self.client)
        self.figure_extractor = FigureExtractor(self.visual_client)
        self.fusion_engine = FusionEngine(self.client)

    def run(
        self,
        *,
        db: Session,
        paper: Document,
        user_query: str,
        mode: str = "auto",
        progress_callback: Callable[[ExtractionRun, str, str], None] | None = None,
    ) -> ExtractionRun:
        normalized_mode = MODE_ALIAS.get(mode.lower(), "auto")
        if normalized_mode not in {"auto"}:
            normalized_mode = "auto"

        markdown_text = paper.cleaned_text or paper.parsed_text or ""
        if not markdown_text.strip():
            raise ValueError("Paper has no parsed text. Run MinerU parse first.")

        run = ExtractionRun(
            paper_id=paper.id,
            user_query=user_query,
            status="classifying",
            phase="classifying",
        )
        db.add(run)
        db.flush()

        def set_progress(phase: str, status: str, message: str) -> None:
            run.phase = phase
            run.status = status
            db.flush()
            if progress_callback is not None:
                progress_callback(run, phase, message)

        errors: list[str] = []
        failed_phases: list[str] = []

        try:
            set_progress("classifying", "classifying", "正在用 LLM 规划内容提取指标")
            mrf_doc = self.mrf_builder.build(markdown_text)
            mapping_scope = self._extractor_scope_maps(mrf_doc)

            mappings = self.classifier.classify(mrf_doc, user_query)
            if not mappings:
                mappings = self._fallback_classification_from_query(user_query)

            plans = self._build_schema_plans(mappings, mrf_doc)
            plan_lookup = {self._norm(plan.field_name): plan for plan in plans}

            run.classification_json = json.dumps(
                [
                    {
                        "field_name": plan.field_name,
                        "entity": plan.entity,
                        "required": plan.required,
                        "priority": plan.priority,
                        "unit_hints": plan.unit_hints,
                        "allowed_derivation_types": plan.allowed_derivation_types,
                        "source_sections": plan.mapping.sections,
                        "source_tables": plan.mapping.tables,
                        "source_figures": plan.mapping.figures,
                    }
                    for plan in plans
                ],
                ensure_ascii=False,
            )
            db.flush()

            set_progress("routing", "routing", "正在检索正文、图注和表格证据")
            retrieval_by_plan = self._retrieve_evidence(
                plans=plans,
                mrf_doc=mrf_doc,
                mode=normalized_mode,
                strict=True,
                db=db,
                paper=paper,
            )
            run.routing_json = json.dumps(
                {
                    "mode": normalized_mode,
                    "initial": retrieval_by_plan,
                    "upgrades": {},
                },
                ensure_ascii=False,
            )
            db.flush()

            set_progress("extracting_sections", "extracting_sections", "正在调用 LLM 提取正文、图注和表格内容")
            first_candidates = self._extract_by_router(
                db=db,
                run=run,
                mrf_doc=mrf_doc,
                mappings=mappings,
                plans=plans,
                retrieval_by_plan=retrieval_by_plan,
                mapping_lookup=plan_lookup,
                user_query=user_query,
                include_figures=False,
                errors=errors,
                failed_phases=failed_phases,
                mapping_scope=mapping_scope,
            )
            first_candidates = self._normalize_candidates(first_candidates)
            validated_first = self._validate_candidates(first_candidates, plan_lookup)

            needs_figure, needs_second_retrieval = self._check_upgrade_needs(
                validated_first,
                plans,
                retrieval_by_plan,
            )

            figure_candidates: list[ExtractionCandidate] = []
            second_pass_candidates: list[ExtractionCandidate] = []

            if needs_figure:
                set_progress("extracting_figures", "extracting_figures", "正在调用视觉 LLM 提取图表内容")
                figure_retrieval = self._retrieve_evidence(
                    plans=plans,
                    mrf_doc=mrf_doc,
                    mode=normalized_mode,
                    strict=False,
                    db=db,
                    paper=paper,
                )
                figure_candidates = self._extract_by_router(
                    db=db,
                    run=run,
                    mrf_doc=mrf_doc,
                    mappings=mappings,
                    plans=plans,
                    retrieval_by_plan=figure_retrieval,
                    mapping_lookup=plan_lookup,
                    user_query=user_query,
                    include_figures=True,
                    errors=errors,
                    failed_phases=failed_phases,
                    mapping_scope=mapping_scope,
                )
                figure_candidates = self._normalize_candidates(figure_candidates)
                figure_candidates = self._validate_candidates(figure_candidates, plan_lookup)
                if figure_retrieval:
                    # only update routing summary for upgrade
                    current_routing = json.loads(run.routing_json or "{}")
                    current_routing["upgrades"] = {"figure_upgrade": figure_retrieval}
                    run.routing_json = json.dumps(current_routing, ensure_ascii=False)

            if needs_second_retrieval:
                set_progress("extracting_text", "extracting_text_rerun", "正在补充检索并复查遗漏内容")
                second_retrieval = self._retrieve_evidence(
                    plans=plans,
                    mrf_doc=mrf_doc,
                    mode=normalized_mode,
                    strict=False,
                    db=db,
                    paper=paper,
                )
                second_pass_candidates = self._extract_by_router(
                    db=db,
                    run=run,
                    mrf_doc=mrf_doc,
                    mappings=mappings,
                    plans=plans,
                    retrieval_by_plan=second_retrieval,
                    mapping_lookup=plan_lookup,
                    user_query=user_query,
                    include_figures=False,
                    errors=errors,
                    failed_phases=failed_phases,
                    mapping_scope=mapping_scope,
                )
                second_pass_candidates = self._normalize_candidates(second_pass_candidates)
                second_pass_candidates = self._validate_candidates(
                    second_pass_candidates, plan_lookup
                )
                if second_retrieval:
                    current_routing = json.loads(run.routing_json or "{}")
                    current_routing["upgrades"]["rerun_retrieval"] = second_retrieval
                    run.routing_json = json.dumps(current_routing, ensure_ascii=False)

            set_progress("fusing", "fusing", "正在融合多来源结果并复核冲突")

            all_candidates = self._dedupe_candidates(
                [*validated_first, *figure_candidates, *second_pass_candidates]
            )
            candidates_by_source = self._group_candidates_by_source(all_candidates)

            fused_candidates = self.fusion_engine.merge(
                candidates_by_source, user_query=user_query
            )
            if not isinstance(fused_candidates, list):
                fused_candidates = []
            fused_candidates = self._validate_candidates(fused_candidates, plan_lookup)

            final_candidates = self._filter_final_candidates(fused_candidates)

            for cand in final_candidates:
                self._write_item(db, run_id=run.id, candidate=cand, mrf_doc=mrf_doc)

            status_summary = self._build_status_summary(validated_first, final_candidates)
            run.summary = json.dumps(status_summary, ensure_ascii=False)
            current_routing = json.loads(run.routing_json or "{}")
            current_routing["status_summary"] = status_summary
            run.routing_json = json.dumps(current_routing, ensure_ascii=False)

            run.completed_at = app_now()
            set_progress("done", "done", "内容提取完成")

        except Exception as exc:
            logger.exception("Content extraction run %s failed", run.id)
            run.status = "failed"
            run.error_message = str(exc)
            run.error_phase = run.phase
            if errors:
                run.error_message = f"{run.error_message} | errors={errors}"
            if failed_phases:
                run.error_message = f"{run.error_message} | failed_phases={failed_phases}"
            db.flush()
            if progress_callback is not None:
                progress_callback(run, "failed", run.error_message or "内容提取失败")

        return run

    def _fallback_classification_from_query(self, user_query: str) -> list[IndicatorMapping]:
        query = user_query.strip()
        if not query:
            return []
        names = [item.strip() for item in TOKEN_SEPARATOR.split(query) if item.strip()]
        if not names:
            names = [query]
        return [
            IndicatorMapping(
                indicator=name,
                indicator_keywords=_extract_keywords_from_text(name),
                figures=[],
                sections=[],
                tables=[],
                extraction_hint=name,
                priority="high",
            )
            for name in names
        ]

    def _build_schema_plans(
        self,
        mappings: list[IndicatorMapping],
        mrf_doc: MarkdownDocument,
    ) -> list[SchemaPlan]:
        plans: list[SchemaPlan] = []
        for mapping in mappings:
            key_terms = set(_extract_keywords_from_text(mapping.indicator))
            key_terms.update(_extract_keywords_from_text(" ".join(mapping.indicator_keywords)))
            unit_hints = []
            for kw in key_terms:
                if any(unit in kw.lower() for unit in ("pa", "pa.s", "mpa", "mpa.s", "pa·s", "mpa·s", "s-1", "s⁻¹", "hz", "°c", "degc")):
                    unit_hints.append(_normalize_unit(kw))

            priority = mapping.priority.lower().strip() if mapping.priority else "medium"
            if priority not in {"high", "medium", "low"}:
                priority = "medium"

            requires_figure_dependency = any(
                token in mapping.indicator.lower()
                for token in ("figure", "图", "曲线", "图形", "chart", "曲线图", "柱状图")
            )
            plans.append(
                SchemaPlan(
                    field_name=self._normalize_field_name(mapping.indicator),
                    entity=mapping.indicator.strip(),
                    required=priority == "high",
                    priority=priority,
                    allowed_derivation_types=["extractive", "normalized", "computed"],
                    unit_hints=[u for u in unit_hints if u],
                    keywords=list(sorted(key_terms)),
                    mapping=mapping,
                    requires_figure_dependency=requires_figure_dependency,
                )
            )

        # Ensure deterministic and unique by field name
        seen: set[str] = set()
        result: list[SchemaPlan] = []
        for plan in plans:
            key = self._norm(plan.field_name)
            if key in seen:
                continue
            seen.add(key)
            result.append(plan)
        return result

    def _extractor_scope_maps(self, mrf_doc: MarkdownDocument) -> dict[str, dict[str, Any]]:
        section_map: dict[str, Any] = {sec.heading: sec for sec in mrf_doc.sections}
        table_map: dict[str, Any] = {tbl.label: tbl for tbl in mrf_doc.tables if tbl.label}
        image_map: dict[str, Any] = {img.label: img for img in mrf_doc.images if img.label}
        section_map_norm = {self._norm(sec.heading): sec for sec in mrf_doc.sections}
        table_map_norm = {self._norm(tbl.label): tbl for tbl in mrf_doc.tables if tbl.label}
        image_map_norm = {self._norm(img.label): img for img in mrf_doc.images if img.label}
        return {
            "section_map": section_map,
            "table_map": table_map,
            "image_map": image_map,
            "section_map_norm": section_map_norm,
            "table_map_norm": table_map_norm,
            "image_map_norm": image_map_norm,
        }

    def _retrieve_evidence(
        self,
        *,
        plans: list[SchemaPlan],
        mrf_doc: MarkdownDocument,
        mode: str,
        strict: bool,
        db: Session | None = None,
        paper: Document | None = None,
    ) -> dict[str, dict[str, list[str]]]:
        result: dict[str, dict[str, list[str]]] = {}
        semantic_by_field: dict[str, dict[str, list[str]]] = {}
        if not strict and db is not None and paper is not None:
            semantic_by_field = self._retrieve_by_semantic(
                db=db,
                paper=paper,
                plans=plans,
                mrf_doc=mrf_doc,
            )
        paper_figure_labels = self._paper_figure_asset_labels(db, paper.id) if db is not None and paper is not None else []

        for plan in plans:
            keywords = plan.keywords or [plan.field_name]
            section_candidates: list[str] = []
            table_candidates: list[str] = []
            caption_candidates: list[str] = []
            figure_candidates: list[str] = []

            # Priority: classifier structural hints first
            section_candidates.extend(plan.mapping.sections)
            table_candidates.extend(plan.mapping.tables)
            figure_candidates.extend(plan.mapping.figures)
            if not section_candidates and not strict:
                for section in mrf_doc.sections:
                    if _contains_keywords(section.body, keywords) or _contains_keywords(
                        section.heading, keywords
                    ):
                        section_candidates.append(section.heading)

            if not table_candidates and not strict:
                for table in mrf_doc.tables:
                    haystack = " ".join(
                        [table.caption or "", " ".join(table.headers), " ".join(" ".join(row) for row in table.rows)]
                    )
                    if _contains_keywords(haystack, keywords):
                        if table.label:
                            table_candidates.append(table.label)

            if not figure_candidates and not strict:
                for image in mrf_doc.images:
                    if _contains_keywords(image.caption or "", keywords):
                        if image.label:
                            figure_candidates.append(image.label)

            if not figure_candidates and plan.requires_figure_dependency and mrf_doc.images:
                # if dependency is explicitly figure-related, keep at least one candidate
                for image in mrf_doc.images[:2]:
                    if image.label:
                        figure_candidates.append(image.label)
            if not strict and not figure_candidates and plan.requires_figure_dependency and paper_figure_labels:
                figure_candidates.extend(paper_figure_labels)

            # Embedding/semantic branch: structured fallback and chunk-level hints
            if not strict:
                hits = semantic_by_field.get(plan.field_name, {})
                for sec in hits.get("sections", []):
                    section_candidates.append(sec)
                for tbl in hits.get("tables", []):
                    table_candidates.append(tbl)
                for fig in hits.get("figures", []):
                    figure_candidates.append(fig)
                for cap in hits.get("captions", []):
                    caption_candidates.append(cap)

                if not section_candidates and mrf_doc.sections:
                    section_candidates.extend(sec.heading for sec in mrf_doc.sections[:2])
                if not table_candidates and mrf_doc.tables:
                    for table in mrf_doc.tables:
                        if table.label:
                            table_candidates.append(table.label)
                            break

            deduped = {
                "sections": self._dedupe(section_candidates),
                "tables": self._dedupe(table_candidates),
                "captions": self._dedupe([s for s in caption_candidates]),
                "figures": self._dedupe(figure_candidates),
            }
            # remove unsupported empty source labels
            if not any(deduped[k] for k in deduped):
                # keep at least one nearest hit from doc index if schema is required
                if mrf_doc.sections:
                    deduped["sections"] = [mrf_doc.sections[0].heading]
            result[plan.field_name] = deduped

        return result

    def _paper_figure_asset_labels(self, db: Session, paper_id: int) -> list[str]:
        assets = (
            db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == paper_id,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
                DocumentAsset.file_path.isnot(None),
            )
            .order_by(DocumentAsset.asset_index.asc().nullslast(), DocumentAsset.id.asc())
            .all()
        )
        labels: list[str] = []
        for asset in assets:
            label = asset.label or f"Asset {asset.id}"
            if label:
                labels.append(label)
        return self._dedupe(labels)

    def _retrieve_by_semantic(
        self,
        db: Session,
        paper: Document,
        plans: list[SchemaPlan],
        mrf_doc: MarkdownDocument,
    ) -> dict[str, dict[str, list[str]]]:
        hits = {}
        if not paper.user_id:
            return hits

        search = DocumentSearchService(db)
        known_sections = {self._norm(section.heading): section.heading for section in mrf_doc.sections}
        known_tables = {self._norm(table.label or ""): table.label for table in mrf_doc.tables if table.label}
        known_figures = {self._norm(img.label or ""): img.label for img in mrf_doc.images if img.label}

        for plan in plans:
            query = " ".join(filter(None, [plan.field_name, plan.entity, *plan.keywords]))
            chunks = search.search_chunks(
                user_id=paper.user_id,
                query=query[:500],
                document_id=paper.id,
                limit=10,
            )
            plan_hits = {"sections": [], "tables": [], "captions": [], "figures": []}
            if not chunks:
                hits[plan.field_name] = plan_hits
                continue

            for hit in chunks:
                source_raw = hit.get("source") or {}
                source = source_raw if isinstance(source_raw, dict) else {}
                chunk_type = str(hit.get("chunk_type") or "").lower()
                metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
                metadata = {
                    key: str(value)
                    for key, value in metadata.items()
                } if isinstance(metadata, dict) else {}
                label = _first_nonempty(
                    metadata.get("label"),
                    metadata.get("table_label"),
                    metadata.get("figure_label"),
                    metadata.get("caption_label"),
                    source.get("label"),
                    source.get("name"),
                    source.get("source"),
                    source.get("type"),
                    metadata.get("title"),
                    metadata.get("id"),
                )
                section_hint = _first_nonempty(
                    metadata.get("section"),
                    metadata.get("section_heading"),
                    metadata.get("section_title"),
                    metadata.get("title"),
                )
                if label:
                    norm_label = self._norm(label)
                    if chunk_type in {"table", "table_asset"} and norm_label in known_tables:
                        plan_hits["tables"].append(known_tables[norm_label])
                    if chunk_type in {"figure", "image", "visual", "diagram"} and norm_label in known_figures:
                        plan_hits["figures"].append(known_figures[norm_label])
                    if chunk_type in {"caption", "figcaption"}:
                        section_hint = known_sections.get(self._norm(section_hint), section_hint)
                        plan_hits["captions"].append(label)
                if section_hint and self._norm(section_hint) in known_sections:
                    plan_hits["sections"].append(
                        known_sections[self._norm(section_hint)]
                    )
                if chunk_type in {"body", "text", "paragraph"}:
                    text = str(hit.get("text") or "")
                    if section_hint and self._norm(section_hint) in known_sections:
                        plan_hits["sections"].append(known_sections[self._norm(section_hint)])
                    elif _contains_keywords(text, query):
                        fallback_section = self._pick_section_hint(metadata, known_sections)
                        if fallback_section:
                            plan_hits["sections"].append(fallback_section)

            hits[plan.field_name] = {
                key: self._dedupe(values) for key, values in plan_hits.items()
            }
        return hits

    @staticmethod
    def _pick_section_hint(metadata: dict[str, str], known_sections: dict[str, str]) -> str:
        for candidate in (
            metadata.get("section_title"),
            metadata.get("section_heading"),
            metadata.get("section_name"),
            metadata.get("heading"),
            metadata.get("heading_text"),
            metadata.get("source"),
        ):
            if not candidate:
                continue
            normalized = re.sub(r"\s+", "", str(candidate).strip().lower())
            if normalized in known_sections:
                return known_sections[normalized]
        return ""

    def _extract_by_router(
        self,
        *,
        db: Session,
        run: ExtractionRun,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        plans: list[SchemaPlan],
        retrieval_by_plan: dict[str, dict[str, list[str]]],
        mapping_lookup: dict[str, SchemaPlan],
        user_query: str,
        include_figures: bool,
        errors: list[str] | None = None,
        failed_phases: list[str] | None = None,
        mapping_scope: dict[str, dict[str, Any]],
    ) -> list[ExtractionCandidate]:
        all_candidates: list[ExtractionCandidate] = []
        plan_map = {self._norm(plan.field_name): plan for plan in plans}

        scoped_sections: list[IndicatorMapping] = []
        scoped_tables: list[IndicatorMapping] = []
        scoped_captions: list[IndicatorMapping] = []
        scoped_figures: list[IndicatorMapping] = []

        for mapping in mappings:
            plan = plan_map.get(self._norm(mapping.indicator)) or next(
                (
                    plan
                    for plan in plans
                    if _contains_keywords(mapping.indicator, [plan.field_name, plan.entity])
                ),
                None,
            )
            if plan is None:
                continue

            route = retrieval_by_plan.get(plan.field_name) or {}

            if route.get("sections"):
                scoped_sections.append(
                    _replace_sources(mapping, sections=_scope_list(route.get("sections")))
                )
            if route.get("tables"):
                scoped_tables.append(
                    _replace_sources(mapping, tables=_scope_list(route.get("tables")))
                )
            if route.get("captions") or route.get("figures"):
                scoped_captions.append(
                    _replace_sources(mapping, figures=_scope_list(route.get("figures")))
                )
            if include_figures and route.get("figures"):
                scoped_figures.append(
                    _replace_sources(mapping, figures=_scope_list(route.get("figures")))
                )

        if scoped_sections:
            records = self._safe_extract(
                "section",
                lambda: self.section_extractor.extract(mrf_doc, scoped_sections, user_query),
                errors or [],
                failed_phases or [],
            )
            all_candidates.extend(
                self._to_candidates(
                    records=records,
                    mapping_lookup=plan_map,
                    mrf_doc=mrf_doc,
                    mapping_scope=mapping_scope,
                )
            )

        if scoped_tables:
            records = self._safe_extract(
                "table",
                lambda: self.table_extractor.extract(mrf_doc, scoped_tables, user_query),
                errors or [],
                failed_phases or [],
            )
            all_candidates.extend(
                self._to_candidates(
                    records=records,
                    mapping_lookup=plan_map,
                    mrf_doc=mrf_doc,
                    mapping_scope=mapping_scope,
                )
            )

        if scoped_captions:
            records = self._safe_extract(
                "caption",
                lambda: self.caption_extractor.extract(mrf_doc, scoped_captions, user_query),
                errors or [],
                failed_phases or [],
            )
            all_candidates.extend(
                self._to_candidates(
                    records=records,
                    mapping_lookup=plan_map,
                    mrf_doc=mrf_doc,
                    mapping_scope=mapping_scope,
                )
            )

        if include_figures and scoped_figures:
            assets = self._get_paper_assets(db, run.paper_id)
            records = self._safe_extract(
                "figure",
                lambda: self.figure_extractor.extract(
                    mrf_doc, scoped_figures, assets, db, user_query
                ),
                errors or [],
                failed_phases or [],
            )
            all_candidates.extend(
                self._to_candidates(
                    records=records,
                    mapping_lookup=plan_map,
                    mrf_doc=mrf_doc,
                    mapping_scope=mapping_scope,
                )
            )

        return all_candidates

    def _normalize_candidates(self, candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
        normalized: list[ExtractionCandidate] = []
        for cand in candidates:
            cand.field_name = self._normalize_field_name(cand.field_name)
            cand.entity = self._normalize_entity(cand.entity)
            cand.unit = _normalize_unit(cand.unit or "")
            cand.value = (cand.value or "").strip()
            if cand.unit and cand.value and not any(
                cand.value.lower().endswith(u.lower()) for u in (cand.unit, cand.unit.replace("·", " "))
            ):
                cand.normalized_value = _parse_numeric(cand.value)
            else:
                cand.normalized_value = _parse_numeric(cand.value)
            if cand.derivation_type == "computed":
                pass
            elif cand.normalized_value is not None and cand.unit:
                cand.derivation_type = "normalized"
            else:
                cand.derivation_type = "extractive"
            normalized.append(cand)
        return normalized

    def _validate_candidates(
        self,
        candidates: list[ExtractionCandidate],
        plan_lookup: dict[str, SchemaPlan],
    ) -> list[ExtractionCandidate]:
        validated: list[ExtractionCandidate] = []
        for cand in candidates:
            plan = plan_lookup.get(self._norm(cand.field_name))
            if not plan:
                cand.status = STATUS_UNSUPPORTED
                cand.confidence = 0.0
                cand.write_to_final = False
                cand.verification_notes = "no_schema_plan"
                validated.append(cand)
                continue

            if cand.derivation_type not in plan.allowed_derivation_types:
                cand.write_to_final = False
                if cand.derivation_type == "inferred":
                    cand.verification_notes = "hypothesis_not_allowed_by_plan"
                else:
                    cand.verification_notes = "derivation_type_not_allowed"
                cand.status = STATUS_UNSUPPORTED
                cand.support_reason = SUPPORT_UNSUPPORTED
                validated.append(cand)
                continue

            if not cand.value.strip():
                cand.status = STATUS_UNSUPPORTED
                cand.confidence = 0.0
                cand.support_reason = SUPPORT_UNSUPPORTED
                cand.verification_notes = "empty_value"
                cand.write_to_final = False
                validated.append(cand)
                continue

            evidence_text = (cand.quote or "").strip()
            has_evidence_span = bool(evidence_text or cand.cell_range or cand.bbox)
            if not has_evidence_span:
                cand.status = STATUS_UNSUPPORTED
                cand.support_reason = SUPPORT_UNSUPPORTED
                cand.verification_notes = "missing_quote"
                cand.write_to_final = False
                cand.confidence = 0.0
                validated.append(cand)
                continue

            evidence_score = 0.0
            if len(evidence_text) >= 20:
                evidence_score += 0.45
            if _contains_keywords(evidence_text, [plan.field_name, plan.entity]):
                evidence_score += 0.15
            if plan.keywords and _contains_keywords(evidence_text, plan.keywords):
                evidence_score += 0.2
            if cand.unit:
                if not plan.unit_hints or any(_norm(cand.unit).endswith(_norm(u)) for u in plan.unit_hints):
                    evidence_score += 0.1
            if cand.derivation_type == "computed":
                evidence_score -= 0.2

            cand.supporting_evidence = [cand.evidence_id] if cand.evidence_id else []
            if evidence_score >= 0.5 or cand.confidence >= 0.5:
                cand.status = STATUS_SUFFICIENT
                cand.support_reason = SUPPORT_SUPPORTED
                cand.verification_notes = "supported"
                cand.confidence = min(1.0, cand.confidence * 1.05)
            elif evidence_score >= 0.5 and cand.confidence >= 0.35:
                cand.status = STATUS_INSUFFICIENT
                # do not pass insufficient as final until fusion confirms consistency
                cand.support_reason = SUPPORT_PARTIAL
                cand.verification_notes = "partially_supported"
                cand.confidence *= 0.75
            elif evidence_score >= 0.3:
                cand.status = STATUS_INSUFFICIENT
                cand.support_reason = SUPPORT_PARTIAL
                cand.verification_notes = "partially_supported"
                cand.confidence *= 0.6
            else:
                cand.status = STATUS_UNSUPPORTED
                cand.confidence = 0.0
                cand.write_to_final = False
                cand.support_reason = SUPPORT_UNSUPPORTED
                cand.verification_notes = "unsupported"
            validated.append(cand)
        return validated

    def _check_upgrade_needs(
        self,
        candidates: list[ExtractionCandidate],
        plans: list[SchemaPlan],
        retrieval_by_plan: dict[str, dict[str, list[str]]],
    ) -> tuple[bool, bool]:
        plan_by_field = {self._norm(plan.field_name): plan for plan in plans}
        groups: dict[str, list[ExtractionCandidate]] = {}
        for cand in candidates:
            groups.setdefault(self._norm(cand.field_name), []).append(cand)

        requires_figure = False
        requires_retrieval = False
        for plan in plans:
            group = groups.get(self._norm(plan.field_name), [])
            if not group:
                # candidate missing in initial pass
                if plan.required:
                    requires_retrieval = True
                if plan.requires_figure_dependency:
                    requires_figure = True
                continue

            best = sorted(group, key=lambda item: item.confidence, reverse=True)[0]
            # partial or low score required field -> escalate
            if best.status == STATUS_UNSUPPORTED or best.support_reason == SUPPORT_UNSUPPORTED:
                requires_retrieval = True
            if best.status == STATUS_INSUFFICIENT:
                if plan.required:
                    requires_retrieval = True
                elif best.support_reason == SUPPORT_PARTIAL:
                    requires_retrieval = requires_retrieval or best.confidence < 0.4
                else:
                    requires_retrieval = requires_retrieval or (best.confidence >= 0.3 and best.confidence < 0.35)
            if best.support_reason == SUPPORT_PARTIAL:
                requires_retrieval = True
            if best.confidence < 0.45:
                requires_retrieval = True
            normalized_unit_hints = {_norm(unit) for unit in plan.unit_hints}
            if normalized_unit_hints and any(
                _norm(g.unit or "") and _norm(g.unit or "") not in normalized_unit_hints for g in group
            ):
                requires_retrieval = True

            unique_vals = {self._value_cluster_signature(g) for g in group if g.status != STATUS_UNSUPPORTED}
            if len(unique_vals) > 1:
                requires_retrieval = True
                requires_figure = requires_figure or any(rec.source_type == "figure" for rec in group)
            if self._has_unit_ambiguity(group):
                requires_retrieval = True
            if any(g.status == STATUS_INSUFFICIENT for g in group):
                if best.confidence < 0.5:
                    requires_retrieval = True
            if plan.requires_figure_dependency and any(g.source_type == "caption" for g in group):
                requires_figure = True
            if (
                any(g.source_type == "caption" for g in group)
                and not any(g.source_type == "figure" for g in group)
                and _contains_keywords("".join(g.quote or "" for g in group), ["figure", "图"])
            ):
                requires_figure = True

        if not requires_figure:
            for field, scope in retrieval_by_plan.items():
                plan = plan_by_field.get(self._norm(field))
                if plan and plan.requires_figure_dependency and not scope.get("figures"):
                    requires_figure = True
                    break

        return requires_figure, requires_retrieval

    @staticmethod
    def _has_unit_ambiguity(candidates: list[ExtractionCandidate]) -> bool:
        normalized_units = {
            _normalize_unit((cand.unit or "").strip()) for cand in candidates if cand.unit
        }
        return len(normalized_units) > 1

    def _to_candidates(
        self,
        records: list[Any],
        *,
        mapping_lookup: dict[str, SchemaPlan],
        mrf_doc: MarkdownDocument,
        mapping_scope: dict[str, dict[str, Any]],
    ) -> list[ExtractionCandidate]:
        from app.services.content_extraction.models import PropertyRecord

        candidates: list[ExtractionCandidate] = []
        for rec in records:
            if not isinstance(rec, PropertyRecord):
                continue
            raw_field = rec.property_name or rec.entity
            plan = mapping_lookup.get(self._norm(raw_field))
            if plan is None:
                plan = mapping_lookup.get(self._norm(rec.entity)) or mapping_lookup.get(self._norm(rec.value_text))
            if plan is None:
                # fallback: use record content as schema
                plan = SchemaPlan(
                    field_name=raw_field or "unknown",
                    entity=rec.entity,
                    required=False,
                    priority="low",
                    allowed_derivation_types=["extractive", "normalized", "computed"],
                    unit_hints=[],
                    keywords=_extract_keywords_from_text(raw_field),
                    mapping=IndicatorMapping(
                        indicator=raw_field or rec.entity,
                        indicator_keywords=_extract_keywords_from_text(raw_field),
                    ),
                )

            evidence = self._build_candidate_evidence(
                source_type=rec.source_type,
                source_ref=rec.source_ref,
                record=rec,
                mapping_scope=mapping_scope,
            )
            evidence.evidence_role = "supporting"

            value = rec.value_text or (str(rec.value_numeric) if rec.value_numeric is not None else "")
            unit = _normalize_unit(rec.value_unit or "")
            normalized_value = rec.value_numeric if rec.value_numeric is not None else _parse_numeric(value)
            derivation_type: DerivationType = "extractive"
            if rec.method and "compute" in rec.method.lower():
                derivation_type = "computed"

            evidence_id = self._build_evidence_id(rec.source_type, rec.source_ref, value, plan.field_name)
            evidence.evidence_id = evidence_id
            quote = rec.evidence_excerpt or evidence.quote or ""

            candidates.append(
                ExtractionCandidate(
                    field_name=plan.field_name,
                    entity=plan.entity,
                    value=value,
                    unit=unit,
                    normalized_value=normalized_value,
                    source_type=rec.source_type,
                    mrf_node_id=rec.source_mrf_node_id or evidence.mrf_node_id or "",
                    evidence_id=evidence_id,
                    quote=quote,
                    cell_range=evidence.cell_range,
                    bbox=evidence.bbox,
                    derivation_type=derivation_type,
                    confidence=float(rec.confidence),
                    source_ref=rec.source_ref,
                    property_category=rec.property_category,
                    condition=rec.condition,
                    method=rec.method,
                    status=STATUS_INSUFFICIENT,
                    evidence=evidence,
                    support_reason="not_validated",
                    supporting_evidence=[evidence_id] if evidence_id else [],
                    write_to_final=True,
                )
            )
        return candidates

    def _build_candidate_evidence(
        self,
        *,
        source_type: str,
        source_ref: str,
        record: PropertyRecord | None = None,
        mapping_scope: dict[str, dict[str, Any]],
    ) -> CandidateEvidence:
        source_label = (source_ref or "").strip()
        source_label_norm = self._norm(source_label)
        section_map = mapping_scope.get("section_map", {})
        table_map = mapping_scope.get("table_map", {})
        image_map = mapping_scope.get("image_map", {})
        section_map_norm = mapping_scope.get("section_map_norm", {})
        table_map_norm = mapping_scope.get("table_map_norm", {})
        image_map_norm = mapping_scope.get("image_map_norm", {})
        section = section_map.get(source_label) or section_map_norm.get(source_label_norm)
        table = table_map.get(source_label) or table_map_norm.get(source_label_norm)
        image = image_map.get(source_label) or image_map_norm.get(source_label_norm)
        char_span = getattr(record, "source_char_span", None) if record else None
        cell_range = getattr(record, "source_cell_range", None) if record else None
        bbox = getattr(record, "source_bbox", None) if record else None

        if source_type == "section":
            section_id = self._norm(section.heading) if section else source_label_norm
            return CandidateEvidence(
                source_type="section",
                mrf_node_id=(record.source_mrf_node_id if record else None) or f"section:{section.heading if section else source_label}",
                page=None,
                section_id=section_id,
                table_id=None,
                figure_id=None,
                caption_id=None,
                char_span=char_span,
                cell_range=cell_range,
                bbox=bbox,
                quote=(record.evidence_excerpt if record else ""),
                evidence_role="supporting",
                evidence_id="",
                payload=getattr(record, "evidence_payload", None),
            )
        if source_type == "table":
            if not table and record and record.source_cell_range:
                table = table_map.get(record.source_ref) or table_map_norm.get(source_label_norm)
            return CandidateEvidence(
                source_type="table",
                mrf_node_id=(record.source_mrf_node_id if record else None) or f"table:{table.label if table else source_label}",
                page=table.page_number if table else None,
                section_id=None,
                table_id=f"table:{self._norm(source_label)}",
                figure_id=None,
                caption_id=None,
                char_span=char_span,
                cell_range=cell_range or (getattr(record, "source_cell_range", None) if record else None),
                bbox=bbox,
                quote=(record.evidence_excerpt if record else ""),
                evidence_role="supporting",
                evidence_id="",
                payload=getattr(record, "evidence_payload", None),
            )
        if source_type in {"caption", "figure"}:
            return CandidateEvidence(
                source_type=source_type,
                mrf_node_id=(record.source_mrf_node_id if record else None) or f"{source_type}:{image.label if image else source_label}",
                page=image.page_number if image else None,
                section_id=self._norm(image.section_heading) if image else None,
                table_id=None,
                figure_id=f"figure:{self._norm(source_label)}" if source_type == "figure" else None,
                caption_id=f"caption:{self._norm(source_label)}",
                char_span=char_span,
                cell_range=cell_range,
                bbox=bbox,
                quote=(record.evidence_excerpt if record else ""),
                evidence_role="supporting",
                evidence_id="",
                payload=getattr(record, "evidence_payload", None),
            )

        return CandidateEvidence(
            source_type="unknown",
            mrf_node_id="",
            page=None,
            section_id=None,
            table_id=None,
            figure_id=None,
            caption_id=None,
            char_span=None,
            cell_range=None,
            bbox=None,
            quote=(record.evidence_excerpt if record else ""),
            evidence_role="supporting",
            evidence_id="",
            payload=getattr(record, "evidence_payload", None),
        )

    def _dedupe_candidates(self, candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
        dedupe_keys: set[tuple[str, str, str, str]] = set()
        output: list[ExtractionCandidate] = []
        for cand in candidates:
            value_sig = self._value_signature(cand)
            key = (self._norm(cand.field_name), self._norm(cand.entity), self._norm(cand.source_type), value_sig)
            if key in dedupe_keys:
                continue
            dedupe_keys.add(key)
            output.append(cand)
        return output

    def _group_candidates_by_source(
        self,
        candidates: list[ExtractionCandidate],
    ) -> dict[str, list[ExtractionCandidate]]:
        grouped: dict[str, list[ExtractionCandidate]] = {"section": [], "table": [], "caption": [], "figure": [], "fusion": []}
        for cand in candidates:
            grouped.setdefault(cand.source_type, []).append(cand)
        return grouped

    def _filter_final_candidates(
        self,
        candidates: list[ExtractionCandidate],
    ) -> list[ExtractionCandidate]:
        final: list[ExtractionCandidate] = []
        for cand in candidates:
            if getattr(cand, "status", STATUS_UNSUPPORTED) == STATUS_UNSUPPORTED:
                continue
            if not cand.write_to_final:
                continue
            if cand.derivation_type == "inferred":
                cand.write_to_final = False
                cand.fusion_decision = "hypothesis_only"
                cand.verification_notes = (cand.verification_notes or "") + "|inferred_not_written"
                continue
            if cand.status in {STATUS_SUFFICIENT, STATUS_CONFLICTED, STATUS_INSUFFICIENT}:
                if cand.status == STATUS_INSUFFICIENT and (
                    "written_as_insufficient" not in (cand.verification_notes or "")
                ):
                    cand.verification_notes = (
                        (cand.verification_notes or "partially_supported") + "|written_as_insufficient"
                    )
                final.append(cand)
        return final

    def _build_status_summary(
        self,
        first_pass: list[ExtractionCandidate],
        final: list[ExtractionCandidate],
    ) -> dict[str, Any]:
        status_count = {
            STATUS_SUFFICIENT: 0,
            STATUS_CONFLICTED: 0,
            STATUS_INSUFFICIENT: 0,
            STATUS_UNSUPPORTED: 0,
            STATUS_UNRESOLVED: 0,
        }
        for cand in first_pass:
            status_count[cand.status] = status_count.get(cand.status, 0) + 1

        final_status_count = {
            STATUS_SUFFICIENT: 0,
            STATUS_CONFLICTED: 0,
            STATUS_INSUFFICIENT: 0,
            STATUS_UNSUPPORTED: 0,
            STATUS_UNRESOLVED: 0,
        }
        for cand in final:
            final_status_count[cand.status] = final_status_count.get(cand.status, 0) + 1

        return {
            "first_pass_total": len(first_pass),
            "first_pass_status": status_count,
            "final_written": len(final),
            "final_status": final_status_count,
        }

    def _safe_extract(
        self,
        phase_name: str,
        extract_fn: Any,
        errors: list[str],
        failed_phases: list[str],
    ) -> list[Any]:
        try:
            result = extract_fn()
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("Content extraction phase '%s' failed: %s", phase_name, exc)
            errors.append(f"{phase_name}: {exc}")
            failed_phases.append(phase_name)
            return []

    def _get_paper_assets(self, db: Session, paper_id: int) -> list[DocumentAsset]:
        from app.models import DocumentAsset as DAModel
        return (
            db.query(DAModel)
            .filter(
                DAModel.document_id == paper_id,
                DAModel.asset_type.in_(["figure", "page_snapshot"]),
            )
            .all()
        )

    def _get_candidate_source_id(
        self,
        db: Session,
        cand: ExtractionCandidate,
        run_id: int,
    ) -> int | None:
        if cand.source_type not in {"figure", "caption"} or not cand.source_ref:
            return None
        run = db.get(ExtractionRun, run_id)
        if run is None:
            return None
        result = (
            db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == run.paper_id,
                DocumentAsset.label == cand.source_ref,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            )
            .first()
        )
        return result.id if result else None

    def _write_item(
        self,
        db: Session,
        run_id: int,
        candidate: ExtractionCandidate,
        mrf_doc: MarkdownDocument,
    ) -> ExtractionItem:
        del mrf_doc
        item = ExtractionItem(
            run_id=run_id,
            indicator=candidate.field_name,
            value_text=candidate.value,
            value_numeric=self._to_float(candidate.normalized_value),
            value_unit=candidate.unit,
            source_type=candidate.source_type,
            extraction_method=(
                f"fusion:{candidate.derivation_type}:{candidate.fusion_decision}"
                if candidate.source_type == "fusion"
                else candidate.method or candidate.source_type
            ),
            figure_label=candidate.source_ref if candidate.source_type in ("figure", "caption") else None,
            confidence=candidate.confidence,
            verification_notes=json.dumps(
                {
                    "status": candidate.status,
                    "supporting_evidence": candidate.supporting_evidence,
                    "rejected_candidates": candidate.rejected_candidates,
                    "fusion_decision": candidate.fusion_decision,
                    "derivation_type": candidate.derivation_type,
                    "support_reason": candidate.support_reason,
                    "condition": candidate.condition,
                    "method": candidate.method,
                },
                ensure_ascii=False,
            ),
        )
        db.add(item)
        db.flush()

        evidence = candidate.evidence
        if evidence is None:
            evidence = CandidateEvidence(
                source_type=candidate.source_type,
                mrf_node_id="",
                quote=candidate.quote,
            )
        evidence_payload = {
            "mrf_node_id": evidence.mrf_node_id,
            "page": evidence.page,
            "section_id": evidence.section_id,
            "table_id": evidence.table_id,
            "figure_id": evidence.figure_id,
            "caption_id": evidence.caption_id,
            "char_span": evidence.char_span,
            "cell_range": evidence.cell_range,
            "bbox": evidence.bbox,
            "quote": evidence.quote or candidate.quote,
            "evidence_role": evidence.evidence_role,
            "evidence_payload": evidence.payload,
        }

        evidence_payload_json = json.dumps(evidence_payload, ensure_ascii=False)
        source_id = self._get_candidate_source_id(db, candidate, run_id)
        db.add(
            ExtractionEvidence(
                item_id=item.id,
                source_type=candidate.source_type,
                source_id=source_id,
                source_label=candidate.source_ref,
                excerpt=candidate.quote,
                excerpt_context=evidence_payload_json,
                page_number=evidence.page,
                relevance=candidate.confidence,
            )
        )
        return item

    @staticmethod
    def _to_float(value: float | str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).lower()

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if not value:
                continue
            n = str(value).strip()
            key = n.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(n)
        return ordered

    @staticmethod
    def _normalize_field_name(name: str) -> str:
        return str(name or "").strip()

    @staticmethod
    def _normalize_entity(entity: str) -> str:
        return str(entity or "").strip()

    @staticmethod
    def _value_signature(candidate: ExtractionCandidate) -> str:
        base = f"{candidate.value}|{candidate.unit or ''}|{candidate.source_type}|{candidate.source_ref}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _value_cluster_signature(candidate: ExtractionCandidate) -> str:
        base = f"{candidate.normalized_value if candidate.normalized_value is not None else candidate.value}|{candidate.unit or ''}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _build_evidence_id(source_type: str, source_ref: str, value: str, field: str) -> str:
        raw = f"{source_type}:{source_ref}:{field}:{value}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _contains_keywords(text: str, tokens: list[str] | str) -> bool:
    if not text:
        return False
    if isinstance(tokens, str):
        tokens = [tokens]
    haystack = (text or "").lower()
    for token in tokens:
        if not token:
            continue
        for candidate in _extract_keywords_from_text(token):
            if candidate in haystack:
                return True
    return False


def _first_nonempty(*values: object) -> str:
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _extract_keywords_from_text(text: str) -> list[str]:
    if not text:
        return []
    raw = re.sub(r"[^\w\u4e00-\u9fff%·°\\^\\-]+", " ", str(text).lower())
    return [tok.strip() for tok in raw.split() if tok.strip() and len(tok.strip()) <= 40]


def _parse_numeric(value: str) -> float | None:
    if value is None:
        return None
    m = NUMERIC_PATTERN.search(str(value))
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _normalize_unit(unit: str) -> str:
    if not unit:
        return ""
    clean = unit.strip().replace("\u00a0", " ").replace(" ", "")
    low = clean.lower()
    low = low.replace("𝑠⁻¹", "s⁻¹").replace("pa·s", "pa*s").replace("mpa·s", "mpa*s")
    if low in UNIT_CANONICAL_MAP:
        return UNIT_CANONICAL_MAP[low]
    mapped = UNIT_CANONICAL_MAP.get(low)
    if mapped:
        return mapped
    if re.fullmatch(r"[a-zA-Z%]+", clean):
        return clean
    return unit.strip()


def _scope_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [v for v in values if v]


def _replace_sources(
    mapping: IndicatorMapping,
    *,
    sections: list[str] | None = None,
    tables: list[str] | None = None,
    figures: list[str] | None = None,
) -> IndicatorMapping:
    return IndicatorMapping(
        indicator=mapping.indicator,
        indicator_keywords=list(mapping.indicator_keywords),
        figures=list(figures or mapping.figures),
        sections=list(sections or mapping.sections),
        tables=list(tables or mapping.tables),
        extraction_hint=mapping.extraction_hint,
        priority=mapping.priority,
    )
