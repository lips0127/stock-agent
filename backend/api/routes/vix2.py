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
from backend.services.vix2_model import train_model, get_model_meta, get_walkforward_meta
from backend.services.vix2_service import (
    get_vix2_latest_api, get_vix2_history_api, backfill_vix2,
    backfill_vix2_walkforward,
)
from backend.api.middleware import login_required

logger = logging.getLogger(__name__)

vix2_bp = Blueprint("vix2", __name__, url_prefix="/api/vix2")


def _strict_integer(value, name: str) -> int:
    """Parse an integer parameter without silently truncating booleans/decimals."""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{name} 必须是整数")
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized and normalized.lstrip("+-").isdigit():
            return int(normalized)
    raise ValueError(f"{name} 必须是整数")


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
    """遗留分类器元数据，以及独立的时间顺序状态拟合审计摘要。"""
    meta = get_model_meta()
    if meta is None:
        return jsonify({
            "trained": False,
            "message": "遗留分类器尚未训练",
            "walkforward_validation": get_walkforward_meta(),
        }), 200
    return jsonify({
        "trained": True,
        **meta,
        "legacy_classifier": True,
        "legacy_warning": "历史分类器未显示稳健预测力，不得解释为交易信号",
        "walkforward_validation": get_walkforward_meta(),
    })


@vix2_bp.route("/train", methods=["POST"])
@login_required
def train_vix2_route():
    """触发离线重训（异步，返回 task_id）。body 可选: pt/sl/horizon/rv_scale。"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "训练参数必须是 JSON 对象"}), 400
    try:
        label_params = {
            "pt": float(body.get("pt", 0.05)),
            "sl": float(body.get("sl", 0.05)),
            "horizon": _strict_integer(body.get("horizon", 20), "horizon"),
            "rv_scale": bool(body.get("rv_scale", True)),
        }
        cv_gap = _strict_integer(body.get("cv_gap", 5), "cv_gap")
    except (TypeError, ValueError):
        return jsonify({"error": "horizon 和 cv_gap 必须是有效整数"}), 400
    if not 1 <= label_params["horizon"] <= 60:
        return jsonify({"error": "horizon 必须在 1 到 60 个交易日之间"}), 400
    if cv_gap < 5 or cv_gap > 60:
        return jsonify({"error": "cv_gap 必须在 5 到 60 个交易日之间"}), 400

    active = get_active_task_runs()
    if any(t.get("kind") == "vix2_train" for t in active):
        existing = next(t for t in active if t.get("kind") == "vix2_train")
        return jsonify({"error": "已有训练任务在进行中", "task_id": existing["id"]}), 409

    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(kind="vix2_train", title="VIX 2.0 模型训练",
                        payload={**label_params, "requested_cv_gap": cv_gap},
                        task_id=task_id) as t:
            meta = train_model(label_params=label_params, cv_gap=cv_gap,
                               progress=t.milestone)
            t.complete(result={
                "model_version": meta["model_version"],
                "cv_auc": meta["cv_auc"],
                "oos_auc": meta["oos_auc"],
                "n_samples": meta["n_samples"],
                "label_horizon": meta["label_horizon"],
                "requested_cv_gap": meta["requested_cv_gap"],
                "cv_gap": meta["cv_gap"],
            })

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({
        "message": "遗留未来方向分类器训练已启动",
        "warning": "该分类器未显示稳健预测力，仅供研究复核",
        "task_id": task_id,
    }), 202


@vix2_bp.route("/backfill", methods=["POST"])
@login_required
def backfill_vix2_route():
    """遗留分类器的全量模型历史回放；仅保留兼容，不是 OOS 结果。"""
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
    return jsonify({
        "message": "VIX 2.0 遗留 in-sample 回放已启动",
        "warning": "legacy research only；不得用作预测能力或交易信号证据",
        "task_id": task_id,
        "days": days,
    }), 202


@vix2_bp.route("/backfill_walkforward", methods=["POST"])
@login_required
def backfill_vix2_walkforward_route():
    """按时间顺序回填同日构造分状态估计（异步，返回 task_id）。

    body: days(0=全历史) / block_size(默认60交易日) / skip_existing。
    每个历史日只用该日之前训练的模型推断，修复旧 backfill 的 in-sample 回放。
    """
    active = get_active_task_runs()
    if any(t.get("kind") == "vix2_backfill" for t in active):
        existing = next(t for t in active if t.get("kind") == "vix2_backfill")
        return jsonify({"error": "已有回填任务在进行中", "task_id": existing["id"]}), 409

    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get("days", 0))
        block_size = int(body.get("block_size", 60))
        cv_gap = int(body.get("cv_gap", 5))
        min_train_samples = int(body.get("min_train_samples", 200))
    except (TypeError, ValueError):
        return jsonify({"error": "回填参数必须是有效整数"}), 400
    if days < 0:
        return jsonify({"error": "days 不能小于 0"}), 400
    if not 1 <= block_size <= 252:
        return jsonify({"error": "block_size 必须在 1 到 252 之间"}), 400
    if not 5 <= cv_gap <= 60:
        return jsonify({"error": "cv_gap 必须在 5 到 60 个交易日之间"}), 400
    if min_train_samples < 200:
        return jsonify({"error": "min_train_samples 必须至少为 200"}), 400
    skip_existing = bool(body.get("skip_existing", False))
    task_id = uuid.uuid4().hex

    def _run():
        with TaskRunner(kind="vix2_backfill",
                        title=f"VIX 2.0 walk-forward 回填 ({days or '全历史'})",
                        payload={"days": days, "block_size": block_size,
                                 "cv_gap": cv_gap,
                                 "min_train_samples": min_train_samples,
                                 "skip_existing": skip_existing, "walkforward": True},
                        task_id=task_id) as t:
            backfill_vix2_walkforward(days=days, block_size=block_size,
                                      skip_existing=skip_existing, task_runner=t,
                                      cv_gap=cv_gap,
                                      min_train_samples=min_train_samples)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({
        "message": "VIX 2.0 时间顺序实验状态估计已启动",
        "warning": "目标是同日构造状态，不是未来收益预测或交易信号",
        "task_id": task_id, "days": days, "block_size": block_size,
        "cv_gap": cv_gap, "min_train_samples": min_train_samples,
    }), 202
