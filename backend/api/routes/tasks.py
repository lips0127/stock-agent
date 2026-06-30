"""统一任务 API 路由（Phase A, 2026-06-10）。

提供所有异步任务的统一查询入口：
- GET  /api/tasks              任务列表
- GET  /api/tasks/active        当前运行中的任务
- GET  /api/tasks/recent        最近完成的任务
- GET  /api/tasks/<id>          任务详情
- GET  /api/tasks/<id>/logs     增量日志
- POST /api/tasks/<id>/cancel   请求取消
"""

import logging
import json as _json
from flask import Blueprint, jsonify, request
from backend.api.middleware import login_required
from backend.core.database import (
    get_active_task_runs,
    get_latest_milestone,
    get_recent_task_runs,
    get_task_run,
    get_task_run_logs,
    list_task_runs,
    mark_task_cancelled,
)
from backend.core.task_kinds import kind_label

tasks_bp = Blueprint("tasks", __name__)
logger = logging.getLogger(__name__)


def _enrich_task(row: dict) -> dict:
    """给 task_run 行增加派生字段（progress_pct / elapsed_seconds / latest_milestone / 失败统计）。

    v2 (2026-06-11): 解析 result_json 暴露 fail_count / success_count / 失败原因分布。
    """
    total = row.get("total") or 0
    done = row.get("done") or 0
    row["progress_pct"] = round(done / total * 100, 1) if total > 0 else 0.0

    started = row.get("started_at")
    finished = row.get("finished_at")
    if started:
        from datetime import datetime
        try:
            end = (
                datetime.fromisoformat(finished)
                if finished
                else datetime.now()
            )
            start = datetime.fromisoformat(started)
            row["elapsed_seconds"] = int((end - start).total_seconds())
        except (ValueError, TypeError):
            row["elapsed_seconds"] = None
    else:
        row["elapsed_seconds"] = None

    row["latest_milestone"] = get_latest_milestone(row["id"])
    row["kind_label"] = kind_label(row.get("kind", ""))

    # 解析 result_json 拿到失败统计（v2 2026-06-11）
    # 字段约定：scan_* 写 {stocks, fail_count}；batch_analyze 写 {analyzed, failed}
    rj = row.get("result_json")
    if rj:
        try:
            payload = _json.loads(rj) if isinstance(rj, str) else rj
            if isinstance(payload, dict):
                row["success_count"] = (
                    payload.get("stocks")
                    or payload.get("analyzed")
                    or payload.get("success_count")
                    or 0
                )
                row["fail_count"] = (
                    payload.get("fail_count")
                    if payload.get("fail_count") is not None
                    else payload.get("failed", 0)
                )
                row["result_payload"] = payload
        except (ValueError, TypeError) as e:
            logger.warning(f"解析 task_runs.result_json 失败 (id={row.get('id')}): {e}")
    return row


@tasks_bp.route("/api/tasks", methods=["GET"])
@login_required
def list_tasks():
    """任务列表，支持 ?kind=&status=&triggered_by=&limit=。"""
    kind = request.args.get("kind")
    status = request.args.get("status")
    triggered_by = request.args.get("triggered_by")
    limit = min(int(request.args.get("limit", 20)), 100)
    rows = list_task_runs(kind=kind, status=status, triggered_by=triggered_by, limit=limit)
    return jsonify([_enrich_task(r) for r in rows])


@tasks_bp.route("/api/tasks/active", methods=["GET"])
@login_required
def active_tasks():
    """当前所有 running 任务。"""
    rows = get_active_task_runs()
    return jsonify([_enrich_task(r) for r in rows])


@tasks_bp.route("/api/tasks/recent", methods=["GET"])
@login_required
def recent_tasks():
    """最近 N 个任务（任意状态）。"""
    limit = min(int(request.args.get("limit", 20)), 100)
    rows = get_recent_task_runs(limit=limit)
    return jsonify([_enrich_task(r) for r in rows])


@tasks_bp.route("/api/tasks/<task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    """任务详情（含进度、耗时、最新 milestone、失败统计）。"""
    row = get_task_run(task_id)
    if not row:
        # 兼容旧 scan_tasks UUID
        from backend.core.database import get_scan_task
        old = get_scan_task(task_id)
        if not old:
            return jsonify({"error": "Task not found"}), 404
        # 旧表行转为兼容格式（旧表无 fail_count，置 0 占位）
        total = old.get("total", 0) or 0
        result_count = old.get("result_count", 0) or 0
        return jsonify({
            "id": old["id"],
            "kind": old.get("type", "scan_legacy"),
            "title": f"扫描 ({old.get('type', '')})",
            "status": old.get("status", "unknown"),
            "total": total,
            "done": old.get("done", 0),
            "progress_pct": round(old.get("done", 0) / max(total, 1) * 100, 1),
            "current_step": None,
            "error_message": old.get("error_message"),
            "triggered_by": "user",
            "started_at": old.get("created_at"),
            "finished_at": None,
            "duration_ms": None,
            "elapsed_seconds": None,
            "latest_milestone": None,
            "kind_label": "扫描",
            "_legacy": True,
            "success_count": result_count,
            "fail_count": max(total - result_count, 0) if total > 0 else 0,
        })
    return jsonify(_enrich_task(row))


@tasks_bp.route("/api/tasks/<task_id>/logs", methods=["GET"])
@login_required
def get_task_logs(task_id):
    """增量拉取任务日志。?since_id=N&level=milestone。"""
    since_id = int(request.args.get("since_id", 0))
    level = request.args.get("level") or None
    logs = get_task_run_logs(task_id, since_id=since_id, level=level)
    next_since_id = logs[-1]["id"] if logs else since_id
    return jsonify({
        "task_run_id": task_id,
        "logs": logs,
        "next_since_id": next_since_id,
        "has_more": len(logs) > 0,
    })


@tasks_bp.route("/api/tasks/<task_id>/cancel", methods=["POST"])
@login_required
def cancel_task(task_id):
    """请求取消任务（协作式，任务自行轮询 cancel_requested 标志）。"""
    found = mark_task_cancelled(task_id)
    if not found:
        return jsonify({"error": "Task not found"}), 404
    logger.info("[task=%s] 用户请求取消", task_id[:8] if len(task_id) > 8 else task_id)
    return jsonify({"message": "取消请求已提交", "task_id": task_id})
