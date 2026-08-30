"""自选股观察池 API 路由测试。

Flask test client + 临时数据库验证 CRUD 契约与鉴权边界；
报价聚合用 mock 避免联网。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class TestWatchlistRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()
        from backend.api.middleware import generate_token
        os.environ["FRONTEND_DEV_PROXY"] = "false"
        from backend.api.app import create_app
        cls.app = create_app(testing=True)
        cls.client = cls.app.test_client()
        cls.token = generate_token("test_user")
        cls.auth = {"HTTP_AUTHORIZATION": f"Bearer {cls.token}"}  # 供 environ_overrides 使用

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._temp_dir, ignore_errors=True)

    def setUp(self):
        from backend.core.database import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM watchlist")

    # ── 鉴权边界 ──

    def test_watchlist_requires_jwt(self):
        for method, path in (
            ("get", "/api/watchlist"),
            ("post", "/api/watchlist"),
            ("patch", "/api/watchlist/600519"),
            ("delete", "/api/watchlist/600519"),
        ):
            with self.subTest(method=method, path=path):
                resp = getattr(self.client, method)(path)
                self.assertEqual(resp.status_code, 401)

    # ── CRUD ──

    def test_add_list_update_delete(self):
        resp = self.client.post(
            "/api/watchlist", json={"code": "600519", "note": "白酒观察"}, environ_overrides=self.auth
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.get_json()["created"])

        # 幂等重复添加
        resp = self.client.post("/api/watchlist", json={"code": "600519"}, environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["created"])

        resp = self.client.get("/api/watchlist", environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual([s["code"] for s in body["data"]], ["600519"])
        self.assertEqual(body["data"][0]["note"], "白酒观察")
        self.assertEqual(body["source"], "tencent")
        self.assertIn("as_of", body)

        resp = self.client.patch(
            "/api/watchlist/600519", json={"note": "改备注"}, environ_overrides=self.auth
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["stock"]["note"], "改备注")

        resp = self.client.delete("/api/watchlist/600519", environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/watchlist", environ_overrides=self.auth)
        self.assertEqual(resp.get_json()["data"], [])

    def test_add_invalid_code_400(self):
        for bad in ("60051", "60051a", "abc123", "", "6005199"):
            with self.subTest(code=bad):
                resp = self.client.post("/api/watchlist", json={"code": bad}, environ_overrides=self.auth)
                self.assertEqual(resp.status_code, 400)

    def test_update_missing_404(self):
        resp = self.client.patch("/api/watchlist/000001", json={"note": "x"}, environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 404)

    def test_delete_missing_404(self):
        resp = self.client.delete("/api/watchlist/000001", environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 404)

    def test_patch_without_note_400(self):
        self.client.post("/api/watchlist", json={"code": "600519"}, environ_overrides=self.auth)
        resp = self.client.patch("/api/watchlist/600519", json={}, environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 400)

    # ── 报价聚合降级语义 ──

    @patch(
        "backend.api.routes.watchlist.watchlist_service.fetch_watch_quotes",
        return_value={
            "data": [{"code": "600519", "name": "贵州茅台", "note": "", "price": 1500.0,
                      "change_pct": 1.2, "quote_error": None}],
            "source": "tencent",
            "as_of": "2026-08-30T15:00:00",
            "coverage": {"expected": 1, "ok": 1, "failed": 0},
            "degraded": False,
            "unavailable": False,
            "errors": [],
        },
    )
    def test_get_returns_quote_metadata(self, _mock):
        self.client.post("/api/watchlist", json={"code": "600519"}, environ_overrides=self.auth)
        resp = self.client.get("/api/watchlist", environ_overrides=self.auth)
        body = resp.get_json()
        self.assertFalse(body["degraded"])
        self.assertEqual(body["coverage"]["ok"], 1)
        self.assertEqual(body["data"][0]["price"], 1500.0)

    def test_empty_watchlist_returns_empty_not_error(self):
        resp = self.client.get("/api/watchlist", environ_overrides=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["data"], [])
        self.assertFalse(body["unavailable"])
        self.assertEqual(body["coverage"]["expected"], 0)


if __name__ == "__main__":
    unittest.main()
