"""
策略基类 — 所有交易策略的抽象父类。

策略生命周期：
  on_init(context) → on_start() → [on_bar() / on_tick() ...] → on_stop()

回测和实盘使用相同的策略代码 — 策略只依赖 StrategyContext。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.strategy.context import StrategyContext
    from backend.engine.events import BarEvent, TickEvent, FillEvent


class BaseStrategy(ABC):
    """交易策略抽象基类。

    子类需要：
      1. 设置 params（策略参数）和 symbols（关注股票）
      2. 实现 on_bar() 或 on_tick() 中的交易逻辑
      3. 使用 self.buy() / self.sell() 下单
    """

    params: dict = {}
    symbols: list[str] = []
    timeframes: list[str] = ["1d"]

    def __init__(self, **kwargs):
        """初始化策略。

        Args:
            params: 策略参数字典（覆盖类级别默认值）
            symbols: 关注的股票代码列表
            timeframes: 关注的K线周期
        """
        self.params = {**self.__class__.params, **kwargs.get("params", {})}
        self.symbols = kwargs.get("symbols", self.__class__.symbols)
        self.timeframes = kwargs.get("timeframes", self.__class__.timeframes)
        self.strategy_id: str = ""
        self.context: "StrategyContext" | None = None

    # ── 生命周期方法 ──────────────────────────────────────

    def set_context(self, context: "StrategyContext"):
        """注入策略上下文（由引擎在启动前调用）。"""
        self.context = context
        self.strategy_id = context.strategy_id

    def on_init(self):
        """策略初始化 — 在启动前调用，可在此预计算指标等。"""
        pass

    def on_start(self):
        """策略启动 — 在开始接收行情前调用。"""
        pass

    def on_bar(self, bar: "BarEvent"):
        """K线回调 — 每根K线完成时调用。"""
        pass

    def on_tick(self, tick: "TickEvent"):
        """Tick回调 — 每次行情更新时调用。"""
        pass

    def on_fill(self, fill: "FillEvent"):
        """成交回调 — 订单成交时调用。"""
        pass

    def on_stop(self):
        """策略停止 — 清理资源。"""
        pass

    # ── 便捷方法（委托给 Context）──────────────────────────

    def buy(self, symbol: str, quantity: float, price: float | None = None) -> str:
        """买入下单，返回 order_id。"""
        if self.context is None:
            raise RuntimeError("策略未初始化：context 为空")
        return self.context.buy(symbol, quantity, price)

    def sell(self, symbol: str, quantity: float, price: float | None = None) -> str:
        """卖出下单，返回 order_id。"""
        if self.context is None:
            raise RuntimeError("策略未初始化：context 为空")
        return self.context.sell(symbol, quantity, price)

    def get_position(self, symbol: str):
        """获取指定股票的持仓。"""
        if self.context is None:
            return None
        return self.context.get_position(symbol)

    def get_positions(self):
        """获取所有持仓。"""
        if self.context is None:
            return []
        return self.context.get_positions()

    def get_portfolio(self) -> dict:
        """获取组合账户信息。"""
        if self.context is None:
            return {}
        return self.context.get_portfolio()

    def get_history(self, symbol: str, timeframe: str = "1d",
                    start: str | None = None, end: str | None = None) -> list:
        """获取历史K线数据。"""
        if self.context is None:
            return []
        return self.context.get_history(symbol, timeframe, start, end)

    def get_sentiment_indicator(self, symbol: str, days: int = 1) -> dict | None:
        """读取舆情时序因子（v3, 2026-06-06）。

        委托给 context.get_sentiment_indicator。返回 None 表示无数据。
        """
        if self.context is None:
            return None
        return self.context.get_sentiment_indicator(symbol, days)
