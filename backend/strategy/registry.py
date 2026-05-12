"""
策略注册表 — 管理所有可用的策略类型。

用法：
  @StrategyRegistry.register("ma_cross")
  class MACrossStrategy(BaseStrategy):
      ...
"""

from __future__ import annotations
from typing import Type, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.strategy.base import BaseStrategy

_registry: dict[str, Type["BaseStrategy"]] = {}


def register(name: str):
    """装饰器：注册策略类。"""
    def decorator(cls: Type["BaseStrategy"]):
        _registry[name] = cls
        return cls
    return decorator


def get(name: str) -> Type["BaseStrategy"] | None:
    """按名称获取策略类。"""
    return _registry.get(name)


def list_strategies() -> list[str]:
    """列出所有已注册的策略名称。"""
    return sorted(_registry.keys())


def get_all() -> dict[str, Type["BaseStrategy"]]:
    """获取所有已注册的策略。"""
    return dict(_registry)
