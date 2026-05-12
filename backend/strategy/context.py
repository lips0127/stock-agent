"""
策略上下文 — 封装策略可以访问的所有系统能力。

策略通过 Context 访问：
  - 下单（buy/sell）
  - 查询持仓（get_position / get_positions）
  - 查询历史数据（get_history）
  - 查询组合信息（get_portfolio）
  - 发布信号（publish_signal）
  - 获取当前时间（now）
"""

from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from backend.engine.events import OrderEvent, SignalEvent
from backend.execution.order import OrderSide, OrderType

if TYPE_CHECKING:
    from backend.engine.event_bus import EventBus
    from backend.engine.clock import Clock
    from backend.data.provider import DataProvider
    from backend.portfolio.manager import PortfolioManager


class StrategyContext:
    """策略上下文 — 策略与系统的桥梁。

    回测和实盘使用相同的 Context，策略代码无需改动。
    """

    def __init__(
        self, strategy_id: str,
        event_bus: "EventBus",
        clock: "Clock",
        data_provider: "DataProvider",
        portfolio_manager: "PortfolioManager",
    ):
        self.strategy_id = strategy_id
        self._event_bus = event_bus
        self._clock = clock
        self._data = data_provider
        self._portfolio = portfolio_manager

    # ── 下单 ──────────────────────────────────────────────

    def buy(self, symbol: str, quantity: float, price: float | None = None) -> str:
        """买入（市价或限价），返回 order_id。"""
        order_id = f"{self.strategy_id}_{symbol}_{int(datetime.now().timestamp())}"
        event = OrderEvent(
            order_id=order_id,
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            price=price,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
        )
        self._event_bus.publish(event)
        return order_id

    def sell(self, symbol: str, quantity: float, price: float | None = None) -> str:
        """卖出（市价或限价），返回 order_id。"""
        order_id = f"{self.strategy_id}_{symbol}_{int(datetime.now().timestamp())}"
        event = OrderEvent(
            order_id=order_id,
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            price=price,
            order_type=OrderType.LIMIT if price else OrderType.MARKET,
        )
        self._event_bus.publish(event)
        return order_id

    # ── 查询 ──────────────────────────────────────────────

    def get_position(self, symbol: str):
        """获取指定股票的持仓。"""
        return self._portfolio.get_position(symbol, self.strategy_id)

    def get_positions(self):
        """获取该策略的所有持仓。"""
        return self._portfolio.get_strategy_positions(self.strategy_id)

    def get_portfolio(self) -> dict:
        """获取组合账户信息。"""
        return self._portfolio.get_portfolio()

    def get_history(
        self, symbol: str, timeframe: str = "1d",
        start: str | None = None, end: str | None = None,
    ) -> list:
        """获取历史K线数据。"""
        s = start or "2015-01-01"
        e = end or self.now().strftime("%Y-%m-%d")
        return self._data.get_bars(symbol, timeframe, s, e)

    def now(self) -> datetime:
        """获取当前时间（回测=回放时间，实盘=系统时间）。"""
        return self._clock.now()

    # ── 信号 ──────────────────────────────────────────────

    def publish_signal(self, symbol: str, direction: str,
                       strength: float = 1.0, reason: str = ""):
        """发布交易信号（记录到日志/DB，不影响执行）。"""
        event = SignalEvent(
            strategy_id=self.strategy_id,
            symbol=symbol,
            direction=direction,
            strength=strength,
            reason=reason,
        )
        self._event_bus.publish(event)
