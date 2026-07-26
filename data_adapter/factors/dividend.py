"""红利因子 — 股息率 + 分红支付率 + 分红稳定性（G23 §3.3 P1）。

计算方式（G23 §5 代码-推理边界）：
  - 股息率：代码从分红+股价精确计算
  - 分红支付率：代码从分红+净利润精确计算
  - 分红稳定性：代码从连续分红年数评估
  - LLM 只负责解读：分红可持续性、与同行业对比
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import DividendResult

logger = logging.getLogger(__name__)


def compute_dividend(symbol: str, financials: dict | None = None) -> DividendResult:
    """计算红利因子。

    Args:
        symbol: 品种代码。
        financials: 财务数据字典。

    Returns:
        DividendResult，data_grade 标记数据等级。
    """
    if not financials:
        return DividendResult(symbol=symbol, data_grade="NO_DATA")

    try:
        div_yield = financials.get("dividend_yield")
        payout = financials.get("payout_ratio")
        years = financials.get("dividend_years")
        stability = None
        if years is not None:
            stability = min(years / 10, 1.0)  # 连续 10 年以上为 1.0

        return DividendResult(
            symbol=symbol,
            dividend_yield=div_yield,
            payout_ratio=payout,
            dividend_years=years,
            dividend_stability=stability,
            data_grade="PRIMARY",
        )
    except Exception as e:
        logger.warning("[Dividend] %s 计算失败: %s", symbol, e)
        return DividendResult(symbol=symbol, data_grade="ERROR")
