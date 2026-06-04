from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import httpx


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str

    @property
    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @property
    def models_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"


def load_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.getenv("OPENAI_BASE_URL", "").strip(),
        model=os.getenv("OPENAI_MODEL", "").strip(),
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
    )


def headers(config: LLMConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


def print_config(config: LLMConfig) -> None:
    print(f"OPENAI_BASE_URL={config.base_url or '<empty>'}")
    print(f"OPENAI_MODEL={config.model or '<empty>'}")
    print(f"OPENAI_API_KEY={'<set>' if config.api_key else '<empty>'}")
    for name in (
        "LLM_API_FORMAT",
        "LLM_MAX_CONCURRENCY",
        "VISUAL_LLM_MAX_WORKERS",
        "LLM_HTTP_RETRIES",
        "LLM_MIN_REQUEST_INTERVAL_SECONDS",
    ):
        print(f"{name}={os.getenv(name, '<unset>')}")


def fetch_models(config: LLMConfig) -> list[str]:
    response = httpx.get(config.models_url, headers=headers(config), timeout=30)
    if response.status_code >= 400:
        print(f"models_status={response.status_code}")
        print(f"models_error={response.text[:500].replace(chr(10), ' ')}")
        return []
    payload = response.json()
    models = [
        str(item.get("id"))
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    print(f"models_status={response.status_code}")
    print(f"models_count={len(models)}")
    if models:
        print("models=" + ", ".join(models[:30]))
    return models


def test_chat(config: LLMConfig) -> tuple[bool, str]:
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "temperature": 0.1,
        "stream": False,
    }
    response = httpx.post(config.chat_url, headers=headers(config), json=body, timeout=60)
    if response.status_code >= 400:
        return False, f"chat_status={response.status_code} chat_error={response.text[:500].replace(chr(10), ' ')}"
    payload = response.json()
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    return bool(content), f"chat_status={response.status_code} content={str(content)[:200].replace(chr(10), ' ')}"


def main() -> int:
    config = load_config()
    print_config(config)
    if not config.base_url or not config.model or not config.api_key:
        print("diagnosis=missing OPENAI_BASE_URL, OPENAI_MODEL, or OPENAI_API_KEY")
        return 2

    models = fetch_models(config)
    if models and config.model not in models:
        case_insensitive = {model.lower(): model for model in models}
        matching = case_insensitive.get(config.model.lower())
        if matching:
            print(f"diagnosis=model case differs from listed id; listed id is {matching}")
        else:
            print("diagnosis=current model is not listed by the upstream /models endpoint")

    ok, message = test_chat(config)
    print(message)
    if ok:
        print("diagnosis=llm configuration is usable")
        return 0

    if "No available accounts" in message:
        print("diagnosis=upstream gateway account pool is unavailable; local app config was read correctly")
    else:
        print("diagnosis=chat request failed; inspect upstream model/base URL/API key compatibility")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
