"""VIX 恐慌指数 + 恐惧贪婪综合指数 API（v2, 2026-06-10 — TaskRunner 重构）"""

from __future__ import annotations

import logging
import threading
import uuid

from flask import Blueprint, jsonify, request

from backend.services.vix_service import (
    get_latest_api, get_history_api, compute_and_store,
    backfill_vix_history,
)
from backend.services.vix_factor_study import run_vix_factor_study
from backend.services.vix_vol_risk_service import get_vix_vol_risk_api
from backend.core.database import get_vix_history_count, get_active_task_runs
from backend.core.task_runner import TaskRunner
from backend.api.middleware import login_required

logger = logging.getLogger(__name__)

vix_bp = Blueprint("vix", __name__, url_prefix="/api/vix")


@vix_bp.route("", methods=["GET"])
@login_required
def get_vix():
    """最新 VIX 快照。"""
    return jsonify(get_latest_api())


@vix_bp.route("/history", methods=["GET"])
@login_required
def get_vix_history_route():
    """历史 VIX。query: days=60"""
    try:
        days = int(request.args.get("days", 60))
    except (TypeError, ValueError):
        days = 60
    days = max(7, min(days, 365))
    db_total = get_vix_history_count()
    return jsonify({
        "days": days,
        "db_total_days": db_total,
        "data": get_history_api(days),
    })


@vix_bp.route("/factor-study", methods=["GET"])
@login_required
def get_vix_factor_study_route():
    """VIX/恐惧贪婪因子事件研究。query: days=365"""
    try:
        days = int(request.args.get("days", 365))
    except (TypeError, ValueError):
        days = 365
    return jsonify(run_vix_factor_study(days))


@vix_bp.route("/vol-risk", methods=["GET"])
@login_required
def get_vix_vol_risk_route():
    """VIX 波动率风险预算因子（只读生产候选，不是买卖信号）。"""
    force = request.args.get("force") in {"1", "true", "yes"}
    return jsonify(get_vix_vol_risk_api(force=force))


@vix_bp.route("/recompute", methods=["POST"])
@login_required
def recompute_vix():
    """手动触发 VIX 重算（异步，返回 task_run_id 供轮询）。"""
    active = get_active_task_runs()
    active_recompute = [t for t in active if t.get("kind") == "vix_recompute"]
    if active_recompute:
        return jsonify({
            "error": "已有重算任务在进行中",
            "task_id": active_recompute[0]["id"],
        }), 409

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(kind="vix_recompute", title="VIX 重算", task_id=task_id) as t:
            snap = compute_and_store()
            if snap:
                t.complete(result={
                    "date": snap.date,
                    "vix": snap.vix,
                    "fear_greed": snap.fear_greed,
                    "composite_score": snap.composite_score,
                    "composite_regime": snap.composite_regime,
                })
            else:
                t.fail("compute_and_store 返回 None")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "VIX 重算已启动", "task_id": task_id}), 202


@vix_bp.route("/recompute_status", methods=["GET"])
@login_required
def recompute_status():
    """[deprecated] 轮询重算状态。请改用 GET /api/tasks/<id>。"""
    return jsonify({
        "deprecated": True,
        "message": "请改用 GET /api/tasks/<task_id> 查询任务状态",
    }), 410


@vix_bp.route("/backfill", methods=["POST"])
@login_required
def backfill_vix():
    """回填历史 VIX。body: {"days": 30, "skip_existing": false}。返回 task_run_id。"""
    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 30))
    days = max(1, min(days, 365))
    skip_existing = bool(body.get("skip_existing", False))

    active = get_active_task_runs()
    active_backfills = [t for t in active if t.get("kind") == "vix_backfill"]
    if active_backfills:
        return jsonify({
            "error": "已有回填任务在进行中",
            "task_id": active_backfills[0]["id"],
        }), 409

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(
            kind="vix_backfill",
            title=f"VIX 历史回填 ({days}天)",
            payload={"days": days, "skip_existing": skip_existing},
            task_id=task_id,
        ) as t:
            backfill_vix_history(days=days, skip_existing=skip_existing, task_runner=t)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({
        "message": "VIX 历史回填已启动",
        "task_id": task_id,
        "days": days,
        "skip_existing": skip_existing,
    }), 202


@vix_bp.route("/backfill_status", methods=["GET"])
@login_required
def backfill_status_route():
    """[deprecated] 轮询回填状态。请改用 GET /api/tasks/<id>。"""
    return jsonify({
        "deprecated": True,
        "message": "请改用 GET /api/tasks/<task_id> 查询任务状态",
    }), 410
