import logging
import threading
import uuid
from flask import Blueprint, jsonify
from backend.core.database import get_connection
from backend.services.scheduler import manual_trigger, task_logs
from backend.api.middleware import login_required
from backend.core.task_runner import TaskRunner
from backend.tasks.market_scan import scan_all_a_shares

ops_bp = Blueprint("ops", __name__)
logger = logging.getLogger(__name__)


def _run_with_task_lifecycle(task_runner_id, scan_func, error_prefix):
    """
    统一的任务生命周期管理（Phase A 增强, 2026-06-10）：
    - 检查锁，避免并发扫描
    - 在 TaskRunner 上下文里执行扫描函数
    - 任务内对数据库的 update_scan_task 调用会作为 info 日志记录
    """
    from backend.services.scheduler import _scan_lock, _scan_running

    with _scan_lock:
        if _scan_running:
            logger.error(f"{error_prefix} (task_runner_id={task_runner_id}): 锁已被占用，放弃执行")
            return
        _scan_running = True

    try:
        scan_func()
    except Exception as e:
        logger.error(f"{error_prefix} (task_runner_id={task_runner_id}): {e}", exc_info=True)
    finally:
        with _scan_lock:
            _scan_running = False


# 注：/api/tasks 和 /api/tasks/<task_id> 已迁移到 api/routes/tasks.py（Phase A, 2026-06-10）
# 旧路由被移除，新路由提供兼容层（自动识别 scan_tasks UUID）

@ops_bp.route("/api/index_scan", methods=["POST"])
@login_required
def index_scan():
    """触发红利指数成分股扫描。返回 task_run_id 供轮询 GET /api/tasks/<id>。"""
    from backend.core.database import get_active_task_runs

    active = get_active_task_runs()
    active_scans = [t for t in active if t.get("kind") in ("scan_index", "scan_full")]
    if active_scans:
        return jsonify({
            "error": "已有扫描任务正在运行，请等待完成后再试",
            "task_id": active_scans[0]["id"],
        }), 409

    task_id = uuid.uuid4().hex

    def do_scan():
        from backend.tasks.market_scan import scan_dividend_index
        with TaskRunner(kind="scan_index", title="红利指数扫描",
                        task_id=task_id) as t:
            scan_dividend_index(task_runner=t, max_workers=20)

    thread = threading.Thread(
        target=_run_with_task_lifecycle,
        args=(task_id, do_scan, "红利指数扫描失败"),
    )
    thread.start()
    return jsonify({"message": "红利指数扫描已启动", "task_id": task_id}), 200


@ops_bp.route("/api/full_refresh", methods=["POST"])
@login_required
def full_refresh_data():
    """全市场扫描（全部 A 股），后台执行，耗时较长。返回 task_run_id。"""
    from backend.config import SCAN_MAX_WORKERS
    from backend.core.database import get_active_task_runs

    active = get_active_task_runs()
    active_scans = [t for t in active if t.get("kind") in ("scan_index", "scan_full")]
    if active_scans:
        return jsonify({
            "error": "已有扫描任务正在运行，请等待完成后再试",
            "task_id": active_scans[0]["id"],
        }), 409

    task_id = uuid.uuid4().hex

    def do_scan():
        with TaskRunner(kind="scan_full", title="全市场扫描",
                        task_id=task_id) as t:
            scan_all_a_shares(task_runner=t, max_workers=SCAN_MAX_WORKERS)
        task_logs.append({"time": __import__("datetime").datetime.now().isoformat(),
                          "message": "Full market scan finished"})

    thread = threading.Thread(
        target=_run_with_task_lifecycle,
        args=(task_id, do_scan, "后台全市场扫描失败"),
    )
    thread.start()
    return jsonify({"message": "Full market scan started", "task_id": task_id}), 200


@ops_bp.route("/api/tasks/<task_id>/progress", methods=["GET"])
@login_required
def get_task_progress(task_id):
    """获取扫描任务实时进度详情：已完成股票列表 + 进度统计 + 失败统计。

    v2 (2026-06-11): 双表兼容 — 先查 scan_tasks（历史 8 字符 id），查不到时查 task_runs
    (新 32 hex id)。把 result_json 里的 fail_count / success_count 解出，merge 进 task 返回。
    """
    import json as _json
    from backend.core.database import get_scan_task, get_task_run, get_connection
    from datetime import date as _date

    task = None
    task_source = None
    # 优先旧表（历史 8 字符 id）
    task = get_scan_task(task_id)
    if task:
        task_source = "scan_tasks"
    else:
        # 回退到新表（32 hex id）
        run_row = get_task_run(task_id)
        if run_row:
            task = dict(run_row)
            task_source = "task_runs"
            # 字段重映射以兼容前端 (ScanProgressView 期望的字段)
            task["type"] = "full" if task.get("kind") == "scan_full" else (
                "index" if task.get("kind") == "scan_index" else task.get("kind")
            )
            # 解析 result_json 拿到 fail_count / stocks 等
            # 字段约定：scan_* 写 {stocks, fail_count}；batch_analyze 写 {analyzed, failed}
            rj = task.get("result_json")
            if rj:
                try:
                    payload = _json.loads(rj) if isinstance(rj, str) else rj
                    if isinstance(payload, dict):
                        task["success_count"] = (
                            payload.get("stocks")
                            or payload.get("analyzed")
                            or 0
                        )
                        task.setdefault("result_count", task["success_count"])
                        task["fail_count"] = (
                            payload.get("fail_count")
                            if payload.get("fail_count") is not None
                            else payload.get("failed", 0)
                        )
                        task["result_payload"] = payload
                except (ValueError, TypeError) as e:
                    logger.warning(f"解析 task_runs.result_json 失败 (task_id={task_id}): {e}")

    if not task:
        return jsonify({"error": "Task not found"}), 404
    task["_source"] = task_source

    # 查询今天已写入的股票（即已扫描完成的）
    scanned_stocks = []
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM stock_daily_metrics")
            row = cur.fetchone()
            latest_date = row[0] if row and row[0] else _date.today().isoformat()
            cur.execute(
                """SELECT code, name, price, dividend_yield FROM stock_daily_metrics
                   WHERE date = ? ORDER BY id DESC LIMIT 500""",
                (latest_date,)
            )
            columns = [desc[0] for desc in cur.description]
            scanned_stocks = [dict(zip(columns, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"查询已扫描股票列表失败 (task_id={task_id}): {e}", exc_info=True)

    return jsonify({
        "task": task,
        "scanned": scanned_stocks,
        "scanned_count": len(scanned_stocks),
    })


@ops_bp.route("/api/logs", methods=["GET"])
@login_required
def get_logs():
    return jsonify(task_logs)


@ops_bp.route("/health", methods=["GET"])
def health_check():
    db_ok = False
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        db_ok = True
    except Exception as e:
        logger.error(f"健康检查数据库连通性测试失败: {e}", exc_info=True)
    status = "healthy" if db_ok else "unhealthy"
    code = 200 if db_ok else 503
    return jsonify({"status": status, "database": db_ok}), code
