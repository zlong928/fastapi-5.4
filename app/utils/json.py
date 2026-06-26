from __future__ import annotations

import json
from typing import Any


def json_dumps_or_none(data: Any) -> str | None:
    if data is None:
        return None
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def json_loads_object_or_none(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def json_loads_object_or_empty(value: str | None) -> dict[str, Any]:
    return json_loads_object_or_none(value) or {}


def merge_json_object(existing_json: str | None, patch: dict[str, Any] | None) -> str | None:
    existing = json_loads_object_or_none(existing_json) or {}
    if patch:
        existing.update(patch)
    return json_dumps_or_none(existing) if existing else None
