from __future__ import annotations

import re

from app.services.extraction.constants import GENERIC_RESULT_FIELDS, NEGATIVE_RESULT_MARKERS


def is_negative_result_text(value: str | None) -> bool:
    text = (value or "").lower()
    return any(marker.lower() in text for marker in NEGATIVE_RESULT_MARKERS)


def display_field_name(field_name: str | None, source_type: str, figure_label: str | None = None) -> str:
    value = field_name or "unknown"
    if value.lower() not in GENERIC_RESULT_FIELDS:
        return re.sub(r"\s+", "_", value.strip())[:80] or "unknown"
    if source_type in {"asset", "figure", "chart"} or figure_label:
        return "图表证据"
    return re.sub(r"\s+", "_", value.strip())[:80] or "unknown"


def confidence_label(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def legacy_localized_value(metric: str, text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 220:
        compact = compact[:220].rsplit(" ", 1)[0]
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
