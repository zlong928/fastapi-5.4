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


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, RESULT_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
