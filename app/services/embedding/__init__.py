"""Embedding provider resolution and exports."""
from app.core.config import EMBEDDING_PROVIDER


def resolve_embedding_provider():
    """Return an appropriate embedding provider based on configuration."""
    if EMBEDDING_PROVIDER == "ollama":
        # Import locally to avoid circularity
        from app.services.embedding.ollama_provider import OllamaEmbeddingProvider
        provider = OllamaEmbeddingProvider()
        if provider.is_available():
            return provider
    # Fallback to hash-based provider
    from .providers import HashEmbeddingProvider
    return HashEmbeddingProvider()