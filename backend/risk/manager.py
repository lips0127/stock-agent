"""
风控管理器 — 在订单执行前进行多重风控校验。

作为 EventBus 上的中间件（priority=15，在 Broker 的 priority=20 之前执行）：
  - 订阅 OrderEvent → 逐条检查风控规则
  - 未通过则将拒绝的 order_id 加入黑名单
  - Broker 在处理前检查黑名单，若被拒则跳过

设计说明：
  事件总线是广播模型，无法阻止事件传播。因此风控采用
  "黑名单"模式：风控先检查并标记，Broker 后检查并跳过。
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from backend.risk.rules import RiskRule

if TYPE_CHECKING:
    from backend.engine.event_bus import EventBus
    from backend.engine.events import OrderEvent
    from backend.portfolio.manager import PortfolioManager

logger = logging.getLogger(__name__)


class RiskManager:
    """风控管理器 — 可插拔的风控规则链。

    用法:
      rm = RiskManager(event_bus, portfolio_manager)
      rm.add_rule(MaxPositionRule(0.3))
      rm.add_rule(DailyLossLimitRule(0.05))
    """

    def __init__(self, event_bus: "EventBus", portfolio: "PortfolioManager"):
        self._event_bus = event_bus
        self._portfolio = portfolio
        self._rules: list[RiskRule] = []
        self._rejected: set[str] = set()  # 被拒绝的 order_id

        from backend.engine.events import OrderEvent
        event_bus.subscribe(OrderEvent, self._check, priority=15)
        logger.info("风控管理器已就绪")

    def add_rule(self, rule: RiskRule):
        """添加风控规则。"""
        self._rules.append(rule)
        logger.info(f"已添加风控规则: {rule.__class__.__name__}")

    def remove_rule(self, rule: RiskRule):
        """移除风控规则。"""
        self._rules.remove(rule)

    def is_rejected(self, order_id: str) -> bool:
        """检查订单是否被风控拒绝。"""
        return order_id in self._rejected

    def _check(self, order: "OrderEvent"):
        """逐条检查所有风控规则。"""
        for rule in self._rules:
            passed, reason = rule.check(order, self._portfolio)
            if not passed:
                logger.warning(f"风控拦截: {order.symbol} {order.side} "
                              f"{order.quantity}股 — {rule.__class__.__name__}: {reason}")
                self._rejected.add(order.order_id)
                return
