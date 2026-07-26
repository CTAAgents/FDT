"""产业链利润因子 — 通过成品-原料价差估算产业链利润（G23 §3.3 P1）。

支持的产业链：
  - 螺纹利润 = RB - 1.6×I - 0.5×J  (简化)
  - 焦化利润 = J - 1.3×JM  (简化)
  - 炼油利润 = SC - (FU 近似)

计算方式：
  - 代码从 K 线收盘价精确计算利润
  - LLM 只负责解读：利润是否处于历史极端、产业政策影响
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import ProfitResult

logger = logging.getLogger(__name__)

# 产业链利润计算规则
# key = output_symbol, value = (margin_type, [(input_symbol, weight), ...])
# 权重 = 生产 1 单位成品所需的原料量（简化）
_CHAIN_RULES: dict[str, tuple[str, list[tuple[str, float]]]] = {
    "RB": ("螺纹利润", [("I", 1.6), ("J", 0.5)]),    # 1吨螺纹 ≈ 1.6吨铁矿石 + 0.5吨焦炭
    "HC": ("热卷利润", [("I", 1.6), ("J", 0.5)]),    # 与螺纹近似
    "J": ("焦化利润", [("JM", 1.3)]),                 # 1吨焦炭 ≈ 1.3吨焦煤
    "SC": ("炼油利润", [("FU", 0.8)]),                # 1吨原油 ≈ 0.8吨燃料油（简化）
}


def compute_profit(
    symbol: str,
    closes: dict[str, float] | None = None,
) -> ProfitResult:
    """计算产业链利润。

    Args:
        symbol: 产成品品种代码
        closes: {symbol: 最新收盘价} 映射

    Returns:
        ProfitResult
    """
    if not closes:
        return ProfitResult(symbol=symbol, data_grade="UNAVAILABLE")

    bare = symbol.upper()
    rule = _CHAIN_RULES.get(bare)
    if rule is None:
        return ProfitResult(symbol=symbol, data_grade="UNAVAILABLE")

    margin_type, inputs = rule
    output_price = closes.get(bare)
    if output_price is None:
        return ProfitResult(symbol=symbol, data_grade="UNAVAILABLE")

    # 计算原料成本
    total_cost = 0.0
    all_inputs_available = True
    for inp_symbol, weight in inputs:
        inp_price = closes.get(inp_symbol)
        if inp_price is None:
            all_inputs_available = False
            break
        total_cost += inp_price * weight

    if not all_inputs_available:
        return ProfitResult(symbol=symbol, data_grade="UNAVAILABLE")

    profit_val = output_price - total_cost
    profit_pct = (profit_val / total_cost * 100) if total_cost > 0 else 0.0

    # 百分位暂不可计算（需要历史序列），留空
    return ProfitResult(
        symbol=bare,
        profit=round(profit_val, 2),
        profit_pct=round(profit_pct, 2),
        percentile=None,
        margin_type=margin_type,
        data_grade="PRIMARY",
    )
