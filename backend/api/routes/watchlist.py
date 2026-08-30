"""自选股观察池路由 — 个人研究关注列表（Core）。

报价聚合带 source/as-of/coverage/degraded 元数据（SPEC §3）；
仅研究浏览用途，不构成任何交易信号。
"""

import logging

from flask import Blueprint, jsonify, request

from backend.api.middleware import login_required
from backend.services import watchlist_service

logger = logging.getLogger(__name__)

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    """观察池 + 实时报价聚合（部分失败显式 degraded，不伪装成完整快照）。"""
    stocks = watchlist_service.list_watch_stocks()
    quotes = watchlist_service.fetch_watch_quotes(stocks)
    return jsonify(quotes)


@watchlist_bp.route("/api/watchlist", methods=["POST"])
@login_required
def add_watch_stock():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", ""))
    try:
        stock, created = watchlist_service.add_watch_stock(
            code,
            name=str(data.get("name", "")).strip(),
            note=str(data.get("note", "")).strip(),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"stock": stock, "created": created}), (201 if created else 200)


@watchlist_bp.route("/api/watchlist/<code>", methods=["PATCH"])
@login_required
def update_watch_stock(code):
    data = request.get_json(silent=True) or {}
    if "note" not in data:
        return jsonify({"error": "缺少 note 字段"}), 400
    try:
        stock = watchlist_service.update_watch_stock(code, note=data.get("note"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if stock is None:
        return jsonify({"error": "自选股不存在"}), 404
    return jsonify({"stock": stock})


@watchlist_bp.route("/api/watchlist/<code>", methods=["DELETE"])
@login_required
def remove_watch_stock(code):
    try:
        removed = watchlist_service.remove_watch_stock(code)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not removed:
        return jsonify({"error": "自选股不存在"}), 404
    return jsonify({"removed": code})
