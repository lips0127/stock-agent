"""财报解析 API 路由。"""

import logging

from flask import Blueprint, jsonify, request

from backend.api.middleware import login_required
from backend.services.report_parser import parse_financial_report
from backend.services.financial_service import get_financial_data
from backend.services.stock_service import get_stock_metrics

logger = logging.getLogger(__name__)

financial_bp = Blueprint("financial", __name__)


@financial_bp.route("/api/financial/parse", methods=["POST"])
@login_required
def parse_report():
    """解析财经报告文本，提取公司列表（仅 LLM 解析，不含财务数据）。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()

    if not text:
        return jsonify({"error": "请提供报告文本"}), 400
    if len(text) < 50:
        return jsonify({"error": "报告文本过短，至少需要50字"}), 400

    result = parse_financial_report(text)
    if result.get("error"):
        return jsonify(result), 500

    return jsonify(result)


@financial_bp.route("/api/financial/analyze", methods=["POST"])
@login_required
def analyze_report():
    """一站式：解析报告 + 拉取每家公司财务数据。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()

    if not text:
        return jsonify({"error": "请提供报告文本"}), 400
    if len(text) < 50:
        return jsonify({"error": "报告文本过短，至少需要50字"}), 400

    # Step 1: LLM 解析
    parsed = parse_financial_report(text)
    if parsed.get("error"):
        return jsonify(parsed), 500

    companies = parsed.get("companies", [])

    # Step 2: 对每家公司拉取价格 + 财务数据
    enriched = []
    for c in companies:
        entry = dict(c)
        code = c.get("code")
        if code:
            # 价格
            try:
                metrics = get_stock_metrics(code)
                if metrics:
                    entry["price"] = metrics.get("最新价")
                    if not entry.get("name") or entry["name"] == c.get("name"):
                        entry["name"] = metrics.get("名称") or c.get("name")
            except Exception as e:
                logger.warning(f"获取股价失败 {code}: {e}")

            # 财务数据
            try:
                fin = get_financial_data(code)
                if fin:
                    # 透传所有财务/行情字段（route 是 passthrough）
                    for k in [
                        "ttm_revenue", "ttm_net_profit", "ttm_gross_profit", "ttm_eps",
                        "ttm_pe", "ttm_pe_percentile", "ttm_pe_percentile_basis",
                        "quarters", "report_date", "price_history", "pe_history",
                        "total_market_cap", "float_market_cap",
                        "total_shares", "float_shares", "eastmoney_url",
                    ]:
                        if k in fin and fin[k] is not None:
                            entry[k] = fin[k]
                    if not entry.get("price") and fin.get("price"):
                        entry["price"] = fin.get("price")
            except Exception as e:
                logger.warning(f"获取财务数据失败 {code}: {e}")
        enriched.append(entry)

    return jsonify({
        "companies": enriched,
        "summary": parsed.get("summary", ""),
    })
