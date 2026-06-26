import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", DATA_DIR / "uploads"))
RESULT_DIR = DATA_DIR / "results"
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
API_LOG_FILE = LOG_DIR / "api_run.log"
TASK_LOG_FILE = LOG_DIR / "task_run.log"

# 从环境变量中读取，并设置默认值
_allowed_ext = os.getenv("ALLOWED_EXTENSIONS", "txt,log,csv,pdf")
ALLOWED_EXTENSIONS = {ext.strip() for ext in _allowed_ext.split(",")}

DEFAULT_MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024
_max_size = os.getenv("MAX_UPLOAD_SIZE") or os.getenv("MAX_UPLOAD_SIZE_BYTES")
MAX_UPLOAD_SIZE_BYTES: int = int(_max_size) if _max_size else DEFAULT_MAX_UPLOAD_SIZE_BYTES


def _safe_int(env_key: str, default: int) -> int:
    """Safely parse environment variable to int with fallback."""
    try:
        value = os.getenv(env_key)
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


def _safe_float(env_key: str, default: float) -> float:
    """Safely parse environment variable to float with fallback."""
    try:
        value = os.getenv(env_key)
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


DOCUMENT_PARSE_TIMEOUT_SECONDS = _safe_int("DOCUMENT_PARSE_TIMEOUT_SECONDS", 1800)
OCR_TIMEOUT_SECONDS = _safe_int("OCR_TIMEOUT_SECONDS", DOCUMENT_PARSE_TIMEOUT_SECONDS)
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")
OCR_TICK_MIN_CONFIDENCE = _safe_float("OCR_TICK_MIN_CONFIDENCE", 45.0)
ENABLE_DOCLING_PARSER = os.getenv("ENABLE_DOCLING_PARSER", "False").lower() in ("true", "1", "t", "yes", "on")
ENABLE_MINERU_PARSER = os.getenv("ENABLE_MINERU_PARSER", "True").lower() in ("true", "1", "t", "yes", "on")
MINERU_API_BASE_URL = os.getenv("MINERU_API_BASE_URL", "https://mineru.net")
MINERU_API_KEY = os.getenv("MINERU_API_KEY", "")
MINERU_MODEL_VERSION = os.getenv("MINERU_MODEL_VERSION", "vlm")
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "en")
MINERU_POLL_INTERVAL_SECONDS = _safe_float("MINERU_POLL_INTERVAL_SECONDS", 5.0)
MINERU_TIMEOUT_SECONDS = _safe_int("MINERU_TIMEOUT_SECONDS", DOCUMENT_PARSE_TIMEOUT_SECONDS)
MINERU_SUBMIT_RATE_LIMIT_PER_MINUTE = _safe_int("MINERU_SUBMIT_RATE_LIMIT_PER_MINUTE", 50)
MINERU_RESULT_RATE_LIMIT_PER_MINUTE = _safe_int("MINERU_RESULT_RATE_LIMIT_PER_MINUTE", 1000)

# 处理布尔类型的环境变量
_enable_worker = os.getenv("ENABLE_BACKGROUND_WORKER", "False")
ENABLE_BACKGROUND_WORKER = _enable_worker.lower() in ("true", "1", "t", "yes", "on")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DOCUMENT_QUEUE_NAME = os.getenv("DOCUMENT_QUEUE_NAME", "pdf_task_queue")
EXTRACTION_QUEUE_NAME = os.getenv("EXTRACTION_QUEUE_NAME", "extraction_task_queue")
BATCH_EXTRACTION_QUEUE_NAME = os.getenv("BATCH_EXTRACTION_QUEUE_NAME", "batch_extraction_queue")
BATCH_EXTRACTION_STALE_AFTER_SECONDS = _safe_int("BATCH_EXTRACTION_STALE_AFTER_SECONDS", 300)

# 批量提取并发：单个 worker 内同时处理的图片数
# LLM 最大 100 路并发，每张图平均 ~1.3 次 LLM 调用（分类 + 可能提取）
# 公式: LLM_MAX_CONCURRENCY / avg_llm_calls_per_image ≈ 100/1.3 ≈ 76
# 留余量给其他 worker 进程，单进程设为 20，用 5 个 worker 可打满 100 路 LLM
BATCH_CONCURRENCY = _safe_int("BATCH_CONCURRENCY", 20)

# 单图提取超时（秒），替代原先写死的 120 秒
IMAGE_EXTRACT_TIMEOUT = _safe_int("IMAGE_EXTRACT_TIMEOUT", 300)

# 进度同步间隔（秒）：每 N 秒输出一次当前完成进度
BATCH_PROGRESS_INTERVAL = _safe_float("BATCH_PROGRESS_INTERVAL", 5.0)

