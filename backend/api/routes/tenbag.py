"""十倍股/财报异动扫描器 API 路由。

端点：
- POST /api/tenbag/scan        触发扫描（异步，返回 task_id）
- GET  /api/tenbag/pools       分层结果列表（?tier=&date=）
- GET  /api/tenbag/signals/<symbol>  单股趋势+异动信号详情
- GET  /api/tenbag/health      生产线健康（最近快照/覆盖/调度）

口径：输出是观察池/基本面雷达，不是买卖信号。
"""

import logging
import threading
import uuid

from flask import Blueprint, jsonify, request

from backend.api.middleware import login_required
from backend.core.database import get_connection, get_active_task_runs
from backend.core.task_runner import TaskRunner

logger = logging.getLogger(__name__)

tenbag_bp = Blueprint("tenbag", __name__)


@tenbag_bp.route("/api/tenbag/scan", methods=["POST"])
@login_required
def tenbag_scan():
    """触发十倍股/财报异动扫描（异步）。返回 task_id 供轮询 GET /api/tasks/<id>。"""
    active = get_active_task_runs()
    if any(t.get("kind") == "tenbag_scan" for t in active):
        running = next(t for t in active if t.get("kind") == "tenbag_scan")
        return jsonify({
            "error": "已有十倍股扫描任务正在运行，请等待完成",
            "task_id": running["id"],
        }), 409

    body = request.get_json(silent=True) or {}
    top_n = int(body.get("top_n", 50))
    top_n = max(1, min(top_n, 200))

    task_id = uuid.uuid4().hex

    def do_scan():
        from backend.services.tenbag_scan_service import run_scan
        with TaskRunner(kind="tenbag_scan", title="十倍股/财报异动扫描",
                        task_id=task_id) as t:
            run_scan(task_runner=t, top_n=top_n)

    thread = threading.Thread(target=do_scan, daemon=True)
    thread.start()
    return jsonify({
        "message": "十倍股扫描已启动",
        "task_id": task_id,
        "top_n": top_n,
    }), 200


@tenbag_bp.route("/api/tenbag/pools", methods=["GET"])
@login_required
def tenbag_pools():
    """分层结果列表。?tier=1|2|3|exclude&date=YYYY-MM-DD（默认最新快照）。"""
    tier = request.args.get("tier")
    if tier and tier not in ("1", "2", "3", "exclude"):
        return jsonify({"error": "tier 必须为 1/2/3/exclude"}), 400
    date = request.args.get("date")
    if date is None:
        date = _latest_pool_snapshot_date()
    if not date:
        return jsonify({"snapshot_date": None, "pools": []}), 200

    from backend.core.database import list_tenbag_pools
    rows = list_tenbag_pools(date, tier=tier)
    pools = []
    for r in rows:
        import json
        pools.append({
            "symbol": r["symbol"],
            "pool_tier": r["pool_tier"],
            "reasons": _loads(r["reasons_json"]),
        })
    return jsonify({"snapshot_date": date, "pools": pools, "count": len(pools)}), 200


@tenbag_bp.route("/api/tenbag/signals/<symbol>", methods=["GET"])
@login_required
def tenbag_signals(symbol):
    """单股趋势 + 异动信号详情。"""
    import json
    symbol = str(symbol).strip().zfill(6)
    from backend.core.database import get_tenbag_trend, get_tenbag_anomaly

    trend = get_tenbag_trend(symbol, _latest_trend_date(symbol))
    anomaly = get_tenbag_anomaly(symbol, _latest_anomaly_date(symbol))

    if not trend and not anomaly:
        return jsonify({"error": "无该股票的扫描数据"}), 404

    def _safe(row):
        if not row:
            return None
        out = dict(row)
        for k in ("signals_json", "core_changes_json", "risks_json"):
            out[k.replace("_json", "")] = _loads(out.pop(k, None))
        return out

    return jsonify({
        "symbol": symbol,
        "trend": _safe(trend),
        "anomaly": _safe(anomaly),
    }), 200


@tenbag_bp.route("/api/tenbag/health", methods=["GET"])
@login_required
def tenbag_health():
    """生产线健康：最近快照日期、各 tier 数量、最近扫描任务。"""
    latest_date = _latest_pool_snapshot_date()
    counts = {"1": 0, "2": 0, "3": 0, "exclude": 0}
    total_scanned = 0
    if latest_date:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT pool_tier, COUNT(*) FROM tenbag_pools "
                "WHERE snapshot_date=? GROUP BY pool_tier",
                (latest_date,),
            )
            for tier, n in cur.fetchall():
                counts[tier] = n
                total_scanned += n

    # 最近一次 tenbag_scan 任务
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, status, started_at, finished_at, duration_ms, result_json "
            "FROM task_runs WHERE kind='tenbag_scan' "
            "ORDER BY started_at DESC LIMIT 1",
        )
        row = cur.fetchone()
    last_task = dict(row) if row else None

    return jsonify({
        "latest_snapshot_date": latest_date,
        "tier_counts": counts,
        "total_scanned": total_scanned,
        "last_task": last_task,
        "note": "观察池/基本面雷达，非买卖信号",
    }), 200


# ── 工具 ─────────────────────────────────────────────────

def _latest_pool_snapshot_date() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(snapshot_date) FROM tenbag_pools").fetchone()
    return row[0] if row and row[0] else None


def _latest_trend_date(symbol: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM tenbag_trend_signals WHERE symbol=?",
            (symbol,)).fetchone()
    return row[0] if row and row[0] else None


def _latest_anomaly_date(symbol: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(report_date) FROM tenbag_anomaly_signals WHERE symbol=?",
            (symbol,)).fetchone()
    return row[0] if row and row[0] else None


def _loads(val):
    import json
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None
