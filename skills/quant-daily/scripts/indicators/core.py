"""
quant-daily 统一指标引擎

直接获取优先：TdxCollector.get_indicators() → tdx_bridge → numpy计算(最后保障)
"""

# 从 calc_core 导入所有TDX兼容指标计算函数
from .calc_core import (
    calculate_tdx_compatible,
    # 基础计算函数
    calculate_ma,
    calculate_ema,
    calculate_rsi,
    calculate_stoch,
    calculate_stochrsi,
    calculate_williams_r,
    calculate_cci,
    calculate_roc,
    calculate_macd,
    calculate_adx,
    calculate_sar,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_supertrend,
    calculate_donchian,
    calculate_vortex,
    calculate_hma,
    calculate_cmf,
    calculate_obv,
    calculate_mfi,
    calculate_kama,
    calculate_ultimate_oscillator,
    # K线形态
    detect_doji,
    detect_hammer,
    detect_engulfing,
    # 布林带分析
    calculate_bb_width,
    calculate_bb_pctb,
    calculate_bb_squeeze,
    # 其他
    calculate_ma_slope,
    detect_higher_high_lower_low,
    detect_volume_price_divergence,
    calculate_linearreg_slope,
    calculate_linearreg_angle,
    calculate_donchian_trend,
    calculate_bull_bear_power,
    calculate_natr,
    calculate_highs_lows,
    calculate_ppo,
    calculate_bb_squeeze as _,
)

__all__ = [
    "assess_trend_maturity",
    "calculate_tdx_compatible",
    "calculate_rsi",
    "calculate_adx",
    "calculate_macd",
    "calculate_stoch",
    "calculate_williams_r",
    "calculate_cci",
    "calculate_atr",
    "calculate_ma",
    "calculate_ema",
    "calculate_bollinger_bands",
    "calculate_supertrend",
    "calculate_donchian",
    "calculate_vortex",
    "calculate_hma",
    "calculate_cmf",
    "calculate_obv",
    "calculate_mfi",
    "calculate_kama",
    "calculate_sar",
    "calculate_roc",
    "calculate_ultimate_oscillator",
    "calculate_ppo",
    "calculate_natr",
    "calculate_highs_lows",
    "calculate_bb_width",
    "calculate_bb_pctb",
    "calculate_bb_squeeze",
    "calculate_ma_slope",
    "calculate_linearreg_slope",
    "calculate_linearreg_angle",
    "calculate_donchian_trend",
    "calculate_bull_bear_power",
    "detect_doji",
    "detect_hammer",
    "detect_engulfing",
    "detect_higher_high_lower_low",
    "detect_volume_price_divergence",
]