# 进程级线程池大小 = BATCH_CONCURRENCY + 少量余量
BATCH_THREAD_POOL_SIZE = _safe_int("BATCH_THREAD_POOL_SIZE", BATCH_CONCURRENCY + 4)
# 单个 worker 同时处理的 job 数量（默认 3 个 job × 20 并发 = 60 线程）
BATCH_WORKER_MAX_JOBS = _safe_int("BATCH_WORKER_MAX_JOBS", 3)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = _safe_int("ACCESS_TOKEN_EXPIRE_MINUTES", 1440)


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def is_production_environment() -> bool:
    return any(
        os.getenv(name, "").strip().lower() == "production"
        for name in ("ENV", "APP_ENV", "NODE_ENV", "ENVIRONMENT")
    )


def is_localhost_url(url: str) -> bool:
    normalized = normalize_url(url).lower()
    return normalized.startswith(("http://localhost", "https://localhost", "http://127.0.0.1", "https://127.0.0.1"))


IS_PRODUCTION = is_production_environment()
_raw_frontend_url = os.getenv("FRONTEND_URL")
FRONTEND_URL = normalize_url(_raw_frontend_url or "http://localhost:3000")

if IS_PRODUCTION and not _raw_frontend_url:
    raise RuntimeError("FRONTEND_URL must be explicitly set in production.")

if IS_PRODUCTION and is_localhost_url(FRONTEND_URL):
    raise RuntimeError("FRONTEND_URL must be set to the deployed frontend URL in production.")

if IS_PRODUCTION and JWT_SECRET_KEY in ("change-me-in-production", "change-me"):
    raise RuntimeError("JWT_SECRET_KEY must be changed from its default value in production.")


def parse_cors_allowed_origins(frontend_url: str, extra_origins: str = "", include_local_defaults: bool = True) -> list[str]:
    origins: list[str] = []
    default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"] if include_local_defaults else []
    for origin in [frontend_url, *default_origins, *extra_origins.split(",")]:
        normalized = normalize_url(origin)
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


CORS_ALLOWED_ORIGINS = parse_cors_allowed_origins(
    FRONTEND_URL,
    os.getenv("CORS_ALLOWED_ORIGINS", ""),
    include_local_defaults=not IS_PRODUCTION,
)
CORS_ALLOWED_ORIGIN_REGEX = os.getenv("CORS_ALLOWED_ORIGIN_REGEX", r"https://.*\.vercel\.app")


def parse_oauth_allowed_frontend_origins(
    frontend_url: str,
    cors_allowed_origins: list[str],
    extra_origins: str = "",
) -> list[str]:
    origins: list[str] = []
    for origin in [frontend_url, *cors_allowed_origins, *extra_origins.split(",")]:
        normalized = normalize_url(origin)
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


OAUTH_ALLOWED_FRONTEND_ORIGINS = parse_oauth_allowed_frontend_origins(
    FRONTEND_URL,
    CORS_ALLOWED_ORIGINS,
    os.getenv("OAUTH_ALLOWED_FRONTEND_ORIGINS", ""),
)


def is_allowed_frontend_origin(origin: str) -> bool:
    normalized = normalize_url(origin)
    return normalized in OAUTH_ALLOWED_FRONTEND_ORIGINS


SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "change-me-in-production")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)
DEBUG_EMAIL_CODE = os.getenv("DEBUG_EMAIL_CODE", "False").lower() in ("true", "1", "t", "yes", "on")
OBSIDIAN_API_URL = os.getenv("OBSIDIAN_API_URL", "http://127.0.0.1:27123")
OBSIDIAN_API_KEY = os.getenv("OBSIDIAN_API_KEY", "")
OBSIDIAN_TARGET_DIR = os.getenv("OBSIDIAN_TARGET_DIR", "Uploads")
OBSIDIAN_SYNC_ENABLED = os.getenv("OBSIDIAN_SYNC_ENABLED", "False").lower() in ("true", "1", "t", "yes", "on")
OBSIDIAN_CREATE_REFERENCE_NOTE = os.getenv("OBSIDIAN_CREATE_REFERENCE_NOTE", "True").lower() in ("true", "1", "t", "yes", "on")
OBSIDIAN_VERIFY_SSL = os.getenv("OBSIDIAN_VERIFY_SSL", "False").lower() in ("true", "1", "t", "yes", "on")

# OpenAI-compatible chat completions
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Embedding / Vector Search
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "hash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

# RAG chunking
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
CHUNK_MIN_SIZE_TARGET = int(os.getenv("CHUNK_MIN_SIZE_TARGET", "120"))
TEXT_SPLITTER = os.getenv("TEXT_SPLITTER", "markdown_header").strip().lower()

# Web Search (Tavily)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "True").lower() in ("true", "1", "t", "yes", "on")
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, RESULT_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
