"""统一任务执行器（Phase A, 2026-06-10）。

提供 TaskRunner 上下文管理器，所有异步任务通过它包裹以获得：
- 唯一 task_run_id
- 持久化进度（task_runs 表）
- milestone / info / warn / error 日志（task_run_logs 表）
- 协作式取消（check_cancelled）
- 自动异常捕获与失败标记
"""

import contextvars
import json
import logging
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from .database import (
    append_task_run_log,
    get_task_run,
    insert_task_run,
    mark_task_cancelled,
    update_task_run,
)

current_task_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_task_run_id", default=None
)


class TaskCancelled(Exception):
    """任务被用户取消时抛出。由 TaskRunner.__exit__ 捕获并吃掉。"""


class TaskRunner:
    """统一任务执行器（上下文管理器）。

    用法:
        with TaskRunner(kind='scan_full', title='全市场扫描', triggered_by='user') as t:
            t.milestone('开始拉取股票列表')
            stocks = get_all_a_share_codes()
            t.set_total(len(stocks))
            t.milestone(f'开始扫描 {len(stocks)} 只股票')
            for i, code in enumerate(stocks):
                t.check_cancelled()
                t.set_current(f'扫描 {code}')
                process_single_stock(code)
                t.progress(i + 1)
            t.milestone('扫描完成')
            t.complete(result={'count': len(stocks)})
    """

    def __init__(
        self,
        kind: str,
        title: str | None = None,
        triggered_by: str = "user",
        user_id: int | None = None,
        scheduler_job: str | None = None,
        payload: dict | None = None,
        task_id: str | None = None,
    ):
        self.id = task_id or uuid.uuid4().hex
        self.kind = kind
        self.title = title or kind
        self.triggered_by = triggered_by
        self.user_id = user_id
        self.scheduler_job = scheduler_job
        self.payload = payload or {}
        self._status = "pending"
        self._total = 0
        self._done = 0
        self._current_step = None
        self._token: Any = None
        self._logger = logging.getLogger(f"task.{kind}")
        self._throttle_counter = 0
        self._cancel_check_counter = 0
        self._cached_cancel_requested = False

    def __enter__(self):
        insert_task_run(
            id=self.id,
            kind=self.kind,
            title=self.title,
            status="running",
            triggered_by=self.triggered_by,
            user_id=self.user_id,
            scheduler_job=self.scheduler_job,
            payload_json=json.dumps(self.payload, ensure_ascii=False),
            started_at=datetime.now().isoformat(),
        )
        self._status = "running"
        self._token = current_task_run_id.set(self.id)
        self._logger.info("[task=%s kind=%s] started: %s", self.id[:8], self.kind, self.title)
        self.milestone(f"任务启动: {self.title}", silent_log=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is TaskCancelled:
                self._finalize("cancelled", error_message="用户取消")
                self._logger.info("[task=%s] cancelled", self.id[:8])
                return True
            elif exc_type is not None:
                tb_text = "".join(
                    traceback.format_exception(exc_type, exc_val, exc_tb)
                )
                self._finalize("failed", error_message=str(exc_val), error_traceback=tb_text)
                self._logger.exception("[task=%s] failed", self.id[:8])
                return False
            elif self._status == "running":
                self._finalize("success")
        finally:
            if self._token is not None:
                current_task_run_id.reset(self._token)

    # ── 进度 API ──

    def set_total(self, total: int):
        self._total = total
        update_task_run(self.id, total=total)

    def set_current(self, step: str):
        self._current_step = step
        update_task_run(self.id, current_step=step)

    def progress(self, done: int):
        """更新已完成数。默认每 5 次调用才写一次 DB（避免高频写）。"""
        self._done = done
        self._throttle_counter += 1
        if self._throttle_counter >= 5 or done == self._total:
            update_task_run(self.id, done=done)
            self._throttle_counter = 0

    # ── 日志 API ──

    def milestone(self, msg: str, context: dict | None = None, silent_log: bool = False):
        """关键节点，前端会突出显示。"""
        append_task_run_log(self.id, level="milestone", message=msg, context_json=context)
        if not silent_log:
            self._logger.info("[milestone] %s", msg)

    def info(self, msg: str, context: dict | None = None):
        """一般进度信息。用于重要节点，不建议在循环内高频调用（无节流）。"""
        append_task_run_log(self.id, level="info", message=msg, context_json=context)
        self._logger.info(msg)

    def warn(self, msg: str, context: dict | None = None):
        """可恢复异常。"""
        append_task_run_log(self.id, level="warning", message=msg, context_json=context)
        self._logger.warning(msg)

    def error(self, msg: str, exc_info: bool = False, context: dict | None = None):
        """不可恢复异常。"""
        append_task_run_log(self.id, level="error", message=msg, context_json=context)
        if exc_info:
            self._logger.exception(msg)
        else:
            self._logger.error(msg)

    # ── 完成 / 失败 / 取消 ──

    def complete(self, result: dict | None = None):
        """标记任务成功完成。"""
        self._finalize(
            "success",
            result_json=json.dumps(result, ensure_ascii=False) if result else None,
        )
        self.milestone("任务完成", silent_log=True)

    def fail(self, error: str, traceback_text: str | None = None):
        """显式标记任务失败。"""
        self._finalize("failed", error_message=error, error_traceback=traceback_text)

    def check_cancelled(self):
        """协作式取消检查点。任务在循环内调用此方法，检测是否被前端取消。

        缓存策略：首次调用查 DB，之后每 20 次查一次；一旦确认被取消则缓存结果不再查 DB。
        """
        if self._cached_cancel_requested:
            raise TaskCancelled()
        self._cancel_check_counter += 1
        if self._cancel_check_counter > 1 and self._cancel_check_counter % 20 != 0:
            return
        row = get_task_run(self.id)
        if row and row.get("cancel_requested"):
            self._cached_cancel_requested = True
            raise TaskCancelled()

    def _finalize(self, status: str, **kwargs):
        if self._status == status:
            return
        self._status = status
        finished_dt = datetime.now()
        finished = finished_dt.isoformat()
        # Calculate duration from started_at
        duration = None
        row = get_task_run(self.id)
        if row and row.get("started_at"):
            try:
                started = datetime.fromisoformat(row["started_at"])
                duration = int((finished_dt - started).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass
        update_task_run(
            self.id,
            status=status,
            finished_at=finished,
            done=self._done,
            current_step=None,
            duration_ms=duration,
            **kwargs,
        )


@contextmanager
def task(kind: str, **kwargs):
    """便捷工厂: with task('scan_full', title='全市场扫描') as t: ..."""
    with TaskRunner(kind, **kwargs) as t:
        yield t
