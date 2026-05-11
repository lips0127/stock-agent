import logging
import threading
from flask import Blueprint, jsonify
from backend.core.database import get_connection
from backend.services.scheduler import manual_trigger, task_logs
from backend.api.middleware import login_required
from backend.tasks.market_scan import scan_all_a_shares

ops_bp = Blueprint("ops", __name__)
logger = logging.getLogger(__name__)


def _run_with_task_lifecycle(task_id, scan_func, error_prefix):
    """
    统一的任务生命周期管理：
    - 检查锁，避免并发扫描
    - 执行扫描函数
    - 无论成功或失败，都会更新 DB 中的任务状态
    """
    from backend.core.database import update_scan_task
    from backend.services.scheduler import _scan_lock, _scan_running

    with _scan_lock:
        if _scan_running:
            update_scan_task(task_id, status='failed',
                             error_message="并发冲突：已有扫描任务正在运行（锁被占用）")
            logger.error(f"{error_prefix} (task_id={task_id}): 锁已被占用，放弃执行")
            return
        _scan_running = True

    try:
        scan_func()
    except Exception as e:
        logger.error(f"{error_prefix} (task_id={task_id}): {e}", exc_info=True)
        update_scan_task(task_id, status='failed', error_message=str(e))
    finally:
        with _scan_lock:
            _scan_running = False


@ops_bp.route("/api/index_scan", methods=["POST"])
@login_required
def index_scan():
    """触发红利指数成分股扫描。"""
    from backend.core.database import create_scan_task, get_all_scan_tasks

    running_tasks = [t for t in get_all_scan_tasks(limit=10) if t['status'] == 'running']
    if running_tasks:
        return jsonify({
            "error": "已有扫描任务正在运行，请等待完成后再试",
            "task_id": running_tasks[0]['id']
        }), 409

    task_id = create_scan_task("index")

    def do_scan():
        from backend.tasks.market_scan import scan_dividend_index
        scan_dividend_index(task_id=task_id, max_workers=20)

    thread = threading.Thread(
        target=_run_with_task_lifecycle,
        args=(task_id, do_scan, "红利指数扫描失败"),
    )
    thread.start()
    return jsonify({"message": "红利指数扫描已启动", "task_id": task_id}), 200


@ops_bp.route("/api/full_refresh", methods=["POST"])
@login_required
def full_refresh_data():
    """全市场扫描（全部 A 股），后台执行，耗时较长。"""
    from backend.config import SCAN_MAX_WORKERS
    from backend.core.database import create_scan_task, get_all_scan_tasks

    running_tasks = [t for t in get_all_scan_tasks(limit=10) if t['status'] == 'running']
    if running_tasks:
        return jsonify({
            "error": "已有扫描任务正在运行，请等待完成后再试",
            "task_id": running_tasks[0]['id']
        }), 409

    task_id = create_scan_task("full")

    def do_scan():
        scan_all_a_shares(max_workers=SCAN_MAX_WORKERS, task_id=task_id)
        task_logs.append({"time": __import__("datetime").datetime.now().isoformat(),
                          "message": "Full market scan finished"})

    thread = threading.Thread(
        target=_run_with_task_lifecycle,
        args=(task_id, do_scan, "后台全市场扫描失败"),
    )
    thread.start()
    return jsonify({"message": "Full market scan started", "task_id": task_id}), 200


@ops_bp.route("/api/tasks", methods=["GET"])
@login_required
def list_tasks():
    """列出最近的任务状态。"""
    from backend.core.database import get_all_scan_tasks
    tasks = get_all_scan_tasks(limit=20)
    return jsonify(tasks)


@ops_bp.route("/api/tasks/<task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    """查询单个任务状态。"""
    from backend.core.database import get_scan_task
    task = get_scan_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@ops_bp.route("/api/tasks/<task_id>/progress", methods=["GET"])
@login_required
def get_task_progress(task_id):
    """获取扫描任务实时进度详情：已完成股票列表 + 进度统计。"""
    from backend.core.database import get_scan_task, get_connection
    from datetime import date as _date

    task = get_scan_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

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
