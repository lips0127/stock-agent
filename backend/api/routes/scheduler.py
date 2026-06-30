"""任务调度 API 路由（v5, 2026-06-06）。"""
import logging

from flask import Blueprint, jsonify, request

from backend.api.middleware import login_required
from backend.core.database import (
    get_all_scheduler_configs, get_recent_runs, get_scheduler_config,
)
from backend.services.scheduler_config_service import (
    JOB_REGISTRY_BY_ID, apply_pause, apply_reschedule, apply_resume,
    compute_next_run_time, validate_field,
)

scheduler_bp = Blueprint("scheduler", __name__)
logger = logging.getLogger(__name__)


def _serialize_row(row: dict) -> dict:
    """把 DB row 转前端友好格式：注入 function_name、格式化 next_run_time。

    next_run_time 兜底逻辑：DB 里的值可能为空（首次启动 init 还没同步，
    或 CronTrigger lazy 计算 get_job().next_run_time 拿不到），
    从 trigger.get_next_fire_time() 算一次。
    """
    reg = JOB_REGISTRY_BY_ID.get(row["job_id"], {})
    out = dict(row)
    out["function_name"] = reg.get("func_name", "unknown")
    nrt = row.get("next_run_time")
    if not nrt:
        try:
            nrt = compute_next_run_time(row)
        except Exception:
            pass
    if nrt and isinstance(nrt, str):
        # SQLite 返回 'YYYY-MM-DD HH:MM:SS'，标准化为 ISO
        if "T" not in nrt and " " in nrt:
            nrt = nrt.replace(" ", "T")
    out["next_run_time"] = nrt
    return out


@scheduler_bp.route("/api/scheduler/configs", methods=["GET"])
@login_required
def list_configs():
    """列出所有 10 个任务的可调配置。"""
    rows = get_all_scheduler_configs()
    return jsonify([_serialize_row(r) for r in rows])


@scheduler_bp.route("/api/scheduler/configs/<job_id>", methods=["PATCH"])
@login_required
def patch_config(job_id: str):
    """更新一个任务的配置（timing / enabled）。保存后立即 reschedule。"""
    row = get_scheduler_config(job_id)
    if not row:
        return jsonify({"error": f"job_id not found: {job_id}"}), 404

    payload = request.json or {}
    trigger_type = row["trigger_type"]

    # 字段验证
    for k, v in payload.items():
        err = validate_field(trigger_type, k, v)
        if err:
            return jsonify({"error": err, "field": k}), 400

    # username 来自 JWT（login_required 中间件注入 g.current_user）
    from flask import g
    updated_by = getattr(g, "current_user", None)

    try:
        result = apply_reschedule(job_id, payload, updated_by=updated_by)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@scheduler_bp.route("/api/scheduler/configs/<job_id>/<action>", methods=["POST"])
@login_required
def action(job_id: str, action: str):
    """立即暂停 / 恢复一个任务（不需重启 Flask）。"""
    row = get_scheduler_config(job_id)
    if not row:
        return jsonify({"error": f"job_id not found: {job_id}"}), 404
    if action == "pause":
        return jsonify(apply_pause(job_id))
    if action == "resume":
        return jsonify(apply_resume(job_id))
    return jsonify({"error": f"unknown action: {action}"}), 400


@scheduler_bp.route("/api/scheduler/configs/<job_id>/runs", methods=["GET"])
@login_required
def list_runs(job_id: str):
    """返回 job_id 的最近 N 条运行记录（按 started_at DESC）。

    Query: ?limit=20（默认 20，上限 100）。
    """
    row = get_scheduler_config(job_id)
    if not row:
        return jsonify({"error": f"job_id not found: {job_id}"}), 404

    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))

    runs = get_recent_runs(job_id, limit=limit)
    return jsonify(runs)
