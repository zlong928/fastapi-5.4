from __future__ import annotations

import httpx

from app.core.config import OLLAMA_BASE_URL, EMBEDDING_MODEL


class OllamaEmbeddingProvider:
    model_name = f"ollama/{EMBEDDING_MODEL}"

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = EMBEDDING_MODEL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available: bool | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"]

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            self._available = resp.is_success
        except Exception:
            self._available = False
        return self._available
