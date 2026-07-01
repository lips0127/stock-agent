"""十倍股 API 路由测试（Step 4b）。

用 Flask test client + 临时数据库验证 4 个端点。不跑真实扫描（scan 端点
验证防重 + 返回 task_id；扫描线程用 mock 避免联网）。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_temp_db():
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


class TestTenbagRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()
        from backend.api.app import create_app
        from backend.api.middleware import generate_token
        os.environ["FRONTEND_DEV_PROXY"] = "false"
        app = create_app()
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.token = generate_token("test_user")
        cls.auth = {"HTTP_AUTHORIZATION": f"Bearer {cls.token}"}

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            for t in ("tenbag_pools", "tenbag_trend_signals",
                     "tenbag_anomaly_signals", "task_runs", "task_run_logs"):
                conn.execute(f"DELETE FROM {t}")

    def test_pools_empty_returns_200(self):
        r = self.client.get("/api/tenbag/pools", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsNone(data["snapshot_date"])
        self.assertEqual(data["pools"], [])

    def test_pools_with_data(self):
        import backend.core.database as db
        db.upsert_tenbag_pool("2026-07-01", "600519", "1", reasons=["趋势确认"])
        db.upsert_tenbag_pool("2026-07-01", "000001", "exclude", reasons=["炒作"])
        r = self.client.get("/api/tenbag/pools?tier=1", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["snapshot_date"], "2026-07-01")
        self.assertEqual(len(data["pools"]), 1)
        self.assertEqual(data["pools"][0]["symbol"], "600519")

    def test_pools_bad_tier_400(self):
        r = self.client.get("/api/tenbag/pools?tier=9", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_signals_404_when_missing(self):
        r = self.client.get("/api/tenbag/signals/999999", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_signals_returns_data(self):
        import backend.core.database as db
        db.upsert_tenbag_trend("600519", "2026-07-01",
                               {"ma60_daily": 100.0}, "downtrend")
        r = self.client.get("/api/tenbag/signals/600519", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["symbol"], "600519")
        self.assertEqual(data["trend"]["regime"], "downtrend")

    def test_health(self):
        r = self.client.get("/api/tenbag/health", environ_overrides=self.auth)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("tier_counts", data)
        self.assertIn("note", data)

    def test_scan_requires_auth(self):
        r = self.client.post("/api/tenbag/scan", json={})
        self.assertEqual(r.status_code, 401)

    def test_scan_starts_task_and_returns_id(self):
        import unittest.mock as mock
        # mock run_scan 避免后台线程联网；让线程快速完成
        from backend.services import tenbag_scan_service as svc
        captured = {}

        def _fake_run(task_runner=None, **kw):
            captured["called"] = True
            captured["top_n"] = kw.get("top_n")
            if task_runner:
                task_runner.set_total(0)
                task_runner.complete(result={"scanned": 0})
            return {"scanned": 0, "failed": 0, "tiers": {}}

        with mock.patch.object(svc, "run_scan", side_effect=_fake_run):
            r = self.client.post("/api/tenbag/scan", json={"top_n": 5},
                                 environ_overrides=self.auth)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("task_id", data)
        self.assertEqual(len(data["task_id"]), 32)
        self.assertEqual(data["top_n"], 5)
        # 后台线程很快跑完；等一下让它执行
        import time
        time.sleep(0.5)
        self.assertTrue(captured.get("called"))


if __name__ == "__main__":
    unittest.main()
