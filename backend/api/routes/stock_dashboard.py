"""公司增强看板 API：聚合 stock_metrics + 财务数据 + 情绪历史，一次性返回。"""

import logging

from flask import Blueprint, jsonify, request

from backend.api.middleware import login_required
from backend.services.financial_service import get_financial_data
from backend.services.stock_service import get_stock_metrics
from backend.services.sentiment_service import get_sentiment_history

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/api/stock/<symbol>/dashboard", methods=["GET"])
@login_required
def get_dashboard(symbol: str):
    """一站式公司增强看板。

    字段来源：
      - stock_metrics: 名称、最新价
      - financial_service: TTM 财务、市值、PE 百分位、季度表、PE/K 线历史（6h 缓存）
      - sentiment_history: 情绪分数 + 极端信号（按 ?days= 控制，默认 60）
    """
    code = str(symbol).strip().zfill(6)
    days = request.args.get("days", 60, type=int)
    include_sentiment = request.args.get("sentiment", "1") != "0"

    result = {
        "code": code,
        "name": None,
        "price": None,
        "metrics": None,
        "financial": None,
        "sentiment": None,
    }

    # 1) stock_metrics（轻量、走缓存）
    try:
        m = get_stock_metrics(code) or {}
        result["name"] = m.get("名称") or code
        result["price"] = m.get("最新价")
        result["metrics"] = m
    except Exception as e:
        logger.warning(f"dashboard 获取 stock_metrics 失败 {code}: {e}")

    # 2) 财务 + 估值（6h 缓存复用）
    try:
        fin = get_financial_data(code) or {}
        result["financial"] = fin
        if not result["name"] or result["name"] == code:
            result["name"] = fin.get("name") or result["name"]
        if result["price"] is None and fin.get("price") is not None:
            result["price"] = fin.get("price")
    except Exception as e:
        logger.warning(f"dashboard 获取 financial 失败 {code}: {e}")

    # 3) 情绪历史（按需）
    if include_sentiment:
        try:
            history = get_sentiment_history(code, forum_type="eastmoney", days=days)
            # 按日期升序 + 简化字段，前端只需 date/score/sentiment/signals
            slim = [
                {
                    "date": h.get("date"),
                    "score": h.get("score"),
                    "sentiment": h.get("sentiment"),
                    "signals": h.get("signals") or {},
                    "summary": h.get("summary"),
                }
                for h in history
                if h.get("date")
            ]
            slim.sort(key=lambda r: r["date"])
            result["sentiment"] = slim
        except Exception as e:
            logger.warning(f"dashboard 获取 sentiment 失败 {code}: {e}")

    return jsonify(result)
