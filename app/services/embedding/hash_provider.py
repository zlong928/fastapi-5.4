"""Fallback embedding provider that falls back to a simple hash‑based embedding."""
from typing import List


class HashEmbeddingProvider:
    """
    Very lightweight embedding provider that creates fixed‑size vectors
    by hashing each token and normalising the result.
    Used only when the primary provider (e.g. Ollama) is unavailable.
    """
    model_name = "hash-embedding-v1"

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Return a list of dense vectors (one per input text)."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str, dimensions: int = 32) -> List[float]:
        """
        Very simple embedding: hash each token and spread the hash
        across ``dimensions`` slots, then L2‑normalise.
        """
        values = [0.0] * dimensions
        token = text.lower()
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dimensions
        values[index] += 1.0
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm if norm > 0 else 0.0 for v in values]