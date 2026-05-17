"""Embedding provider base protocol."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Protocol that all embedding providers must satisfy."""

    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert a list of texts into a list of vectors."""
        ...