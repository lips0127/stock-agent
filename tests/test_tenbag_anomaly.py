"""财报异动信号服务 单元测试（Step 2, TDD）。

先于实现编写。纯函数 derive_anomaly_signals(financials) 输入结构化财报 dict
（含近 4 期资产负债表/现金流/损益关键字段）-> 输出异动信号 + 核心变化/风险/结论。
akshare 抓取函数单独测试（mock），不联网。
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _period(**kw):
    """一期财报：默认 0，调用方覆盖关键字段。"""
    base = {
        "report_date": None,
        "revenue": None, "net_profit": None, "gross_margin": None,
        "inventory": None, "contract_liab": None,
        "cip": None, "fixed_asset": None, "accounts_rece": None,
        "netcash_operate": None,
    }
    base.update(kw)
    return base


class TestDeriveAnomalySignals(unittest.TestCase):
    def _svc(self):
        from backend.services import tenbag_anomaly_service as svc
        return svc

    def test_revenue_high_growth(self):
        svc = self._svc()
        # 近 4 期，营收 YoY +60%（Q1 vs 去年 Q1）
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", revenue=160, net_profit=20),
                _period(report_date="2025Q4", revenue=550, net_profit=60),
                _period(report_date="2025Q3", revenue=400, net_profit=45),
                _period(report_date="2025Q1", revenue=100, net_profit=12),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["revenue_high_growth"])
        self.assertTrue(sig["signals"]["net_profit_high_growth"])

    def test_contract_liability_up(self):
        svc = self._svc()
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", contract_liab=180),
                _period(report_date="2025Q4", contract_liab=150),
                _period(report_date="2025Q3", contract_liab=120),
                _period(report_date="2025Q1", contract_liab=100),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        # 合同负债 YoY +80%（180 vs 100）
        self.assertTrue(sig["signals"]["contract_liability_up"])
        self.assertIn("合同负债", " ".join(sig["core_changes"]))

    def test_inventory_down(self):
        svc = self._svc()
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", inventory=60, revenue=200),
                _period(report_date="2025Q4", inventory=70, revenue=180),
                _period(report_date="2025Q3", inventory=80, revenue=160),
                _period(report_date="2025Q1", inventory=100, revenue=100),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["inventory_down"])

    def test_gross_margin_improve(self):
        svc = self._svc()
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", gross_margin=35.0),
                _period(report_date="2025Q4", gross_margin=32.0),
                _period(report_date="2025Q3", gross_margin=30.0),
                _period(report_date="2025Q1", gross_margin=28.0),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["gross_margin_improve"])
        # 毛利率 Q1 35 vs 去年 Q1 28 -> +7pct >= 5
        self.assertIn("毛利率", " ".join(sig["core_changes"]))

    def test_receivable_risk_flagged(self):
        svc = self._svc()
        # 应收增速 > 营收增速 -> 风险
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", accounts_rece=200, revenue=150),
                _period(report_date="2025Q4", accounts_rece=180, revenue=140),
                _period(report_date="2025Q3", accounts_rece=150, revenue=130),
                _period(report_date="2025Q1", accounts_rece=100, revenue=100),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["receivable_risk"])
        self.assertTrue(any("应收" in r for r in sig["risks"]))

    def test_cip_to_fixed_asset(self):
        svc = self._svc()
        # 在建工程下降 + 固定资产上升 -> 转固
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", cip=50, fixed_asset=300),
                _period(report_date="2025Q4", cip=60, fixed_asset=280),
                _period(report_date="2025Q3", cip=70, fixed_asset=260),
                _period(report_date="2025Q1", cip=80, fixed_asset=240),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["cip_to_fixed_asset"])

    def test_cashflow_lag_flagged(self):
        svc = self._svc()
        # 经营现金流净额为负 / 远低于净利润 -> 风险
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", net_profit=50, netcash_operate=5),
                _period(report_date="2025Q4", net_profit=40, netcash_operate=4),
                _period(report_date="2025Q3", net_profit=35, netcash_operate=3),
                _period(report_date="2025Q1", net_profit=30, netcash_operate=2),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertTrue(sig["signals"]["cashflow_lag"])
        self.assertTrue(any("现金流" in r for r in sig["risks"]))

    def test_conclusion_field(self):
        svc = self._svc()
        fin = {
            "symbol": "000001", "name": "测试",
            "periods": [
                _period(report_date="2026Q1", revenue=160, contract_liab=180),
                _period(report_date="2025Q4", revenue=150, contract_liab=150),
                _period(report_date="2025Q3", revenue=140, contract_liab=120),
                _period(report_date="2025Q1", revenue=100, contract_liab=100),
            ],
        }
        sig = svc.derive_anomaly_signals(fin)
        self.assertIn("conclusion", sig)
        self.assertIn("score", sig)
        # 2 个正向异动 -> 有分但不一定进观察池
        self.assertIsInstance(sig["score"], (int, float))

    def test_insufficient_periods_safe(self):
        svc = self._svc()
        fin = {"symbol": "000001", "name": "测试",
               "periods": [_period(report_date="2026Q1", revenue=100)]}
        sig = svc.derive_anomaly_signals(fin)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["conclusion"], "数据不足")


if __name__ == "__main__":
    unittest.main()
