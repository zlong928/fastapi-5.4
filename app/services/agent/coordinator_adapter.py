from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Callable
from typing import Any

from app.services.agent.coordinator import FallbackExtractionCoordinator
from app.services.agent.types import PaperData


class CoordinatorAdapter:
    def __init__(self) -> None:
        self.config = self._load_config()

    def run(self, *, paper: PaperData, user_query: str, on_event: Callable[[dict], None] | None = None) -> tuple[dict, list[dict]]:
        coordinator = self._build_coordinator(on_event=on_event)
        events: list[dict] = []
        final_results: dict | None = None
        for event in coordinator.extract(paper=paper, user_query=user_query):
            events.append(event)
            if on_event is not None:
                on_event(event)
            if event.get("phase") == "FINISH":
                final_results = event.get("results") or {}
        return final_results or {}, events

    def _build_coordinator(self, on_event: Callable[[dict], None] | None = None):
        if not self.config.get("api_key"):
            return FallbackExtractionCoordinator()
        try:
            from app.services.agent.coordinator import OpenAIExtractionCoordinator

            return OpenAIExtractionCoordinator(self.config, on_event=on_event)
        except Exception:
            return FallbackExtractionCoordinator()

    def _load_config(self) -> dict[str, Any]:
        env_config = {
            "base_url": os.getenv("OPENAI_BASE_URL", "https://2api.narrafark.com"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "api_format": os.getenv("LLM_API_FORMAT", "responses"),
            "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            "stream_max_seconds": float(os.getenv("LLM_STREAM_MAX_SECONDS", "90")),
        }
        if env_config["api_key"]:
            return env_config

        config_path = Path("llm.json")
        if config_path.exists():
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
                profiles = payload.get("profiles") or []
                if profiles and profiles[0].get("api_key"):
                    return profiles[0]
            except Exception:
                return env_config
        return env_config
