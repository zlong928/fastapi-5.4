import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
API_LOG_FILE = LOG_DIR / "api_run.log"
TASK_LOG_FILE = LOG_DIR / "task_run.log"

# 从环境变量中读取，并设置默认值
_allowed_ext = os.getenv("ALLOWED_EXTENSIONS", "txt,log,csv,pdf")
ALLOWED_EXTENSIONS = {ext.strip() for ext in _allowed_ext.split(",")}

_max_size = os.getenv("MAX_UPLOAD_SIZE_BYTES")
MAX_UPLOAD_SIZE_BYTES: int | None = int(_max_size) if _max_size else None

# 处理布尔类型的环境变量
_enable_worker = os.getenv("ENABLE_BACKGROUND_WORKER", "False")
ENABLE_BACKGROUND_WORKER = _enable_worker.lower() in ("true", "1", "t", "yes", "on")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def parse_cors_allowed_origins(frontend_url: str, extra_origins: str = "") -> list[str]:
    origins: list[str] = []
    for origin in [frontend_url, "http://localhost:3000", "http://127.0.0.1:3000", *extra_origins.split(",")]:
        normalized = origin.strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


CORS_ALLOWED_ORIGINS = parse_cors_allowed_origins(FRONTEND_URL, os.getenv("CORS_ALLOWED_ORIGINS", ""))
CORS_ALLOWED_ORIGIN_REGEX = os.getenv("CORS_ALLOWED_ORIGIN_REGEX", r"https://.*\.vercel\.app")
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


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, RESULT_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
