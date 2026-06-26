from __future__ import annotations

import os

from app.core import config as app_config


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _lora_headers(prefix: str) -> dict[str, str]:
    lora_id = os.getenv(f"{prefix}_LORA_ID", "").strip()
    return {"lora_id": lora_id} if lora_id else {}


def build_llm_config() -> dict:
    """Build a shared LLM config with .env-backed OpenAI values as primary defaults."""
    return {
        "base_url": os.getenv("LLM_BASE_URL") or app_config.OPENAI_BASE_URL,
        "api_key": os.getenv("LLM_API_KEY") or app_config.OPENAI_API_KEY,
        "model": os.getenv("LLM_MODEL") or app_config.OPENAI_MODEL,
        "fallback_models": os.getenv("LLM_FALLBACK_MODELS", ""),
        "api_format": os.getenv("LLM_API_FORMAT", "responses"),
        "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        "stream_max_seconds": float(os.getenv("LLM_STREAM_MAX_SECONDS", "180")),
        "max_concurrency": int(os.getenv("LLM_MAX_CONCURRENCY", "4")),
        "http_retries": int(os.getenv("LLM_HTTP_RETRIES", "2")),
        "retry_backoff_seconds": float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.5")),
        "min_request_interval_seconds": float(os.getenv("LLM_MIN_REQUEST_INTERVAL_SECONDS", "1.0")),
        "allow_root_chat_fallback": env_bool("LLM_ALLOW_ROOT_CHAT_FALLBACK", False),
        "allow_non_stream_fallback": env_bool("LLM_ALLOW_NON_STREAM_FALLBACK", False),
        "extra_headers": _lora_headers("LLM"),
        "force_jpeg_images": env_bool("LLM_IMAGE_FORCE_JPEG", True),
        "max_image_bytes": int(os.getenv("LLM_IMAGE_MAX_BYTES", "1500000")),
        "max_image_side": int(os.getenv("LLM_IMAGE_MAX_SIDE", "1000")),
        "image_jpeg_quality": int(os.getenv("LLM_IMAGE_JPEG_QUALITY", "75")),
    }


def build_vlm_config() -> dict:
    """Build a visual-LLM config with VLM_* overrides ahead of shared LLM defaults."""
    shared = build_llm_config()
    shared.update(
        {
            "base_url": os.getenv("VLM_BASE_URL") or shared["base_url"],
            "api_key": os.getenv("VLM_API_KEY") or shared["api_key"],
            "model": os.getenv("VLM_MODEL") or shared["model"],
            "fallback_models": os.getenv("VLM_FALLBACK_MODELS", shared["fallback_models"]),
            "api_format": os.getenv("VLM_API_FORMAT") or shared["api_format"],
            "timeout": float(os.getenv("VLM_TIMEOUT_SECONDS", str(shared["timeout"]))),
            "stream_max_seconds": float(os.getenv("VLM_STREAM_MAX_SECONDS", str(shared["stream_max_seconds"]))),
            "max_concurrency": int(os.getenv("VLM_MAX_CONCURRENCY", str(shared["max_concurrency"]))),
            "http_retries": int(os.getenv("VLM_HTTP_RETRIES", str(shared["http_retries"]))),
            "retry_backoff_seconds": float(os.getenv("VLM_RETRY_BACKOFF_SECONDS", str(shared["retry_backoff_seconds"]))),
            "min_request_interval_seconds": float(
                os.getenv("VLM_MIN_REQUEST_INTERVAL_SECONDS", str(shared["min_request_interval_seconds"]))
            ),
            "allow_root_chat_fallback": env_bool(
                "VLM_ALLOW_ROOT_CHAT_FALLBACK",
                bool(shared["allow_root_chat_fallback"]),
            ),
            "allow_non_stream_fallback": env_bool(
                "VLM_ALLOW_NON_STREAM_FALLBACK",
                env_bool("LLM_ALLOW_NON_STREAM_FALLBACK", False),
            ),
            "extra_headers": _lora_headers("VLM") or shared["extra_headers"],
            "force_jpeg_images": env_bool("VLM_IMAGE_FORCE_JPEG", bool(shared["force_jpeg_images"])),
            "max_image_bytes": int(os.getenv("VLM_IMAGE_MAX_BYTES", str(shared["max_image_bytes"]))),
            "max_image_side": int(os.getenv("VLM_IMAGE_MAX_SIDE", str(shared["max_image_side"]))),
            "image_jpeg_quality": int(os.getenv("VLM_IMAGE_JPEG_QUALITY", str(shared["image_jpeg_quality"]))),
        }
    )
    return shared
