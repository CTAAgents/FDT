"""价值因子 — PE/PB/PS/PCF 历史分位 + EV/EBITDA（G23 §3.3 P0）。

计算方式（G23 §5 代码-推理边界）：
  - PE/PB/PS/PCF 历史百分位：代码从时间序列精确计算
  - EV/EBITDA：代码从市值+负债+现金精确计算
  - 综合 Z-Score：代码从各百分位聚合
  - LLM 只负责解读：估值是否合理、行业对比
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .types import ValueResult

logger = logging.getLogger(__name__)


def _percentile(values: list[float], current: float) -> float:
    """计算当前值在历史序列中的百分位（0~100）。"""
    if not values:
        return 50.0
    arr = np.array(values)
    below = float(np.sum(arr < current))
    equal = float(np.sum(arr == current))
    n = len(arr)
    return round((below + 0.5 * equal) / n * 100, 1)


def compute_value(symbol: str, financials: dict | None = None) -> ValueResult:
    """计算价值因子。

    输入 financials 支持两种模式：
    1. 预计算模式：传入 pe_percentile/pb_percentile 等已计算好的百分位
    2. 时间序列模式：传入 pe_history/pb_history 等列表 + pe_current/pb_current 当前值

    Args:
        symbol: 品种代码。
        financials: 财务数据字典。

    Returns:
        ValueResult。
    """
    if not financials:
        return ValueResult(symbol=symbol, data_grade="NO_DATA")

    try:
        # 优先使用预计算百分位
        pe_pct = financials.get("pe_percentile")
        pb_pct = financials.get("pb_percentile")
        ps_pct = financials.get("ps_percentile")
        pcf_pct = financials.get("pcf_percentile")

        # 时间序列模式：自动计算百分位
        if pe_pct is None and financials.get("pe_history"):
            pe_pct = _percentile(financials["pe_history"], financials.get("pe_current", 0))
        if pb_pct is None and financials.get("pb_history"):
            pb_pct = _percentile(financials["pb_history"], financials.get("pb_current", 0))
        if ps_pct is None and financials.get("ps_history"):
            ps_pct = _percentile(financials["ps_history"], financials.get("ps_current", 0))
        if pcf_pct is None and financials.get("pcf_history"):
            pcf_pct = _percentile(financials["pcf_history"], financials.get("pcf_current", 0))

        ev_ebitda = financials.get("ev_ebitda")
        div_yield = financials.get("dividend_yield")

        # 综合 Z-Score：百分位偏离 50% 的程度，归一化到 -1~+1
        pcts = [v for v in [pe_pct, pb_pct, ps_pct, pcf_pct] if v is not None]
        composite = (sum(pcts) / len(pcts) - 50) / 50 if pcts else None

        return ValueResult(
            symbol=symbol,
            pe_percentile=pe_pct,
            pb_percentile=pb_pct,
            ps_percentile=ps_pct,
            pcf_percentile=pcf_pct,
            ev_ebitda=ev_ebitda,
            dividend_yield=div_yield,
            composite_zscore=composite,
            data_grade="PRIMARY",
        )
    except Exception as e:
        logger.warning("[Value] %s 计算失败: %s", symbol, e)
        return ValueResult(symbol=symbol, data_grade="ERROR")
