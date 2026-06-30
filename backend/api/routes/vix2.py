"""VIX 2.0（机器学习）API。设计见 docs/vix2-ml-design.md §4.3。

与 v6.1 /api/vix 并行；异步端点统一走 TaskRunner，返回 32-hex task_id，
前端用 GET /api/tasks/<id> 轮询（CLAUDE.md Phase A/B 约束）。
"""

from __future__ import annotations

import logging
import threading
import uuid

from flask import Blueprint, jsonify, request

from backend.core.database import get_active_task_runs, get_vix2_history_count
from backend.core.task_runner import TaskRunner
from backend.services.vix2_model import train_model, get_model_meta
from backend.services.vix2_service import (
    get_vix2_latest_api, get_vix2_history_api, backfill_vix2,
)
from backend.api.middleware import login_required

logger = logging.getLogger(__name__)

vix2_bp = Blueprint("vix2", __name__, url_prefix="/api/vix2")


@vix2_bp.route("", methods=["GET"])
@login_required
def get_vix2():
    """最新 VIX 2.0 快照 + 模型状态。"""
    return jsonify(get_vix2_latest_api())


@vix2_bp.route("/history", methods=["GET"])
@login_required
def get_vix2_history_route():
    """历史 VIX 2.0 序列。query: days=365"""
    try:
        days = int(request.args.get("days", 365))
    except (TypeError, ValueError):
        days = 365
    days = max(7, min(days, 3000))
    return jsonify({
        "days": days,
        "db_total_days": get_vix2_history_count(),
        "data": get_vix2_history_api(days),
    })


@vix2_bp.route("/model", methods=["GET"])
@login_required
def get_vix2_model():
    """当前模型元数据 + 因子权重（前端画权重条形图）。"""
    meta = get_model_meta()
    if meta is None:
        return jsonify({"trained": False, "message": "模型尚未训练"}), 200
    return jsonify({"trained": True, **meta})


@vix2_bp.route("/train", methods=["POST"])
@login_required
def train_vix2_route():
    """触发离线重训（异步，返回 task_id）。body 可选: pt/sl/horizon/rv_scale。"""
    active = get_active_task_runs()
    if any(t.get("kind") == "vix2_train" for t in active):
        existing = next(t for t in active if t.get("kind") == "vix2_train")
        return jsonify({"error": "已有训练任务在进行中", "task_id": existing["id"]}), 409

    body = request.get_json(silent=True) or {}
    label_params = {
        "pt": float(body.get("pt", 0.05)),
        "sl": float(body.get("sl", 0.05)),
        "horizon": int(body.get("horizon", 20)),
        "rv_scale": bool(body.get("rv_scale", True)),
    }
    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(kind="vix2_train", title="VIX 2.0 模型训练",
                        payload=label_params, task_id=task_id) as t:
            meta = train_model(label_params=label_params, progress=t.milestone)
            t.complete(result={
                "model_version": meta["model_version"],
                "cv_auc": meta["cv_auc"],
                "oos_auc": meta["oos_auc"],
                "n_samples": meta["n_samples"],
            })

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "VIX 2.0 训练已启动", "task_id": task_id}), 202


@vix2_bp.route("/backfill", methods=["POST"])
@login_required
def backfill_vix2_route():
    """用当前模型回填历史 score（异步，返回 task_id）。body: days/skip_existing。"""
    active = get_active_task_runs()
    if any(t.get("kind") == "vix2_backfill" for t in active):
        existing = next(t for t in active if t.get("kind") == "vix2_backfill")
        return jsonify({"error": "已有回填任务在进行中", "task_id": existing["id"]}), 409

    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 0))          # 0 = 全历史
    skip_existing = bool(body.get("skip_existing", False))
    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(kind="vix2_backfill",
                        title=f"VIX 2.0 回填 ({days or '全历史'})",
                        payload={"days": days, "skip_existing": skip_existing},
                        task_id=task_id) as t:
            backfill_vix2(days=days, skip_existing=skip_existing, task_runner=t)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "VIX 2.0 回填已启动", "task_id": task_id, "days": days}), 202
