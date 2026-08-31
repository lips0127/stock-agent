# -*- coding: utf-8 -*-
"""init_scheduler 回归测试（2026-08-31 生产事故）。

事故背景：init_scheduler 以 add_job(..., next_run_time=None) 注册任务，而
APScheduler 3.x 中 next_run_time=None 的语义是「以暂停态添加」。导致除
forum_prefetch（显式传了 now）外，全部 8 个 cron 任务出生即暂停、永不触发，
且 DB next_run_time 显示为 NULL 长期未被发现。

本测试固化两条约束：
1. 启用任务注册后必须带有 trigger 计算出的 next_run_time（cron 也是）；
2. 禁用任务必须处于 paused（next_run_time 为 None）。

注意：init_scheduler 首次调用时才 seed scheduler_task_config（INSERT OR IGNORE），
因此 setUpClass 先跑一次 init 完成种子，UPDATE/断言才有目标行。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_temp_db() -> None:
    d = tempfile.mkdtemp()
    os.environ["CACHE_DIR"] = d
    import backend.core.database as db_mod
    import backend.core.db_compat as compat_mod
    import importlib
    importlib.reload(compat_mod)
    importlib.reload(db_mod)
    db_mod._DB_PATH = Path(d) / "stocks.db"
    db_mod.init_db()


class TestSchedulerInitJobState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_temp_db()
        # 首次 init 完成 seed；否则后续 UPDATE 无行可改
        from backend.services.scheduler import init_scheduler, get_scheduler
        init_scheduler()
        get_scheduler().shutdown(wait=False)

    def tearDown(self):
        """每个用例结束后关掉调度器，避免线程泄漏。"""
        try:
            from backend.services.scheduler import get_scheduler, set_scheduler_for_test
            get_scheduler().shutdown(wait=False)
        except Exception:
            pass
        set_scheduler_for_test(None)

    def _init(self):
        from backend.services.scheduler import init_scheduler, get_scheduler
        init_scheduler()
        return get_scheduler()

    def test_enabled_cron_jobs_have_next_run_time(self):
        """启用任务（含全部 cron 任务）注册后必须有非 None 的 next_run_time。

        修复前：cron 任务因 next_run_time=None 被添加为 paused，断言失败。
        """
        # 本用例与禁用用例共享临时 DB，先把自己依赖的行恢复为启用
        from backend.core.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE scheduler_task_config SET enabled = 1 WHERE job_id = 'daily_vix'"
            )

        sched = self._init()
        jobs = {job.id: job for job in sched.get_jobs()}

        self.assertIn("daily_update", jobs)
        self.assertIn("daily_vix", jobs)
        for job_id in ("daily_update", "daily_vix", "daily_sentiment",
                       "universe_aggregate_daily"):
            job = jobs.get(job_id)
            self.assertIsNotNone(job, f"{job_id} 未注册")
            self.assertIsNotNone(
                job.next_run_time,
                f"{job_id} next_run_time 为 None：任务处于 paused，永远不会触发",
            )

    def test_disabled_job_is_paused(self):
        """禁用任务注册后应处于 paused（next_run_time 为 None）。"""
        from backend.core.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "UPDATE scheduler_task_config SET enabled = 0 WHERE job_id = 'daily_vix'"
            )
        sched = self._init()
        job = next(j for j in sched.get_jobs() if j.id == "daily_vix")
        self.assertIsNone(job.next_run_time, "禁用任务应被暂停")


if __name__ == "__main__":
    unittest.main()
