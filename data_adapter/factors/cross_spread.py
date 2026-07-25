"""跨品种价差因子 — 从 K 线数据计算配对价差、Z-Score、百分位。

全部为纯 pandas 计算，零外部依赖。
配对品种对来自 FACTOR_PAIRS 配置。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .types import CrossSpreadResult

logger = logging.getLogger(__name__)


def compute_cross_spreads(
    symbols: list[str],
    kline_data: dict,
    pairs: list[tuple[str, str]],
) -> list[CrossSpreadResult]:
    """计算跨品种价差。

    Args:
        symbols: 品种列表（用于过滤配对）
        kline_data: state["kline"] — {symbol: KlineResult}
        pairs: 品种对列表，如 [("RB", "HC"), ...]

    Returns:
        可用的跨品种价差列表（仅当配对的两个品种都有 K 线数据）
    """
    results: list[CrossSpreadResult] = []
    symbol_set = {s.upper() for s in symbols}

    for sym_a, sym_b in pairs:
        if sym_a.upper() not in symbol_set or sym_b.upper() not in symbol_set:
            continue

        try:
            closes_a = _extract_closes(kline_data, sym_a)
            closes_b = _extract_closes(kline_data, sym_b)

            if closes_a is None or closes_b is None:
                logger.info("[CrossSpread] %s-%s: K线数据不足，跳过", sym_a, sym_b)
                continue

            # 对齐长度
            min_len = min(len(closes_a), len(closes_b))
            if min_len < 30:
                logger.info("[CrossSpread] %s-%s: K线不足30根(%d)，跳过", sym_a, sym_b, min_len)
                continue

            closes_a = closes_a[-min_len:]
            closes_b = closes_b[-min_len:]

            # 价差序列（a - b）
            spread_series = closes_a - closes_b
            current = float(spread_series[-1])
            mean = float(np.mean(spread_series))
            std = float(np.std(spread_series, ddof=1))

            zscore = round((current - mean) / std, 2) if std > 0 else 0.0

            # 百分位
            percentile = _compute_percentile(spread_series, current)

            # 趋势判断（最近5日斜率）
            trend = _detect_trend(spread_series)

            results.append(CrossSpreadResult(
                pair=(sym_a.upper(), sym_b.upper()),
                current_spread=round(current, 2),
                historical_mean=round(mean, 2),
                historical_std=round(std, 2),
                zscore=zscore,
                percentile=round(percentile, 1),
                trend=trend,
                data_grade="PRIMARY",
            ))

        except Exception as e:
            logger.warning("[CrossSpread] %s-%s 计算失败: %s", sym_a, sym_b, e)

    return results


def _extract_closes(kline_data: dict, symbol: str) -> Optional[np.ndarray]:
    """从 kline_data 提取某个品种的收盘价序列。"""
    kres = kline_data.get(symbol.upper())
    if kres is None:
        return None

    bars = getattr(kres, "bars", None) or (kres.get("bars", []) if isinstance(kres, dict) else [])
    if not bars or len(bars) < 30:
        return None

    if hasattr(bars[0], "close"):
        closes = np.array([b.close for b in bars], dtype=float)
    elif isinstance(bars[0], dict):
        closes = np.array([b.get("close", 0) for b in bars], dtype=float)
    else:
        return None

    # 过滤零值
    closes = closes[closes > 0]
    return closes if len(closes) >= 30 else None


def _compute_percentile(series: np.ndarray, value: float) -> float:
    """计算 value 在 series 中的百分位（0~100）。"""
    count_less = np.sum(series <= value)
    return float(count_less / len(series) * 100)


def _detect_trend(series: np.ndarray, lookback: int = 5) -> str:
    """判断价差趋势：widening / narrowing / stable。"""
    if len(series) < lookback:
        return "stable"
    recent = series[-lookback:]
    slope = recent[-1] - recent[0]
    threshold = np.std(series) * 0.2
    if abs(slope) <= threshold:
        return "stable"
    return "widening" if slope > 0 else "narrowing"