def assess_trend_maturity(tech: dict, sym: dict, score: int) -> dict:
    """评估趋势阶段：launch/trending/exhausted/reversal (v2.17修正版)。

    判断逻辑：
    1. reversal: 价格穿越DC55中轨反方向 + ADX<35(强趋势不标反转)
    2. exhausted: DC20通道极值(多头>0.85/空头<0.15) + RSI极端(多头>75/空头<25)
    3. launch: 突破DC20通道(多头>0.7/空头<0.3) + (Boll收口或DC55同向拐头)
    4. trending: DC20上半区 + ADX>=25强制promotion
    """
    last_price = sym.get("last_price")
    ma20 = tech.get("MA20")
    rsi = tech.get("RSI14")

    is_bull = score > 0

    # 价格偏离度
    price_deviation_pct = 0
    if last_price and ma20 and ma20 > 0:
        price_deviation_pct = (last_price - ma20) / ma20 * 100

    # ===== 通道数据 =====
    bb_upper = tech.get("BB_UPPER")
    bb_middle = tech.get("BB_MIDDLE")
    bb_lower = tech.get("BB_LOWER")
    dc_upper = tech.get("DC_UPPER")
    dc_lower = tech.get("DC_LOWER")
    dc_mid = tech.get("DC_MID")
    dc55_upper = tech.get("DC55_UPPER")
    dc55_lower = tech.get("DC55_LOWER")
    dc55_mid = tech.get("DC55_MID")
    dc55_trend = tech.get("DC55_TREND")  # 'up' / 'down' / 'flat'
    bb_squeeze = tech.get("BB_SQUEEZE", False)
    bb_width_pct = tech.get("BB_WIDTH_PCT")

    # ===== DC20 通道位置 =====
    dc_pos = None
    if dc_upper and dc_lower and last_price and (dc_upper - dc_lower) > 0:
        if is_bull:
            dc_pos = (last_price - dc_lower) / (dc_upper - dc_lower)
        else:
            dc_pos = (dc_upper - last_price) / (dc_upper - dc_lower)
        dc_pos = max(0, min(1.0, dc_pos))

    # ===== Boll 通道位置 =====
    bb_pos = None
    if bb_upper and bb_lower and bb_middle and last_price and (bb_upper - bb_lower) > 0:
        if is_bull:
            bb_pos = (last_price - bb_middle) / (bb_upper - bb_middle) if (bb_upper - bb_middle) > 0 else 0.5
        else:
            bb_pos = (bb_middle - last_price) / (bb_middle - bb_lower) if (bb_middle - bb_lower) > 0 else 0.5
        bb_pos = max(0, min(2.0, bb_pos))

    # ===== DC55 位置（判断反转） =====
    dc55_pos = None
    if dc55_upper and dc55_lower and last_price and (dc55_upper - dc55_lower) > 0:
        if is_bull:
            dc55_pos = (last_price - dc55_lower) / (dc55_upper - dc55_lower)
        else:
            dc55_pos = (dc55_upper - last_price) / (dc55_upper - dc55_lower)
        dc55_pos = max(0, min(1.0, dc55_pos))

    # ===== 辅助信号 =====
    rsi_extreme = False
    if rsi is not None:
        if is_bull and rsi > 75:
            rsi_extreme = True
        elif not is_bull and rsi < 25:
            rsi_extreme = True

    price_extreme = abs(price_deviation_pct) > 12

    # ===== 四阶段判断 =====
    stage = "unknown"

    # 1. 反转期
    if dc55_mid and last_price:
        adx_val = tech.get("ADX")
        if adx_val is not None and adx_val >= 35:
            pass  # 强趋势，不标反转
        elif (is_bull and last_price < dc55_mid) or (not is_bull and last_price > dc55_mid):
            stage = "reversal"

    # 2. 衰竭期
    if stage == "unknown" and dc_pos is not None:
        exhausted_bull = is_bull and dc_pos > 0.85
        exhausted_bear = not is_bull and dc_pos < 0.15
        if (exhausted_bull or exhausted_bear) and rsi_extreme:
            stage = "exhausted"
        elif dc_pos > 0.85 and price_extreme and rsi_extreme:
            stage = "exhausted"

    # 3. 启动期
    if stage == "unknown" and dc_pos is not None:
        breakout = (is_bull and dc_pos > 0.7) or (not is_bull and dc_pos < 0.3)
        if breakout and (bb_squeeze or dc55_trend == "up" and is_bull or dc55_trend == "down" and not is_bull):
            stage = "launch"
        elif breakout and dc_pos > 0.7 and dc_pos <= 0.85:
            stage = "launch"
        elif not is_bull and breakout and dc_pos <= 0.15:
            stage = "launch"

    # 4. 主升期
    if stage == "unknown" and dc_pos is not None:
        if dc_pos > 0.5:
            stage = "trending"
        elif dc_pos > 0.3:
            if bb_pos is not None and bb_pos > 0.3:
                stage = "trending"
            else:
                stage = "launch"
        else:
            stage = "launch"

    # 5. ADX强制修正
    if stage == "launch":
        adx_val = tech.get("ADX")
        if adx_val is not None and adx_val >= 25:
            stage = "trending"

    # 6. 无通道数据回退
    if stage == "unknown":
        if price_extreme:
            stage = "exhausted"
        elif abs(price_deviation_pct) > 5:
            stage = "trending"
        else:
            stage = "launch"

    # 综合通道位置
    if dc_pos is not None:
        if dc_pos <= 0.3:
            channel_position = "near_lower"
        elif dc_pos <= 0.5:
            channel_position = "below_mid"
        elif dc_pos <= 0.7:
            channel_position = "above_mid"
        elif dc_pos <= 0.85:
            channel_position = "near_upper"
        else:
            channel_position = "at_extreme"
    else:
        channel_position = "unknown"

    return {
        "stage": stage,
        "channel_position": channel_position,
        "dc_pos": round(dc_pos, 3) if dc_pos is not None else None,
        "dc55_pos": round(dc55_pos, 3) if dc55_pos is not None else None,
        "bb_pos": round(bb_pos, 3) if bb_pos is not None else None,
        "price_deviation_pct": round(price_deviation_pct, 2),
        "price_extreme": price_extreme,
        "rsi_extreme": rsi_extreme,
    }
