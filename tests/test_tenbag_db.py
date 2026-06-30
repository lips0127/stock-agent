"""十倍股/财报异动扫描器 DB schema 测试（Step 0, TDD）。

先于实现编写，定义 tenbag_anomaly_signals / tenbag_trend_signals / tenbag_pools
三张表 + CRUD helper 的预期行为。每个类使用独立临时数据库。
"""

import json
import os
import sys
import tempfile
import unittest
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


class TestTenbagAnomalySignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def _db(self):
        import backend.core.database as db
        return db

    def test_upsert_and_get_anomaly(self):
        db = self._db()
        signals = {"revenue_high_growth": True, "contract_liability_up": True}
        db.upsert_tenbag_anomaly(
            symbol="600519", report_date="2026Q1",
            signals=signals, score=72.0,
            core_changes=["Q1 毛利率环比 +5pct"], risks=["应收账款上升"],
        )
        row = db.get_tenbag_anomaly("600519", "2026Q1")
        self.assertIsNotNone(row)
        self.assertEqual(row["symbol"], "600519")
        self.assertEqual(json.loads(row["signals_json"])["revenue_high_growth"], True)
        self.assertEqual(row["score"], 72.0)
        self.assertEqual(json.loads(row["core_changes_json"]), ["Q1 毛利率环比 +5pct"])

    def test_upsert_replaces_on_same_key(self):
        db = self._db()
        db.upsert_tenbag_anomaly(symbol="000001", report_date="2026Q1",
                                 signals={"a": True}, score=10.0)
        db.upsert_tenbag_anomaly(symbol="000001", report_date="2026Q1",
                                 signals={"b": True}, score=90.0)
        row = db.get_tenbag_anomaly("000001", "2026Q1")
        self.assertEqual(row["score"], 90.0)
        self.assertEqual(json.loads(row["signals_json"]), {"b": True})


class TestTenbagTrendSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def _db(self):
        import backend.core.database as db
        return db

    def test_upsert_and_get_trend(self):
        db = self._db()
        db.upsert_tenbag_trend(
            symbol="600519", date="2026-06-30",
            signals={"ma12": 1500.0, "drawdown_from_high": -8.0},
            regime="stage2_breakout",
        )
        row = db.get_tenbag_trend("600519", "2026-06-30")
        self.assertIsNotNone(row)
        self.assertEqual(row["regime"], "stage2_breakout")
        self.assertEqual(json.loads(row["signals_json"])["drawdown_from_high"], -8.0)


class TestTenbagPools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = _setup_temp_db()

    def _db(self):
        import backend.core.database as db
        return db

    def setUp(self):
        db = self._db()
        with db.get_connection() as conn:
            conn.execute("DELETE FROM tenbag_pools")

    def test_upsert_and_list_pools(self):
        db = self._db()
        db.upsert_tenbag_pool("2026-06-30", "600519", "1",
                              reasons=["趋势确认", "3 个正向异动"])
        db.upsert_tenbag_pool("2026-06-30", "000001", "exclude",
                              reasons=["纯炒作"])
        db.upsert_tenbag_pool("2026-06-30", "300750", "2", reasons=["趋势启动"])
        rows = db.list_tenbag_pools(snapshot_date="2026-06-30")
        self.assertEqual(len(rows), 3)
        tier1 = db.list_tenbag_pools(snapshot_date="2026-06-30", tier="1")
        self.assertEqual(len(tier1), 1)
        self.assertEqual(tier1[0]["symbol"], "600519")
        self.assertEqual(json.loads(tier1[0]["reasons_json"]), ["趋势确认", "3 个正向异动"])

    def test_upsert_pool_replaces_on_same_key(self):
        db = self._db()
        db.upsert_tenbag_pool("2026-06-30", "600519", "3", reasons=["旧"])
        db.upsert_tenbag_pool("2026-06-30", "600519", "1", reasons=["新"])
        rows = db.list_tenbag_pools(snapshot_date="2026-06-30")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool_tier"], "1")


if __name__ == "__main__":
    unittest.main()
