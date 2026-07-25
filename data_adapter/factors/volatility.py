"""波动率因子 — 从 K 线数据计算历史波动率、偏度、峰度、ATR。

全部为纯 numpy/pandas 计算，零外部依赖。
K 线数据来自 state["kline"]（P2.5 已有采集）。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .types import VolatilityResult

logger = logging.getLogger(__name__)


def compute_volatility(
    symbols: list[str],
    kline_data: dict,
) -> dict[str, VolatilityResult]:
    """从 K 线数据计算波动率因子。

    Args:
        symbols: 品种列表
        kline_data: state["kline"] — {symbol: KlineResult}

    Returns:
        {symbol: VolatilityResult}
    """
    results: dict[str, VolatilityResult] = {}

    for sym in symbols:
        try:
            kres = kline_data.get(sym)
            if kres is None:
                results[sym] = VolatilityResult(symbol=sym, data_grade="NO_DATA")
                continue

            bars = getattr(kres, "bars", None) or kres.get("bars", []) if isinstance(kres, dict) else []
            if len(bars) < 20:
                results[sym] = VolatilityResult(symbol=sym, data_grade="INSUFFICIENT_DATA")
                continue

            # 提取收盘价
            if hasattr(bars[0], "close"):
                closes = np.array([b.close for b in bars], dtype=float)
                highs = np.array([b.high for b in bars], dtype=float)
                lows = np.array([b.low for b in bars], dtype=float)
            elif isinstance(bars[0], dict):
                closes = np.array([b.get("close", 0) for b in bars], dtype=float)
                highs = np.array([b.get("high", 0) for b in bars], dtype=float)
                lows = np.array([b.get("low", 0) for b in bars], dtype=float)
            else:
                results[sym] = VolatilityResult(symbol=sym, data_grade="INVALID_DATA")
                continue

            # 过滤零值
            mask = closes > 0
            closes = closes[mask]
            highs = highs[mask]
            lows = lows[mask]
            if len(closes) < 20:
                results[sym] = VolatilityResult(symbol=sym, data_grade="INSUFFICIENT_DATA")
                continue

            # 对数收益率
            log_returns = np.log(closes[1:] / closes[:-1])

            # 历史波动率（年化，假设 250 个交易日）
            hv_5 = _annualized_vol(log_returns, 5, 250) if len(log_returns) >= 5 else None
            hv_20 = _annualized_vol(log_returns, 20, 250) if len(log_returns) >= 20 else None
            hv_60 = _annualized_vol(log_returns, 60, 250) if len(log_returns) >= 60 else None

            # 偏度 + 峰度
            skewness = float(round(pd.Series(log_returns).skew(), 4)) if len(log_returns) >= 3 else None
            kurtosis = float(round(pd.Series(log_returns).kurt(), 4)) if len(log_returns) >= 4 else None

            # 最大回撤
            max_dd = _compute_max_drawdown(closes)

            # ATR
            atr_val, atr_pct = _compute_atr(highs, lows, closes, period=14)

            results[sym] = VolatilityResult(
                symbol=sym,
                hv_5=hv_5,
                hv_20=hv_20,
                hv_60=hv_60,
                skewness=skewness,
                kurtosis=kurtosis,
                max_drawdown=max_dd,
                atr=atr_val,
                atr_pct=atr_pct,
                data_grade="PRIMARY",
            )

        except Exception as e:
            logger.warning("[Volatility] 计算 %s 波动率失败: %s", sym, e)
            results[sym] = VolatilityResult(symbol=sym, data_grade="ERROR")

    return results


def _annualized_vol(log_returns: np.ndarray, period: int, trading_days: int = 250) -> float:
    """计算周期内年化波动率（%）。"""
    if len(log_returns) < period:
        return 0.0
    recent = log_returns[-period:]
    std = np.std(recent, ddof=1)
    return round(float(std * np.sqrt(trading_days) * 100), 2)


def _compute_max_drawdown(prices: np.ndarray) -> float:
    """计算区间最大回撤（%）。"""
    if len(prices) < 2:
        return 0.0
    peak = np.maximum.accumulate(prices)
    drawdown = (prices - peak) / peak
    return round(float(abs(np.min(drawdown)) * 100), 2)


def _compute_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> tuple[Optional[float], Optional[float]]:
    """计算 ATR 及 ATR 百分比。"""
    if len(highs) < period + 1:
        return None, None

    # 真实波幅
    prev_close = closes[:-1]
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - prev_close),
            np.abs(lows[1:] - prev_close),
        ),
    )
    if len(tr) < period:
        return None, None

    atr = float(round(np.mean(tr[-period:]), 2))
    current_price = float(closes[-1])
    atr_pct = round(atr / current_price * 100, 2) if current_price > 0 else None

    return atr, atr_pct
