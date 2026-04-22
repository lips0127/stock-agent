from flask import Flask, jsonify, request
from contextlib import contextmanager
import sqlite3
import logging
from datetime import date

from backend.config import DB_PATH as DB_FILE
from backend.core.database import init_db, authenticate_user
from backend.core.logging_config import setup_logging
from backend.services.stock_service import get_stock_metrics
from backend.services.scanner_service import get_high_dividend_stocks_by_concept
from backend.services.scheduler import init_scheduler, manual_trigger, task_logs
from backend.api.middleware import init_cors, login_required, rate_limit, generate_token

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Flask 应用工厂。"""
    app = Flask(__name__)

    setup_logging()
    init_db()
    init_cors(app)
    init_scheduler()

    @contextmanager
    def get_db_connection():
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @app.route('/api/login', methods=['POST'])
    def login():
        data = request.json or {}
        username = data.get('username', '')
        password = data.get('password', '')
        if authenticate_user(username, password):
            token = generate_token(username)
            return jsonify({"success": True, "token": token}), 200
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    @app.route('/api/indices', methods=['GET'])
    @login_required
    def get_indices():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM market_indices")
            row = cursor.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            indices = conn.execute(
                "SELECT * FROM market_indices WHERE date = ?", (latest_date,)
            ).fetchall()
        return jsonify([dict(ix) for ix in indices])

    @app.route('/api/top_stocks', methods=['GET'])
    @login_required
    @rate_limit
    def get_top_stocks():
        limit = request.args.get('limit', 20, type=int)
        if limit < 1 or limit > 100:
            limit = 20
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM stock_daily_metrics")
            row = cursor.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            top_stocks = conn.execute(
                "SELECT * FROM stock_daily_metrics WHERE date = ? ORDER BY dividend_yield DESC LIMIT ?",
                (latest_date, limit),
            ).fetchall()
        return jsonify([dict(s) for s in top_stocks])

    @app.route('/api/stock/<symbol>', methods=['GET'])
    @login_required
    def get_stock(symbol):
        try:
            data = get_stock_metrics(symbol)
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error fetching stock {symbol}: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 400

    @app.route('/api/refresh', methods=['POST'])
    @login_required
    def refresh_data():
        msg = manual_trigger()
        return jsonify({"message": msg}), 200

    @app.route('/api/logs', methods=['GET'])
    @login_required
    def get_logs():
        return jsonify(task_logs)

    @app.route('/health', methods=['GET'])
    def health_check():
        db_ok = False
        try:
            with get_db_connection() as conn:
                conn.execute("SELECT 1")
            db_ok = True
        except Exception:
            pass
        status = "healthy" if db_ok else "unhealthy"
        code = 200 if db_ok else 503
        return jsonify({"status": status, "database": db_ok}), code

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
