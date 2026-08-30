# 全局禁用 tqdm 进度条（必须在所有 akshare 导入之前打补丁）
import tqdm
import logging as _logging


class _SilentTqdm(tqdm.tqdm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('disable', True)
        super().__init__(*args, **kwargs)


tqdm.tqdm = _SilentTqdm

# 同步 sys.modules 中其他模块对 tqdm 的引用
import sys
for name, mod in list(sys.modules.items()):
    if 'tqdm' in name and hasattr(mod, 'tqdm') and mod.tqdm is not _SilentTqdm:
        try:
            mod.tqdm = _SilentTqdm
        except Exception as _e:
            _logging.getLogger(__name__).debug(f"替换 tqdm 引用失败 ({name}): {_e}")

from flask import Flask, jsonify, send_from_directory, request
import atexit
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import requests as _requests

# 全局代理强制直连（2026-06-15 修复 82.push2.eastmoney.com 走 Clash 被掐断）
# 必须在任何 Blueprint / service 导入之前执行。
from backend.core.proxy_bypass import install_proxy_bypass
install_proxy_bypass()

from backend.config import (
    HOST,
    PORT,
    DEBUG,
    FRONTEND_DEV_PROXY,
    VITE_PORT,
    SCHEDULER_ENABLED,
)
from backend.core.logging_config import setup_logging
from backend.core.database import init_db, cleanup_orphan_task_runs
from backend.api.middleware import init_cors, install_security_headers
from backend.api.routes.auth import auth_bp
from backend.api.routes.market import market_bp
from backend.api.routes.stock import stock_bp
from backend.api.routes.watchlist import watchlist_bp
from backend.api.routes.ops import ops_bp
from backend.api.routes.sentiment import sentiment_bp, init_stock_cache
from backend.api.routes.intraday import intraday_bp
from backend.api.routes.vix import vix_bp
from backend.api.routes.vix2 import vix2_bp
from backend.api.routes.scheduler import scheduler_bp
from backend.api.routes.tasks import tasks_bp
from backend.api.routes.financial import financial_bp
from backend.api.routes.stock_dashboard import dashboard_bp
from backend.api.routes.tenbag import tenbag_bp
from backend.services.scheduler import init_scheduler

logger = logging.getLogger(__name__)

_SENSITIVE_QUERY_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "smtp",
)


def _redacted_query_args() -> dict[str, str | list[str]]:
    """Return diagnostic query args without exposing credential-like values."""
    redacted: dict[str, str | list[str]] = {}
    for key, values in request.args.lists():
        normalized_key = key.casefold()
        safe_values = (
            ["[REDACTED]"]
            if any(fragment in normalized_key for fragment in _SENSITIVE_QUERY_KEY_FRAGMENTS)
            else values
        )
        redacted[key] = safe_values[0] if len(safe_values) == 1 else safe_values
    return redacted

VITE_DEV_URL = f"http://localhost:{VITE_PORT}"
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_vite_process: subprocess.Popen | None = None


def _terminate_vite_subprocess() -> None:
    """进程退出时回收 Flask 拉起的 Vite 子进程，避免 npm 残留占用端口。"""
    global _vite_process
    if _vite_process is not None and _vite_process.poll() is None:
        try:
            _vite_process.terminate()
            _vite_process.wait(timeout=5)
        except Exception as e:
            logger.debug(f"回收 Vite 子进程失败: {e}")
    _vite_process = None


def _vite_reachable() -> bool:
    """检查 Vite dev server 是否在跑。"""
    try:
        r = _requests.get(VITE_DEV_URL, timeout=0.5)
        return r.status_code < 500
    except Exception:
        return False


