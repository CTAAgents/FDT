"""
quant-daily 策略层
==============
可插拔策略框架。新增策略仅需:
  1. 新建一个 .py 实现 BaseStrategy
  2. 在 registry.py 中注册一行

现有策略:
  - layered_l1l4  (默认, 唯一活跃)
  - true_layered  (已废弃, 保留装饰)
  - factor_timing (因子择时, 5因子L1-L4)
"""
from .registry import get_strategy, list_strategies, register_strategy
from .base import BaseStrategy, SignalResult

__all__ = ["get_strategy", "list_strategies", "register_strategy", "BaseStrategy", "SignalResult"]
