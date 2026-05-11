import logging
from flask import Blueprint, jsonify
from backend.services.stock_service import get_stock_metrics
from backend.api.middleware import login_required

stock_bp = Blueprint("stock", __name__)
logger = logging.getLogger(__name__)


@stock_bp.route("/api/stock/<symbol>", methods=["GET"])
@login_required
def get_stock(symbol):
    try:
        data = get_stock_metrics(symbol)
        return jsonify({
            "code": symbol,
            "name": data["名称"],
            "price": data["最新价"],
            "dividend_yield": data["股息率"],
            "dividend_per_share": data["每股分红"],
            "dividend_note": data["分红备注"],
        })
    except Exception as e:
        logger.error(f"Error fetching stock {symbol}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400
