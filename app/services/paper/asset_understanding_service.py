from __future__ import annotations

import json
import re

from app.models import DocumentAsset


class AssetUnderstandingService:
    """Conservative, evidence-preserving summaries for paper assets."""

    def understand(self, asset: DocumentAsset) -> None:
        if asset.asset_type == "table":
            self._understand_table(asset)
        elif asset.asset_type in {"figure", "page_snapshot"}:
            self._understand_figure(asset)

    def _understand_table(self, asset: DocumentAsset) -> None:
        metadata = self._metadata(asset)
        markdown = asset.markdown or asset.text_content or asset.ocr_text or ""
        headers, first_row = self._table_shape(markdown)
        label = asset.label or f"Table {asset.asset_index + 1 if asset.asset_index is not None else asset.id}"

        if not asset.summary:
            if headers:
                asset.summary = f"{label} reports {', '.join(headers[:5])}."
            else:
                asset.summary = f"{label} contains extracted table-like evidence."

        key_findings = metadata.get("key_findings")
        if not isinstance(key_findings, list):
            key_findings = []
        if first_row and not key_findings:
            key_findings.append(" | ".join(first_row[:5]))
        metadata["key_findings"] = key_findings
        metadata.setdefault("metrics", headers[:8])
        metadata.setdefault("uncertainties", [] if headers else ["表格列结构不完整，无法可靠判断最佳方法"])
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _understand_figure(self, asset: DocumentAsset) -> None:
        metadata = self._metadata(asset)
        caption = asset.caption or str(metadata.get("caption") or metadata.get("context") or "")
        figure_type = str(metadata.get("figure_type") or self._figure_type(caption))
        metadata["figure_type"] = figure_type
        metadata.setdefault("visible_elements", self._visible_elements(caption))
        metadata.setdefault("data_extraction_possible", figure_type in {"bar_chart", "line_chart", "scatter_plot"})
        metadata.setdefault("precise_values_extracted", False)
        uncertainties = metadata.get("uncertainties")
        if not isinstance(uncertainties, list):
            uncertainties = []
        if metadata["data_extraction_possible"] and metadata.get("precise_values_extracted") is False:
            uncertainties.append("未进行精确数值还原")
        metadata["uncertainties"] = list(dict.fromkeys(str(item) for item in uncertainties if str(item).strip()))

        if not asset.text_content:
            asset.text_content = caption or "Visual evidence extracted from the PDF."
        if not asset.summary:
            asset.summary = asset.text_content[:500]
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _metadata(self, asset: DocumentAsset) -> dict:
        if not asset.metadata_json:
            return {}
        try:
            parsed = json.loads(asset.metadata_json)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _table_shape(self, markdown: str) -> tuple[list[str], list[str]]:
        rows = []
        for line in markdown.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [cell.strip().replace("\\|", "|") for cell in line.strip("|").split("|")]
            if cells and not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
                rows.append(cells)
        headers = rows[0] if rows else []
        first_row = rows[1] if len(rows) > 1 else []
        return headers, first_row

    def _figure_type(self, text: str) -> str:
        lower = text.lower()
        if any(term in lower for term in ("architecture", "framework", "model overview")):
            return "architecture_diagram"
        if any(term in lower for term in ("flowchart", "workflow", "pipeline")):
            return "flowchart"
        if any(term in lower for term in ("bar chart", "barplot", "histogram")):
            return "bar_chart"
        if any(term in lower for term in ("line chart", "trend", "curve")):
            return "line_chart"
        if any(term in lower for term in ("scatter", "umap", "tsne", "t-sne")):
            return "scatter_plot"
        if any(term in lower for term in ("microscope", "microscopy", "sem", "tem")):
            return "microscope_image"
        if "colony" in lower:
            return "colony_image"
        if any(term in lower for term in ("material", "sample", "film")):
            return "material_image"
        return "ordinary_figure" if text.strip() else "unknown"

    def _visible_elements(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return [cleaned[:200]] if cleaned else []
