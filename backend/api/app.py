from flask import Flask, jsonify, send_from_directory
import logging
import os

from backend.core.logging_config import setup_logging
from backend.core.database import init_db
from backend.api.middleware import init_cors
from backend.api.routes.auth import auth_bp
from backend.api.routes.market import market_bp
from backend.api.routes.stock import stock_bp
from backend.api.routes.ops import ops_bp
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

    # 前端静态页面（开发模式备用，生产环境由 Nginx 托管 dist/）
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')

    @app.route('/')
    def index():
        return send_from_directory(frontend_dir, 'index.html')

    # 全局错误处理
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == '__main__':
    from backend.config import HOST, PORT, DEBUG
    app = create_app()
    app.run(host=HOST, port=PORT, debug=DEBUG)
