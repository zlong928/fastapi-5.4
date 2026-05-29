from __future__ import annotations

import base64
import json
import re
import threading
from pathlib import Path

import httpx


class LLMClient:
    """Shared LLM call layer for all agents. Thread-safe token tracking."""

    def __init__(self, config: dict) -> None:
        self.base_url = str(config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = str(config.get("api_key") or "")
        self.model = str(config.get("model") or "gpt-4o-mini")
        self.timeout = float(config.get("timeout") or 60)
        self._token_stats: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def token_stats(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._token_stats)

    def chat_json(self, messages: list[dict], *, phase: str) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "stream": True,
        }
        content = self._stream_content(body, phase=phase)
        try:
            return self._parse_json(content)
        except (ValueError, json.JSONDecodeError) as exc:
            self._merge_usage(phase, {})
            raise RuntimeError(
                f"LLM JSON 解析失败 (phase={phase}): {exc}"
            ) from exc

    def image_base64(self, image_path: str) -> str | None:
        try:
            path = Path(image_path)
            if not path.exists():
                return None
            return base64.b64encode(path.read_bytes()).decode("utf-8")
        except Exception:
            return None

    def _stream_content(self, body: dict, *, phase: str) -> str:
        last_error: Exception | None = None
        for url in self._chat_urls():
            try:
                chunks: list[str] = []
                usage: dict = {}
                with httpx.stream(
                    "POST",
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                    timeout=self.timeout,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[len("data:"):].strip()
                        if line == "[DONE]":
                            break
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if payload.get("usage"):
                            usage = payload["usage"]
                        choice = (payload.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            chunks.append(delta["content"])
                        message = choice.get("message") or {}
                        if message.get("content"):
                            chunks.append(message["content"])
                content = "".join(chunks).strip()
                if content:
                    self._merge_usage(phase, usage)
                    return content
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"LLM stream failed phase={phase} model={self.model}: {last_error}")

    def _chat_urls(self) -> list[str]:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return [f"{base}/chat/completions"]
        return [f"{base}/v1/chat/completions", f"{base}/chat/completions"]

    def _merge_usage(self, phase: str, usage: dict) -> None:
        with self._lock:
            phase_usage = self._token_stats.setdefault(phase, {})
            total_usage = self._token_stats.setdefault("total", {})
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = int(usage.get(key) or 0)
                phase_usage[key] = int(phase_usage.get(key) or 0) + value
                total_usage[key] = int(total_usage.get(key) or 0) + value

    def _parse_json(self, content: str) -> dict:
        text = (content or "").strip()
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if match:
            text = match.group(1)
        elif "{" in text and "}" in text:
            text = text[text.find("{"): text.rfind("}") + 1]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            snippet = text[:200] if text else "(empty)"
            raise ValueError(
                f"LLM 返回非法 JSON，无法解析。原始内容前200字: {snippet}. 错误: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM 返回的 JSON 不是对象类型，实际类型: {type(parsed).__name__}")
        return parsed
