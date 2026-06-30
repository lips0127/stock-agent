"""TaskRunner 单元测试（Phase A, 2026-06-10）。

TDD: 这些测试在 TaskRunner 实现之前编写，定义预期行为。
每个类使用独立的临时数据库，确保测试隔离。
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_temp_db() -> str:
    """Create a temp dir for DB and return its path. Caller must init_db()."""
    d = tempfile.mkdtemp()
    os.environ["CACHE_DIR"] = d
    # Force fresh imports for the new CACHE_DIR
    import backend.core.database as db_mod
    import backend.core.db_compat as compat_mod
    import importlib
    importlib.reload(compat_mod)
    importlib.reload(db_mod)
    db_mod._DB_PATH = Path(d) / "stocks.db"
    db_mod.init_db()
    return d


class TestTaskRunnerDatabase(unittest.TestCase):
    """task_runs / task_run_logs 表的 CRUD 操作（无 TaskRunner 依赖）。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")

    def _db(self):
        import backend.core.database as db
        return db

    def test_insert_and_get_task_run(self):
        db = self._db()
        tid = "test-insert-1"
        db.insert_task_run(
            id=tid, kind="scan_full", title="测试扫描", status="running",
            total=100, done=0, triggered_by="user",
        )
        row = db.get_task_run(tid)
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "scan_full")
        self.assertEqual(row["title"], "测试扫描")
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["total"], 100)
        self.assertEqual(row["done"], 0)

    def test_update_task_run(self):
        db = self._db()
        tid = "test-update-1"
        db.insert_task_run(id=tid, kind="scan_full", status="running", done=0)
        db.update_task_run(tid, status="success", done=100, duration_ms=5000)
        row = db.get_task_run(tid)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["done"], 100)
        self.assertEqual(row["duration_ms"], 5000)

    def test_update_task_run_ignores_unknown_fields(self):
        db = self._db()
        tid = "test-update-2"
        db.insert_task_run(id=tid, kind="scan_full", status="running")
        db.update_task_run(tid, nonexistent_field="should_be_ignored", status="success")
        row = db.get_task_run(tid)
        self.assertEqual(row["status"], "success")

    def test_list_task_runs_with_filters(self):
        db = self._db()
        db.insert_task_run(id="list-1", kind="scan_full", status="running", triggered_by="user")
        db.insert_task_run(id="list-2", kind="vix_backfill", status="success", triggered_by="user")
        db.insert_task_run(id="list-3", kind="scan_full", status="success", triggered_by="scheduler")

        results = db.list_task_runs(kind="scan_full", limit=10)
        self.assertEqual(len(results), 2)

        results = db.list_task_runs(status="running", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "list-1")

        results = db.list_task_runs(triggered_by="scheduler", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "list-3")

    def test_get_active_task_runs(self):
        db = self._db()
        db.insert_task_run(id="active-1", kind="scan_full", status="running")
        db.insert_task_run(id="active-2", kind="vix_backfill", status="running")
        db.insert_task_run(id="active-3", kind="scan_full", status="success")
        results = db.get_active_task_runs()
        self.assertEqual(len(results), 2)
        ids = {r["id"] for r in results}
        self.assertIn("active-1", ids)
        self.assertIn("active-2", ids)

    def test_get_recent_task_runs(self):
        db = self._db()
        for i in range(5):
            db.insert_task_run(id=f"recent-{i}", kind="scan_full", status="success")
        results = db.get_recent_task_runs(limit=3)
        self.assertEqual(len(results), 3)

    def test_mark_task_cancelled(self):
        db = self._db()
        tid = "cancel-1"
        db.insert_task_run(id=tid, kind="scan_full", status="running")
        result = db.mark_task_cancelled(tid)
        self.assertTrue(result)
        row = db.get_task_run(tid)
        self.assertEqual(row["cancel_requested"], 1)

        result = db.mark_task_cancelled("nonexistent")
        self.assertFalse(result)

    def test_append_and_get_task_run_logs(self):
        db = self._db()
        tid = "logs-1"
        db.insert_task_run(id=tid, kind="scan_full", status="running")
        db.append_task_run_log(tid, "milestone", "任务启动")
        db.append_task_run_log(tid, "info", "正在扫描 600519")
        db.append_task_run_log(tid, "milestone", "扫描完成")
        db.append_task_run_log(tid, "error", "网络超时", context_json={"code": "000001"})

        logs = db.get_task_run_logs(tid)
        self.assertEqual(len(logs), 4)

        logs = db.get_task_run_logs(tid, since_id=logs[1]["id"])
        self.assertEqual(len(logs), 2)

        logs = db.get_task_run_logs(tid, level="milestone")
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(l["level"] == "milestone" for l in logs))

    def test_get_latest_milestone(self):
        db = self._db()
        tid = "milestone-1"
        db.insert_task_run(id=tid, kind="scan_full", status="running")
        db.append_task_run_log(tid, "milestone", "第一阶段")
        db.append_task_run_log(tid, "info", "中间信息")
        db.append_task_run_log(tid, "milestone", "第二阶段")

        m = db.get_latest_milestone(tid)
        self.assertIsNotNone(m)
        self.assertEqual(m["message"], "第二阶段")


