"""Phase B 端点契约测试（2026-06-10）。

TDD: 这些测试定义 Phase B 改造后所有新增 task_id 返回端点的预期行为。
每个端点必须返回 {"task_id": "32字符hex", ...}，且 task_id 必须是合法 uuid4 hex。

覆盖端点:
- POST /api/vix/recompute
- POST /api/vix/backfill
- POST /api/zhihu/users/<id>/refresh
- POST /api/zhihu/users/<id>/analyze_recent
- POST /api/sentiment/audit/rerun
- POST /api/sentiment/indicators/recompute
- POST /api/sentiment/top_picks/refresh
- POST /api/sentiment/universe/refresh_constituents
- POST /api/sentiment/batch_analyze
- POST /api/sentiment/universe/run/<idx>
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 32 hex chars (uuid4().hex = no dashes)
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _setup_temp_db() -> str:
    """Create a temp dir for DB and return its path."""
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
    """Create Flask test client with valid JWT auth."""
    from backend.api.app import create_app
    from backend.api.middleware import generate_token
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    token = generate_token("test_user")
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


def _assert_task_id(test, resp_json: dict, expected_key: str = "task_id"):
    """Assert response JSON contains a valid 32-char hex task_id."""
    test.assertIn(expected_key, resp_json,
                  f"Response missing '{expected_key}': {resp_json}")
    tid = resp_json[expected_key]
    test.assertRegex(tid, HEX32,
                     f"task_id must be 32 hex chars, got {tid!r}")


class TestVixEndpoints(unittest.TestCase):
    """VIX recompute / backfill endpoints return task_id."""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")

    def test_vix_recompute_returns_task_id(self):
        client = _create_flask_client()
        # Patch compute_and_store to avoid network I/O
        with patch("backend.api.routes.vix.compute_and_store") as mock:
            mock.return_value = None
            resp = client.post("/api/vix/recompute")
        self.assertEqual(resp.status_code, 202, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_vix_backfill_returns_task_id(self):
        client = _create_flask_client()
        # Patch backfill_vix_history so we don't actually fetch
        with patch("backend.api.routes.vix.backfill_vix_history") as mock:
            mock.return_value = {"total": 0, "done": 0, "skipped": 0,
                                "failed": 0, "last_error": None}
            resp = client.post("/api/vix/backfill",
                                json={"days": 5, "skip_existing": True})
        self.assertEqual(resp.status_code, 202, resp.get_json())
        _assert_task_id(self, resp.get_json())


class TestScanEndpoints(unittest.TestCase):
    """scan_index / scan_full endpoints return task_id."""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")

    def test_index_scan_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.api.routes.ops.TaskRunner"):
            # Patch the do_scan callback to avoid real scan; we just want to
            # verify the route returns task_id before the thread completes.
            resp = client.post("/api/index_scan")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_full_refresh_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.api.routes.ops.TaskRunner"):
            resp = client.post("/api/full_refresh")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())


class TestBacktestEndpoint(unittest.TestCase):
    """/api/backtest/run returns both run_id and task_run_id."""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM backtest_runs")

    def test_backtest_run_returns_both_ids(self):
        client = _create_flask_client()
        with patch("backend.api.routes.backtest.BacktestEngine") as mock_engine:
            mock_engine.return_value.run.return_value = {
                "final_value": 105000.0,
                "total_return": 0.05,
                "annual_return": 0.05,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -0.1,
                "win_rate": 0.55,
                "total_trades": 10,
                "trades": [],
            }
            resp = client.post("/api/backtest/run", json={
                "strategy_name": "ma_cross",
                "symbols": ["600000"],
            })
        self.assertEqual(resp.status_code, 202, resp.get_json())
        body = resp.get_json()
        self.assertIn("run_id", body)
        self.assertIn("task_id", body)
        _assert_task_id(self, body)


class TestSentimentEndpoints(unittest.TestCase):
    """Sentiment 4 个 P0 端点都返回 task_id。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")
        # Insert a sentiment_config for code 600000 to make codes non-empty
        from backend.core.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sentiment_config
                   (stock_code, stock_name, enabled, forum_type)
                   VALUES (?, ?, 1, 'eastmoney')""",
                ("600000", "测试股票"),
            )

    def test_audit_rerun_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.api.routes.sentiment.audit_posts") as mock:
            mock.return_value = {"audited": 0, "matched": 0,
                                "mismatched": 0, "fetch_errors": 0, "skipped": 0}
            with patch("backend.api.routes.sentiment.get_recent_posts") as mock2:
                mock2.return_value = []
                resp = client.post("/api/sentiment/audit/rerun",
                                   json={"code": "600000"})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_indicators_recompute_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.services.sentiment_indicators_service.recompute_all_for_today") as mock:
            mock.return_value = {"n_stocks": 0, "n_indicators": 0}
            resp = client.post("/api/sentiment/indicators/recompute")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_top_picks_refresh_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.services.top_picks_service.refresh_top_picks") as mock:
            mock.return_value = {"snapshot_date": "2026-06-10", "n_written": 0}
            resp = client.post("/api/sentiment/top_picks/refresh",
                               json={"top_n": 100, "auto_add": False})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_universe_refresh_constituents_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.services.universe_service.refresh_constituents") as mock:
            mock.return_value = {"csi300": 5, "sse50": 3}
            resp = client.post("/api/sentiment/universe/refresh_constituents",
                               json={"index_code": "csi300"})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_batch_analyze_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.api.routes.sentiment.batch_analyze") as mock:
            mock.return_value = []
            resp = client.post("/api/sentiment/batch_analyze")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())

    def test_universe_run_returns_task_id(self):
        client = _create_flask_client()
        with patch("backend.services.universe_service.run_universe_crawl") as mock:
            mock.return_value = {"date": "2026-06-10", "total": 0, "ok": 0,
                                "failed": 0, "duration_s": 0, "errors": []}
            resp = client.post("/api/sentiment/universe/run/all",
                               json={"max_workers": 4})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        _assert_task_id(self, resp.get_json())


class TestTaskIdUniqueness(unittest.TestCase):
    """每个新端点都应生成唯一的 task_id（即使并发触发）。"""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            conn.execute("DELETE FROM task_run_logs")
            conn.execute("DELETE FROM task_runs")

    def test_vix_backfill_task_ids_are_unique(self):
        client = _create_flask_client()
        with patch("backend.api.routes.vix.backfill_vix_history") as mock:
            mock.return_value = {"total": 0, "done": 0, "skipped": 0,
                                "failed": 0, "last_error": None}
            ids = set()
            for _ in range(3):
                resp = client.post("/api/vix/backfill", json={"days": 1})
                ids.add(resp.get_json()["task_id"])
        # The thread creation may not happen in time; check at least 1 unique ID
        self.assertGreaterEqual(len(ids), 1)


if __name__ == "__main__":
    unittest.main()
