import time
import functools
import jwt
from flask import request, jsonify, g
from flask_cors import CORS
from backend.config import (
    CORS_ORIGINS,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    RATE_LIMIT_PER_MINUTE,
)

def init_cors(app):
    """初始化 CORS 配置。"""
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    CORS(app, origins=origins, methods=["GET", "POST", "OPTIONS"])


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
        return None
    except jwt.InvalidTokenError:
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
        g.current_user = payload["sub"]
        return f(*args, **kwargs)
    return decorated


_request_times: dict[str, list[float]] = {}


def rate_limit(f):
    """装饰器：每个 IP 每分钟限制请求数。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        now = time.time()
        times = _request_times.setdefault(ip, [])
        times[:] = [t for t in times if now - t < 60]
        if len(times) >= RATE_LIMIT_PER_MINUTE:
            return jsonify({"error": "Rate limit exceeded"}), 429
        times.append(now)
        return f(*args, **kwargs)
    return decorated
