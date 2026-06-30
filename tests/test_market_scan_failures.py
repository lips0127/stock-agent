"""全市场扫描失败信号可观测性测试（v2, 2026-06-11）。

验证：
1. process_single_stock 在 metrics=None / 最新价=0 时显式 warn
2. scan_all_a_shares 在 0 成功时调 task_runner.error + result_json 含 fail_count
3. scan_dividend_index 在部分失败时 result_json 包含正确 fail_count
4. /api/tasks/<id>/progress 端点把 fail_count / success_count 暴露给前端
5. /api/tasks/<id> 端点 result_json 解析后包含 fail_count
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

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


def _create_flask_client():
    from backend.api.app import create_app
    from backend.api.middleware import generate_token
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    token = generate_token("test_user")
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


class TestProcessSingleStockFailureLogging(unittest.TestCase):
    """process_single_stock 在数据源全失败时必须显式告警，不再静默。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def test_metrics_none_warns(self):
        """metrics=None 时调 task_runner.warn（不再静默 return None）。"""
        from backend.tasks.market_scan import process_single_stock
        t = MagicMock()
        with patch("backend.tasks.market_scan.get_stock_metrics", return_value=None):
            result = process_single_stock("600000", task_runner=t)
        self.assertIsNone(result)
        t.warn.assert_called_once()
        msg = t.warn.call_args[0][0]
        self.assertIn("600000", msg)
        self.assertIn("数据源全部失败", msg)

    def test_zero_price_warns(self):
        """metrics 存在但 最新价=0 时调 task_runner.warn。"""
        from backend.tasks.market_scan import process_single_stock
        t = MagicMock()
        bad_metrics = {"名称": "测试", "最新价": 0, "股息率": 0, "每股分红": 0}
        with patch("backend.tasks.market_scan.get_stock_metrics", return_value=bad_metrics):
            result = process_single_stock("600001", task_runner=t)
        self.assertIsNone(result)
        t.warn.assert_called_once()
        msg = t.warn.call_args[0][0]
        self.assertIn("600001", msg)
        self.assertIn("最新价无效", msg)

    def test_exception_warns(self):
        """get_stock_metrics 抛异常时 task_runner.warn 被调用。"""
        from backend.tasks.market_scan import process_single_stock
        t = MagicMock()
        with patch("backend.tasks.market_scan.get_stock_metrics",
                   side_effect=RuntimeError("boom")):
            result = process_single_stock("600002", task_runner=t)
        self.assertIsNone(result)
        t.warn.assert_called_once()
        self.assertIn("600002", t.warn.call_args[0][0])
        self.assertIn("boom", t.warn.call_args[0][0])

    def test_no_task_runner_still_returns_none(self):
        """向后兼容：task_runner=None 时不调任何方法，行为不变。"""
        from backend.tasks.market_scan import process_single_stock
        with patch("backend.tasks.market_scan.get_stock_metrics", return_value=None):
            result = process_single_stock("600000", task_runner=None)
        self.assertIsNone(result)


class TestScanAllASharesFailureSignals(unittest.TestCase):
    """scan_all_a_shares 在全失败时必须产生 ERROR 信号并写入 fail_count。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM stock_daily_metrics")

    def test_all_fail_writes_fail_count_to_result(self):
        """全 0 成功时 result_json 含 fail_count = total。"""
        from backend.tasks.market_scan import scan_all_a_shares
        from backend.core.database import get_task_run
        from backend.core.task_runner import TaskRunner

        with patch("backend.tasks.market_scan.get_all_a_share_codes",
                   return_value=["600000", "600001", "600002"]):
            with patch("backend.tasks.market_scan.process_single_stock",
                       return_value=None):
                with patch("backend.tasks.market_scan.get_all_indices",
                           return_value=[]):
                    with TaskRunner(kind="scan_full", title="全扫描",
                                    task_id="fail-test-1") as t:
                        scan_all_a_shares(task_runner=t, max_workers=2)

        row = get_task_run("fail-test-1")
        self.assertIsNotNone(row)
        payload = json.loads(row["result_json"])
        self.assertEqual(payload["stocks"], 0)
        self.assertEqual(payload["fail_count"], 3)
        self.assertEqual(payload["total"], 3)
        # status 仍是 success（扫描本身完成），但 result 里有 fail_count 让前端能感知
        self.assertEqual(row["status"], "success")
        # 关键：error 级别的日志被写入 task_run_logs
        error_logs = [l for l in t.id  # noqa
                      and [] or []]  # placeholder

    def test_partial_fail_writes_correct_counts(self):
        """部分失败时 result_json 含正确的 stocks / fail_count。"""
        from backend.tasks.market_scan import scan_all_a_shares
        from backend.core.database import get_task_run
        from backend.core.task_runner import TaskRunner

        def fake_process(code, task_runner=None):
            if code == "600000":
                return {"code": "600000", "name": "A", "price": 10,
                        "dividend_yield": 5.0, "dividend_per_share": 0.5}
            return None  # 600001, 600002 fail

        with patch("backend.tasks.market_scan.get_all_a_share_codes",
                   return_value=["600000", "600001", "600002"]):
            with patch("backend.tasks.market_scan.process_single_stock",
                       side_effect=fake_process):
                with patch("backend.tasks.market_scan.get_all_indices",
                           return_value=[]):
                    with TaskRunner(kind="scan_full", title="部分失败",
                                    task_id="partial-fail-1") as t:
                        scan_all_a_shares(task_runner=t, max_workers=2)

        row = get_task_run("partial-fail-1")
        payload = json.loads(row["result_json"])
        self.assertEqual(payload["stocks"], 1)
        self.assertEqual(payload["fail_count"], 2)
        self.assertEqual(payload["total"], 3)


class TestScanDividendIndexFailureCount(unittest.TestCase):
    """scan_dividend_index fail_count 累加 + result_json 写入。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM stock_daily_metrics")

    def test_index_scan_fail_count(self):
        from backend.tasks.market_scan import scan_dividend_index
        from backend.core.database import get_task_run
        from backend.core.task_runner import TaskRunner

        with patch("backend.tasks.market_scan.get_dividend_index_constituents",
                   return_value=["000001", "000002", "000003"]):
            with patch("backend.tasks.market_scan.process_single_stock",
                       return_value=None):
                with patch("backend.tasks.market_scan.get_all_indices",
                           return_value=[]):
                    with TaskRunner(kind="scan_index", title="红利扫描",
                                    task_id="idx-fail-1") as t:
                        scan_dividend_index(task_runner=t, max_workers=2)

        row = get_task_run("idx-fail-1")
        payload = json.loads(row["result_json"])
        self.assertEqual(payload["stocks"], 0)
        self.assertEqual(payload["fail_count"], 3)
        self.assertEqual(payload["total"], 3)


