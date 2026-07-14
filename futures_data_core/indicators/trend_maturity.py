"""趋势阶段评估（已收编至 FDC，单一真相源）。

采用原 indicators_legacy.py 的 v2.17 修正版（功能超集：返回含 ``bb_squeeze`` / ``bb_width_pct`` / ``dc55_trend`` 字段）。
与 core.py 旧副本合并时，以本超集版为权威（非损失性，调用方无破坏）。
"""

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

    # 1. 反转期 (v2.17修正): 价格穿越DC55中轨与当前趋势方向相反
    #    停止使用dc55_pos极值判断(强趋势下价格自然在DC55外运行)
    if dc55_mid and last_price:
        # v2.17修正: 强趋势下(ADX>=35)价格穿越DC55中轨是正常震荡，不是反转
        adx_val = tech.get("ADX")
        if adx_val is not None and adx_val >= 35:
            pass  # 强趋势，不标反转
        elif (is_bull and last_price < dc55_mid) or (not is_bull and last_price > dc55_mid):
            stage = "reversal"

    # 2. 衰竭期：DC20通道极值 + RSI极端（必须RSI确认，单靠通道位置不够）
    if stage == "unknown" and dc_pos is not None:
        # 多头衰竭: DC20上轨极值+RSI极端; 空头衰竭: DC20下轨极值+RSI极端
        exhausted_bull = is_bull and dc_pos > 0.85
        exhausted_bear = not is_bull and dc_pos < 0.15
        if (exhausted_bull or exhausted_bear) and rsi_extreme:
            stage = "exhausted"
        elif dc_pos > 0.85 and price_extreme and rsi_extreme:
            stage = "exhausted"

    # 3. 启动期：突破DC20通道 + (Boll squeeze 或 DC55拐头)
    if stage == "unknown" and dc_pos is not None:
        breakout = (is_bull and dc_pos > 0.7) or (not is_bull and dc_pos < 0.3)
        if breakout and (bb_squeeze or dc55_trend == "up" and is_bull or dc55_trend == "down" and not is_bull):
            stage = "launch"
        elif breakout and dc_pos > 0.7 and dc_pos <= 0.85:
            # 多头突破但未到极值 → 启动期
            stage = "launch"
        elif not is_bull and breakout and dc_pos <= 0.15:
            # 空头突破到通道下轨附近 → 启动期
            stage = "launch"

    # 4. 主升期：价格在DC20上半区运行，趋势确认
    if stage == "unknown" and dc_pos is not None:
        if dc_pos > 0.5:
            stage = "trending"
        elif dc_pos > 0.3:
            # 中间区域，看Boll位置
            if bb_pos is not None and bb_pos > 0.3:
                stage = "trending"
            else:
                stage = "launch"
        else:
            stage = "launch"

    # 5. ADX强制修正: 高ADX品种应为trending而非launch
    if stage == "launch":
        adx_val = tech.get("ADX")
        if adx_val is not None and adx_val >= 25:
            stage = "trending"

    # 6. 无通道数据时回退
    if stage == "unknown":
        if price_extreme:
            stage = "exhausted"
        elif abs(price_deviation_pct) > 5:
            stage = "trending"
        else:
            stage = "launch"

    # 综合通道位置（用于报告输出）
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
        "bb_squeeze": bb_squeeze,
        "bb_width_pct": round(bb_width_pct, 1) if bb_width_pct is not None else None,
        "dc55_trend": dc55_trend,
        "price_deviation_pct": round(price_deviation_pct, 2),
        "price_extreme": price_extreme,
        "rsi_extreme": rsi_extreme,
    }
