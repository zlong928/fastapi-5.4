"""CSV exporter for content extraction pipeline.

Produces property-specific CSV with semantic columns matching the
PropertyRecord dataclass fields.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from app.services.content_extraction.models import PropertyRecord

CSV_HEADERS = [
    "entity",
    "property_name",
    "property_category",
    "value_text",
    "value_numeric",
    "value_unit",
    "condition",
    "method",
    "confidence",
    "source_type",
    "source_ref",
    "extraction_method",
    "evidence_excerpt",
]


def export_property_csv(records: list[PropertyRecord]) -> str:
    """Export PropertyRecords to a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_HEADERS)

    for rec in records:
        writer.writerow([
            rec.entity,
            rec.property_name,
            rec.property_category,
            rec.value_text,
            _fmt_float(rec.value_numeric),
            rec.value_unit or "",
            rec.condition,
            rec.method,
            _fmt_float(rec.confidence),
            rec.source_type,
            rec.source_ref,
            rec.extraction_method,
            rec.evidence_excerpt,
        ])

    return output.getvalue()


def export_property_csv_file(
    records: list[PropertyRecord],
    path: str | Path,
) -> Path:
    """Export PropertyRecords to a CSV file with BOM for Excel compat."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = export_property_csv(records)
    path.write_text(content, encoding="utf-8-sig")
    return path


def _fmt_float(value: Any) -> str:
    if value is None:
        return ""
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return f"{f:.6g}"
    except (TypeError, ValueError):
        return str(value)
