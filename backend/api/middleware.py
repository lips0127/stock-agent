import time
import functools
import logging
import threading
import jwt
from flask import request, jsonify, g
from flask_cors import CORS
from backend.config import (
    CORS_ORIGINS,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    RATE_LIMIT_PER_MINUTE,
    LOGIN_RATE_LIMIT_PER_MINUTE,
    ENABLE_HSTS,
)

logger = logging.getLogger(__name__)

# SPA 文档 CSP：Vite 产物全部为外部 /assets 脚本，无内联脚本；
# Element Plus / ECharts 需要内联样式，故 style-src 保留 unsafe-inline。
_DOCUMENT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def install_security_headers(app):
    """为所有响应附加安全头；CSP 只作用于 HTML 文档，API JSON 不受影响。

    - X-Content-Type-Options / X-Frame-Options / Referrer-Policy：全响应。
    - Content-Security-Policy：仅 text/html（前端页面），限制脚本/连接来源并禁 iframe 嵌套。
    - Strict-Transport-Security：仅当 ENABLE_HSTS=true（前置 TLS 终止时开启）。
    """
    @app.after_request
    def _apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        content_type = (response.content_type or "").lower()
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", _DOCUMENT_CSP)
        if ENABLE_HSTS:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    return app


def init_cors(app):
    """初始化 CORS 配置。"""
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    CORS(
        app,
        origins=origins,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def generate_token(username: str) -> str:
    """为已认证用户生成 JWT token。"""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRATION_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict | None:
    """验证 JWT token，返回 payload 或 None。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT token 无效: {type(e).__name__}")
        return None


def login_required(f):
    """装饰器：要求请求携带有效 JWT token。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 401
        token = auth_header[7:]
        payload = verify_token(token)
        if payload is None:
            return jsonify({"error": "Token expired or invalid"}), 401
        sub = payload.get("sub")
        if not sub:
            # 无主体的 token 不应导致 500，而是按未认证处理
            return jsonify({"error": "Token expired or invalid"}), 401
        g.current_user = sub
        return f(*args, **kwargs)
    return decorated


# 进程内滑动窗口限流。线程安全（gevent worker + 调度线程并发访问），
# 桶数量有界，防止恶意伪造 IP 刷爆内存。多进程部署下各进程独立计数，
# 仅作为第一道防线；严格限流需要共享存储，此处按单实例产品语义实现。
_request_times: dict[str, list[float]] = {}
_rate_lock = threading.Lock()
_MAX_RATE_BUCKETS = 10000


def _hit_rate_bucket(key: str, limit: int, window_seconds: int = 60) -> bool:
    """在限流桶上记录一次访问。返回 True 表示放行，False 表示超限。"""
    now = time.time()
    allowed = False
    with _rate_lock:
        times = _request_times.setdefault(key, [])
        times[:] = [t for t in times if now - t < window_seconds]
        if len(times) < limit:
            times.append(now)
            allowed = True
        if len(_request_times) > _MAX_RATE_BUCKETS:
            # 淘汰最久未活跃的桶
            oldest_key = min(
                _request_times,
                key=lambda k: _request_times[k][-1] if _request_times[k] else 0.0,
            )
            if oldest_key != key:
                _request_times.pop(oldest_key, None)
    return allowed


def rate_limit(f):
    """装饰器：每个 IP 每分钟限制请求数。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        if not _hit_rate_bucket(f"req:{ip}", RATE_LIMIT_PER_MINUTE):
            return jsonify({"error": "Rate limit exceeded"}), 429
        return f(*args, **kwargs)
    return decorated


def login_rate_limit(f):
    """装饰器：登录接口专用更严格限流，缓解密码爆破。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        if not _hit_rate_bucket(f"login:{ip}", LOGIN_RATE_LIMIT_PER_MINUTE):
            logger.warning(f"登录限流触发（疑似爆破尝试）: ip={ip}")
            return jsonify({"success": False, "message": "尝试过于频繁，请稍后再试"}), 429
        return f(*args, **kwargs)
    return decorated
