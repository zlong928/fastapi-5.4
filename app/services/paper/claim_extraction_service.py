from __future__ import annotations

import json
import re

from app.models import DocumentAsset, DocumentChunk, DocumentClaim


RESULT_SECTION_RE = re.compile(r"(?i)\b(abstract|result|results|experiment|experiments|discussion|conclusion|limitations?)\b")
RESULT_SIGNAL_RE = re.compile(
    r"(?i)\b(achieved|achieves|outperform|outperformed|improve|improved|increase|increased|decrease|decreased|"
    r"significant|accuracy|f1|auc|precision|recall|limitation|limited|conclude|conclusion|result|results)\b|[%=><±]"
)


class ClaimExtractionService:
    """Extract explicit claims from already persisted evidence objects."""

    def extract(
        self,
        *,
        chunks: list[DocumentChunk],
        assets: list[DocumentAsset],
        existing_count: int = 0,
    ) -> list[DocumentClaim]:
        claims: list[DocumentClaim] = []
        seen: set[tuple[str, str, int | None]] = set()

        for chunk in chunks:
            for sentence in self._claim_sentences(chunk.cleaned_text or chunk.text, self._chunk_section(chunk)):
                key = (sentence.lower(), "chunk", chunk.id)
                if key in seen:
                    continue
                seen.add(key)
                claims.append(
                    DocumentClaim(
                        document_id=chunk.document_id,
                        claim_text=sentence,
                        claim_type=self._claim_type(sentence),
                        source_type="chunk",
                        source_id=chunk.id,
                        page_number=chunk.page_start,
                        evidence_text=sentence,
                        confidence=self._confidence(sentence, self._chunk_section(chunk)),
                        metadata_json=json.dumps({"section_title": self._chunk_section(chunk), "chunk_index": chunk.chunk_index}, ensure_ascii=False),
                    )
                )

        for asset in assets:
            if asset.asset_type not in {"table", "figure"}:
                continue
            evidence_text = self._asset_evidence_text(asset)
            if not evidence_text:
                continue
            key = (evidence_text.lower(), asset.asset_type, asset.id)
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                DocumentClaim(
                    document_id=asset.document_id,
                    claim_text=evidence_text,
                    claim_type="result" if asset.asset_type == "table" else "conclusion",
                    source_type=asset.asset_type,
                    source_id=asset.id,
                    page_number=asset.page_number,
                    evidence_text=evidence_text,
                    confidence="medium" if asset.asset_type == "table" else "low",
                    metadata_json=json.dumps({"asset_label": asset.label, "asset_type": asset.asset_type}, ensure_ascii=False),
                )
            )

        return claims[existing_count:]

    def _claim_sentences(self, text: str, section: str | None) -> list[str]:
        if not text.strip():
            return []
        section_is_relevant = bool(section and RESULT_SECTION_RE.search(section))
        sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        claims: list[str] = []
        for sentence in sentences:
            cleaned = re.sub(r"\s+", " ", sentence).strip()
            if len(cleaned) < 24 or len(cleaned) > 500:
                continue
            if section_is_relevant or RESULT_SIGNAL_RE.search(cleaned):
                claims.append(cleaned)
            if len(claims) >= 4:
                break
        return claims

    def _chunk_section(self, chunk: DocumentChunk) -> str | None:
        if not chunk.metadata_json:
            return None
        try:
            metadata = json.loads(chunk.metadata_json)
        except Exception:
            return None
        if not isinstance(metadata, dict):
            return None
        section = metadata.get("section_title") or metadata.get("heading")
        if section:
            return str(section)
        section_path = metadata.get("section_path")
        if isinstance(section_path, list) and section_path:
            return str(section_path[-1])
        return None

    def _claim_type(self, text: str) -> str:
        lower = text.lower()
        if any(term in lower for term in ("limitation", "limited", "fail", "cannot")):
            return "limitation"
        if any(term in lower for term in ("outperform", "better than", "compared", "versus", "vs.")):
            return "comparison"
        if any(term in lower for term in ("method", "approach", "framework", "model")):
            return "method"
        if any(term in lower for term in ("conclude", "conclusion", "therefore")):
            return "conclusion"
        return "result"

    def _confidence(self, text: str, section: str | None) -> str:
        if section and RESULT_SECTION_RE.search(section) and re.search(r"\d|%", text):
            return "high"
        if RESULT_SIGNAL_RE.search(text):
            return "medium"
        return "low"

    def _asset_evidence_text(self, asset: DocumentAsset) -> str:
        metadata = {}
        if asset.metadata_json:
            try:
                parsed = json.loads(asset.metadata_json)
                metadata = parsed if isinstance(parsed, dict) else {}
            except Exception:
                metadata = {}
        key_findings = metadata.get("key_findings")
        if isinstance(key_findings, list) and key_findings:
            return str(key_findings[0])[:500]
        return (asset.summary or asset.text_content or asset.caption or "").strip()[:500]
