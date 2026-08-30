"""登录限流 / JWT 边界 / stock 错误语义 / live 指数降级元数据测试。"""

import unittest
from unittest.mock import patch

from flask import Flask

from backend.api import middleware
from backend.api.middleware import generate_token
from backend.api.routes.auth import auth_bp
from backend.api.routes.stock import stock_bp
from backend.api.routes.market import market_bp


def _make_app(*blueprints):
    app = Flask(__name__)
    app.config["TESTING"] = True
    for bp in blueprints:
        app.register_blueprint(bp)
    return app


class LoginRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(auth_bp)
        self.client = self.app.test_client()
        middleware._request_times.clear()

    def tearDown(self):
        middleware._request_times.clear()

    @patch("backend.api.routes.auth.authenticate_user", return_value=False)
    @patch.object(middleware, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    def test_login_rate_limited_after_threshold(self, _mock_auth):
        for _ in range(3):
            resp = self.client.post(
                "/api/login",
                json={"username": "u", "password": "p"},
            )
            self.assertEqual(resp.status_code, 401)

        resp = self.client.post(
            "/api/login",
            json={"username": "u", "password": "p"},
        )
        self.assertEqual(resp.status_code, 429)
        self.assertFalse(resp.get_json().get("success", True))

    @patch.object(middleware, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    def test_login_missing_credentials_400(self):
        resp = self.client.post("/api/login", json={"username": ""})
        self.assertEqual(resp.status_code, 400)

    @patch("backend.api.routes.auth.authenticate_user", return_value=True)
    def test_login_success_with_default_limit(self, _mock_auth):
        resp = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "x"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["token"])


class JwtSubjectBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(stock_bp)
        self.client = self.app.test_client()
        middleware._request_times.clear()

    def tearDown(self):
        middleware._request_times.clear()

    def _token_without_sub(self):
        import jwt as pyjwt
        import time
        from backend.config import JWT_SECRET, JWT_ALGORITHM

        payload = {"iat": int(time.time()), "exp": int(time.time()) + 600}
        return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def test_token_without_sub_is_401_not_500(self):
        headers = {"Authorization": f"Bearer {self._token_without_sub()}"}
        resp = self.client.get("/api/stock/600519", headers=headers)
        self.assertEqual(resp.status_code, 401)


class StockErrorSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(stock_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": f"Bearer {generate_token('tester')}"}

    @patch("backend.api.routes.stock.get_stock_metrics", return_value=None)
    def test_unavailable_stock_returns_404(self, _mock):
        resp = self.client.get("/api/stock/600519", headers=self.headers)
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.get_json())

    @patch(
        "backend.api.routes.stock.get_stock_metrics",
        side_effect=RuntimeError("connect to http://internal-host/secret-token failed"),
    )
    def test_upstream_failure_returns_502_without_internal_details(self, _mock):
        resp = self.client.get("/api/stock/600519", headers=self.headers)
        self.assertEqual(resp.status_code, 502)
        body = resp.get_data(as_text=True)
        self.assertNotIn("secret-token", body)
        self.assertNotIn("internal-host", body)

    @patch(
        "backend.api.routes.stock.get_stock_metrics",
        return_value={
            "名称": "贵州茅台",
            "最新价": 1500.0,
            "股息率": 1.2,
            "每股分红": 18.0,
            "分红备注": "FY2024",
        },
    )
    def test_valid_stock_returns_200(self, _mock):
        resp = self.client.get("/api/stock/600519", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["name"], "贵州茅台")


class MarketLiveDegradedTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(market_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": f"Bearer {generate_token('tester')}"}
        middleware._request_times.clear()

    def tearDown(self):
        middleware._request_times.clear()

    @staticmethod
    def _spot(name):
        return {
            "name": name,
            "current": 3000.0,
            "change_amount": 10.0,
            "change_pct": 0.33,
        }

    @patch(
        "backend.api.routes.market.get_sina_index_spot",
        side_effect=lambda s: (
            MarketLiveDegradedTests._spot(s)
            if s != "s_sh000688"
            else (_ for _ in ()).throw(TimeoutError("upstream"))
        ),
    )
    def test_partial_failure_marks_degraded(self, _mock):
        resp = self.client.get("/api/indices/live", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["degraded"])
        self.assertEqual(body["coverage"]["ok"], 4)
        self.assertEqual(body["coverage"]["expected"], 5)
        self.assertEqual(body["coverage"]["failed"], 1)
        self.assertEqual(len(body["data"]), 4)
        # 错误只回显类型，不透出内部错误串
        self.assertEqual(body["errors"][0]["error"], "TimeoutError")
        self.assertNotIn("upstream", resp.get_data(as_text=True))

    @patch(
        "backend.api.routes.market.get_sina_index_spot",
        side_effect=ConnectionError("boom"),
    )
    def test_total_failure_marks_unavailable(self, _mock):
        resp = self.client.get("/api/indices/live", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["unavailable"])
        self.assertEqual(body["data"], [])
        self.assertFalse(body["degraded"])

    @patch(
        "backend.api.routes.market.get_sina_index_spot",
        side_effect=lambda s: MarketLiveDegradedTests._spot(s),
    )
    def test_full_success_not_degraded_and_ordered(self, _mock):
        resp = self.client.get("/api/indices/live", headers=self.headers)
        body = resp.get_json()
        self.assertFalse(body["degraded"])
        self.assertEqual(body["source"], "sina")
        self.assertIn("as_of", body)
        symbols = [item["symbol"] for item in body["data"]]
        self.assertEqual(
            symbols,
            ["sh000001", "sz399001", "sz399006", "sh000688", "sh000012"],
        )


class DatabaseConnectionPragmaTests(unittest.TestCase):
    def test_busy_timeout_set_on_every_connection(self):
        from backend.core.database import get_connection

        with get_connection() as conn:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            self.assertEqual(row[0], 5000)
            row = conn.execute("PRAGMA synchronous").fetchone()
            self.assertEqual(row[0], 1)  # NORMAL


class ScanLifecycleConflictTests(unittest.TestCase):
    """锁被占用时，已返回给客户端的 task_id 必须得到 failed 终态（无幽灵任务）。"""

    def test_lock_busy_marks_promised_task_failed(self):
        from unittest.mock import patch

        import backend.services.scheduler as sched
        from backend.api.routes import ops

        prev = sched._scan_running
        sched._scan_running = True
        try:
            with patch("backend.core.database.insert_task_run") as mock_insert:
                ops._run_with_task_lifecycle(
                    "testtask0001", lambda: None, "测试扫描", "scan_index"
                )
                mock_insert.assert_called_once()
                kwargs = mock_insert.call_args.kwargs
                self.assertEqual(kwargs["id"], "testtask0001")
                self.assertEqual(kwargs["status"], "failed")
                self.assertIn("并发冲突", kwargs["error_message"])
        finally:
            sched._scan_running = prev

    def test_lock_free_runs_scan(self):
        from unittest.mock import patch

        from backend.api.routes import ops

        executed = []
        with patch("backend.core.database.insert_task_run"):
            ops._run_with_task_lifecycle(
                "testtask0002", lambda: executed.append(1), "测试扫描", "scan_full"
            )
        self.assertEqual(executed, [1])


if __name__ == "__main__":
    unittest.main()
