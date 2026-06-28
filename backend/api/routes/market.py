from flask import Blueprint, request, jsonify
from datetime import date
import logging

from backend.core.database import get_connection
from backend.api.middleware import rate_limit
from backend.services.stock_service import get_sina_index_spot

logger = logging.getLogger(__name__)

market_bp = Blueprint("market", __name__)

# 排除 ST/*ST/退市 股票：其崩塌股价 + 往年正常分红会算出异常股息率，污染排名。
# 与扫描层 stock_service.is_risk_stock 保持同一规则；此处兜底过滤 DB 中历史遗留行。
_EXCLUDE_RISK_SQL = "AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'"

INDEX_SYMBOLS = {
    "s_sh000001": "上证指数",
    "s_sz399001": "深证成指",
    "s_sz399006": "创业板指",
    "s_sh000688": "科创50",
    "s_sh000012": "国债指数",
}


@market_bp.route("/api/indices", methods=["GET"])
def get_indices():
    """从 DB 获取最后一次扫描时的大盘指数（可能滞后）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM market_indices")
        row = cur.fetchone()
        latest_date = row[0] if row and row[0] else date.today().isoformat()
        cur.execute(
            "SELECT * FROM market_indices WHERE date = ?",
            (latest_date,)
        )
        columns = [desc[0] for desc in cur.description]
        indices = [dict(zip(columns, row)) for row in cur.fetchall()]
    return jsonify(indices)


@market_bp.route("/api/indices/live", methods=["GET"])
def get_indices_live():
    """实时从新浪获取大盘指数。"""
    results = []
    for symbol, expected_name in INDEX_SYMBOLS.items():
        try:
            data = get_sina_index_spot(symbol)
            if data:
                results.append({
                    "symbol": symbol.replace("s_", ""),
                    "name": data["name"],
                    "value": data["current"],
                    "change_amount": data["change_amount"],
                    "change_pct": data["change_pct"],
                })
        except Exception as e:
            logger.warning(f"获取实时指数 {symbol} 失败: {e}", exc_info=True)
    return jsonify(results)


@market_bp.route("/api/top_stocks", methods=["GET"])
@rate_limit
def get_top_stocks():
    """获取高股息股票 TOP N（优先取全市场扫描结果）。"""
    limit = request.args.get("limit", 20, type=int)
    if limit < 1 or limit > 100:
        limit = 20
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM stock_daily_metrics")
        row = cur.fetchone()
        latest_date = row[0] if row and row[0] else date.today().isoformat()

        # 优先取全市场扫描数据，若无则回退到全部
        cur.execute(
            "SELECT COUNT(*) FROM stock_daily_metrics WHERE date = ? AND scan_type = 'full'",
            (latest_date,),
        )
        full_count = cur.fetchone()[0]
        if full_count > 0:
            cur.execute(
                f"SELECT * FROM stock_daily_metrics WHERE date = ? AND scan_type = 'full' {_EXCLUDE_RISK_SQL} ORDER BY dividend_yield DESC LIMIT ?",
                (latest_date, limit),
            )
        else:
            cur.execute(
                f"SELECT * FROM stock_daily_metrics WHERE date = ? {_EXCLUDE_RISK_SQL} ORDER BY dividend_yield DESC LIMIT ?",
                (latest_date, limit),
            )
        columns = [desc[0] for desc in cur.description]
        top_stocks = [dict(zip(columns, row)) for row in cur.fetchall()]
    return jsonify(top_stocks)


@market_bp.route("/api/all_stocks", methods=["GET"])
@rate_limit
def get_all_stocks():
    """获取最新扫描日期的全部股票，带分页。

    可选 `scan_type`（'index' / 'full'）：指定时按该扫描类型取其**自身最近一次**
    扫描日期的数据（红利指数页用 'index'，避免被当日全市场扫描掩盖）；
    不指定时沿用旧逻辑——优先全市场（full），无则回退全部。
    """
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 100, type=int)
    scan_type = request.args.get("scan_type", type=str)
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 100
    offset = (page - 1) * page_size

    with get_connection() as conn:
        cur = conn.cursor()

        if scan_type in ("index", "full"):
            # 指定扫描类型：取该类型自身最近一次的扫描日期
            cur.execute(
                "SELECT MAX(date) FROM stock_daily_metrics WHERE scan_type = ?",
                (scan_type,),
            )
            row = cur.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            scan_filter = "AND scan_type = ?"
            scan_params = (scan_type,)
        else:
            cur.execute("SELECT MAX(date) FROM stock_daily_metrics")
            row = cur.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            # 优先取全市场扫描数据，若无则回退到全部
            cur.execute(
                "SELECT COUNT(*) FROM stock_daily_metrics WHERE date = ? AND scan_type = 'full'",
                (latest_date,),
            )
            full_count = cur.fetchone()[0]
            scan_filter = "AND scan_type = 'full'" if full_count > 0 else ""
            scan_params = ()

        # 总数
        cur.execute(
            f"SELECT COUNT(*) FROM stock_daily_metrics WHERE date = ? {scan_filter} {_EXCLUDE_RISK_SQL}",
            (latest_date, *scan_params),
        )
        total = cur.fetchone()[0]

        # 分页数据
        cur.execute(
            f"""SELECT * FROM stock_daily_metrics
               WHERE date = ? {scan_filter} {_EXCLUDE_RISK_SQL} ORDER BY dividend_yield DESC
               LIMIT ? OFFSET ?""",
            (latest_date, *scan_params, page_size, offset),
        )
        columns = [desc[0] for desc in cur.description]
        stocks = [dict(zip(columns, row)) for row in cur.fetchall()]

    return jsonify({
        "date": latest_date,
        "total": total,
        "page": page,
        "page_size": page_size,
        "stocks": stocks
    })
