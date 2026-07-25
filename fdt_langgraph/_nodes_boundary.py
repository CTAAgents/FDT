"""代码-推理边界函数 — L0 硬约束（stop_loss/target 精确计算 + 仓位钳制）。

本模块零依赖，仅使用 Python 标准库。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 代码-推理边界: stop_loss/target 精确计算（L0 硬约束） ──
_DEFAULT_RISK_MULTIPLIER = 1.5     # 止损 = ATR × 1.5
_DEFAULT_REWARD_MULTIPLIER = 2.0   # 止盈 = ATR × 2.0
_MAX_SINGLE_POSITION_PCT = 20.0    # 单品种最大仓位 (%)
_ACCOUNT_EQUITY = 1_000_000.0      # 默认账户权益
_MARGIN_RATE = 0.1                 # 默认保证金率


def _compute_stop_target(
    direction: str, entry_price: float, atr: float,
    risk_multiplier: float = _DEFAULT_RISK_MULTIPLIER,
    reward_multiplier: float = _DEFAULT_REWARD_MULTIPLIER,
) -> tuple[float, float]:
    """精确计算止损和止盈价格（L0 硬约束，LLM 不可修改）。

    多头: stop = entry - atr × risk, target = entry + atr × reward
    空头: stop = entry + atr × risk, target = entry - atr × reward
    neutral: 返回 0, 0

    当 ATR 不可用时使用默认百分比降级（1%）。
    """
    if atr is None or atr <= 0:
        # 降级策略: 使用固定百分比
        pct = 0.01
        atr = entry_price * pct if entry_price > 0 else 0.0

    if direction in ("bullish", "long", "buy", "BUY"):
        stop = entry_price - atr * risk_multiplier
        target = entry_price + atr * reward_multiplier
    elif direction in ("bearish", "short", "sell", "SELL"):
        stop = entry_price + atr * risk_multiplier
        target = entry_price - atr * reward_multiplier
    else:
        return 0.0, 0.0
    return round(float(stop), 2), round(float(target), 2)


def _clamp_position(
    symbol: str, llm_pct: float,
    max_single_pct: float = _MAX_SINGLE_POSITION_PCT,
) -> float:
    """仓位代码硬校验（L0 硬约束）：钳制 LLM 输出仓位至上限。

    当账户权益/保证金不可知时跳过钳制（降级策略），仅记录 warning。
    """
    try:
        llm_val = float(llm_pct)
    except (TypeError, ValueError):
        logger.warning(f"[Position] {symbol}: LLM输出仓位'{llm_pct}'非法，使用默认值3%")
        return 3.0

    clamped = min(llm_val, max_single_pct)
    if clamped != llm_val:
        logger.warning(
            f"[Position] {symbol}: LLM输出仓位{llm_val}%超限(>{max_single_pct}%)，钳制为{max_single_pct}%")
    return round(clamped, 1)
