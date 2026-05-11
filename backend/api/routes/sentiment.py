"""舆情监控 API 路由。"""

import logging
import time
from flask import Blueprint, jsonify, request

from backend.core.database import (
    get_sentiment_configs, add_sentiment_config, delete_sentiment_config,
)
from backend.services.sentiment_service import (
    analyze_sentiment, batch_analyze, get_sentiment_history,
)
from backend.api.middleware import login_required

sentiment_bp = Blueprint("sentiment", __name__)
logger = logging.getLogger(__name__)

# 股票名称缓存
import threading
_stock_cache = []
_stock_cache_file = None


def _cache_file_path():
    global _stock_cache_file
    if _stock_cache_file is None:
        from pathlib import Path
        from backend.config import CACHE_DIR
        p = Path(CACHE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        _stock_cache_file = p / "stock_names.json"
    return _stock_cache_file


def init_stock_cache():
    """启动时预加载股票名称缓存（文件缓存 + 后台刷新）。"""
    import json as _json
    cache_file = _cache_file_path()
    # 优先读文件缓存
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = _json.load(f)
            _stock_cache[:] = data
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            logger.info(f"从文件加载股票名称缓存: {len(_stock_cache)} 条 (age={age_hours:.0f}h)")
        except Exception:
            pass
    # 后台异步刷新
    threading.Thread(target=_refresh_stock_cache, daemon=True).start()


def _refresh_stock_cache():
    """后台从网络刷新股票名称缓存。"""
    global _stock_cache
    import json as _json
    try:
        from backend.services.stock_service import _no_proxy
        import akshare as ak
        with _no_proxy():
            df = ak.stock_info_a_code_name()
        new_cache = [
            {"code": str(r["code"]).zfill(6), "name": r["name"]}
            for _, r in df.iterrows()
        ]
        _stock_cache[:] = new_cache
        with open(_cache_file_path(), "w", encoding="utf-8") as f:
            _json.dump(new_cache, f, ensure_ascii=False)
        logger.info(f"股票名称缓存已刷新: {len(new_cache)} 条")
    except Exception as e:
        logger.warning(f"股票名称缓存后台刷新失败: {e}")


def _get_stock_cache() -> list:
    """获取股票名称缓存。"""
    return _stock_cache


@sentiment_bp.route("/api/sentiment/configs", methods=["GET"])
@login_required
def list_configs():
    """获取所有监控配置。"""
    configs = get_sentiment_configs()
    return jsonify(configs)


@sentiment_bp.route("/api/sentiment/configs", methods=["POST"])
@login_required
def add_config():
    """新增监控配置。"""
    body = request.get_json(silent=True) or {}
    stock_code = body.get("stock_code", "").strip()
    forum_type = body.get("forum_type", "eastmoney").strip()

    if not stock_code or len(stock_code) != 6:
        return jsonify({"error": "请输入6位股票代码"}), 400

    # 自动获取股票名称
    stock_name = body.get("stock_name", "").strip()
    if not stock_name:
        from backend.services.stock_service import _get_sina_hq, _get_eastmoney_hq
        try:
            hq = _get_sina_hq(stock_code)
            stock_name = hq.get("name", "")
        except Exception:
            try:
                hq = _get_eastmoney_hq(stock_code)
                stock_name = hq.get("name", "")
            except Exception:
                pass

    result = add_sentiment_config(stock_code, forum_type, stock_name)
    if result:
        return jsonify(result), 201
    return jsonify({"error": "添加失败（可能已存在）"}), 409


@sentiment_bp.route("/api/sentiment/configs/<int:config_id>", methods=["DELETE"])
@login_required
def remove_config(config_id):
    """删除监控配置。"""
    ok = delete_sentiment_config(config_id)
    if ok:
        return jsonify({"message": "已删除"})
    return jsonify({"error": "配置不存在"}), 404


@sentiment_bp.route("/api/sentiment/analyze", methods=["POST"])
@login_required
def run_analysis():
    """手动触发单只股票的情绪分析。"""
    body = request.get_json(silent=True) or {}
    stock_code = body.get("stock_code", "").strip()
    forum_type = body.get("forum_type", "eastmoney").strip()

    if not stock_code:
        return jsonify({"error": "请提供 stock_code"}), 400

    result = analyze_sentiment(stock_code, forum_type)
    if not result:
        return jsonify({"error": "分析失败，请检查 API Key 配置或网络"}), 500

    result["code"] = stock_code
    result["forum_type"] = forum_type
    result["guba_url"] = f"https://guba.eastmoney.com/list,{stock_code}.html"
    return jsonify(result)


@sentiment_bp.route("/api/sentiment/batch_analyze", methods=["POST"])
@login_required
def run_batch():
    """批量分析所有启用监控的股票。"""
    import threading

    def _run():
        results = batch_analyze()
        logger.info(f"批量舆情分析完成: {len(results)} 只股票")

    thread = threading.Thread(target=_run)
    thread.start()
    return jsonify({"message": "批量分析已启动，请稍后查询结果"})


@sentiment_bp.route("/api/sentiment/scores", methods=["GET"])
@login_required
def get_scores():
    """获取情绪评分历史。"""
    code = request.args.get("code", "").strip()
    forum_type = request.args.get("forum_type", "eastmoney").strip()
    days = request.args.get("days", 30, type=int)

    if not code:
        return jsonify({"error": "请提供 code 参数"}), 400

    history = get_sentiment_history(code, forum_type, days=days)
    return jsonify(history)


@sentiment_bp.route("/api/sentiment/search", methods=["GET"])
@login_required
def search_stock():
    """根据代码或名称搜索股票。"""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])

    # 尝试用现有服务获取行情（自动补全名称）
    from backend.services.stock_service import _get_sina_hq, _get_eastmoney_hq
    import re

    # 如果是6位数字，直接查
    if re.match(r"^\d{6}$", q):
        try:
            hq = _get_sina_hq(q)
        except Exception:
            try:
                hq = _get_eastmoney_hq(q)
            except Exception:
                hq = None
        if hq and hq.get("price", 0) > 0:
            return jsonify([{"code": q, "name": hq["name"]}])
        return jsonify([])

    # 从内存缓存中模糊搜索
    cache = _get_stock_cache()
    results = [
        s for s in cache if q in s["name"] or q in s["code"]
    ][:10]
    return jsonify(results)


@sentiment_bp.route("/api/sentiment/latest", methods=["GET"])
@login_required
def get_latest():
    """获取所有监控股票的最新情绪数据。"""
    from backend.services.forum_service import get_recent_posts
    configs = get_sentiment_configs()
    results = []
    for cfg in configs:
        history = get_sentiment_history(
            cfg["stock_code"], cfg["forum_type"], days=1
        )
        posts = get_recent_posts(cfg["stock_code"], cfg["forum_type"], limit=15)
        code = cfg["stock_code"]
        guba_url = f"https://guba.eastmoney.com/list,{code}.html"
        item = {
            "stock_code": code,
            "stock_name": cfg.get("stock_name", ""),
            "forum_type": cfg["forum_type"],
            "guba_url": guba_url,
            "posts": [{"title": p["title"], "url": p["url"]} for p in posts],
        }
        if history:
            item.update(history[0])
        else:
            item.update({"sentiment": None, "score": None, "summary": "暂无数据"})
        results.append(item)
    return jsonify(results)
