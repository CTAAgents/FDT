"""价值因子 — PE/PB/PS/PCF 历史分位 + EV/EBITDA（G23 §3.3 P0）。

计算方式（G23 §5 代码-推理边界）：
  - PE/PB/PS/PCF 历史百分位：代码从财务数据精确计算
  - EV/EBITDA：代码从市值+负债+现金精确计算
  - LLM 只负责解读：估值是否合理、行业对比
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import ValueResult

logger = logging.getLogger(__name__)


def compute_value(symbol: str, financials: dict | None = None) -> ValueResult:
    """计算价值因子。

    Args:
        symbol: 品种代码。
        financials: 财务数据字典，含 pe/pb/ps/pcf/ev_ebitda 等。

    Returns:
        ValueResult，data_grade 标记数据等级。
    """
    if not financials:
        return ValueResult(symbol=symbol, data_grade="NO_DATA")

    try:
        pe_pct = financials.get("pe_percentile")
        pb_pct = financials.get("pb_percentile")
        ps_pct = financials.get("ps_percentile")
        pcf_pct = financials.get("pcf_percentile")
        ev_ebitda = financials.get("ev_ebitda")
        div_yield = financials.get("dividend_yield")

        zscores = [v for v in [pe_pct, pb_pct, ps_pct, pcf_pct] if v is not None]
        composite = (sum(zscores) / len(zscores) - 50) / 50 if zscores else None

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
