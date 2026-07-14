"""
quant-daily 策略层
==============
可插拔策略框架。新增策略仅需:
  1. 新建一个 .py 实现 BaseStrategy
  2. 在 registry.py 中注册一行

"""

from .registry import get_strategy, list_strategies, register_strategy
from .base import BaseStrategy, SignalResult

__all__ = ["get_strategy", "list_strategies", "register_strategy", "BaseStrategy", "SignalResult"]
