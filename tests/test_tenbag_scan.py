"""十倍股扫描编排服务 单元测试（Step 4a, TDD）。

先于实现编写。run_scan(task_runner, top_n, snapshot_date) 编排:
取候选池 -> 遍历跑 trend+anomaly+pool -> 写 DB。
fetch 函数全部 mock，不联网。使用独立临时数据库。
"""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

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


def _fake_bars():
    return [{"date": f"2025-01-{i:02d}", "open": 10.0, "close": 10.0 + i * 0.1,
             "high": 10.5 + i * 0.1, "low": 9.8, "volume": 10000.0} for i in range(1, 80)]


class _FakeTaskRunner:
    """极简 TaskRunner 替身，只记录调用。"""
    def __init__(self):
        self.total = None
        self.progressed = 0
        self.completed = None
        self.warnings = []
        self.milestones = []

    def set_total(self, n): self.total = n
    def progress(self, done): self.progressed = done
    def check_cancelled(self): pass
    def milestone(self, msg, **kw): self.milestones.append(msg)
    def warn(self, msg, **kw): self.warnings.append(msg)
    def info(self, msg, **kw): pass
    def complete(self, result=None): self.completed = result


class TestRunScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def setUp(self):
        import backend.core.database as db
        with db.get_connection() as conn:
            for t in ("tenbag_pools", "tenbag_trend_signals",
                     "tenbag_anomaly_signals", "sentiment_top_picks"):
                conn.execute(f"DELETE FROM {t}")

    def _svc(self):
        from backend.services import tenbag_scan_service as svc
        return svc

    def _patch(self, svc, candidates, trend_bars=None, financials=None):
        """patch 取数函数。"""
        import unittest.mock as mock
        patches = [
            mock.patch.object(svc, "get_latest_top_picks", return_value=candidates),
            mock.patch.object(svc, "_fetch_tencent_kline",
                              return_value=trend_bars or _fake_bars()),
            mock.patch.object(svc, "fetch_financials_em",
                              return_value=financials or {"symbol": "000001",
                              "name": "测试", "periods": [
                                  {"report_date": "2026Q1", "revenue": 160,
                                   "net_profit": 20, "gross_margin": 35.0,
                                   "contract_liab": 180, "inventory": None,
                                   "cip": None, "fixed_asset": None,
                                   "accounts_rece": None, "netcash_operate": None},
                                  {"report_date": "2025Q4", "revenue": 150,
                                   "net_profit": 18, "gross_margin": 32.0,
                                   "contract_liab": 150, "inventory": None,
                                   "cip": None, "fixed_asset": None,
                                   "accounts_rece": None, "netcash_operate": None},
                                  {"report_date": "2025Q3", "revenue": 140,
                                   "net_profit": 16, "gross_margin": 30.0,
                                   "contract_liab": 120, "inventory": None,
                                   "cip": None, "fixed_asset": None,
                                   "accounts_rece": None, "netcash_operate": None},
                                  {"report_date": "2025Q1", "revenue": 100,
                                   "net_profit": 12, "gross_margin": 28.0,
                                   "contract_liab": 100, "inventory": None,
                                   "cip": None, "fixed_asset": None,
                                   "accounts_rece": None, "netcash_operate": None},
                              ]}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_scan_writes_pools_and_signals(self):
        svc = self._svc()
        candidates = [
            {"stock_code": "000001", "stock_name": "平安银行", "rank": 1},
            {"stock_code": "600519", "stock_name": "贵州茅台", "rank": 2},
        ]
        self._patch(svc, candidates)
        runner = _FakeTaskRunner()
        result = svc.run_scan(task_runner=runner, top_n=50,
                              snapshot_date="2026-07-01")
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(runner.total, 2)
        self.assertEqual(runner.progressed, 2)
        self.assertIsNotNone(runner.completed)

        # DB 应有 2 行 pool + 2 行 trend + 2 行 anomaly
        import backend.core.database as db
        pools = db.list_tenbag_pools("2026-07-01")
        self.assertEqual(len(pools), 2)
        self.assertEqual(len(db.get_tenbag_trend("000001", "2026-07-01")["signals_json"]) > 2, True)
        self.assertIsNotNone(db.get_tenbag_anomaly("000001", "2026Q1"))

    def test_scan_tier_counts(self):
        svc = self._svc()
        candidates = [{"stock_code": "000001", "stock_name": "X", "rank": 1}]
        self._patch(svc, candidates)
        result = svc.run_scan(top_n=50, snapshot_date="2026-07-01")
        self.assertIn("tiers", result)
        self.assertEqual(sum(result["tiers"].values()), 1)

    def test_scan_handles_fetch_failure(self):
        svc = self._svc()
        candidates = [{"stock_code": "000001", "stock_name": "X", "rank": 1}]

        import unittest.mock as mock
        def boom(*a, **kw):
            raise RuntimeError("网络炸了")
        p1 = mock.patch.object(svc, "get_latest_top_picks", return_value=candidates)
        p2 = mock.patch.object(svc, "_fetch_tencent_kline", side_effect=boom)
        p3 = mock.patch.object(svc, "fetch_financials_em", return_value={"periods": []})
        for p in (p1, p2, p3):
            p.start(); self.addCleanup(p.stop)

        runner = _FakeTaskRunner()
        result = svc.run_scan(task_runner=runner, top_n=50, snapshot_date="2026-07-01")
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(len(runner.warnings), 1)

    def test_scan_empty_candidates(self):
        svc = self._svc()
        self._patch(svc, [])
        runner = _FakeTaskRunner()
        result = svc.run_scan(task_runner=runner, top_n=50, snapshot_date="2026-07-01")
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(runner.total, 0)


if __name__ == "__main__":
    unittest.main()
