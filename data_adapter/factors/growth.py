"""成长因子 — 营收/利润增长率 + 分析师预期修正（G23 §3.3 P1）。

计算方式（G23 §5 代码-推理边界）：
  - 营收/利润增长率：代码从财务数据精确计算（YoY / 3Y CAGR）
  - 分析师预期修正：从数据源获取一致预期
  - LLM 只负责解读：增长质量、可持续性、行业对比
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import GrowthResult

logger = logging.getLogger(__name__)


def compute_growth(symbol: str, financials: dict | None = None) -> GrowthResult:
    """计算成长因子。

    Args:
        symbol: 品种代码。
        financials: 财务数据字典。

    Returns:
        GrowthResult，data_grade 标记数据等级。
    """
    if not financials:
        return GrowthResult(symbol=symbol, data_grade="NO_DATA")

    try:
        return GrowthResult(
            symbol=symbol,
            revenue_growth_1y=financials.get("revenue_growth_1y"),
            revenue_growth_3y=financials.get("revenue_growth_3y"),
            profit_growth_1y=financials.get("profit_growth_1y"),
            analyst_revision=financials.get("analyst_revision"),
            data_grade="PRIMARY",
        )
    except Exception as e:
        logger.warning("[Growth] %s 计算失败: %s", symbol, e)
        return GrowthResult(symbol=symbol, data_grade="ERROR")
