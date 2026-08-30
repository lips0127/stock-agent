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
    except Exception:
        # 上游行情源异常：不得把内部错误串回显给客户端
        logger.error(f"Error fetching stock {symbol}", exc_info=True)
        return jsonify({"error": "行情源暂时不可用，请稍后重试", "degraded": True}), 502
    if data is None:
        # 所有数据源都拿不到行情：代码不存在或源全部失败
        return jsonify({"error": "无法获取该股票行情，请确认代码是否正确或稍后重试"}), 404
    return jsonify({
        "code": symbol,
        "name": data["名称"],
        "price": data["最新价"],
        "dividend_yield": data["股息率"],
        "dividend_per_share": data["每股分红"],
        "dividend_note": data["分红备注"],
    })
