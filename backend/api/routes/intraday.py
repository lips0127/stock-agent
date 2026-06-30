"""市场分时K线数据 API 路由。"""

import logging
from flask import Blueprint, jsonify, request

from backend.data.intraday import get_intraday_bars
from backend.api.middleware import login_required

intraday_bp = Blueprint("intraday", __name__)
logger = logging.getLogger(__name__)


@intraday_bp.route("/api/market/intraday", methods=["GET"])
@login_required
def get_intraday():
    """获取指数分时K线数据。"""
    symbol = request.args.get("symbol", "sh000001")
    interval = request.args.get("interval", "30min")
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 14))
    data = get_intraday_bars(symbol, interval=interval, days=days)
    return jsonify(data)
