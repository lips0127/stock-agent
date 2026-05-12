"""
组合管理器 — 监听成交事件，维护持仓和资金状态。

作为 EventBus 上的消费者：
  - 订阅 FillEvent → 更新持仓和资金
  - 提供持仓查询接口（供策略和前端使用）

支持按 strategy_id 隔离，实现多策略组合管理。
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from backend.portfolio.position import Position

if TYPE_CHECKING:
    from backend.engine.event_bus import EventBus

logger = logging.getLogger(__name__)


class PortfolioManager:
    """组合管理器。

    职责：
      1. 跟踪每个策略的持仓（按 strategy_id 隔离）
      2. 跟踪总资金（初始资金 + 已实现盈亏）
      3. 提供持仓和组合快照查询
    """

    def __init__(self, event_bus: "EventBus", initial_capital: float = 100_000.0):
        self._event_bus = event_bus
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._realized_pnl = 0.0

        # 持仓：{(strategy_id, symbol) → Position}
        self._positions: dict[tuple[str, str], Position] = {}

        # 价格缓存：symbol → latest_price
        self._prices: dict[str, float] = {}

        # 订阅成交事件
        from backend.engine.events import FillEvent
        event_bus.subscribe(FillEvent, self._on_fill, priority=30)

        logger.info(f"组合管理器初始化: 初始资金 {initial_capital:,.0f}")

    # ── 事件处理 ──────────────────────────────────────────

    def _on_fill(self, fill):
        """处理成交事件，更新持仓和资金。"""
        key = (fill.strategy_id, fill.symbol)
        if key not in self._positions:
            self._positions[key] = Position(
                symbol=fill.symbol,
                quantity=0,
                avg_cost=0,
                strategy_id=fill.strategy_id,
            )
        pos = self._positions[key]
        old_qty = pos.quantity

        if fill.side == "BUY":
            quantity = fill.quantity
        else:
            quantity = -fill.quantity

        pos.apply_fill(quantity, fill.price, fill.commission)

        # 更新资金
        if fill.side == "BUY":
            self._cash -= (fill.quantity * fill.price + fill.commission)
        else:
            self._cash += (fill.quantity * fill.price - fill.commission)

        self._realized_pnl = sum(p.realized_pnl for p in self._positions.values())

        logger.debug(f"持仓更新: {fill.symbol} {fill.side} "
                     f"{fill.quantity}股 @ {fill.price:.2f}, "
                     f"持仓: {old_qty} → {pos.quantity}")

        # 发布持仓变化事件
        from backend.engine.events import PositionEvent
        self._event_bus.publish(PositionEvent(
            symbol=fill.symbol,
            strategy_id=fill.strategy_id,
            quantity=pos.quantity,
            avg_cost=pos.avg_cost,
            realized_pnl=pos.realized_pnl,
        ))

    # ── 价格更新 ──────────────────────────────────────────

    def update_price(self, symbol: str, price: float):
        """更新股票最新价格，联动更新持仓市值。"""
        self._prices[symbol] = price
        for (sid, sym), pos in self._positions.items():
            if sym == symbol and pos.quantity != 0:
                pos.update_price(price)

    # ── 查询接口 ──────────────────────────────────────────

    def get_position(self, symbol: str, strategy_id: str = "") -> Position | None:
        """获取指定股票和策略的持仓。"""
        return self._positions.get((strategy_id, symbol))

    def get_strategy_positions(self, strategy_id: str) -> list[Position]:
        """获取某策略的所有持仓。"""
        return [p for (sid, _), p in self._positions.items()
                if sid == strategy_id and p.quantity != 0]

    def get_all_positions(self) -> list[Position]:
        """获取所有非零持仓。"""
        return [p for p in self._positions.values() if p.quantity != 0]

    def get_position_value(self) -> float:
        """所有持仓的总市值。"""
        return sum(p.market_value for p in self._positions.values())

    def get_total_value(self) -> float:
        """组合总价值 = 现金 + 持仓市值。"""
        return self._cash + self.get_position_value()

    def get_total_pnl(self) -> float:
        """总盈亏 = 总价值 - 初始资金。"""
        return self.get_total_value() - self._initial_capital

    def get_portfolio(self) -> dict:
        """获取组合汇总信息。"""
        positions_value = self.get_position_value()
        total = self._cash + positions_value
        return {
            "initial_capital": self._initial_capital,
            "available": self._cash,
            "cash": self._cash,
            "positions_value": positions_value,
            "total_value": total,
            "realized_pnl": self._realized_pnl,
            "unrealized_pnl": sum(p.unrealized_pnl for p in self._positions.values()),
            "total_pnl": total - self._initial_capital,
            "total_return": (total - self._initial_capital) / self._initial_capital
                            if self._initial_capital else 0,
            "position_count": sum(1 for p in self._positions.values() if p.quantity != 0),
        }

    def get_positions_detail(self) -> list[dict]:
        """获取持仓明细（供 API 使用）。"""
        return [p.to_dict() for p in self._positions.values() if p.quantity != 0]
