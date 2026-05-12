"""
风控规则定义 — 可组合的风险控制规则。

每条规则是一个可调用对象，接收 (OrderEvent, PortfolioManager)，
返回 (passed: bool, reason: str)。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.events import OrderEvent
    from backend.portfolio.manager import PortfolioManager


class RiskRule(ABC):
    """风控规则抽象基类。"""

    @abstractmethod
    def check(self, order: "OrderEvent", portfolio: "PortfolioManager") -> tuple[bool, str]:
        """检查订单是否通过风控。

        Returns:
            (passed: bool, reason: str) — passed=True 表示通过
        """
        ...


class MaxPositionRule(RiskRule):
    """单票持仓上限 — 禁止单只股票持仓超过总资产的指定比例。"""

    def __init__(self, max_pct: float = 0.3):
        self.max_pct = max_pct

    def check(self, order, portfolio):
        if order.side != "BUY":
            return True, ""
        total = portfolio.get_total_value()
        pos = portfolio.get_position(order.symbol, order.strategy_id)
        current_value = pos.market_value if pos else 0
        new_value = current_value + order.quantity * (order.price or 0)
        if total > 0 and new_value / total > self.max_pct:
            return False, f"单票持仓超限: {new_value / total:.1%} > {self.max_pct:.0%}"
        return True, ""


class OrderSizeRule(RiskRule):
    """单笔订单金额上限。"""

    def __init__(self, max_amount: float = 500_000):
        self.max_amount = max_amount

    def check(self, order, portfolio):
        if order.price and order.quantity * order.price > self.max_amount:
            return False, f"单笔订单金额超限: {order.quantity * order.price:,.0f} > {self.max_amount:,.0f}"
        return True, ""


class DailyLossLimitRule(RiskRule):
    """日亏损限额 — 当日累计亏损超过阈值后禁止开仓。"""

    def __init__(self, max_loss_pct: float = 0.05):
        self.max_loss_pct = max_loss_pct

    def check(self, order, portfolio):
        if order.side != "BUY":
            return True, ""
        pnl = portfolio.get_total_pnl()
        if pnl < -portfolio.get_portfolio()["initial_capital"] * self.max_loss_pct:
            return False, f"日亏损超限: {pnl:,.0f} > {self.max_loss_pct:.0%}"
        return True, ""