def _start_vite_subprocess() -> None:
    """若 Vite 不可达且 node_modules 已装，作为子进程拉起 Vite。"""
    global _vite_process
    if _vite_reachable():
        logger.info(f"Vite dev server 已在运行: {VITE_DEV_URL}")
        return
    if not (_FRONTEND_DIR / "node_modules").exists():
        logger.warning(
            f"未找到 {_FRONTEND_DIR / 'node_modules'}，跳过自动启动 Vite。"
            "请先 `cd frontend && npm install`，或将 FRONTEND_DEV_PROXY=false 回退到 dist/。"
        )
        return
    if not (_FRONTEND_DIR / "package.json").exists():
        logger.warning(f"未找到 {_FRONTEND_DIR / 'package.json'}，跳过自动启动 Vite。")
        return

    logger.info(f"自动启动 Vite dev server (cwd={_FRONTEND_DIR}, port={VITE_PORT})...")
    kwargs = dict(
        cwd=str(_FRONTEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Windows 下避免弹出黑色 console 窗口
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    # Windows 上 npm 是 npm.cmd 批处理，Popen 只解析 .exe，必须用 which 解析完整路径
    npm_exe = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_exe:
        logger.warning(
            "PATH 中找不到 npm，跳过自动启动 Vite。"
            "可手动 `cd frontend && npm run dev`，或 FRONTEND_DEV_PROXY=false 回退到 dist/。"
        )
        return
    try:
        _vite_process = subprocess.Popen(
            [npm_exe, "run", "dev", "--", "--port", str(VITE_PORT)],
            **kwargs,
        )
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"无法启动 Vite: {e}")
        return
    atexit.register(_terminate_vite_subprocess)

    for _ in range(40):  # 最多等 10s
        if _vite_reachable():
            logger.info(f"Vite dev server 已就绪: {VITE_DEV_URL}")
            return
        time.sleep(0.25)
    logger.warning(f"Vite 启动超时（10s），将回退到 dist/。")


# dist/ 静态资源路径（prod 兜底）
_DIST_DIR = _FRONTEND_DIR / "dist"
_DIST_ASSETS = _DIST_DIR / "assets"


def _serve_dist_index():
    if (_DIST_DIR / "index.html").exists():
        return send_from_directory(str(_DIST_DIR), "index.html")
    return jsonify({
        "error": "Frontend not built",
        "hint": "Run `cd frontend && npm run dev` (auto via Flask if FRONTEND_DEV_PROXY=true) "
                "or `cd frontend && npm run build` for static serving.",
    }), 503


def create_app(*, testing: bool = False) -> Flask:
    """Flask 应用工厂。

    ``testing=True`` creates an application without process-level background
    side effects.  Database schema initialization is retained so the test
    client sees the same routes and persistence contract as production, while
    scheduler startup, orphan cleanup, the stock-cache refresh thread and the
    Vite subprocess are deliberately skipped.
    """
    app = Flask(__name__)
    app.config["TESTING"] = testing

    # 初始化顺序：日志 → 数据库 → CORS → 安全头 → 调度器
    setup_logging()
    init_db()
    init_cors(app)
    install_security_headers(app)
    if not testing:
        cleanup_orphan_task_runs()
        if SCHEDULER_ENABLED:
            init_scheduler()

    # 注册 Blueprint 路由
    app.register_blueprint(auth_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(sentiment_bp)
    app.register_blueprint(intraday_bp)
    app.register_blueprint(vix_bp)
    app.register_blueprint(vix2_bp)
    app.register_blueprint(scheduler_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(financial_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tenbag_bp)
    if not testing:
        init_stock_cache()  # 预加载股票名称缓存，避免首次搜索卡顿

    # dev 模式：自动拉起 Vite 子进程，实现「改源码即热更新」
    if FRONTEND_DEV_PROXY and not testing:
        _start_vite_subprocess()

    # 请求日志只保留诊断元数据。不得读取或记录原始 body、认证头或 Cookie。
    @app.before_request
    def log_request():
        logger.info(
            f"--> {request.method} {request.path} | "
            f"args={_redacted_query_args()} | "
            f"content_length={request.content_length}"
        )

    @app.after_request
    def log_response(response):
        logger.info(
            f"<-- {request.method} {request.path} {response.status_code} | "
            f"content_type={response.content_type or 'unknown'} | "
            f"content_length={response.content_length}"
        )
        return response

    # 前端页面：dev 模式 302 重定向到 Vite（5173，由 Flask 自动拉起的子进程），
    # Vite 自己会处理源码 + HMR，并把 /api/* 反向代理回 Flask。
    # prod 模式（Nginx/静态托管）直接返回 dist/ 静态文件。
    from flask import redirect

    @app.route('/')
    def index():
        if FRONTEND_DEV_PROXY and _vite_reachable():
            return redirect(f"http://localhost:{VITE_PORT}/", code=302)
        return _serve_dist_index()

    @app.route('/assets/<path:filename>')
    def serve_assets(filename):
        # prod 静态资源；dev 模式理论上不会到这里（被 catch-all 拦截了）
        if _DIST_ASSETS.exists():
            return send_from_directory(str(_DIST_ASSETS), filename)
        return jsonify({"error": "Not found"}), 404

    # 前端路由兜底：所有非 API 路径都交给 Vite（SPA 路由 + HMR 都在那边）
    @app.route('/<path:path>')
    def serve_frontend(path):
        if path.startswith('api/'):
            return jsonify({"error": "Not found"}), 404
        if FRONTEND_DEV_PROXY and _vite_reachable():
            target = f"http://localhost:{VITE_PORT}/{path}"
            if request.query_string:
                target += "?" + request.query_string.decode("latin-1")
            return redirect(target, code=302)
        return _serve_dist_index()

    # 全局错误处理
    @app.errorhandler(404)
    def not_found(e):
        logger.warning(f"404 Not Found: {request.method} {request.path}")
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        logger.warning(f"405 Method Not Allowed: {request.method} {request.path}")
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == '__main__':
    from backend.config import HOST, PORT, DEBUG
    app = create_app()
    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
