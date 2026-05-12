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
import logging
import os

from backend.core.logging_config import setup_logging
from backend.core.database import init_db
from backend.api.middleware import init_cors
from backend.api.routes.auth import auth_bp
from backend.api.routes.market import market_bp
from backend.api.routes.stock import stock_bp
from backend.api.routes.ops import ops_bp
from backend.api.routes.sentiment import sentiment_bp, init_stock_cache
from backend.api.routes.strategies import strategies_bp
from backend.api.routes.backtest import backtest_bp
from backend.api.routes.quant import quant_bp
from backend.services.scheduler import init_scheduler

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Flask 应用工厂。"""
    app = Flask(__name__)

    # 初始化顺序：日志 → 数据库 → CORS → 调度器
    setup_logging()
    init_db()
    init_cors(app)
    init_scheduler()

    # 注册 Blueprint 路由
    app.register_blueprint(auth_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(sentiment_bp)
    app.register_blueprint(strategies_bp)
    app.register_blueprint(backtest_bp)
    app.register_blueprint(quant_bp)
    init_stock_cache()  # 预加载股票名称缓存，避免首次搜索卡顿

    # 每个请求进来时打印详细路由信息
    @app.before_request
    def log_request():
        try:
            body = request.get_data(as_text=True)
            body_display = body[:200] if body else "(empty)"
        except Exception:
            body_display = "(read error)"
        logger.info(
            f"--> {request.method} {request.path} | "
            f"args={dict(request.args)} | "
            f"body={body_display}"
        )

    @app.after_request
    def log_response(response):
        try:
            is_direct = bool(getattr(response, "_is_legacy_direct_passthrough", False))
        except Exception:
            is_direct = True
        if is_direct:
            logger.info(f"<-- {request.method} {request.path} {response.status_code} | (static file)")
            return response
        ct = response.content_type or ""
        if "application/json" in ct or "text/" in ct:
            try:
                body = response.get_data(as_text=True)
            except Exception as e:
                body = f"(read error: {e})"
        else:
            body = f"({response.content_type or 'unknown type'})"
        try:
            logger.info(
                f"<-- {request.method} {request.path} {response.status_code} | "
                f"body={body[:600] if body else '-'}"
            )
        except Exception:
            pass
        return response

    # 前端静态页面（开发模式备用，生产环境由 Nginx 托管 dist/）
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')

    @app.route('/')
    def index():
        return send_from_directory(frontend_dir, 'index.html')

    @app.route('/assets/<path:filename>')
    def serve_assets(filename):
        return send_from_directory(os.path.join(frontend_dir, 'assets'), filename)

    # 前端路由兜底：所有非 API 路径都返回 index.html，让 Vue Router 接管
    @app.route('/<path:path>')
    def serve_frontend(path):
        # 避免拦截 API 路由
        if path.startswith('api/'):
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(frontend_dir, 'index.html')

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
