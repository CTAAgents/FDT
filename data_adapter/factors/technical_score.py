"""技术评分代码化 — 从已计算的技术指标精确生成基准评分（L1 边界）。

本模块属于"代码计算 + LLM 赋意"层（L1）：
- 代码从已有技术指标精确计算 0-100 基准分
- LLM 在 ±10 范围内根据定性判断微调
- 保证评分可复现、可审计
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def compute_technical_score(
    symbol: str,
    indicators: dict[str, Any],
    volatility: Optional[dict[str, Any]] = None,
) -> int:
    """从技术指标计算基准评分（0-100），保证可复现性。

    评分规则（四维度加权）:
        - 趋势分 40%：均线排列方向 + 趋势强度
        - 动量分 30%：RSI 位置 + ADX 趋势确认
        - 成交量分 20%：量价配合关系
        - 波动率分 10%：ATR 相对位置

    Args:
        symbol: 品种代码（仅用于日志）
        indicators: fdc_data 中的技术指标字典（含 MA5/MA20/MA60/RSI14/ADX/VOL_RATIO/ATR14 等）
        volatility: 可选，波动率因子（HV/偏度/峰度），来自 P2.5 因子采集

    Returns:
        0-100 整数评分
    """
    score = 50  # 中性基准

    # ── 1. 趋势分 40% ──
    trend_score = _trend_score(indicators)
    score += trend_score * 0.40

    # ── 2. 动量分 30% ──
    momentum_score = _momentum_score(indicators)
    score += momentum_score * 0.30

    # ── 3. 成交量分 20% ──
    volume_score = _volume_score(indicators)
    score += volume_score * 0.20

    # ── 4. 波动率分 10% ──
    volatility_score = _volatility_score(indicators, volatility)
    score += volatility_score * 0.10

    # 钳制到 0-100 范围
    return max(0, min(100, round(score)))


def _get_indicator(
    indicators: dict[str, Any], key: str,
) -> Optional[float]:
    """安全获取指标值，兼容 list/float/int/None。"""
    v = indicators.get(key)
    if v is None:
        return None
    if isinstance(v, list):
        return float(v[-1]) if v else None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _trend_score(indicators: dict[str, Any]) -> int:
    """趋势维度评分（-25 ~ +25）。"""
    ma5 = _get_indicator(indicators, "MA5")
    ma10 = _get_indicator(indicators, "MA10")
    ma20 = _get_indicator(indicators, "MA20")
    ma60 = _get_indicator(indicators, "MA60")
    supertrend = _get_indicator(indicators, "SUPERTREND_DIR")
    dc_pos = _get_indicator(indicators, "DC_POS")
    kama_cross = _get_indicator(indicators, "KAMA_CROSS")
    hma_cross = _get_indicator(indicators, "HMA_CROSS")

    s = 0
    # 均线排列（核心信号）
    if ma5 is not None and ma20 is not None:
        if ma60 is not None:
            if ma5 > ma20 > ma60:
                s += 20  # 多头排列
            elif ma5 < ma20 < ma60:
                s -= 20  # 空头排列
            elif ma5 > ma20:
                s += 8  # 短多
            elif ma5 < ma20:
                s -= 8  # 短空
            else:
                s += 0  # 粘合
        else:
            if ma5 > ma20:
                s += 10
            elif ma5 < ma20:
                s -= 10

    # 唐奇安通道位置
    if dc_pos is not None:
        if dc_pos >= 0.8:
            s += 5  # 高位
        elif dc_pos <= 0.2:
            s -= 5  # 低位

    # Supertrend 方向
    if supertrend is not None:
        if supertrend > 0:
            s += 3
        elif supertrend < 0:
            s -= 3

    # KAMA/HMA 交叉
    if kama_cross is not None:
        if kama_cross > 0:
            s += 2
        elif kama_cross < 0:
            s -= 2
    if hma_cross is not None:
        if hma_cross > 0:
            s += 2
        elif hma_cross < 0:
            s -= 2

    return max(-25, min(25, s))


def _momentum_score(indicators: dict[str, Any]) -> int:
    """动量维度评分（-20 ~ +20）。"""
    rsi = _get_indicator(indicators, "RSI14")
    adx = _get_indicator(indicators, "ADX")
    cci = _get_indicator(indicators, "CCI20")
    macd_dif = _get_indicator(indicators, "MACD_DIF")
    macd_dea = _get_indicator(indicators, "MACD_DEA")

    s = 0

    # RSI 位置
    if rsi is not None:
        if rsi > 70:
            s -= 8  # 超买
        elif rsi > 60:
            s -= 3  # 偏多但接近超买
        elif rsi < 30:
            s += 8  # 超卖
        elif rsi < 40:
            s += 3  # 偏空但接近超卖
        # 30-60: 中性

    # ADX 趋势强度（仅在趋势明确时加减分）
    has_trend = adx is not None and adx >= 25
    if has_trend:
        if adx >= 40:
            s += 4  # 强趋势
        else:
            s += 2  # 中等趋势

    # CCI
    if cci is not None:
        if cci > 100:
            s -= 4  # 超买
        elif cci < -100:
            s += 4  # 超卖

    # MACD 柱
    if macd_dif is not None and macd_dea is not None:
        if macd_dif > macd_dea:
            s += 3  # 金叉区间
        else:
            s -= 3  # 死叉区间

    return max(-20, min(20, s))


def _volume_score(indicators: dict[str, Any]) -> int:
    """成交量维度评分（-15 ~ +15）。

    需要判断价格变化方向和成交量变化方向是否一致。
    VOL_RATIO > 1.2 = 放量, < 0.8 = 缩量
    ```
    """
    vol_ratio = _get_indicator(indicators, "VOL_RATIO")
    ma5 = _get_indicator(indicators, "MA5")
    ma20 = _get_indicator(indicators, "MA20")
    close = _get_indicator(indicators, "close")

    s = 0

    if vol_ratio is None:
        return 0

    # 判断价格方向（使用 MA 关系或收盘价变化）
    if ma5 is not None and ma20 is not None:
        price_up = ma5 > ma20
    elif close is not None:
        price_up = True  # 无法判断时默认中性
    else:
        return 0

    # 量价配合分析
    if vol_ratio > 1.3:
        # 放量
        s += 12 if price_up else -12
    elif vol_ratio > 1.1:
        # 微放量
        s += 6 if price_up else -6
    elif vol_ratio < 0.7:
        # 缩量
        s += 0  # 缩量时信号不明确
    elif vol_ratio < 0.9:
        # 微缩量
        s += -3 if price_up else 3  # 价量背离方向

    return max(-15, min(15, s))


def _volatility_score(
    indicators: dict[str, Any],
    volatility: Optional[dict[str, Any]] = None,
) -> int:
    """波动率维度评分（-10 ~ +10）。

    低波动 → 建仓区域（加分）
    高波动 → 风险区域（减分）
    """
    atr_pct = _get_indicator(indicators, "volatility_pct")

    s = 0

    if atr_pct is not None:
        if atr_pct < 0.5:
            s += 5  # 低波动，趋势可能即将启动
        elif atr_pct < 1.0:
            s += 2  # 正常波动
        elif atr_pct < 2.0:
            s -= 2  # 偏高波动
        else:
            s -= 5  # 极高波动，风险大

    # 波动率因子补充（如可用）
    if volatility:
        hv_20 = volatility.get("hv_20")
        if hv_20 is not None:
            if hv_20 < 15:
                s += 3
            elif hv_20 > 40:
                s -= 3

    return max(-10, min(10, s))