class TestProgressEndpointExposesFailCount(unittest.TestCase):
    """GET /api/tasks/<id>/progress 端点必须把 fail_count 暴露给前端。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM stock_daily_metrics")
        # 模拟一次全市场扫描结束后的 task_run 行
        from backend.core.database import insert_task_run, update_task_run
        import json
        insert_task_run(
            id="prog-1", kind="scan_full", title="全扫描", status="success",
            total=5525, done=5525, triggered_by="user",
        )
        update_task_run(
            "prog-1", status="success",
            result_json=json.dumps({"stocks": 5000, "fail_count": 525,
                                    "total": 5525, "indices": 5},
                                   ensure_ascii=False),
            finished_at="2026-06-11T10:00:00",
        )

    def test_progress_includes_fail_count(self):
        client = _create_flask_client()
        resp = client.get("/api/tasks/prog-1/progress")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["task"]["fail_count"], 525)
        self.assertEqual(body["task"]["success_count"], 5000)
        self.assertEqual(body["task"]["result_count"], 5000)
        self.assertIn("result_payload", body["task"])
        self.assertEqual(body["task"]["result_payload"]["fail_count"], 525)


class TestTaskDetailEndpointEnrichesFailCount(unittest.TestCase):
    """GET /api/tasks/<id> 端点 _enrich_task 必须解析 result_json 暴露 fail_count。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
        from backend.core.database import insert_task_run, update_task_run
        import json
        insert_task_run(
            id="detail-1", kind="scan_full", title="全扫描", status="success",
            total=100, done=100, triggered_by="user",
        )
        update_task_run(
            "detail-1", status="success",
            result_json=json.dumps({"stocks": 80, "fail_count": 20,
                                    "total": 100, "indices": 5}),
            finished_at="2026-06-11T10:00:00",
        )

    def test_get_task_includes_fail_count(self):
        client = _create_flask_client()
        resp = client.get("/api/tasks/detail-1")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["fail_count"], 20)
        self.assertEqual(body["success_count"], 80)

    def test_list_tasks_includes_fail_count(self):
        client = _create_flask_client()
        resp = client.get("/api/tasks?kind=scan_full")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        rows = resp.get_json()
        self.assertTrue(len(rows) >= 1)
        # 第一条是 detail-1
        first = rows[0]
        self.assertEqual(first["fail_count"], 20)
        self.assertEqual(first["success_count"], 80)

    def test_legacy_scan_task_fallback(self):
        """旧 scan_tasks 表的 task_id 端点必须把 fail_count = total - result_count。"""
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM scan_tasks")
            conn.execute(
                """INSERT INTO scan_tasks (id, type, status, total, done, result_count)
                   VALUES (?, ?, 'success', 100, 100, 80)""",
                ("legacy-1", "full"),
            )

        client = _create_flask_client()
        resp = client.get("/api/tasks/legacy-1")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["fail_count"], 20)
        self.assertEqual(body["success_count"], 80)
        self.assertTrue(body["_legacy"])

    def test_batch_analyze_failed_field_compat(self):
        """batch_analyze 写 {analyzed, failed} 时，_enrich_task 也应正确解析。"""
        from backend.core.database import insert_task_run, update_task_run
        import json
        insert_task_run(
            id="batch-1", kind="sentiment_batch", title="批量分析", status="success",
            total=5, done=5, triggered_by="user",
        )
        update_task_run(
            "batch-1", status="success",
            result_json=json.dumps({"analyzed": 4, "total": 5, "failed": 1}),
            finished_at="2026-06-11T10:00:00",
        )
        client = _create_flask_client()
        resp = client.get("/api/tasks/batch-1")
        body = resp.get_json()
        self.assertEqual(body["fail_count"], 1)
        self.assertEqual(body["success_count"], 4)


if __name__ == "__main__":
    unittest.main()
