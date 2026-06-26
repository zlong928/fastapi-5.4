"""LLM configuration with fallback strategy and health checking."""

from __future__ import annotations

import os
import logging
from typing import Any

import httpx

from app.core import config as app_config

logger = logging.getLogger(__name__)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def check_api_health(base_url: str, api_key: str, model: str) -> bool:
    """Quick health check for an API endpoint."""
    if not api_key or not base_url:
        return False

    # Try to ping the API with a minimal request
    endpoints = [
        f"{base_url.rstrip('/')}/v1/chat/completions",
        f"{base_url.rstrip('/')}/chat/completions",
    ]

    body = {
        "model": model,
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 1,
    }

    for url in endpoints:
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=5.0,
            )

            # Accept 200 (success) or 401 (auth issue but endpoint works)
            # Reject 403 (client restricted), 502 (service down)
            if response.status_code in (200, 401, 400):
                logger.info(f"API health check passed for {base_url} (status: {response.status_code})")
                return True

        except Exception as e:
            logger.debug(f"Health check failed for {url}: {e}")
            continue

    return False


def build_llm_config_with_fallback() -> dict:
    """Build LLM config with automatic fallback to working endpoints."""

    # Primary configuration
    primary = {
        "base_url": os.getenv("LLM_BASE_URL") or app_config.OPENAI_BASE_URL,
        "api_key": os.getenv("LLM_API_KEY") or app_config.OPENAI_API_KEY,
        "model": os.getenv("LLM_MODEL") or app_config.OPENAI_MODEL,
    }

    # Fallback configurations
    fallbacks = [
        {
            "name": "mimo",
            "base_url": os.getenv("FALLBACK_MIMO_BASE_URL", ""),
            "api_key": os.getenv("FALLBACK_MIMO_API_KEY", ""),
            "model": os.getenv("FALLBACK_MIMO_MODEL", ""),
        },
        {
            "name": "narrafark",
            "base_url": "https://2api.narrafark.com",
            "api_key": os.getenv("FALLBACK_API_KEY_1", ""),
            "model": "claude-opus-4-6",
        },
        {
            "name": "xf-yun",
            "base_url": "https://maas-api.cn-huabei-1.xf-yun.com/v1",
            "api_key": os.getenv("FALLBACK_API_KEY_2", ""),
            "model": "spark-v3.5",
        },
    ]

    # Check primary
    if check_api_health(primary["base_url"], primary["api_key"], primary["model"]):
        logger.info(f"Using primary LLM: {primary['base_url']}")
        return _build_full_config(primary)

    logger.warning(f"Primary LLM endpoint unavailable: {primary['base_url']}")

    # Try fallbacks
    for fallback in fallbacks:
        if not fallback["api_key"]:
            continue

        if check_api_health(fallback["base_url"], fallback["api_key"], fallback["model"]):
            logger.warning(f"Falling back to {fallback['name']}: {fallback['base_url']}")
            return _build_full_config(fallback)

    # No working endpoint found - return primary config anyway
    # The LLMClient will handle errors
    logger.error("No working LLM endpoint found. Using primary config (may fail).")
    return _build_full_config(primary)


def build_vlm_config_with_fallback() -> dict:
    """Build VLM config with fallback strategy."""
    shared = build_llm_config_with_fallback()

    # VLM-specific overrides
    vlm_base = os.getenv("VLM_BASE_URL")
    vlm_key = os.getenv("VLM_API_KEY")
    vlm_model = os.getenv("VLM_MODEL")

    if vlm_base and vlm_key and vlm_model:
        if check_api_health(vlm_base, vlm_key, vlm_model):
            shared.update({
                "base_url": vlm_base,
                "api_key": vlm_key,
                "model": vlm_model,
            })
            logger.info(f"Using dedicated VLM endpoint: {vlm_base}")
        else:
            logger.warning(f"VLM endpoint unavailable, using shared LLM config")

    # Apply VLM-specific settings
    shared.update({
        "api_format": os.getenv("VLM_API_FORMAT") or shared.get("api_format"),
        "timeout": float(os.getenv("VLM_TIMEOUT_SECONDS", str(shared.get("timeout", 120)))),
    })

    return shared


def _build_full_config(base: dict[str, Any]) -> dict:
    """Build full config from base settings."""
    return {
        "base_url": base["base_url"],
        "api_key": base["api_key"],
        "model": base["model"],
        "fallback_models": os.getenv("LLM_FALLBACK_MODELS", ""),
        "api_format": os.getenv("LLM_API_FORMAT", "openai_chat"),
        "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        "stream_max_seconds": float(os.getenv("LLM_STREAM_MAX_SECONDS", "180")),
        "max_concurrency": int(os.getenv("LLM_MAX_CONCURRENCY", "4")),
        "http_retries": int(os.getenv("LLM_HTTP_RETRIES", "2")),
        "retry_backoff_seconds": float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.5")),
        "min_request_interval_seconds": float(os.getenv("LLM_MIN_REQUEST_INTERVAL_SECONDS", "1.0")),
        "allow_root_chat_fallback": env_bool("LLM_ALLOW_ROOT_CHAT_FALLBACK", False),
        "force_jpeg_images": env_bool("LLM_IMAGE_FORCE_JPEG", True),
        "max_image_bytes": int(os.getenv("LLM_IMAGE_MAX_BYTES", "1500000")),
        "max_image_side": int(os.getenv("LLM_IMAGE_MAX_SIDE", "1000")),
        "image_jpeg_quality": int(os.getenv("LLM_IMAGE_JPEG_QUALITY", "75")),
    }


# Backwards compatibility - use these as drop-in replacements
build_llm_config = build_llm_config_with_fallback
build_vlm_config = build_vlm_config_with_fallback
