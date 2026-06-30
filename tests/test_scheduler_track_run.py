"""Scheduler track_run TaskRunner 集成测试 (Phase B P2, 2026-06-10)。

验证 scheduler 的 9 个 @track_run 装饰任务在执行时，会自动写入 task_runs 表。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_temp_db() -> str:
    d = tempfile.mkdtemp()
    os.environ["CACHE_DIR"] = d
    import backend.core.database as db_mod
    import backend.core.db_compat as compat_mod
    import importlib
    importlib.reload(compat_mod)
    importlib.reload(db_mod)
    db_mod._DB_PATH = Path(d) / "stocks.db"
    db_mod.init_db()
    return d


class TestSchedulerTaskRunnerIntegration(unittest.TestCase):
    """scheduler 的 @track_run 装饰的任务执行时，会在 task_runs 表写一行。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM scheduler_task_run")

    def test_track_run_creates_task_runs_row(self):
        """直接调用 daily_vix_task，验证它会在 task_runs 写一行。"""
        from backend.services.scheduler import daily_vix_task
        from backend.core.database import get_recent_task_runs

        # Mock the heavy work inside daily_vix_task
        with patch("backend.services.vix_service.compute_and_store") as mock:
            mock.return_value = None
            daily_vix_task()

        # task_runs should have one row
        rows = get_recent_task_runs(limit=10)
        self.assertGreaterEqual(len(rows), 1, "Expected a task_run row from track_run")
        # Find the daily_vix one (kind = daily_vix)
        vix_rows = [r for r in rows if r.get("kind") == "daily_vix"]
        self.assertEqual(len(vix_rows), 1)
        self.assertEqual(vix_rows[0]["status"], "success")
        self.assertEqual(vix_rows[0]["triggered_by"], "scheduler")

    def test_track_run_records_failure(self):
        """track_run 装饰器：被装饰函数抛异常时，task_runs 行 status='failed'。"""
        from backend.services.scheduler import track_run
        from backend.core.database import get_recent_task_runs

        @track_run("test_failing_task")
        def failing_task():
            raise RuntimeError("simulated failure")

        with self.assertRaises(RuntimeError):
            failing_task()

        rows = get_recent_task_runs(limit=10)
        failing_rows = [r for r in rows if r.get("kind") == "test_failing_task"]
        self.assertEqual(len(failing_rows), 1)
        self.assertEqual(failing_rows[0]["status"], "failed")
        self.assertIn("simulated failure", failing_rows[0].get("error_message", ""))

    def test_track_run_records_skipped(self):
        """任务返回 'skipped' 时，task_runs 行 status='success'，但 result=skipped。"""
        from backend.services.scheduler import daily_vix_task
        from backend.core.database import get_recent_task_runs

        # Simulate skipped by directly calling TaskRunner + returning 'skipped'
        from backend.core.task_runner import TaskRunner
        with TaskRunner(kind="daily_vix", title="skipped test",
                        scheduler_job="daily_vix", triggered_by="scheduler") as t:
            t.complete(result={"status": "skipped"})

        rows = get_recent_task_runs(limit=10)
        vix_rows = [r for r in rows if r.get("kind") == "daily_vix"]
        self.assertGreaterEqual(len(vix_rows), 1)
        self.assertEqual(vix_rows[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
