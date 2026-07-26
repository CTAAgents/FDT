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


def _momentum_from_prices(prices: np.ndarray, lookback: int, skip: int = 0) -> float | None:
    """计算时序动量：（当前价格 / 历史价格 - 1）× 100。"""
    if len(prices) < lookback + skip + 1:
        return None
    start = -(lookback + skip)
    return float((prices[-1] / prices[start] - 1) * 100)


def compute_momentum(symbol: str, closes: list[float] | None = None) -> MomentumResult:
    """计算单个品种的动量因子（时序动量 12-1M/6M/3M）。

    Args:
        symbol: 品种代码。
        closes: 历史收盘价序列（从旧到新，至少 252 个交易日）。

    Returns:
        MomentumResult。
    """
    if not closes or len(closes) < 20:
        return MomentumResult(symbol=symbol, data_grade="INSUFFICIENT_DATA")

    try:
        prices = np.array(closes, dtype=float)

        mom_12m1m = _momentum_from_prices(prices, 252, 21)   # 12-1M
        mom_6m = _momentum_from_prices(prices, 126)           # 6 个月
        mom_3m = _momentum_from_prices(prices, 63)            # 3 个月

        return MomentumResult(symbol=symbol,
                              momentum_12m1m=mom_12m1m,
                              momentum_6m=mom_6m,
                              momentum_3m=mom_3m,
                              data_grade="PRIMARY")
    except Exception as e:
        logger.warning("[Momentum] %s 计算失败: %s", symbol, e)
        return MomentumResult(symbol=symbol, data_grade="ERROR")


def compute_momentum_batch(data: dict[str, list[float]]) -> dict[str, MomentumResult]:
    """批量计算动量因子（含截面排序 + 残差动量）。

    与 compute_momentum 不同的是，本函数接受全品种数据，
    在时序动量基础上额外计算：
      - cross_sectional_rank: 截面动量百分位
      - residual_momentum: 回归残差再计算动量

    Args:
        data: {symbol: [close1, close2, ...]}，从旧到新。

    Returns:
        {symbol: MomentumResult}。
    """
    if not data:
        return {}

    # 1. 先计算时序动量
    results: dict[str, MomentumResult] = {}
    all_mom_6m: dict[str, float] = {}
    returns_latest: dict[str, float] = {}

    for symbol, closes in data.items():
        if not closes or len(closes) < 20:
            results[symbol] = MomentumResult(symbol=symbol, data_grade="INSUFFICIENT_DATA")
            continue
        try:
            prices = np.array(closes, dtype=float)
            m6 = _momentum_from_prices(prices, 126)
            m3 = _momentum_from_prices(prices, 63)
            m12m1 = _momentum_from_prices(prices, 252, 21)

            results[symbol] = MomentumResult(
                symbol=symbol,
                momentum_12m1m=m12m1,
                momentum_6m=m6,
                momentum_3m=m3,
                data_grade="PRIMARY",
            )
            if m6 is not None:
                all_mom_6m[symbol] = m6
            if len(prices) >= 2:
                returns_latest[symbol] = float((prices[-1] / prices[-2] - 1) * 100)
        except Exception as e:
            logger.warning("[Momentum] %s 计算失败: %s", symbol, e)
            results[symbol] = MomentumResult(symbol=symbol, data_grade="ERROR")

    if len(all_mom_6m) < 3:
        return results  # 品种太少，截面和残差无意义

    # 2. 截面动量排序
    ranked = sorted(all_mom_6m.items(), key=lambda x: x[1])
    total = len(ranked)
    for idx, (sym, _) in enumerate(ranked):
        pct = (idx + 1) / total * 100  # 0~100
        if sym in results and results[sym].data_grade == "PRIMARY":
            results[sym].cross_sectional_rank = round(pct, 1)

    # 3. 残差动量：对截面做 OLS 回归，取残差再算动量
    try:
        sym_list = list(returns_latest.keys())
        if len(sym_list) >= 5:
            mom_vals = np.array([all_mom_6m[s] for s in sym_list])
            ret_vals = np.array([returns_latest[s] for s in sym_list])

            # OLS: ret = α + β × mom + ε
            A = np.vstack([np.ones(len(mom_vals)), mom_vals]).T
            coeffs, _, _, _ = np.linalg.lstsq(A, ret_vals, rcond=None)
            residuals = ret_vals - A @ coeffs

            for i, sym in enumerate(sym_list):
                if sym in results:
                    results[sym].residual_momentum = round(float(residuals[i]), 2)
    except Exception as e:
        logger.debug("[Momentum] 残差动量计算跳过: %s", e)

    return results
