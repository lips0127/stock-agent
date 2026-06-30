"""分层器 单元测试（Step 3, TDD）。

先于实现编写。纯函数 classify_pool(trend_signals, anomaly_signals,
industry_signals=None) -> {tier, reasons}。
tier ∈ {'1','2','3','exclude'}。确定性规则，覆盖四档边界。
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _trend(regime, new_high=0.2, volume_ratio=1.0, drawdown=-5.0):
    return {
        "regime": regime,
        "new_high_ratio": new_high,
        "volume_ratio": volume_ratio,
        "drawdown_from_high": drawdown,
        "ma60_daily": 100.0,
        "ma120_daily": 100.0,
        "relative_strength": 0.0,
    }


def _anom(positive_keys, risk_keys=()):
    """造 anomaly_signals：positive_keys 为命中的正向信号键，risk_keys 为风险键。"""
    all_pos = ["revenue_high_growth", "net_profit_high_growth",
               "gross_margin_improve", "inventory_down",
               "contract_liability_up", "cip_to_fixed_asset"]
    all_risk = ["receivable_risk", "cashflow_lag"]
    sigs = {k: (k in positive_keys) for k in all_pos}
    sigs.update({k: (k in risk_keys) for k in all_risk})
    return {
        "signals": sigs,
        "core_changes": ["x"] * len(positive_keys),
        "risks": ["r"] * len(risk_keys),
        "score": float(len(positive_keys) - 0.5 * len(risk_keys)),
        "conclusion": "ok",
    }


class TestClassifyPool(unittest.TestCase):
    def _svc(self):
        from backend.services import tenbag_pool_service as svc
        return svc

    def test_tier1_strong_anomaly_trend_confirmed(self):
        svc = self._svc()
        trend = _trend("stage2_breakout")
        anom = _anom(["revenue_high_growth", "net_profit_high_growth",
                      "contract_liability_up"])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "1")
        self.assertTrue(len(out["reasons"]) >= 1)

    def test_tier1_blocked_by_risk(self):
        svc = self._svc()
        # 3 正向但有应收风险 -> 不进一级
        trend = _trend("stage2_breakout")
        anom = _anom(["revenue_high_growth", "net_profit_high_growth",
                      "contract_liability_up"], risk_keys=["receivable_risk"])
        out = svc.classify_pool(trend, anom)
        self.assertNotEqual(out["tier"], "1")

    def test_tier2_trend_confirmed_weak_anomaly(self):
        svc = self._svc()
        # 趋势确认但只有 1-2 个正向异动（业绩未全面兑现）
        trend = _trend("advancing")
        anom = _anom(["contract_liability_up"])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "2")

    def test_tier2_anomaly_strong_but_trend_not_confirmed(self):
        svc = self._svc()
        # 3 正向异动但趋势横盘（业绩兑现但趋势未确认）
        trend = _trend("consolidation")
        anom = _anom(["revenue_high_growth", "net_profit_high_growth",
                      "contract_liability_up"])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "2")

    def test_tier3_concept_strong_finance_weak(self):
        svc = self._svc()
        # 概念强（stage2 + 放量 + 新高）但无正向异动
        trend = _trend("stage2_breakout", new_high=0.6, volume_ratio=2.0)
        anom = _anom([])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "3")

    def test_exclude_downtrend_no_anomaly(self):
        svc = self._svc()
        trend = _trend("downtrend")
        anom = _anom([])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "exclude")

    def test_exclude_nothing_at_all(self):
        svc = self._svc()
        # 横盘 + 无异动 + 无概念
        trend = _trend("consolidation", new_high=0.0, volume_ratio=0.9)
        anom = _anom([])
        out = svc.classify_pool(trend, anom)
        self.assertEqual(out["tier"], "exclude")

    def test_industry_boost_optional(self):
        svc = self._svc()
        # industry_signals=None 不应崩溃；高景气行业对一级有加成（仅 reasons 体现）
        trend = _trend("stage2_breakout")
        anom = _anom(["revenue_high_growth", "net_profit_high_growth",
                      "contract_liability_up"])
        out_none = svc.classify_pool(trend, anom, industry_signals=None)
        out_high = svc.classify_pool(trend, anom,
                                     industry_signals={"prosperity": "high"})
        self.assertEqual(out_none["tier"], "1")
        self.assertEqual(out_high["tier"], "1")  # 都是一级

    def test_reasons_explain_tier(self):
        svc = self._svc()
        trend = _trend("stage2_breakout")
        anom = _anom(["revenue_high_growth", "contract_liability_up",
                      "cip_to_fixed_asset"])
        out = svc.classify_pool(trend, anom)
        # reasons 应提及趋势确认 + 异动
        joined = " ".join(out["reasons"])
        self.assertTrue("趋势" in joined or "异动" in joined)


if __name__ == "__main__":
    unittest.main()
