"""
券商接口抽象 — 定义订单执行的标准接口。

实现：
  PaperBroker — 模拟交易，用于回测和策略验证
  未来：HuataiBroker, GuoxinBroker 等真实券商接口
"""

from __future__ import annotations
from abc import ABC, abstractmethod

from backend.execution.order import Order
from backend.portfolio.position import Position


class AbstractBroker(ABC):
    """券商接口抽象。

    所有真实券商实现必须遵循此接口。
    策略不直接依赖具体券商，通过此抽象实现解耦。
    """

    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """提交订单，返回 order_id。"""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单，返回是否成功。"""
        ...

    @abstractmethod
    def get_orders(self, **filters) -> list[Order]:
        """查询订单列表（支持按状态、股票、策略筛选）。"""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """获取当前持仓列表。"""
        ...

    @abstractmethod
    def get_account(self) -> dict:
        """获取账户信息。

        Returns:
            {"capital": float, "available": float, "total_value": float, ...}
        """
        ...

    @abstractmethod
    def connect(self, **credentials) -> bool:
        """连接到券商接口，返回是否成功。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接。"""
        ...
