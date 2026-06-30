"""模块二 股价趋势分析器 单元测试（Step 1, TDD）。

先于实现编写。纯函数 compute_trend_signals(daily_bars, benchmark_bars=None)
输入日 K 列表 -> 输出趋势信号 dict + regime。所有用例用固定 fixture K 线，
不联网。fixture 构造器生成可控的上涨/横盘/下跌序列。
"""

import unittest
from datetime import date, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _gen_bars(start_price: float, daily_ret: float, n: int,
              start_date: date = date(2024, 1, 2), base_volume: float = 10000.0):
    """生成 n 根日 K：每日 close 按 daily_ret 复利，high/low 围绕 close 抖动。"""
    bars = []
    d = start_date
    price = start_price
    for i in range(n):
        op = price
        cl = round(price * (1 + daily_ret), 3)
        hi = round(max(op, cl) * 1.005, 3)
        lo = round(min(op, cl) * 0.995, 3)
        vol = base_volume * (1 + (i % 5) * 0.1)
        bars.append({"date": d.isoformat(), "open": op, "close": cl,
                     "high": hi, "low": lo, "volume": vol})
        price = cl
        d += timedelta(days=1)
    return bars


class TestComputeTrendSignals(unittest.TestCase):
    def _svc(self):
        from backend.services import tenbag_trend_service as svc
        return svc

    def test_monthly_resample_and_ma(self):
        svc = self._svc()
        # 约 60 个交易日，稳步上涨 -> 月线 MA12 不可得但 MA 应可算
        bars = _gen_bars(100.0, 0.003, 60)
        sig = svc.compute_trend_signals(bars)
        self.assertIn("monthly_bars", sig)
        self.assertGreaterEqual(len(sig["monthly_bars"]), 2)
        # 上涨序列 -> 末根月线 close > 首根
        self.assertGreater(sig["monthly_bars"][-1]["close"],
                           sig["monthly_bars"][0]["close"])

    def test_drawdown_from_52w_high(self):
        svc = self._svc()
        bars = _gen_bars(100.0, 0.0, 60)  # 横盘
        sig = svc.compute_trend_signals(bars)
        self.assertIn("drawdown_from_high", sig)
        # 横盘 -> 回撤约 0
        self.assertAlmostEqual(sig["drawdown_from_high"], 0.0, places=1)

    def test_stage2_breakout_regime(self):
        svc = self._svc()
        # 构造稳步上涨 + 站上 MA12 + 距高点回撤 < 15% -> stage2_breakout
        bars = _gen_bars(100.0, 0.006, 80)
        sig = svc.compute_trend_signals(bars)
        self.assertEqual(sig["regime"], "stage2_breakout")
        self.assertLess(sig["drawdown_from_high"], 15.0)

    def test_downtrend_regime(self):
        svc = self._svc()
        bars = _gen_bars(100.0, -0.005, 80)
        sig = svc.compute_trend_signals(bars)
        self.assertEqual(sig["regime"], "downtrend")

    def test_new_high_ratio(self):
        svc = self._svc()
        bars = _gen_bars(100.0, 0.004, 80)
        sig = svc.compute_trend_signals(bars)
        self.assertIn("new_high_ratio", sig)
        # 持续上涨 -> 新高比例高
        self.assertGreater(sig["new_high_ratio"], 0.3)

    def test_volume_ratio(self):
        svc = self._svc()
        bars = _gen_bars(100.0, 0.0, 30, base_volume=10000.0)
        # 把末根放量
        bars[-1]["volume"] = 50000.0
        sig = svc.compute_trend_signals(bars)
        self.assertIn("volume_ratio", sig)
        self.assertGreater(sig["volume_ratio"], 2.0)

    def test_relative_strength(self):
        svc = self._svc()
        stock = _gen_bars(100.0, 0.005, 60)
        bench = _gen_bars(100.0, 0.0, 60)  # 大盘横盘
        sig = svc.compute_trend_signals(stock, benchmark_bars=bench)
        self.assertIn("relative_strength", sig)
        # 股票涨、大盘横盘 -> RS > 0
        self.assertGreater(sig["relative_strength"], 0.0)

    def test_empty_bars_safe(self):
        svc = self._svc()
        sig = svc.compute_trend_signals([])
        self.assertIsNone(sig["regime"])
        self.assertEqual(sig["monthly_bars"], [])

    def test_insufficient_bars_no_crash(self):
        svc = self._svc()
        sig = svc.compute_trend_signals(_gen_bars(100.0, 0.0, 5))
        # 数据不足不应崩溃，regime 可为 None 或 consolidation
        self.assertIn(sig["regime"], (None, "consolidation"))


if __name__ == "__main__":
    unittest.main()
