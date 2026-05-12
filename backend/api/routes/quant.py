"""量化交易辅助 API — 组合快照、持仓、风控规则。"""

import logging
from flask import Blueprint, jsonify

from backend.core.database import get_connection
from backend.api.middleware import login_required

logger = logging.getLogger(__name__)

quant_bp = Blueprint("quant", __name__)


@quant_bp.route("/api/quant/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    """获取最新一次组合快照（来自回测的终值快照）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM portfolio_snapshots
               ORDER BY date DESC, id DESC LIMIT 1"""
        )
        row = cur.fetchone()
        if not row:
            return jsonify({
                "total_value": 0,
                "cash": 0,
                "positions_value": 0,
                "daily_pnl": 0,
                "cumulative_pnl": 0,
                "daily_return": 0,
            })
        return jsonify(dict(row))


@quant_bp.route("/api/quant/positions", methods=["GET"])
@login_required
def get_positions():
    """获取当前持仓列表（来自 DB positions 表）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM positions WHERE quantity != 0 ORDER BY symbol"
        )
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@quant_bp.route("/api/quant/snapshots", methods=["GET"])
@login_required
def get_snapshots():
    """获取组合净值历史快照（来自最近一次回测的 equity_curve）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY date ASC LIMIT 500"
        )
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@quant_bp.route("/api/quant/risk/rules", methods=["GET"])
@login_required
def get_risk_rules():
    """获取可用的风控规则说明。"""
    rules = [
        {
            "name": "MaxPositionRule",
            "description": "限制单只股票持仓占总资产的最大比例",
            "params": {"max_ratio": "float (0~1)，例如 0.3 表示单票不超过 30%"},
        },
        {
            "name": "OrderSizeRule",
            "description": "限制单笔订单金额上限",
            "params": {"max_amount": "float，例如 50000 表示单笔不超过 5 万"},
        },
        {
            "name": "DailyLossLimitRule",
            "description": "当日累计亏损达到阈值后禁止开仓",
            "params": {"max_loss_ratio": "float (0~1)，例如 0.05 表示日亏 5% 即停止"},
        },
    ]
    return jsonify(rules)
