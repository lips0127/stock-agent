"""策略管理 API — 列出已注册的策略类型，管理策略实例。"""

import logging
from flask import Blueprint, jsonify

# 导入策略模块以触发 @register 装饰器
import backend.strategy.examples.ma_cross  # noqa: F401

from backend.strategy.registry import list_strategies, get as get_strategy_cls
from backend.api.middleware import login_required

logger = logging.getLogger(__name__)

strategies_bp = Blueprint("strategies", __name__)


@strategies_bp.route("/api/strategies", methods=["GET"])
@login_required
def get_strategies():
    """列出所有已注册的策略类型（含默认参数、关注标的等元信息）。"""
    items = []
    for name in list_strategies():
        cls = get_strategy_cls(name)
        if cls is None:
            continue
        items.append({
            "name": name,
            "class_name": cls.__name__,
            "params": cls.params,
            "symbols": cls.symbols,
            "timeframes": cls.timeframes,
            "doc": (cls.__doc__ or "").strip(),
        })
    return jsonify(items)


@strategies_bp.route("/api/strategies/<name>", methods=["GET"])
@login_required
def get_strategy(name):
    """获取单个策略的详细信息。"""
    cls = get_strategy_cls(name)
    if cls is None:
        return jsonify({"error": f"策略 '{name}' 未注册"}), 404
    return jsonify({
        "name": name,
        "class_name": cls.__name__,
        "params": cls.params,
        "symbols": cls.symbols,
        "timeframes": cls.timeframes,
        "doc": (cls.__doc__ or "").strip(),
    })
