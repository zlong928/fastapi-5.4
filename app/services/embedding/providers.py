"""Concrete embedding provider implementations."""

from typing import List

import hashlib
import math

from .base import EmbeddingProvider


class HashEmbeddingProvider(EmbeddingProvider):
    """
    A very lightweight fallback embedding provider that creates fixed-size
    vectors by hashing tokens and normalising the result.
    Used only when the primary provider (e.g., Ollama) is unavailable.
    """
    model_name = "hash-embedding-v1"

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Convert each input text into a dense vector."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str, dimensions: int = 32) -> List[float]:
        """
        Generate a simple embedding by hashing each token and spreading the
        hash across a fixed number of dimensions, then L2‑normalising.
        """
        dimensions = 32  # default dimensionality
        values = [0.0] * dimensions
        token = text.lower()
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dimensions
        values[index] += 1.0
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            return values
        return [v / norm for v in values]