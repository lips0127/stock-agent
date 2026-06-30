"""舆情监控 API 路由。"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request

from backend.core.database import (
    get_sentiment_configs, add_sentiment_config, delete_sentiment_config,
    get_sentiment_filters, add_sentiment_filter, delete_sentiment_filter,
    get_audit_posts, get_audit_summary, get_post_by_id,
    accept_actual_title, mark_post_broken, reset_post_audit,
    update_post_content,
)
from backend.services.sentiment_service import (
    analyze_sentiment, batch_analyze, get_sentiment_history,
    get_batch_status,
)
from backend.services.forum_service import (
    fetch_forum_posts, get_recent_posts, audit_posts,
)
from backend.api.middleware import login_required
from backend.core.task_runner import TaskRunner

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
        from backend.services.stock_service import _get_sina_hq, _get_tencent_hq
        try:
            hq = _get_sina_hq(stock_code)
            stock_name = hq.get("name", "")
        except Exception:
            try:
                hq = _get_tencent_hq(stock_code)
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
    """手动触发单只股票的情绪分析。

    v3 2026-06-06：根据失败原因返回准确的 HTTP 状态码：
    - circuit_open / network_error / no_posts → 503（服务端临时不可用）
    - no_llm → 503（依赖未配置）
    - parse_error / internal → 500（服务端异常）
    """
    body = request.get_json(silent=True) or {}
    stock_code = body.get("stock_code", "").strip()
    forum_type = body.get("forum_type", "eastmoney").strip()

    if not stock_code:
        return jsonify({"error": "请提供 stock_code"}), 400

    result = analyze_sentiment(stock_code, forum_type)

    # 错误响应精细化（v3）
    if result and result.get("_error"):
        reason = result["_reason"]
        message = result["_message"]
        # 503 类：临时不可用（guba 熔断 / 网络 / 无帖子 / 无 LLM Key）
        if reason in ("circuit_open", "network_error", "no_posts", "no_llm"):
            from backend.services.forum_service import _GUBA_CIRCUIT
            payload = {
                "error": message,
                "reason": reason,
            }
            if reason == "circuit_open":
                payload["circuit_state"] = _GUBA_CIRCUIT.state
                payload["retry_after_seconds"] = _GUBA_CIRCUIT.state["cooldown_remaining"]
            return jsonify(payload), 503
        # 500 类：服务端异常（parse / internal）
        return jsonify({"error": message, "reason": reason}), 500

    if not result:
        return jsonify({"error": "分析失败（未知原因）"}), 500

    result["code"] = stock_code
    result["forum_type"] = forum_type
    result["guba_url"] = f"https://guba.eastmoney.com/list,{stock_code}.html"
    return jsonify(result)


@sentiment_bp.route("/api/sentiment/batch_analyze", methods=["POST"])
@login_required
def run_batch():
    """批量分析所有启用监控的股票。返回 task_run_id 供轮询 GET /api/tasks/<id>。"""
    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="sentiment_batch",
            title="舆情批量分析",
            task_id=task_id,
        ) as t:
            results = batch_analyze(task_runner=t)
            logger.info(f"批量舆情分析完成: {len(results)} 只股票")

    thread = threading.Thread(target=_run)
    thread.start()
    return jsonify({"message": "批量分析已启动", "task_id": task_id})


@sentiment_bp.route("/api/sentiment/batch_analyze_status", methods=["GET"])
@login_required
def batch_analyze_status():
    """批量分析任务进度（前端轮询用）。"""
    return jsonify(get_batch_status())


@sentiment_bp.route("/api/sentiment/batch_analyze_count", methods=["GET"])
@login_required
def batch_analyze_count():
    """本次若触发将分析多少只股票（仅"我的关注"范围）。
    用于前端按钮显示「批量分析 (N)」实时数量。"""
    from backend.core.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sentiment_config WHERE enabled=1"
        ).fetchone()
    return jsonify({"count": int(row["n"])})


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
    from backend.services.stock_service import _get_sina_hq, _get_tencent_hq
    import re

    # 如果是6位数字，直接查
    if re.match(r"^\d{6}$", q):
        try:
            hq = _get_sina_hq(q)
        except Exception:
            try:
                hq = _get_tencent_hq(q)
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
    """获取所有监控股票的最新情绪数据。

    v3 2026-06-06：附带 signals（panic/euphoria）+ indicators（EMA3/5）
    v7 2026-06-29：消除 N+1——改一次批量查询（3 条 SQL 替代 per-config 3×N）。
    """
    from backend.core.database import get_sentiment_latest_overview
    configs = get_sentiment_configs()
    # 按 forum_type 分组批量取（绝大多数为 eastmoney）
    by_ft: dict[str, list] = {}
    for cfg in configs:
        by_ft.setdefault(cfg["forum_type"], []).append(cfg)

    results = []
    for forum_type, group in by_ft.items():
        codes = [c["stock_code"] for c in group]
        overview = get_sentiment_latest_overview(codes, forum_type, post_limit=15)
        for cfg in group:
            code = cfg["stock_code"]
            ov = overview.get(code, {})
            history_row = ov.get("history")
            latest_ind = ov.get("indicators") or {}
            posts = ov.get("posts") or []
            guba_url = f"https://guba.eastmoney.com/list,{code}.html"

            signals = {}
            if history_row and history_row.get("signals_json"):
                try:
                    signals = json.loads(history_row["signals_json"])
                except Exception:
                    signals = {}

            item = {
                "stock_code": code,
                "stock_name": cfg.get("stock_name", ""),
                "forum_type": forum_type,
                "guba_url": guba_url,
                "posts": [{
                    "title": p["title"], "url": p["url"],
                    "post_id": p.get("post_id"),
                    "actual_title": p.get("actual_title"),
                    "title_match": p.get("title_match"),
                    "audit_status": p.get("audit_status"),
                } for p in posts],
                "signals": signals,
                "indicators": {
                    "ema3": latest_ind.get("ema3"),
                    "ema5": latest_ind.get("ema5"),
                    "panic_signal": latest_ind.get("panic_signal", 0),
                    "euphoria_signal": latest_ind.get("euphoria_signal", 0),
                    "momentum_cross": latest_ind.get("momentum_cross", 0),
                },
            }
            if history_row:
                item.update(history_row)
            else:
                item.update({"sentiment": None, "score": None, "summary": "暂无数据"})
            results.append(item)
    return jsonify(results)


# ── 舆情帖子过滤规则管理 ────────────────────────────────────────────

@sentiment_bp.route("/api/sentiment/filters", methods=["GET"])
@login_required
def list_filters():
    """获取过滤规则白名单。"""
    filter_type = request.args.get("filter_type", None)
    filters = get_sentiment_filters(filter_type=filter_type)
    return jsonify(filters)


@sentiment_bp.route("/api/sentiment/filters", methods=["POST"])
@login_required
def add_filter():
    """新增过滤规则。"""
    body = request.get_json(silent=True) or {}
    filter_key = body.get("filter_key", "").strip()
    filter_type = body.get("filter_type", "title_keyword").strip()
    description = body.get("description", "").strip()

    if not filter_key:
        return jsonify({"error": "请提供 filter_key"}), 400

    result = add_sentiment_filter(filter_key, filter_type, description)
    if result:
        return jsonify(result), 201
    return jsonify({"error": "添加失败（可能已存在）"}), 409


@sentiment_bp.route("/api/sentiment/filters/<int:filter_id>", methods=["DELETE"])
@login_required
def remove_filter(filter_id):
    """删除过滤规则。"""
    ok = delete_sentiment_filter(filter_id)
    if ok:
        return jsonify({"message": "已删除"})
    return jsonify({"error": "规则不存在"}), 404


# ── 标题真实性审计（v1, 2026-06-04） ──────────────────────────────────

@sentiment_bp.route("/api/sentiment/audit", methods=["GET"])
@login_required
def list_audit_posts():
    """获取某股票所有帖子的审计状态列表。"""
    code = request.args.get("code", "").strip()
    forum_type = request.args.get("forum_type", "eastmoney").strip() or "eastmoney"
    only_mismatch = request.args.get("only_mismatch", "0") in ("1", "true", "yes")
    limit = request.args.get("limit", 200, type=int)

    if not code or len(code) != 6:
        return jsonify({"error": "请提供 6 位 stock_code"}), 400

    posts = get_audit_posts(code, forum_type, only_mismatch=only_mismatch, limit=limit)
    return jsonify(posts)


@sentiment_bp.route("/api/sentiment/audit/rerun", methods=["POST"])
@login_required
def rerun_audit():
    """重新跑标题审计（不调 LLM）。

    body: {"code": "xxx"} 或 {"code": "xxx", "reset": true}
    不传 code 时，遍历所有 sentiment_config 启用的股票。
    """
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    reset = bool(body.get("reset", False))
    forum_type = (body.get("forum_type") or "eastmoney").strip()

    if reset:
        # 重置该股票所有帖子的审计状态为 pending
        from backend.core.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """UPDATE forum_posts
                   SET actual_title=NULL, title_match=NULL,
                       title_verified_at=NULL, audit_status='pending',
                       audit_note=NULL
                   WHERE stock_code=? AND forum_type=?""",
                (code, forum_type),
            )

    if code:
        codes = [code]
    else:
        configs = get_sentiment_configs()
        codes = list({c["stock_code"] for c in configs})

    task_id = uuid.uuid4().hex

    def _run_all():
        with TaskRunner(
            kind="sentiment_audit_rerun",
            title=f"标题真实性重审 ({len(codes)} 只股票)",
            payload={"codes": codes, "reset": reset, "forum_type": forum_type},
            task_id=task_id,
        ) as t:
            t.set_total(len(codes))
            total_summary = {"audited": 0, "matched": 0, "mismatched": 0,
                             "fetch_errors": 0, "skipped": 0}
            for i, c in enumerate(codes):
                t.check_cancelled()
                t.set_current(f"审计 {c}")
                try:
                    posts = get_recent_posts(c, forum_type, limit=80)
                    if not posts:
                        t.progress(i + 1)
                        continue
                    summary = audit_posts(
                        [{"post_id": p.get("post_id"), "title": p.get("title"),
                          "code": c, "url": p.get("url")}
                         for p in posts if p.get("post_id")],
                        forum_type=forum_type,
                    )
                    for k in total_summary:
                        total_summary[k] += summary.get(k, 0)
                except Exception as e:
                    logger.error(f"重跑审计 {c} 失败: {e}", exc_info=True)
                t.progress(i + 1)
            logger.info(f"审计重跑完成: {total_summary}")
            t.complete(result=total_summary)

    threading.Thread(target=_run_all, daemon=True).start()
    return jsonify({"message": f"已启动重跑 {len(codes)} 只股票",
                    "task_id": task_id, "codes": codes, "reset": reset})


@sentiment_bp.route("/api/sentiment/posts/<int:post_id>/accept_actual",
                    methods=["POST"])
@login_required
def accept_actual(post_id):
    """接受 actual_title 覆盖 title。"""
    updated = accept_actual_title(post_id)
    if not updated:
        return jsonify({"error": "帖子不存在或没有 actual_title"}), 404
    return jsonify(updated)


@sentiment_bp.route("/api/sentiment/posts/<int:post_id>/mark_broken",
                    methods=["POST"])
@login_required
def mark_broken(post_id):
    """标记帖子为垃圾（前端展示时过滤）。"""
    body = request.get_json(silent=True) or {}
    note = (body.get("note") or "").strip()
    ok = mark_post_broken(post_id, note=note)
    if not ok:
        return jsonify({"error": "帖子不存在"}), 404
    return jsonify({"message": "已标记为垃圾", "post_id": post_id})


@sentiment_bp.route("/api/sentiment/posts/<int:post_id>/reset", methods=["POST"])
@login_required
def reset_audit(post_id):
    """重置帖子审计状态为 pending。"""
    ok = reset_post_audit(post_id)
    if not ok:
        return jsonify({"error": "帖子不存在"}), 404
    return jsonify({"message": "已重置", "post_id": post_id})


# ── 站内查看缓存帖子（v3, 2026-06-04） ────────────────────────────────
# guba.eastmoney.com 在部分网络下完全不可达，外链点不开。
# 这两个端点让前端可以在 dialog 里展示 DB 缓存的帖子内容。

@sentiment_bp.route("/api/sentiment/posts/<int:post_id>", methods=["GET"])
@login_required
def get_post_detail(post_id):
    """获取单条帖子完整缓存数据（含 content）。"""
    post = get_post_by_id(post_id)
    if not post:
        return jsonify({"error": "帖子不存在"}), 404
    return jsonify(post)


@sentiment_bp.route("/api/sentiment/posts/<int:post_id>/refresh_content",
                    methods=["POST"])
@login_required
def refresh_post_content(post_id):
    """手动重抓某条帖子的正文（用户在 dialog 里点的"重新抓取"）。

    走熔断器/重试链路；熔断中返回 503 给前端清晰提示。
    成功后用新的 actual_title + content 更新 DB。
    """
    post = get_post_by_id(post_id)
    if not post:
        return jsonify({"error": "帖子不存在"}), 404

    import re as _re
    pid_match = _re.search(r"/news,\d+,(\d+)\.html", post.get("url") or "")
    if not pid_match:
        return jsonify({"error": "url 异常，无法定位 post_id"}), 400
    guba_pid = pid_match.group(1)

    from backend.services.forum_service import (
        fetch_post_full, _GUBA_CIRCUIT, CircuitOpenError,
    )
    from backend.core.database import update_post_audit

    try:
        full = fetch_post_full(post["stock_code"], guba_pid)
    except CircuitOpenError:
        return jsonify({
            "error": "guba.eastmoney.com 暂时不可达，已熔断",
            "circuit_state": _GUBA_CIRCUIT.state,
        }), 503
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

    if not full:
        return jsonify({"error": "抓取失败（无返回）"}), 502

    content = full.get("content")
    actual = full.get("actual_title")
    fetch_error = full.get("fetch_error")

    if content:
        update_post_content(post_id, content)
    if actual:
        # 同步审计字段（如果新拿到了真实标题）
        from backend.services.forum_service import _normalize
        match = _normalize(post.get("title", "")) == _normalize(actual)
        update_post_audit(
            post_id,
            actual_title=actual,
            title_match=match,
            audit_status="verified" if match else "mismatch",
            audit_note=fetch_error,
        )

    refreshed = get_post_by_id(post_id)
    return jsonify({
        "post": refreshed,
        "fetch_error": fetch_error,
        "circuit_state": _GUBA_CIRCUIT.state,
    })


@sentiment_bp.route("/api/sentiment/audit/summary", methods=["GET"])
@login_required
def audit_summary():
    """全局（或单只股票）审计摘要。"""
    code = request.args.get("code", "").strip() or None
    summary = get_audit_summary(code)
    return jsonify(summary)


# ── 网络韧性：仅拉取 + 熔断状态（v2, 2026-06-04） ──────────────────────

@sentiment_bp.route("/api/sentiment/fetch", methods=["POST"])
@login_required
def fetch_only():
    """仅拉取帖子到缓存，不调 LLM。

    用途：warm up 缓存 / 调试 / 验证 guba 可达性。
    body: {"stock_code": "xxx", "forum_type": "eastmoney",
           "days": 3, "fetch_content": true, "audit": true}
    """
    body = request.get_json(silent=True) or {}
    code = body.get("stock_code", "").strip()
    forum_type = body.get("forum_type", "eastmoney").strip() or "eastmoney"
    try:
        days = int(body.get("days", 3))
    except (TypeError, ValueError):
        days = 3
    fetch_content_raw = body.get("fetch_content", True)
    if isinstance(fetch_content_raw, bool):
        fetch_content = fetch_content_raw
    else:
        fetch_content = str(fetch_content_raw).lower() in ("1", "true", "yes")
    do_audit_raw = body.get("audit", True)
    if isinstance(do_audit_raw, bool):
        do_audit = do_audit_raw
    else:
        do_audit = str(do_audit_raw).lower() in ("1", "true", "yes")

    if not code or len(code) != 6:
        return jsonify({"error": "请提供 6 位 stock_code"}), 400

    from backend.services.forum_service import (
        fetch_forum_posts, _GUBA_CIRCUIT, CircuitOpenError,
    )

    try:
        posts, audit_summary = fetch_forum_posts(
            code, forum_type, days=days,
            fetch_content=fetch_content, audit=do_audit,
        )
    except CircuitOpenError as e:
        return jsonify({
            "error": "guba.eastmoney.com 暂时不可达，已熔断",
            "circuit_state": _GUBA_CIRCUIT.state,
            "retry_after_seconds": _GUBA_CIRCUIT.state["cooldown_remaining"],
        }), 503
    except Exception as e:
        logger.error(f"fetch_only 失败: {code}: {e}", exc_info=True)
        return jsonify({"error": str(e)[:200]}), 500

    return jsonify({
        "code": code,
        "forum_type": forum_type,
        "posts_count": len(posts),
        "circuit_state": _GUBA_CIRCUIT.state,
        "audit": audit_summary,
        "posts": [{
            "post_id": p.get("post_id"),
            "title": p.get("title"),
            "actual_title": p.get("actual_title"),
            "title_match": p.get("title_match"),
            "audit_status": p.get("audit_status"),
            "author": p.get("author"),
            "post_time": p.get("post_time"),
            "url": p.get("url"),
        } for p in posts[:50]],
    })


@sentiment_bp.route("/api/sentiment/circuit_status", methods=["GET"])
@login_required
def circuit_status():
    """guba 熔断器状态 + cookie 健康度（调试 + 前端展示）。"""
    from backend.services.forum_service import _GUBA_CIRCUIT, _COOKIE_STALE
    state = dict(_GUBA_CIRCUIT.state)
    state["cookie_stale"] = _COOKIE_STALE
    return jsonify(state)


@sentiment_bp.route("/api/sentiment/circuit_reset", methods=["POST"])
@login_required
def circuit_reset():
    """手动重置 guba 熔断器（同时清除 cookie stale 告警，便于更新 cookie 后重试）。"""
    import backend.services.forum_service as fm
    fm._GUBA_CIRCUIT.reset()
    fm._COOKIE_STALE = False
    return jsonify({"message": "已重置", "circuit_state": fm._GUBA_CIRCUIT.state,
                    "cookie_stale": False})


# ── v3 算法升级（2026-06-06）：时序因子 + 热门股池 ──

@sentiment_bp.route("/api/sentiment/indicators", methods=["GET"])
@login_required
def list_indicators():
    """获取某只股票的时序因子序列（前端趋势图用）。

    Query: ?code=xxx&days=30
    """
    code = request.args.get("code", "").strip()
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if not code or len(code) != 6:
        return jsonify({"error": "请提供 6 位 code 参数"}), 400
    from backend.services.sentiment_indicators_service import get_stock_indicator_series
    rows = get_stock_indicator_series(code, days=days)
    return jsonify(rows)


@sentiment_bp.route("/api/sentiment/extreme_signals", methods=["GET"])
@login_required
def list_extreme_signals():
    """获取某日（默认今天）所有触发 panic / euphoria 的股票。

    用途：前端「今日极端情绪」看板 + 策略层消费。
    """
    from backend.services.sentiment_indicators_service import get_extreme_signals
    target_date = request.args.get("date", "").strip() or None
    rows = get_extreme_signals(target_date)
    return jsonify(rows)


@sentiment_bp.route("/api/sentiment/indicators/recompute", methods=["POST"])
@login_required
def recompute_indicators():
    """对所有启用的监控股票重新算今日 indicators（手动触发）。返回 task_run_id。"""
    from backend.services.sentiment_indicators_service import recompute_all_for_today

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="indicators_recompute",
            title="时序因子重算",
            task_id=task_id,
        ) as t:
            result = recompute_all_for_today()
            logger.info(f"手动重算 indicators: {result}")
            t.complete(result=result)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "已启动重算", "task_id": task_id})


@sentiment_bp.route("/api/sentiment/top_picks", methods=["GET"])
@login_required
def list_top_picks_route():
    """获取最新 top picks 列表。"""
    from backend.services.top_picks_service import list_top_picks
    snapshot_date = request.args.get("date", "").strip() or None
    return jsonify(list_top_picks(snapshot_date))


@sentiment_bp.route("/api/sentiment/top_picks/refresh", methods=["POST"])
@login_required
def refresh_top_picks_route():
    """手动刷新 top picks。返回 task_run_id。

    Body: {"top_n": 100, "auto_add": false, "analyze_limit": 20}
    """
    from backend.services.top_picks_service import refresh_top_picks, analyze_top_picks
    body = request.get_json(silent=True) or {}
    try:
        top_n = int(body.get("top_n", 100))
    except (TypeError, ValueError):
        top_n = 100
    auto_add = bool(body.get("auto_add", False))
    try:
        analyze_limit = int(body.get("analyze_limit", 0) or 0)
    except (TypeError, ValueError):
        analyze_limit = 0
    analyze_limit = max(0, min(analyze_limit, 100))
    if top_n not in (50, 100, 200, 500):
        return jsonify({"error": "top_n 必须是 50/100/200/500"}), 400

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="top_picks_refresh",
            title=f"热门股池刷新 (top {top_n})",
            payload={"top_n": top_n, "auto_add": auto_add, "analyze_limit": analyze_limit},
            task_id=task_id,
        ) as t:
            result = refresh_top_picks(top_n=top_n, auto_add=auto_add)
            if analyze_limit and result.get("count"):
                result["analysis"] = analyze_top_picks(limit=analyze_limit, task_runner=t)
            logger.info(f"手动刷新 top_picks: {result}")
            t.complete(result=result)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": f"已启动刷新 top {top_n}", "task_id": task_id})


@sentiment_bp.route("/api/sentiment/top_picks/analyze", methods=["POST"])
@login_required
def analyze_top_picks_route():
    """手动分析当前热门股池 top N。返回 task_run_id。"""
    from backend.services.top_picks_service import analyze_top_picks
    body = request.get_json(silent=True) or {}
    try:
        limit = int(body.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="top_picks_analyze",
            title=f"热门股池分析 (top {limit})",
            payload={"limit": limit},
            task_id=task_id,
        ) as t:
            result = analyze_top_picks(limit=limit, task_runner=t)
            logger.info(f"手动分析 top_picks: {result}")
            t.complete(result=result)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": f"已启动分析热门股 top {limit}", "task_id": task_id})


@sentiment_bp.route("/api/sentiment/health", methods=["GET"])
@login_required
def sentiment_health():
    """舆情因子生产线健康状态：覆盖率、鲜度、关键调度。"""
    from backend.core.database import (
        get_all_scheduler_configs, get_latest_run,
        get_recent_task_runs, get_connection,
    )
    from backend.services.top_picks_service import list_top_picks
    from backend.services.scheduler_config_service import JOB_REGISTRY_BY_ID, compute_next_run_time

    today = datetime.now().date().isoformat()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM sentiment_config WHERE enabled=1").fetchone()
        monitored_count = int(row["n"] or 0)
        row = conn.execute(
            "SELECT COUNT(DISTINCT stock_code) AS n FROM sentiment_scores WHERE date=?",
            (today,),
        ).fetchone()
        scored_today = int(row["n"] or 0)
        row = conn.execute(
            "SELECT COUNT(DISTINCT stock_code) AS n FROM sentiment_indicators WHERE date=?",
            (today,),
        ).fetchone()
        indicators_today = int(row["n"] or 0)

    top_picks = list_top_picks()
    top_picks_count = len(top_picks)
    top_picks_date = top_picks[0]["snapshot_date"] if top_picks else None
    analyzed_top_picks = sum(
        1 for p in top_picks
        if p.get("score") is not None and p.get("sentiment_date") == today
    )

    jobs = []
    rows = get_all_scheduler_configs()
    watch = {"daily_sentiment", "daily_top_picks", "daily_indicators_recompute", "forum_prefetch"}
    for row in rows:
        job_id = row["job_id"]
        if job_id not in watch:
            continue
        run = get_latest_run(job_id)
        next_run = row.get("next_run_time")
        if not next_run:
            try:
                next_run = compute_next_run_time(row)
            except Exception:
                next_run = None
        jobs.append({
            "job_id": job_id,
            "name": JOB_REGISTRY_BY_ID.get(job_id, {}).get("display_name", job_id),
            "enabled": bool(row.get("enabled")),
            "next_run_time": next_run,
            "last_run": run,
        })

    recent = get_recent_task_runs(limit=10)
    unhealthy_jobs = [j for j in jobs if j["enabled"] and j["last_run"] and j["last_run"].get("status") == "failed"]
    status = "healthy"
    if unhealthy_jobs:
        status = "degraded"
    if monitored_count and scored_today == 0 and analyzed_top_picks == 0:
        status = "stale"

    return jsonify({
        "date": today,
        "status": status,
        "coverage": {
            "monitored_count": monitored_count,
            "scored_today": scored_today,
            "indicators_today": indicators_today,
            "top_picks_count": top_picks_count,
            "top_picks_date": top_picks_date,
            "analyzed_top_picks": analyzed_top_picks,
        },
        "jobs": jobs,
        "recent_tasks": recent,
    })


# ── 全市场舆情观测台（v4, 2026-06-06）──

@sentiment_bp.route("/api/sentiment/universe/indices", methods=["GET"])
@login_required
def list_universe_indices():
    """列出所有 enabled 指数定义。"""
    from backend.services.universe_service import list_indices
    return jsonify(list_indices(enabled_only=True))


@sentiment_bp.route("/api/sentiment/universe/summary", methods=["GET"])
@login_required
def universe_summary():
    """取某日各指数的聚合汇总（看板主数据）。

    Query: ?date=YYYY-MM-DD（默认今天）
    """
    from backend.services.universe_service import get_summary
    date_str = request.args.get("date", "").strip() or None
    return jsonify(get_summary(date_str))


@sentiment_bp.route("/api/sentiment/universe/history/<index_code>", methods=["GET"])
@login_required
def universe_history(index_code: str):
    """单指数时序（过去 N 天的每日聚合）。

    Path: /<index_code>  其中 index_code ∈ {csi300, sse50, star50, csi1000, csi2000, chinext}
    Query: ?days=60（默认 60）
    """
    from backend.services.universe_service import get_history
    try:
        days = int(request.args.get("days", "60"))
    except (TypeError, ValueError):
        days = 60
    return jsonify(get_history(index_code, days=days))


@sentiment_bp.route("/api/sentiment/universe/constituents/<index_code>", methods=["GET"])
@login_required
def universe_constituents(index_code: str):
    """某指数当日成分股的情绪分。

    Path: /<index_code>
    Query: ?date=YYYY-MM-DD&limit=500&offset=0
    """
    from backend.services.universe_service import get_constituents
    date_str = request.args.get("date", "").strip() or None
    try:
        limit = int(request.args.get("limit", "500"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 500, 0
    return jsonify(get_constituents(index_code, date_str=date_str, limit=limit, offset=offset))


@sentiment_bp.route("/api/sentiment/universe/jobs", methods=["GET"])
@login_required
def universe_jobs():
    """任务进度（前端轮询用）。

    Query: ?date=YYYY-MM-DD（默认今天）
    """
    from backend.services.universe_service import get_jobs
    date_str = request.args.get("date", "").strip() or None
    return jsonify(get_jobs(date_str))


@sentiment_bp.route("/api/sentiment/universe/progress", methods=["GET"])
@login_required
def universe_progress():
    """6 指数合并的实时进度（X/Y + 当前状态）。

    Query: ?date=YYYY-MM-DD（默认今天）
    Returns: {
      "date": "2026-06-07",
      "total": 3700, "completed": 1234, "failed": 56,
      "running": true, "current": "600118", "current_name": "中国卫星",
      "by_index": [{...}],
    }

    从 DB 聚合（跨进程可用）。current/current_name 从最近一条 running 的
    sentiment_universe / universe_crawl_daily task_run 取。
    （v7 2026-06-29：废弃内存态优先分支——多进程部署下读不到，且违反 Phase B。）
    """
    from backend.services.universe_service import get_jobs
    from backend.core.database import get_connection
    from datetime import date as _date
    date_str = request.args.get("date", "").strip() or _date.today().isoformat()
    jobs = get_jobs(date_str)

    total = sum(int(j.get("total_stocks") or 0) for j in jobs)
    completed = sum(int(j.get("completed_stocks") or 0) for j in jobs)
    failed = sum(int(j.get("failed_stocks") or 0) for j in jobs)
    running = any((j.get("status") or "") == "running" for j in jobs) if jobs else False

    current = None
    current_name = None
    if running:
        # 从最近一条 running 的 universe crawl task_run 取当前处理的股票
        with get_connection() as conn:
            row = conn.execute(
                "SELECT current_step, result_json FROM task_runs "
                "WHERE kind IN ('sentiment_universe','universe_crawl_daily') "
                "AND status='running' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row:
            current = row["current_step"] or None
            if row["result_json"]:
                try:
                    snap = json.loads(row["result_json"])
                    current = snap.get("current") or current
                    current_name = snap.get("current_name")
                except Exception:
                    pass

    return jsonify({
        "date": date_str,
        "total": total,
        "completed": completed,
        "failed": failed,
        "pct": round((completed + failed) / total * 100, 1) if total else 0.0,
        "running": running,
        "current": current,
        "current_name": current_name,
        "by_index": jobs,
    })


@sentiment_bp.route("/api/sentiment/universe/count", methods=["GET"])
@login_required
def universe_count():
    """本次若触发将分析多少只去重后的成分股。"""
    from backend.services.universe_service import get_universe_for_date
    from datetime import date as _date
    date_str = request.args.get("date", "").strip() or _date.today().isoformat()
    stocks, _by_index = get_universe_for_date(date_str)
    return jsonify({"date": date_str, "count": len(stocks)})


@sentiment_bp.route("/api/sentiment/universe/refresh_constituents", methods=["POST"])
@login_required
def universe_refresh_constituents():
    """手动刷成分股（异步）。返回 task_run_id。
    body: {"index_code": "csi300" | null for all}
    """
    from backend.services.universe_service import refresh_constituents
    payload = request.json or {}
    index_code = payload.get("index_code")
    scope = index_code or "all"

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="universe_constituents_refresh",
            title=f"成分股周更 ({scope})",
            payload={"index_code": index_code},
            task_id=task_id,
        ) as t:
            try:
                result = refresh_constituents(index_code=index_code)
                logger.info(f"手动刷新 universe 成分股: {result}")
                t.complete(result=result)
            except Exception as e:
                logger.exception(f"手动刷新 universe 成分股失败: {e}")
                t.fail(str(e))

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": f"已启动刷新 {scope} 成分股（异步）", "task_id": task_id})


@sentiment_bp.route("/api/sentiment/universe/run/<index_code>", methods=["POST"])
@login_required
def universe_run(index_code: str):
    """手动触发全量爬取（异步）。返回 task_run_id。
    body: {"max_workers": 8}
    """
    from backend.services.universe_service import run_universe_crawl
    from backend.config import UNIVERSE_CRAWL_MAX_WORKERS
    payload = request.json or {}
    max_workers = int(payload.get("max_workers", UNIVERSE_CRAWL_MAX_WORKERS))
    target = None if index_code == "all" else index_code

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="sentiment_universe",
            title=f"全市场舆情爬取 ({index_code})",
            payload={"index_code": target, "max_workers": max_workers},
            task_id=task_id,
        ) as t:
            try:
                result = run_universe_crawl(
                    max_workers=max_workers, index_code=target, task_runner=t,
                )
                logger.info(f"手动 universe crawl: {result}")
                t.complete(result=result)
            except Exception as e:
                logger.exception(f"手动 universe crawl 失败: {e}")
                t.fail(str(e))

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": f"已启动 crawl {index_code} (max_workers={max_workers})",
                    "task_id": task_id})


