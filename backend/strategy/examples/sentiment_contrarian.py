"""
舆情反向下单策略（v3, 2026-06-06）— A 股散户舆情反向套利。

设计哲学：
  A 股散户舆情是强烈的"反向指标"：
  - 极致恐慌（panic_signal）→ 买在无人问津处
  - 极致狂热（euphoria_signal）→ 卖在情绪高点

参数：
  - position_size_pct: 每次建仓占组合的 %（默认 10%）
  - max_hold_days: 最大持仓天数（默认 10）
  - require_volume: 是否要求当日成交额 > 5 日均（流动性过滤，默认 True）
  - cooldown_days: 同一标的两次信号间隔天数（默认 3）

交易规则：
  - 当 panic_signal=1 且无持仓且满足冷却期 → 买入
  - 当 euphoria_signal=1 且有持仓 → 卖出
  - 持仓超过 max_hold_days → 强制平仓
  - 每次下单前 publish_signal 写日志

回测注意：
  - A 股必须扣除印花税（0.1% 卖出）+ 过户费（0.001%）+ 双边佣金（0.025%）
  - 至少 0.1% 滑点
  - 日线级别持仓轮动，避免高频摩擦
"""

from __future__ import annotations
from datetime import datetime
from backend.strategy.base import BaseStrategy
from backend.strategy.registry import register


@register("sentiment_contrarian")
class SentimentContrarianStrategy(BaseStrategy):
    """舆情反向下单策略。"""

    params = {
        "position_size_pct": 0.10,
        "max_hold_days": 10,
        "require_volume": True,
        "cooldown_days": 3,
    }
    symbols: list[str] = []
    timeframes = ["1d"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buy_date: dict[str, str] = {}      # symbol → 入场日期
        self._last_signal_date: dict[str, str] = {}  # symbol → 上次信号日期

    def on_bar(self, bar):
        symbol = bar.symbol
        if symbol not in self.symbols:
            return

        # ── 1. 拉取最新 sentiment_indicators ──
        ind = self.get_sentiment_indicator(symbol, days=1)
        if ind is None:
            return  # 无舆情数据，跳过

        bar_date = bar.timestamp.strftime("%Y-%m-%d") if hasattr(bar, "timestamp") else ""

        # ── 2. 冷却期检查 ──
        cooldown = self.params["cooldown_days"]
        if symbol in self._last_signal_date:
            try:
                last = datetime.strptime(self._last_signal_date[symbol], "%Y-%m-%d")
                curr = datetime.strptime(bar_date, "%Y-%m-%d")
                if (curr - last).days < cooldown:
                    return
            except Exception:
                pass

        pos = self.get_position(symbol)
        quantity = pos.quantity if pos else 0

        # ── 3. 流动性过滤（可选） ──
        if self.params["require_volume"] and hasattr(bar, "amount"):
            # 真实实盘需要拉 5 日均成交额；回测时由 DataProvider 注入
            # 这里简单判断当日成交额 > 1 亿（活跃股）
            if bar.amount < 1e8:
                return

        # ── 4. Panic 信号 → 买入 ──
        if ind.get("panic_signal") == 1 and quantity <= 0:
            portfolio = self.get_portfolio()
            available = portfolio.get("available", 0)
            qty = int(available * self.params["position_size_pct"] / bar.close / 100) * 100
            if qty > 0:
                self.buy(symbol, float(qty))
                self._buy_date[symbol] = bar_date
                self._last_signal_date[symbol] = bar_date
                self.publish_signal(
                    symbol, "BUY", strength=1.0,
                    reason=f"panic_signal=1, score={ind.get('score')}, "
                           f"bearish={ind.get('bearish_ma30')}",
                )
            return

        # ── 5. Euphoria 信号 → 卖出 ──
        if ind.get("euphoria_signal") == 1 and quantity > 0:
            self.sell(symbol, quantity)
            self._last_signal_date[symbol] = bar_date
            self.publish_signal(
                symbol, "SELL", strength=1.0,
                reason=f"euphoria_signal=1, score={ind.get('score')}, "
                       f"bullish={ind.get('bullish_ma30')}",
            )
            return

        # ── 6. 持仓超时 → 强制平仓 ──
        if quantity > 0 and symbol in self._buy_date:
            try:
                buy_d = datetime.strptime(self._buy_date[symbol], "%Y-%m-%d")
                curr = datetime.strptime(bar_date, "%Y-%m-%d")
                if (curr - buy_d).days >= self.params["max_hold_days"]:
                    self.sell(symbol, quantity)
                    self._last_signal_date[symbol] = bar_date
                    self.publish_signal(
                        symbol, "SELL", strength=0.5,
                        reason=f"max_hold_days reached ({self.params['max_hold_days']}d)",
                    )
            except Exception:
                pass
