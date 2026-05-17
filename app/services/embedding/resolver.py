"""Embedding provider resolver.

This module breaks the circular import between:
- document_embedding_service.py (imports resolve_embedding_provider)
- embedding/__init__.py (exports resolve_embedding_provider)

The resolver is imported directly by services that need it, avoiding partial
initialization issues.
"""
from app.core.config import EMBEDDING_PROVIDER

from app.services.embedding.ollama_provider import OllamaEmbeddingProvider
from app.services.embedding.hash_provider import HashEmbeddingProvider


def resolve_embedding_provider() -> object:
    """Return an available embedding provider instance."""
    if EMBEDDING_PROVIDER == "ollama":
        provider = OllamaEmbeddingProvider()
        if provider.is_available():
            return provider
    return HashEmbeddingProvider()