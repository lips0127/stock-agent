import os
from pathlib import Path
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _env(key: str, default: str = "", cast: type = str) -> object:
    val = os.environ.get(key, default)
    if cast is bool:
        return val.lower() in ("1", "true", "yes")
    return cast(val)


# ── 服务器 ──
HOST = _env("APP_HOST", "0.0.0.0")
PORT = _env("APP_PORT", "5000", int)
DEBUG = _env("APP_DEBUG", "false", bool)

# ── JWT ──
JWT_SECRET = _env("JWT_SECRET", "change-me-in-production-256bit")
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = _env("JWT_EXPIRATION_HOURS", "2", int)

# ── 调度器 ──
SCHEDULER_HOUR = _env("SCHEDULER_HOUR", "15", int)
SCHEDULER_MINUTE = _env("SCHEDULER_MINUTE", "30", int)
SCHEDULER_MAX_RETRIES = _env("SCHEDULER_MAX_RETRIES", "3", int)
SCHEDULER_RETRY_INTERVAL = _env("SCHEDULER_RETRY_INTERVAL", "60", int)
SCAN_MAX_WORKERS = _env("SCAN_MAX_WORKERS", "20", int)

# ── 缓存 ──
CACHE_DIR = _env("CACHE_DIR", str(_PROJECT_ROOT))
CACHE_EXPIRE_HOURS = _env("CACHE_EXPIRE_HOURS", "6", int)

# ── CORS ──
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000")

# ── Sina API ──
SINA_HQ_URL = _env("SINA_HQ_URL", "http://hq.sinajs.cn/list=")
SINA_REFERER = _env("SINA_REFERER", "http://finance.sina.com.cn")
SINA_TIMEOUT = _env("SINA_TIMEOUT", "10", int)
SINA_INDEX_TIMEOUT = _env("SINA_INDEX_TIMEOUT", "5", int)

# ── 股息计算 ──
DIVIDEND_LOOKBACK_MONTHS = _env("DIVIDEND_LOOKBACK_MONTHS", "18", int)

# ── 限流 ──
RATE_LIMIT_PER_MINUTE = _env("RATE_LIMIT_PER_MINUTE", "30", int)

# ── 日志 ──
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_DIR = _env("LOG_DIR", str(_PROJECT_ROOT / "logs"))

# ── 默认管理员 ──
DEFAULT_ADMIN_USER = _env("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = _env("DEFAULT_ADMIN_PASSWORD", "admin123")
