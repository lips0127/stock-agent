"""
持仓模型 — 单只股票的持仓及其盈亏信息。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Position:
    """单只股票的持仓。"""
    symbol: str
    quantity: float             # 持仓数量（正=多仓，0=空仓）
    avg_cost: float             # 平均成本价
    strategy_id: str = ""
    current_price: float = 0.0
    realized_pnl: float = 0.0   # 已实现盈亏
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def market_value(self) -> float:
        """当前市值。"""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        """成本总额。"""
        return self.quantity * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏（浮动盈亏）。"""
        return self.quantity * (self.current_price - self.avg_cost)

    @property
    def total_pnl(self) -> float:
        """总盈亏（已实现 + 未实现）。"""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def pnl_pct(self) -> float:
        """盈亏百分比。"""
        if self.cost_basis == 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost

    def update_price(self, price: float):
        """更新当前价格，重新计算浮动盈亏。"""
        self.current_price = price
        self.updated_at = datetime.now()

    def apply_fill(self, fill_qty: float, fill_price: float, commission: float = 0.0):
        """应用一笔成交，更新持仓。"""
        if self.quantity == 0:
            # 新开仓
            self.avg_cost = fill_price
            self.quantity = fill_qty
        elif (self.quantity > 0 and fill_qty > 0) or (self.quantity < 0 and fill_qty < 0):
            # 加仓：加权平均成本
            total_cost = self.quantity * self.avg_cost + fill_qty * fill_price
            self.quantity += fill_qty
            self.avg_cost = total_cost / self.quantity if self.quantity != 0 else 0
        else:
            # 减仓/平仓：计算已实现盈亏
            close_qty = min(abs(self.quantity), abs(fill_qty))
            if self.quantity > 0:
                self.realized_pnl += close_qty * (fill_price - self.avg_cost) - commission
            else:
                self.realized_pnl += close_qty * (self.avg_cost - fill_price) - commission
            self.quantity += fill_qty
            if self.quantity == 0:
                self.avg_cost = 0
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.total_pnl,
            "pnl_pct": self.pnl_pct,
        }
