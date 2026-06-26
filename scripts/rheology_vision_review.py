from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.services.agent.llm_client import LLMClient


SYSTEM_PROMPT = """You are a visual reviewer for rheology strain sweep marker digitization.
You must only confirm visible evidence in the supplied image patch.
Do not invent missing points or infer a curve merely because six curves are expected.
Return strict JSON with a top-level "decisions" array."""


def _client() -> LLMClient:
    return LLMClient(
        {
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "api_format": os.getenv("LLM_API_FORMAT", "responses"),
            "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            "http_retries": int(os.getenv("LLM_HTTP_RETRIES", "2")),
            "max_concurrency": 1,
        }
    )


def _decision_prompt(request: dict) -> str:
    return json.dumps(
        {
            "task": "Review this single marker patch.",
            "allowed_decisions": ["confirm_role", "confirm_track", "reject_candidate", "uncertain"],
            "output_schema": {
                "decisions": [
                    {
                        "marker_id": request["marker_id"],
                        "decision": "confirm_role|confirm_track|reject_candidate|uncertain",
                        "curve_role": "G_prime|G_double_prime|unknown",
                        "track_id": "optional existing track id",
                        "confidence": "0.0-1.0",
                        "reason": "short visible-evidence reason",
                    }
                ]
            },
            "review_request": request,
            "rules": [
                "Filled colored center means G_prime.",
                "White or background-colored center with colored ring means G_double_prime.",
                "If the patch is ambiguous, choose uncertain.",
                "Never create a coordinate or a missing marker.",
            ],
        },
        ensure_ascii=False,
    )


def run(manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = _client()
    decisions = []
    for request in manifest.get("requests", []):
        image_url = client.image_data_url(str(request.get("patch_path") or ""))
        if not image_url:
            decisions.append(
                {
                    "marker_id": request.get("marker_id"),
                    "decision": "uncertain",
                    "curve_role": "unknown",
                    "confidence": 0.0,
                    "reason": "patch_unreadable",
                }
            )
            continue
        response = client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _decision_prompt(request)},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            phase="rheology_vision_review",
        )
        for decision in response.get("decisions", []):
            if isinstance(decision, dict):
                decision.setdefault("marker_id", request.get("marker_id"))
                decisions.append(decision)
    out_path = Path(str(manifest.get("decisions_path") or manifest_path.with_name("vision_decisions.json")))
    out_path.write_text(json.dumps({"schema_version": "rheology_vision_decisions.v1", "decisions": decisions}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/rheology_vision_review.py /path/to/vision_review_manifest.json")
    print(run(Path(sys.argv[1])))