class TestTaskRunnerLifecycle(unittest.TestCase):
    """TaskRunner 上下文管理器生命周期测试。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")

    def _db(self):
        import backend.core.database as db
        return db

    def _runner(self):
        from backend.core.task_runner import TaskRunner
        return TaskRunner

    def test_basic_lifecycle_success(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="测试任务", triggered_by="user") as t:
            t.set_total(100)
            t.milestone("开始处理")
            t.progress(50)
            t.complete(result={"count": 100})

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["total"], 100)
        self.assertEqual(row["done"], 50)
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["finished_at"])

        logs = db.get_task_run_logs(t.id, level="milestone")
        milestone_msgs = [l["message"] for l in logs]
        self.assertTrue(any("任务启动" in m for m in milestone_msgs))
        self.assertTrue(any("开始处理" in m for m in milestone_msgs))
        self.assertTrue(any("任务完成" in m for m in milestone_msgs))

    def test_auto_complete_on_clean_exit(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="自动完成") as t:
            t.set_total(10)
            t.progress(10)

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "success")

    def test_failure_on_exception(self):
        TaskRunner = self._runner()
        db = self._db()

        with self.assertRaises(ValueError):
            with TaskRunner(kind="scan_full", title="会失败的任务") as t:
                t.milestone("开始")
                raise ValueError("模拟业务异常")

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "failed")
        self.assertIn("模拟业务异常", row["error_message"] or "")
        self.assertIsNotNone(row["error_traceback"])

    def test_cancellation(self):
        TaskRunner, TaskCancelled = self._runner(), None
        from backend.core.task_runner import TaskCancelled
        db = self._db()

        with self._runner()(kind="scan_full", title="可取消任务") as t:
            t.milestone("开始")
            raise TaskCancelled()

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "cancelled")

    def test_check_cancelled_polling(self):
        from backend.core.task_runner import TaskCancelled
        TaskRunner = self._runner()
        db = self._db()

        # 创建一个任务，在循环内检测到取消标记
        with TaskRunner(kind="scan_full", title="检查取消") as t:
            t.set_total(5)
            db.mark_task_cancelled(t.id)
            # 第一次 check_cancelled 查 DB，发现 cancel_requested=1 → 抛出
            t.check_cancelled()
            # 不应该走到这里
            self.fail("TaskCancelled not raised")

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "cancelled")

    def test_progress_throttle(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="节流测试") as t:
            t.set_total(100)
            for i in range(1, 21):
                t.progress(i)
            t.complete()

        row = db.get_task_run(t.id)
        self.assertEqual(row["done"], 20)

    def test_duration_calculation(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="耗时测试") as t:
            time.sleep(0.01)
            t.complete()

        row = db.get_task_run(t.id)
        self.assertIsNotNone(row["duration_ms"])
        self.assertGreater(row["duration_ms"], 0)

    def test_id_is_unique(self):
        TaskRunner = self._runner()
        ids = set()
        for _ in range(10):
            with TaskRunner(kind="scan_full", title="唯一性测试") as t:
                ids.add(t.id)
        self.assertEqual(len(ids), 10)

    def test_set_current_step(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="步骤测试") as t:
            t.set_current("扫描 600519")
            t.complete()

        row = db.get_task_run(t.id)
        # completed 时 current_step 被清空
        self.assertIsNone(row["current_step"])

        # running 中（未完成）读 current_step 需在 with 块内
        task_id = None
        with TaskRunner(kind="scan_full", title="步骤测试2") as t:
            task_id = t.id
            t.set_current("扫描 000001")
            # 不调 complete，但在 with 块内 current_step 应为设置值
            # 注意：set_current 立即写 DB，所以在 with 块内可以读到
            row2 = db.get_task_run(task_id)
            self.assertEqual(row2["current_step"], "扫描 000001")

    def test_info_warn_error_logs(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(kind="scan_full", title="日志测试") as t:
            t.info("一般信息")
            t.warn("警告信息")
            t.error("错误信息", exc_info=False)
            t.complete()

        logs = db.get_task_run_logs(t.id)
        levels = {l["level"] for l in logs}
        self.assertIn("info", levels)
        self.assertIn("warning", levels)
        self.assertIn("error", levels)

    def test_contextvar_injection(self):
        TaskRunner = self._runner()
        from backend.core.task_runner import current_task_run_id

        self.assertIsNone(current_task_run_id.get())
        with TaskRunner(kind="scan_full", title="contextvar测试") as t:
            self.assertEqual(current_task_run_id.get(), t.id)
        self.assertIsNone(current_task_run_id.get())

    def test_convenience_factory(self):
        from backend.core.task_runner import task
        db = self._db()

        with task("scan_full", title="便捷测试") as t:
            t.complete()

        row = db.get_task_run(t.id)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["kind"], "scan_full")

    def test_payload_json(self):
        TaskRunner = self._runner()
        db = self._db()

        with TaskRunner(
            kind="scan_full", title="带参数", payload={"symbols": ["600519", "000858"]}
        ) as t:
            t.complete()

        row = db.get_task_run(t.id)
        payload = json.loads(row["payload_json"])
        self.assertEqual(payload["symbols"], ["600519", "000858"])


if __name__ == "__main__":
    unittest.main()
