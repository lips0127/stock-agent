"""
均线交叉策略 — 经典的双均线金叉/死叉策略。

参数：
  fast: 快线周期（默认 5）
  slow: 慢线周期（默认 20）

交易规则：
  - 快线上穿慢线（金叉）→ 买入
  - 快线下穿慢线（死叉）→ 卖出
  - 单次交易量：账户总价值的 95%
"""

from __future__ import annotations
from backend.strategy.base import BaseStrategy
from backend.strategy.registry import register


@register("ma_cross")
class MACrossStrategy(BaseStrategy):
    """均线交叉策略。"""

    params = {"fast": 5, "slow": 20}
    symbols = []
    timeframes = ["1d"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._closes: dict[str, list[float]] = {}     # symbol → 原始收盘价序列
        self._prev_fast: dict[str, float] = {}         # 前一根快线值
        self._prev_slow: dict[str, float] = {}         # 前一根慢线值
        self._inited: set[str] = set()

    def on_init(self):
        for symbol in self.symbols:
            self._init_symbol(symbol)

    def _init_symbol(self, symbol: str):
        bars = self.get_history(symbol, "1d")
        if len(bars) < self.params["slow"] + 1:
            return

        closes = [b.close for b in bars]
        self._closes[symbol] = closes

        fast, slow = self.params["fast"], self.params["slow"]
        fast_ma = self._calc_sma_list(closes, fast)
        slow_ma = self._calc_sma_list(closes, slow)

        if fast_ma and slow_ma:
            self._prev_fast[symbol] = fast_ma[-1]
            self._prev_slow[symbol] = slow_ma[-1]
            self._inited.add(symbol)

    def on_bar(self, bar):
        symbol = bar.symbol

        if symbol not in self._inited:
            self._init_symbol(symbol)
            return

        if symbol not in self._closes or len(self._closes[symbol]) < self.params["slow"]:
            return

        # 追加最新收盘价
        self._closes[symbol].append(bar.close)
        closes = self._closes[symbol]
        fast = self.params["fast"]
        slow = self.params["slow"]

        new_fast = self._calc_sma_list(closes, fast)
        new_slow = self._calc_sma_list(closes, slow)

        if not new_fast or not new_slow or len(new_fast) < 2:
            return

        curr_fast = new_fast[-1]
        curr_slow = new_slow[-1]

        # 金叉：快线上穿慢线
        if self._prev_fast[symbol] <= self._prev_slow[symbol] and curr_fast > curr_slow:
            pos = self.get_position(symbol)
            if pos is None or pos.quantity <= 0:
                portfolio = self.get_portfolio()
                available = portfolio.get("available", 0)
                qty = int(available * 0.95 / bar.close / 100) * 100
                if qty > 0:
                    self.buy(symbol, float(qty))

        # 死叉：快线下穿慢线
        elif self._prev_fast[symbol] >= self._prev_slow[symbol] and curr_fast < curr_slow:
            pos = self.get_position(symbol)
            if pos is not None and pos.quantity > 0:
                self.sell(symbol, pos.quantity)

        self._prev_fast[symbol] = curr_fast
        self._prev_slow[symbol] = curr_slow

    @staticmethod
    def _calc_sma_list(values: list[float], period: int) -> list[float]:
        """计算简单移动平均线序列。"""
        if len(values) < period:
            return []
        result = []
        window_sum = sum(values[:period])
        result.append(window_sum / period)
        for i in range(period, len(values)):
            window_sum += values[i] - values[i - period]
            result.append(window_sum / period)
        return result
