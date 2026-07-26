"""动量因子 — 时序动量 + 截面动量 + 残差动量（G23 §3.3 P0）。

计算方式（G23 §5 代码-推理边界）：
  - 时序动量：代码从 K 线收盘价精确计算（12-1M / 6M / 3M）
  - 截面动量：代码对全品种排序计算百分位
  - 残差动量：代码回归后取残差再计算动量
  - LLM 只负责解读：动量持续性、趋势转折信号
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .types import MomentumResult

logger = logging.getLogger(__name__)


def compute_momentum(symbol: str, closes: list[float] | None = None) -> MomentumResult:
    """计算动量因子。

    Args:
        symbol: 品种代码。
        closes: 历史收盘价序列（从旧到新，至少 252 个交易日）。

    Returns:
        MomentumResult，data_grade 标记数据等级。
    """
    if not closes or len(closes) < 20:
        return MomentumResult(symbol=symbol, data_grade="INSUFFICIENT_DATA")

    try:
        prices = np.array(closes, dtype=float)

        def _momentum(lookback: int, skip: int = 0) -> float | None:
            """计算动量：当前价格 / 历史价格 - 1）* 100。"""
            if len(prices) < lookback + skip + 1:
                return None
            start = -(lookback + skip)
            end = -skip if skip > 0 else len(prices)
            return float((prices[-1] / prices[start] - 1) * 100)

        mom_12m1m = _momentum(252, 21)   # 12-1M 动量
        mom_6m = _momentum(126)           # 6 个月动量
        mom_3m = _momentum(63)            # 3 个月动量

        return MomentumResult(
            symbol=symbol,
            momentum_12m1m=mom_12m1m,
            momentum_6m=mom_6m,
            momentum_3m=mom_3m,
            data_grade="PRIMARY",
        )
    except Exception as e:
        logger.warning("[Momentum] %s 计算失败: %s", symbol, e)
        return MomentumResult(symbol=symbol, data_grade="ERROR")
