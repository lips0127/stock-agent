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

# ── 前端开发代理 ──
# dev 模式下 Flask 启动时自动 spawn Vite 子进程，前端请求代理到 Vite，
# 实现「改 .vue 立即生效」无需 build。生产环境关掉即可走 dist/。
FRONTEND_DEV_PROXY = _env("FRONTEND_DEV_PROXY", "true", bool)
VITE_PORT = _env("VITE_PORT", "5173", int)

# ── JWT ──
# 不再保留公开的弱默认值（旧值 "change-me-in-production-256bit" 可被攻击者用来伪造任意
# JWT 绕过鉴权）。未显式配置时生成一个进程内随机密钥：本地开发可用，但进程重启后所有
# 已签发 token 失效、多 worker 间 token 不互通 —— 部署时必须显式设置 JWT_SECRET。
_raw_jwt_secret = _env("JWT_SECRET", "")
if _raw_jwt_secret:
    JWT_SECRET = _raw_jwt_secret
else:
    import secrets as _secrets
    import logging as _logging
    JWT_SECRET = _secrets.token_urlsafe(48)
    _logging.getLogger(__name__).warning(
        "JWT_SECRET 未配置，已生成进程内随机密钥（重启后 token 失效、多 worker 不互通）。"
        "生产/多 worker 部署务必在 .env 中设置固定的 JWT_SECRET。"
    )
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = _env("JWT_EXPIRATION_HOURS", "2", int)

# ── 调度器 ──
SCHEDULER_ENABLED = _env("SCHEDULER_ENABLED", "true", bool)
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

# ── Tencent 行情 API（HTTPS，最稳定） ──
TENCENT_HQ_URL = _env("TENCENT_HQ_URL", "https://qt.gtimg.cn/q=")
TENCENT_TIMEOUT = _env("TENCENT_TIMEOUT", "10", int)

# ── 通用浏览器 UA（避免被反爬） ──
BROWSER_USER_AGENT = _env(
    "BROWSER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# ── 行情源重试 ──
HQ_SOURCE_RETRIES = _env("HQ_SOURCE_RETRIES", "2", int)
HQ_SOURCE_RETRY_BACKOFF = _env("HQ_SOURCE_RETRY_BACKOFF", "0.5", float)

# ── 股息计算 ──
DIVIDEND_LOOKBACK_MONTHS = _env("DIVIDEND_LOOKBACK_MONTHS", "18", int)

# ── 限流 ──
RATE_LIMIT_PER_MINUTE = _env("RATE_LIMIT_PER_MINUTE", "30", int)
# 登录接口专用更严格限流（缓解密码爆破）
LOGIN_RATE_LIMIT_PER_MINUTE = _env("LOGIN_RATE_LIMIT_PER_MINUTE", "10", int)

# ── 安全响应头 ──
# 在容器前置了 TLS（云负载均衡 / Caddy / Nginx 等）终止时置 true，下发 HSTS。
# 本地 HTTP 调试保持 false，避免浏览器强制 https。
ENABLE_HSTS = _env("ENABLE_HSTS", "false", bool)

# ── 日志 ──
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_DIR = _env("LOG_DIR", str(_PROJECT_ROOT / "logs"))

# ── 默认管理员 ──
DEFAULT_ADMIN_USER = _env("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = _env("DEFAULT_ADMIN_PASSWORD", "admin123")

# ── guba 论坛抓取网络韧性（v1, 2026-06-04）──
GUBA_CB_FAILURE_THRESHOLD = _env("GUBA_CB_FAILURE_THRESHOLD", "3", int)
GUBA_CB_COOLDOWN_SECONDS = _env("GUBA_CB_COOLDOWN_SECONDS", "60", float)
GUBA_HTTP_RETRIES = _env("GUBA_HTTP_RETRIES", "1", int)
GUBA_HTTP_RETRY_BACKOFF = _env("GUBA_HTTP_RETRY_BACKOFF", "0.5", float)
GUBA_AUDIT_MAX_WORKERS = _env("GUBA_AUDIT_MAX_WORKERS", "4", int)
GUBA_PREFETCH_INTERVAL_HOURS = _env("GUBA_PREFETCH_INTERVAL_HOURS", "2", int)
# v9 2026-08-31：guba 引导壳为速率型间歇反爬（与 cookie 无关），详情页全局节流 +
# 单次正文补抓上限（旧实现补抓 DB 全量无正文帖子，单股数千条必然触发反爬）。
GUBA_DETAIL_MIN_INTERVAL = _env("GUBA_DETAIL_MIN_INTERVAL", "0.8", float)
GUBA_BACKFILL_MAX_PER_RUN = _env("GUBA_BACKFILL_MAX_PER_RUN", "150", int)

# ── 全市场舆情观测台（v4, 2026-06-06）──
# 6 指数的成分股每周日 17:00 拉一次（指数再平衡是季度级，无需日更）
UNIVERSE_CONSTITUENT_REFRESH_DOW = _env("UNIVERSE_CONSTITUENT_REFRESH_DOW", "sun")
UNIVERSE_CONSTITUENT_REFRESH_HOUR = _env("UNIVERSE_CONSTITUENT_REFRESH_HOUR", "17", int)
UNIVERSE_CONSTITUENT_REFRESH_MINUTE = _env("UNIVERSE_CONSTITUENT_REFRESH_MINUTE", "0", int)
# 工作日 18:00 跑全量情绪（避开 16:35 indicators_recompute，给 90min buffer）
UNIVERSE_CRAWL_HOUR = _env("UNIVERSE_CRAWL_HOUR", "18", int)
UNIVERSE_CRAWL_MINUTE = _env("UNIVERSE_CRAWL_MINUTE", "0", int)
# 19:30 跑指数级聚合（crawl 完 1.5h 后，保证所有分数都落库）
UNIVERSE_AGG_HOUR = _env("UNIVERSE_AGG_HOUR", "19", int)
UNIVERSE_AGG_MINUTE = _env("UNIVERSE_AGG_MINUTE", "30", int)
UNIVERSE_CRAWL_MAX_WORKERS = _env("UNIVERSE_CRAWL_MAX_WORKERS", "8", int)
UNIVERSE_CRAWL_STOCK_DELAY_S = _env("UNIVERSE_CRAWL_STOCK_DELAY_S", "0.5", float)
SENTIMENT_TOP_PICKS_ANALYZE_LIMIT = _env("SENTIMENT_TOP_PICKS_ANALYZE_LIMIT", "20", int)
