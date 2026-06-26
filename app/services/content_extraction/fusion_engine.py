"""Fusion engine for structured extraction candidates."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from app.services.content_extraction.contracts import get_contract, validate_numeric
from app.services.content_extraction.models import ExtractionCandidate, PropertyRecord
from app.services.content_extraction.prompts import FUSION_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient

logger = logging.getLogger(__name__)


_SOURCE_PRIORITY = {"section": 0, "table": 1, "caption": 2, "figure": 3, "fusion": 4}


class FusionEngine:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client

    def merge(
        self,
        records_by_source: dict[str, list[PropertyRecord | ExtractionCandidate]],
        user_query: str = "",
    ) -> list[ExtractionCandidate]:
        candidates = self._coerce_records(records_by_source)
        if not candidates:
            return []

        groups: dict[tuple[str, str], list[ExtractionCandidate]] = {}
        for cand in candidates:
            key = (self._norm(cand.entity), self._norm(cand.field_name))
            groups.setdefault(key, []).append(cand)

        merged: list[ExtractionCandidate] = []
        for (_, _), group in groups.items():
            merged.extend(self._merge_group(group, user_query))
        return merged

    def _coerce_records(
        self,
        records_by_source: dict[str, list[PropertyRecord | ExtractionCandidate]],
    ) -> list[ExtractionCandidate]:
        out: list[ExtractionCandidate] = []
        for records in records_by_source.values():
            for record in records:
                if isinstance(record, ExtractionCandidate):
                    out.append(record)
                elif isinstance(record, PropertyRecord):
                    out.append(self._convert_property_record(record))
        return out

    def _convert_property_record(self, record: PropertyRecord) -> ExtractionCandidate:
        return ExtractionCandidate(
            field_name=record.property_name,
            entity=record.entity,
            value=(record.value_text or ""),
            unit=record.value_unit or None,
            normalized_value=None,
            source_type=record.source_type,
            mrf_node_id="",
            evidence_id="",
            quote=record.evidence_excerpt,
            cell_range=None,
            bbox=None,
            derivation_type="extractive",
            confidence=record.confidence,
            source_ref=record.source_ref,
            property_category=record.property_category,
            condition=record.condition,
            method=record.method,
            status="insufficient",
            support_reason="coerced",
            supporting_evidence=[],
            rejected_candidates=[],
            fusion_decision="coerced_record",
            write_to_final=True,
        )

    def _merge_group(
        self,
        records: list[ExtractionCandidate],
        user_query: str,
    ) -> list[ExtractionCandidate]:
        # ignore unsupported candidates
        valid = [r for r in records if r.status != "unsupported"]
        if not valid:
            return []

        # keep strongest single candidate directly if no conflict
        if len(valid) == 1:
            chosen = self._apply_contract_penalty(valid[0])
            chosen.fusion_decision = "single_candidate"
            return [chosen]

        grouped = self._group_by_signature(valid)
        if len(grouped) == 1:
            return [self._merge_consistent(valid)]

        # conflict: keep evidence-backed candidates and request rule-based resolution
        if self.client and self._need_llm_arbitration(grouped, user_query):
            arbitration = self._llm_arbitrate(valid, user_query)
            if arbitration:
                return arbitration

        # fallback: keep all conflicting candidates and mark contradiction
        output: list[ExtractionCandidate] = []
        evidence_index = [self._candidate_identity(rec) for rec in valid]
        for idx, item in enumerate(valid):
            item = self._clone(item)
            item.status = "conflicted"
            item.fusion_decision = "contradicting_evidence"
            item.confidence *= 0.85
            item.supporting_evidence = sorted(set(item.supporting_evidence))
            item.rejected_candidates = [
                key
                for i, key in enumerate(evidence_index)
                if i != idx and key
            ]
            output.append(item)
        return output

    def _merge_consistent(self, records: list[ExtractionCandidate]) -> ExtractionCandidate:
        # prioritize highest confidence; but keep additional evidences
        sorted_records = sorted(
            records,
            key=lambda r: (self._status_importance(r.status), r.confidence, -_SOURCE_PRIORITY.get(r.source_type, 9)),
            reverse=True,
        )
        primary = self._clone(sorted_records[0])
        extra_evidences = self._unique([*primary.supporting_evidence])
        for rec in sorted_records[1:]:
            extra_evidences.extend(rec.supporting_evidence)
            if rec.evidence_id:
                extra_evidences.append(rec.evidence_id)
        primary.supporting_evidence = self._unique(extra_evidences)
        primary.source_type = "fusion"
        primary.confidence = min(1.0, primary.confidence + 0.05)
        primary.fusion_decision = "rule_merge_consistent"
        primary.rejected_candidates = []
        primary.status = "sufficient" if primary.confidence >= 0.55 else "conflicted"
        return self._apply_contract_penalty(primary)

    def _group_by_signature(self, records: list[ExtractionCandidate]) -> dict[str, list[ExtractionCandidate]]:
        groups: dict[str, list[ExtractionCandidate]] = {}
        for rec in records:
            groups.setdefault(self._signature(rec), []).append(rec)
        return groups

    def _signature(self, record: ExtractionCandidate) -> str:
        value_key = str(record.normalized_value) if record.normalized_value is not None else (record.value or "").strip().lower()
        unit_key = (record.unit or "").strip().lower()
        return hashlib.sha1(f"{value_key}|{unit_key}".encode("utf-8")).hexdigest()[:16]

    def _apply_contract_penalty(self, record: ExtractionCandidate) -> ExtractionCandidate:
        normalized = self._clone(record)
        if normalized.value_unit:
            # preserve non-empty unit if unsupported contract
            pass
        violations = self._check_contract(normalized)
        if violations:
            normalized.confidence *= 0.85
            normalized.verification_notes = f"Contract violations: {violations}"
            if normalized.status == "sufficient":
                normalized.status = "conflicted"
        return normalized

    def _check_contract(self, record: ExtractionCandidate) -> list[str]:
        if not record.field_name:
            return []
        prop_name = record.field_name
        contract = get_contract(prop_name)
        if not contract:
            return []
        out: list[str] = []
        if record.unit and contract.expected_units:
            if record.unit.lower() not in {u.lower() for u in contract.expected_units}:
                out.append(f"unit '{record.unit}' not in {contract.expected_units}")
        if record.normalized_value is not None and isinstance(record.normalized_value, (int, float)):
            out.extend(validate_numeric(prop_name, float(record.normalized_value)))
        return out

    def _need_llm_arbitrate(self, grouped: dict[str, list[ExtractionCandidate]], user_query: str) -> bool:
        del user_query
        if len(grouped) <= 1:
            return False
        # Keep deterministic rule-path whenever it is already clear.
        if len(grouped) == 2:
            if self._is_unit_conversion_ambiguous(grouped):
                return True
            if self._is_semantic_equivalent_conflict(grouped):
                return True
            # keep deterministic fallback for other two-way conflicts
            return False
        # For more than two conflicting signatures, request arbitration only when ambiguity is detected.
        return self._is_unit_conversion_ambiguous(grouped) or self._is_semantic_equivalent_conflict(grouped)

    @staticmethod
    def _is_unit_conversion_ambiguous(grouped: dict[str, list[ExtractionCandidate]]) -> bool:
        units = set()
        for records in grouped.values():
            for record in records:
                if record.unit:
                    units.add((record.unit or "").strip().lower())
        if len(units) <= 1:
            return False
        # allow direct synonyms that are already normalized to the same unit
        normalized = {(u.lower()).replace(" ", "") for u in units}
        return len(normalized) > 1

    @staticmethod
    def _is_semantic_equivalent_conflict(grouped: dict[str, list[ExtractionCandidate]]) -> bool:
        entities = set()
        for records in grouped.values():
            for record in records:
                entities.add((record.entity or "").strip().lower())
        # same field_name, different entities indicates likely semantic split that may need arbitration.
        return len(entities) > 1

    def _llm_arbitrate(
        self,
        records: list[ExtractionCandidate],
        user_query: str,
    ) -> list[ExtractionCandidate] | None:
        if not self.client:
            return None
        conflict_text = self._format_conflict(records)
        messages = [
            {"role": "system", "content": FUSION_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_arbitration_prompt(conflict_text, user_query)},
        ]
        try:
            result = self.client.chat_json(messages, phase="content_fusion_arbitration")
            return self._apply_arbitration_verdict(result, records)
        except Exception as exc:
            logger.warning("LLM arbitration failed: %s", exc)
            return None

    def _format_conflict(self, records: list[ExtractionCandidate]) -> str:
        lines: list[str] = []
        for i, rec in enumerate(records):
            lines.append(
                f"[{i}] source={rec.source_type} value='{rec.value}' unit={rec.unit} "
                f"conf={rec.confidence:.2f} evidence={rec.quote[:120]}"
            )
        return "\n".join(lines)

    def _build_arbitration_prompt(self, conflict_text: str, user_query: str) -> str:
        return "\n".join(
            [
                "# 用户需求",
                user_query or "",
                "",
                "# 冲突候选（同一字段）",
                conflict_text,
                "",
                "# 任务",
                "仅从候选中选择1~n条可信候选，不得编造新值。若无法判定，返回synthesis_type='keep_all'。",
                "返回JSON: {\"synthesis_type\":\"select|keep_all\", \"selected_indices\":[0], \"note\":\"...\"}",
            ]
        )

    def _apply_arbitration_verdict(
        self,
        verdict: dict,
        records: list[ExtractionCandidate],
    ) -> list[ExtractionCandidate]:
        selected = verdict.get("selected_indices")
        mode = str(verdict.get("synthesis_type") or verdict.get("mode") or "").strip().lower()
        note = str(verdict.get("note") or "")
        if mode == "keep_all":
            for rec in records:
                rec = self._clone(rec)
                rec.fusion_decision = "llm_keep_all"
                rec.status = "conflicted"
                rec.verification_notes = note
                rec.supporting_evidence = self._unique(rec.supporting_evidence)
                rec.rejected_candidates = [
                    self._candidate_identity(other)
                    for other in records
                    if self._candidate_identity(other) != self._candidate_identity(rec)
                ]
            return [self._clone(rec) for rec in records]

        if not isinstance(selected, list):
            return None

        picked: list[ExtractionCandidate] = []
        seen: set[str] = set()
        for idx in selected:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if not 0 <= i < len(records):
                continue
            rec = self._clone(records[i])
            rec.fusion_decision = "llm_selected"
            rec.status = "sufficient" if rec.confidence >= 0.4 else "insufficient"
            rec.verification_notes = note or rec.verification_notes
            rec.rejected_candidates = [
                self._candidate_identity(other)
                for j, other in enumerate(records)
                if j != i
            ]
            key = self._signature(rec)
            if key in seen:
                continue
            seen.add(key)
            picked.append(rec)

        if picked:
            return picked
        return None

    @staticmethod
    def _status_importance(status: str) -> int:
        if status == "sufficient":
            return 3
        if status == "conflicted":
            return 2
        if status == "insufficient":
            return 1
        return 0

    @staticmethod
    def _clone(record: ExtractionCandidate) -> ExtractionCandidate:
        return ExtractionCandidate(
            field_name=record.field_name,
            entity=record.entity,
            value=record.value,
            unit=record.unit,
            normalized_value=record.normalized_value,
            source_type=record.source_type,
            mrf_node_id=record.mrf_node_id,
            evidence_id=record.evidence_id,
            quote=record.quote,
            cell_range=record.cell_range,
            bbox=record.bbox,
            derivation_type=record.derivation_type,
            confidence=record.confidence,
            source_ref=record.source_ref,
            property_category=record.property_category,
            condition=record.condition,
            method=record.method,
            status=record.status,
            support_reason=record.support_reason,
            supporting_evidence=record.supporting_evidence[:],
            rejected_candidates=record.rejected_candidates[:],
            fusion_decision=record.fusion_decision,
            write_to_final=record.write_to_final,
            evidence=record.evidence,
        )

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        return list(dict.fromkeys([i for i in items if i]))

    def _candidate_identity(self, record: ExtractionCandidate) -> str:
        return record.evidence_id or self._signature(record)

    @staticmethod
    def _norm(value: str) -> str:
        return (value or "").strip().lower()
