# -*- coding: utf-8 -*-
"""技术指标计算与趋势评分。"""

from typing import Optional


def safe_float(val) -> Optional[float]:
    """安全转换为float。"""
    try:
        import pandas as pd

        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None


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


def identify_market_state(tech_data: dict, sym_data: dict) -> tuple:
    """识别市场状态。返回 (market_state, trend_score)。"""
    try:
        from .config import MARKET_STATE_SYSTEM
    except ImportError:
        from config import MARKET_STATE_SYSTEM

    ma5 = tech_data.get("MA5")
    ma10 = tech_data.get("MA10")
    ma20 = tech_data.get("MA20")
    ma40 = tech_data.get("MA40")
    ma60 = tech_data.get("MA60")
    atr = tech_data.get("ATR14")
    last_price = sym_data.get("last_price")

    trend_score = 0
    # 多层级MA排列判断（短中期MA5>MA10>MA20，中长期MA20>MA40>MA60）
    if ma5 and ma10 and ma20:
        short_bull = ma5 > ma10 > ma20
        short_bear = ma5 < ma10 < ma20
        long_bull = (ma20 > ma40 > ma60) if (ma40 and ma60) else short_bull
        long_bear = (ma20 < ma40 < ma60) if (ma40 and ma60) else short_bear

        # 紧密度检测：MA5-MA20间距<0.5% → 震荡，排列信号不可靠
        ma_spread = abs(ma5 - ma20) / ma20 if ma20 else 0
        is_tight = ma_spread < 0.005

        if short_bull and long_bull and not is_tight:
            trend_score = 30  # 完全多头排列
        elif short_bull and not is_tight:
            trend_score = 15  # 仅短周期多头（长周期未配合）
        elif short_bear and long_bear and not is_tight:
            trend_score = -30  # 完全空头排列
        elif short_bear and not is_tight:
            trend_score = -15  # 仅短周期空头

    volatility = 0
    if atr and last_price:
        volatility = atr / last_price * 100

    if abs(trend_score) >= MARKET_STATE_SYSTEM["trend_threshold"]:
        if volatility >= MARKET_STATE_SYSTEM["volatile_threshold"]:
            return "volatile", trend_score
        return "trending", trend_score
    elif abs(trend_score) <= MARKET_STATE_SYSTEM["range_threshold"]:
        return "ranging", trend_score
    return "transitional", trend_score


def calculate_trend_score(tech: dict, sym: dict, chain_name: str = "") -> dict:
    """[已弃用] 使用 scoring_system.calculate_composite_score() 替代。

    此函数保留仅用于测试兼容。新代码禁止调用。
    """
    import warnings

    warnings.warn(
        "calculate_trend_score 已弃用，请使用 scoring_system.calculate_composite_score()",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from .config import get_adaptive_weights, get_product_type
    except ImportError:
        from config import get_adaptive_weights, get_product_type

    market_state, _ = identify_market_state(tech, sym)
    product_type = get_product_type(chain_name) if chain_name else "industrial"
    weights = get_adaptive_weights(product_type, market_state)

    score = 0
    reasons = []

    ma5, ma10, ma20 = tech.get("MA5"), tech.get("MA10"), tech.get("MA20")
    ma40, ma60 = tech.get("MA40"), tech.get("MA60")
    macd_dif = tech.get("MACD_DIF")
    macd_dea = tech.get("MACD_DEA")
    rsi = tech.get("RSI14")
    pdi, mdi = tech.get("DMI_PDI"), tech.get("DMI_MDI")
    atr = tech.get("ATR14")
    obv = tech.get("OBV")
    obv_ma20 = tech.get("OBV_MA20")

    # MA多层级排列（逐级验证，非全有全无）
    last_price = sym.get("last_price")
    if ma5 and ma10 and ma20:
        w = weights.get("MA", 30)

        # === 层级1: 短周期排列 (MA5/MA10/MA20) ===
        short_bull = ma5 > ma10 > ma20
        short_bear = ma5 < ma10 < ma20

        # === 层级2: 长周期排列 (MA20/MA40/MA60) ===
        long_bull = (ma20 > ma40 > ma60) if (ma40 and ma60) else short_bull
        long_bear = (ma20 < ma40 < ma60) if (ma40 and ma60) else short_bear

        # === 紧密度检测 ===
        ma_spread = abs(ma5 - ma20) / ma20 if ma20 else 0
        is_tight_ma = ma_spread < 0.005  # MA间距 < 0.5% → 震荡

        # === 价格相对于MA20的位置 ===
        price_above = last_price and last_price >= ma20
        price_below = last_price and last_price <= ma20

        # === 综合评分 ===
        if is_tight_ma:
            # 均线紧密纠缠 → 震荡，大幅减分
            if short_bull and price_above:
                score += w * 0.10
                reasons.append(f"MA短多但紧密震荡(spread={ma_spread:.3f},{w * 0.10:.0f})")
            elif short_bear and price_below:
                score -= w * 0.10
                reasons.append(f"MA短空但紧密震荡(spread={ma_spread:.3f},{-w * 0.10:.0f})")
        elif short_bull and long_bull and price_above:
            # 完全多头排列（短+长共振） + 价格在MA20上 = 最强
            score += w
            reasons.append(f"MA完全多头排列(短+长共振,{w:.0f})")
        elif short_bull and price_above:
            # 仅短周期多头（长周期未配合）= 弱多头
            score += w * 0.5
            reasons.append(f"MA短多但长周期未共振({w * 0.5:.0f})")
        elif short_bull and not price_above:
            # MA排列多头但价格跌破MA20 → 排列已破坏
            score += w * 0.2
            reasons.append(f"MA排列多头但价格跌破MA20({w * 0.2:.0f})")
        elif short_bear and long_bear and price_below:
            # 完全空头排列 + 价格在MA20下 = 最强
            score -= w
            reasons.append(f"MA完全空头排列(短+长共振,{-w:.0f})")
        elif short_bear and price_below:
            score -= w * 0.5
            reasons.append(f"MA短空但长周期未共振({-w * 0.5:.0f})")
        elif short_bear and not price_below:
            score -= w * 0.2
            reasons.append(f"MA排列空头但价格突破MA20({-w * 0.2:.0f})")

    # MACD（区分零轴上下 + 金叉/死叉，非纯二元判断）
    if macd_dif is not None:
        w = weights.get("MACD", 20)
        if macd_dif > 0:
            # 零轴上方
            if macd_dea is not None and macd_dif > macd_dea:
                # 零轴上 + 金叉（DIF > DEA）→ 最强多头
                score += w
                reasons.append(f"MACD零轴上金叉({w:.0f})")
            elif macd_dea is not None:
                # 零轴上 + 死叉 → 多头减弱
                score += w * 0.5
                reasons.append(f"MACD零轴上死叉(DIF↓,{w * 0.5:.0f})")
            else:
                score += w * 0.7  # 无DEA时保守
                reasons.append(f"MACD零轴上({w * 0.7:.0f})")
        else:
            # 零轴下方
            if macd_dea is not None and macd_dif > macd_dea:
                # 零轴下 + 金叉（DIF上穿DEA）→ 弱势反弹，减分减弱
                score -= w * 0.4
                reasons.append(f"MACD零轴下金叉(弱势反弹,{-w * 0.4:.0f})")
            elif macd_dea is not None:
                # 零轴下 + 死叉 → 最强空头
                score -= w
                reasons.append(f"MACD零轴下死叉({-w:.0f})")
            else:
                score -= w * 0.7
                reasons.append(f"MACD零轴下({-w * 0.7:.0f})")

    # RSI
    if rsi is not None:
        w = weights.get("RSI", 10)
        if rsi < 30:
            score += w
            reasons.append(f"RSI超卖({rsi:.0f},{w:.0f})")
        elif rsi > 70:
            score -= w
            reasons.append(f"RSI超买({rsi:.0f},{w:.0f})")

    # DMI
    if pdi and mdi:
        w = weights.get("DMI", 20)
        if pdi > mdi:
            score += w
            reasons.append(f"PDI>MDI({w:.0f})")
        else:
            score -= w
            reasons.append(f"MDI>PDI({w:.0f})")

    # ATR波动率（仅记录状态，不参与评分）
    if atr and last_price:
        atr_pct = atr / last_price * 100
        tech["volatility_pct"] = atr_pct
        tech["volatility_state"] = "high" if atr_pct > 3 else ("low" if atr_pct < 1 else "normal")

    # 成交量确认
    if obv is not None and obv_ma20 is not None:
        w = weights.get("VOLUME", 10)
        if obv > obv_ma20:
            score += w
            reasons.append(f"OBV>MA20({w:.0f})")
        elif obv < obv_ma20:
            score -= w
            reasons.append(f"OBV<MA20({w:.0f})")

    # ===== 通道突破信号（v2.9 新增，替代ADX作为趋势阶段主判断） =====
    bb_upper = tech.get("BB_UPPER")
    bb_lower = tech.get("BB_LOWER")
    bb_middle = tech.get("BB_MIDDLE")
    dc_upper = tech.get("DC_UPPER")
    dc_lower = tech.get("DC_LOWER")
    dc_mid = tech.get("DC_MID")

    channel_score = 0
    channel_reasons = []

    # Bollinger Bands 突破信号
    if bb_upper and bb_lower and last_price:
        bb_width = bb_upper - bb_lower
        if bb_width > 0:
            bb_pct = (last_price - bb_middle) / (bb_width / 2) if bb_middle else 0
            if last_price > bb_upper:
                # 突破上轨 → 多头突破信号
                w = weights.get("CHANNEL_BREAKOUT", 15)
                channel_score += w
                channel_reasons.append(f"Boll突破上轨({w:.0f})")
            elif last_price < bb_lower:
                # 突破下轨 → 空头突破信号
                w = weights.get("CHANNEL_BREAKOUT", 15)
                channel_score -= w
                channel_reasons.append(f"Boll突破下轨({-w:.0f})")
            elif last_price > bb_middle:
                # 中轨上方运行 → 偏多
                w = weights.get("CHANNEL_POSITION", 10)
                channel_score += int(w * 0.5)
                channel_reasons.append(f"Boll中轨上方({int(w * 0.5):.0f})")
            elif last_price < bb_middle:
                # 中轨下方运行 → 偏空
                w = weights.get("CHANNEL_POSITION", 10)
                channel_score -= int(w * 0.5)
                channel_reasons.append(f"Boll中轨下方({int(-w * 0.5):.0f})")

    # Donchian Channel 突破信号
    if dc_upper and dc_lower and last_price:
        dc_width = dc_upper - dc_lower
        if dc_width > 0:
            if last_price >= dc_upper:
                # 突破20日新高 → 多头
                w = weights.get("CHANNEL_BREAKOUT", 15)
                channel_score += w
                channel_reasons.append(f"Donchian突破新高({w:.0f})")
            elif last_price <= dc_lower:
                # 跌破20日新低 → 空头
                w = weights.get("CHANNEL_BREAKOUT", 15)
                channel_score -= w
                channel_reasons.append(f"Donchian跌破新低({-w:.0f})")
            elif dc_mid and last_price > dc_mid:
                # 通道上半区 → 偏多
                w = weights.get("CHANNEL_POSITION", 10)
                channel_score += int(w * 0.3)
                channel_reasons.append(f"Donchian上半区({int(w * 0.3):.0f})")
            elif dc_mid and last_price < dc_mid:
                # 通道下半区 → 偏空
                w = weights.get("CHANNEL_POSITION", 10)
                channel_score -= int(w * 0.3)
                channel_reasons.append(f"Donchian下半区({int(-w * 0.3):.0f})")

    # 双通道共振加分
    if len(channel_reasons) >= 2:
        # Boll + Donchian 同时给出同方向信号 → 早期信号置信度最高
        bullish_signals = sum(
            1 for r in channel_reasons if "突破上轨" in r or "突破新高" in r or "上方" in r or "上半区" in r
        )
        bearish_signals = sum(
            1 for r in channel_reasons if "突破下轨" in r or "跌破新低" in r or "下方" in r or "下半区" in r
        )
        if bullish_signals >= 2:
            channel_score += 5  # 双通道共振加分
            channel_reasons.append("双通道多头共振(+5)")
        elif bearish_signals >= 2:
            channel_score -= 5
            channel_reasons.append("双通道空头共振(-5)")

    score += channel_score
    reasons.extend(channel_reasons)

    # ===== ADX 降为辅助信号（v2.9 改造） =====
    # ADX 不再作为趋势阶段判断，仅作为趋势强度的辅助确认
    # ADX > 25 时通道信号加分（趋势确认），ADX < 18 时震荡过滤
    adx = tech.get("ADX")
    if adx is not None:
        if adx < 18:
            # 震荡市：通道信号打5折（但不惩罚MA/MACD等其他信号）
            if channel_score != 0:
                penalty = int(channel_score * 0.5)
                score = score - channel_score + penalty
                reasons.append(f"ADX={adx:.0f}<18震荡(通道信号×0.5)")
        elif adx >= 25:
            # 趋势确认：通道信号+20%加分
            if channel_score != 0:
                bonus = int(channel_score * 0.2)
                score += bonus
                reasons.append(f"ADX={adx:.0f}≥25趋势确认(通道+20%)")

    # 趋势判断
    if score >= 30:
        trend = "strong_bull"
    elif score >= 10:
        trend = "weak_bull"
    elif score <= -30:
        trend = "strong_bear"
    elif score <= -10:
        trend = "weak_bear"
    else:
        trend = "neutral"

    # ================================================================
    # 趋势阶段评估（v2.11 四阶段：启动/主升/衰竭/反转）
    # ================================================================
    trend_maturity = assess_trend_maturity(tech, sym, score)

    stage = trend_maturity["stage"]
    dc_pos_val = trend_maturity.get("dc_pos")
    dev = trend_maturity["price_deviation_pct"]

    if stage == "reversal":
        # 反转期：直接清零（趋势已终结）
        score = 0
        reasons.append(f"反转期(DC55破位)(清零)")
    elif stage == "exhausted":
        # 衰竭期：打2折
        score = int(score * 0.2)
        pos_str = f"DC20={dc_pos_val:.2f}" if dc_pos_val else f"偏离{dev:.1f}%"
        reasons.append(f"衰竭期[{pos_str}](×0.2)")
    elif stage == "trending":
        # 主升期：不打折（趋势健康）
        pass
    elif stage == "launch":
        # 启动期：不打折（刚突破，空间大）
        pass

    return {
        "score": score,
        "trend": trend,
        "reasons": reasons,
        "market_state": market_state,
        "maturity": trend_maturity,
    }


def _compute_indicators_numpy(klines, symbol: str = None) -> dict:
    """Fallback: numpy/pandas 计算全部技术指标（不依赖 tqsdk.ta）。

    RSI/ADX/ATR 使用通达信Wilder平滑（SMA(X,N,1)），与通达信公式一致。

    如传入symbol且TQ-Local可用，会用通达信实盘指标覆盖DMI/RSI/CCI/MACD。

    接受: DataFrame with columns [open,high,low,close,volume] 或 dict of arrays
    """
    import pandas as pd, numpy as np

    if isinstance(klines, dict):
        df = pd.DataFrame(klines)
    else:
        df = klines if hasattr(klines, "columns") else pd.DataFrame(klines)

    # Normalize Chinese column names to English
    cn_to_en = {
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "持仓量": "open_interest",
        "日期": "date",
    }
    df = df.rename(columns={k: v for k, v in cn_to_en.items() if k in df.columns})
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    v = df.get("volume", np.zeros_like(c))
    if hasattr(v, "values"):
        v = v.values.astype(float)

    tech = {}
    n = len(c)
    if n < 60:
        return tech

    # ---- helpers ----
    def sma(x, p):
        return pd.Series(x).rolling(p).mean().values

    def wilder_rma(x, p):
        """Wilder平滑（通达信SMA(X,N,1)）: alpha=1/p, 用于RSI/ADX/ATR"""
        out = np.zeros_like(x)
        out[p - 1] = np.mean(x[:p])
        for i in range(p, len(x)):
            out[i] = (x[i] + (p - 1) * out[i - 1]) / p
        return out

    def ema(x, p):
        a = 2 / (p + 1)
        e = np.zeros_like(x)
        e[0] = x[0]
        for i in range(1, len(x)):
            e[i] = a * x[i] + (1 - a) * e[i - 1]
        return e

    def sd(x, p):
        return pd.Series(x).rolling(p).std().values

    def md(x, p):
        return pd.Series(x).rolling(p).apply(lambda v: np.mean(np.abs(v - np.mean(v))), raw=True).values

    def max_(x, p):
        return pd.Series(x).rolling(p).max().values

    def min_(x, p):
        return pd.Series(x).rolling(p).min().values

    def atr_fn(p=14):
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        return wilder_rma(tr, p)

    # ---- MA ----
    for p in [5, 10, 20, 40, 60, 120]:
        tech[f"MA{p}"] = float(sma(c, p)[-1])

    # MA20_SLOPE (linear regression on last 5 days of MA20)
    ma20_series = sma(c, 20)
    t = np.arange(5)
    slope, _ = np.polyfit(t, ma20_series[-5:], 1) if n >= 25 else (0, 0)
    tech["MA20_SLOPE"] = float(slope)

    # ---- MACD ----
    e12 = ema(c, 12)
    e26 = ema(c, 26)
    dif = e12 - e26
    dea = ema(dif, 9)
    tech["MACD_DIF"] = float(dif[-1])
    tech["MACD_DEA"] = float(dea[-1])

    # ---- RSI14 (通达信Wilder平滑) ----
    d = np.diff(c, prepend=c[0])
    g = np.clip(d, 0, None)
    ls = np.clip(-d, 0, None)
    ag = wilder_rma(g, 14)
    al = wilder_rma(ls, 14)
    tech["RSI14"] = float(100 - 100 / (1 + ag[-1] / al[-1])) if al[-1] > 0 else 100.0

    # ---- CCI20 ----
    tp = (h + l + c) / 3
    tp_ma = sma(tp, 20)
    tp_md_ = md(tp, 20)
    tech["CCI20"] = float((tp[-1] - tp_ma[-1]) / (0.015 * tp_md_[-1])) if tp_md_[-1] > 0 else 0.0

    # ---- ATR14 ----
    a14 = atr_fn(14)
    tech["ATR14"] = float(a14[-1])
    tech["ATR_PERCENTILE"] = float(np.percentile(a14[-20:], [50])[0]) if n >= 20 else 0
    a20 = atr_fn(20) if n >= 20 else a14
    tech["ATR_RATIO_20"] = float(a14[-1] / np.mean(a20[-60:])) if n >= 60 and np.mean(a20[-60:]) > 0 else 1.0
    tech["volatility_pct"] = float(a14[-1] / c[-1] * 100) if c[-1] > 0 else 0
    tech["volatility_state"] = "high" if tech["volatility_pct"] > 3 else "normal"

    # ---- DMI / ADX (通达信Wilder平滑) ----
    up_ = h - np.roll(h, 1)
    dn_ = np.roll(l, 1) - l
    pdm = np.where((up_ > dn_) & (up_ > 0), up_, 0.0)
    mdm = np.where((dn_ > up_) & (dn_ > 0), dn_, 0.0)
    at14 = np.where(a14 == 0, 1e-10, a14)
    pdi = 100 * wilder_rma(pdm, 14) / at14
    mdi = 100 * wilder_rma(mdm, 14) / at14
    dx = 100 * np.abs(pdi - mdi) / (pdi + mdi + 1e-10)
    adx_ = wilder_rma(dx, 14)
    tech["DMI_PDI"] = float(pdi[-1])
    tech["DMI_MDI"] = float(mdi[-1])
    tech["ADX"] = float(adx_[-1])

    # ---- DC Donchian ----
    for p, suffix in [(20, ""), (55, "55")]:
        u = max_(h, p)
        lw = min_(l, p)
        tech[f"DC{suffix}_UPPER"] = float(u[-1])
        tech[f"DC{suffix}_LOWER"] = float(lw[-1])
        tech[f"DC{suffix}_MID"] = float((u[-1] + lw[-1]) / 2)
    dc20_l = tech["DC_LOWER"]
    dc20_u = tech["DC_UPPER"]
    tech["DC_POS"] = float((c[-1] - dc20_l) / (dc20_u - dc20_l)) if dc20_u > dc20_l else 0.5
    # DC55_TREND: use MA20 slope direction
    tech["DC55_TREND"] = "up" if tech["MA20_SLOPE"] > 0.01 else ("down" if tech["MA20_SLOPE"] < -0.01 else "flat")

    # ---- BB Bollinger ----
    bb_mid = sma(c, 20)
    bb_std = sd(c, 20)
    tech["BB_UPPER"] = float(bb_mid[-1] + 2 * bb_std[-1])
    tech["BB_LOWER"] = float(bb_mid[-1] - 2 * bb_std[-1])
    tech["BB_MIDDLE"] = float(bb_mid[-1])
    tech["BB_PCTB"] = (
        float((c[-1] - tech["BB_LOWER"]) / (tech["BB_UPPER"] - tech["BB_LOWER"]))
        if tech["BB_UPPER"] > tech["BB_LOWER"]
        else 0.5
    )
    tech["BB_WIDTH"] = (
        float((tech["BB_UPPER"] - tech["BB_LOWER"]) / tech["BB_MIDDLE"] * 100) if tech["BB_MIDDLE"] > 0 else 0
    )
    tech["BB_WIDTH_PCT"] = tech["BB_WIDTH"]
    bw20 = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid * 100
    tech["BB_SQUEEZE"] = bool(bw20[-1] < np.percentile(bw20[-60:], 10)) if n >= 60 else False

    # ---- SUPERTREND (10,3) ----
    at10 = atr_fn(10)
    hl = (h + l) / 2
    upper = hl + 3 * at10
    lower = hl - 3 * at10
    st_arr = np.zeros(n)
    st_dir_arr = np.zeros(n)
    trend = 1
    st_arr[0] = lower[0]
    st_dir_arr[0] = 1
    for i in range(1, n):
        if trend == 1:
            if c[i] < st_arr[i - 1]:
                trend = -1
                st_arr[i] = upper[i]
            else:
                st_arr[i] = max(lower[i], st_arr[i - 1])
        else:
            if c[i] > st_arr[i - 1]:
                trend = 1
                st_arr[i] = lower[i]
            else:
                st_arr[i] = min(upper[i], st_arr[i - 1])
        st_dir_arr[i] = trend
    tech["SUPERTREND_DIR"] = int(st_dir_arr[-1])
    tech["SUPERTREND_JUST_FLIPPED"] = st_dir_arr[-1] != st_dir_arr[-2] if n >= 3 else False

    # ---- Vortex (14) ----
    vm_p = np.abs(h - np.roll(l, 1))
    vm_m = np.abs(l - np.roll(h, 1))
    tr_v_atr = atr_fn(14)
    tr_v = np.where(tr_v_atr == 0, 1e-10, tr_v_atr)
    vp = wilder_rma(vm_p, 14) / tr_v
    vm = wilder_rma(vm_m, 14) / tr_v
    tech["VI_PLUS"] = float(vp[-1])
    tech["VI_MINUS"] = float(vm[-1])

    # ---- HMA ----
    def hma_fn(x, p):
        h1 = sma(x, p // 2) * 2 - sma(x, p)
        return sma(h1, int(np.sqrt(p)))

    if n >= 20:
        tech["HMA10"] = float(hma_fn(c, 10)[-1]) if n >= 10 else 0
        tech["HMA20"] = float(hma_fn(c, 20)[-1])
        hma10_series = hma_fn(c, 10)
        tech["HMA_CROSS"] = 1 if hma10_series[-1] > tech["HMA20"] else -1
        tech["HMA_JUST_CROSSED"] = (
            hma10_series[-2] <= tech.get("HMA20_PREV", tech["HMA20"]) and tech["HMA_CROSS"] == 1
        ) or (hma10_series[-2] >= tech.get("HMA20_PREV", tech["HMA20"]) and tech["HMA_CROSS"] == -1)
    else:
        tech["HMA10"] = 0
        tech["HMA20"] = 0
        tech["HMA_CROSS"] = 0
        tech["HMA_JUST_CROSSED"] = False

    # ---- KAMA ----
    if n >= 10:
        eff = np.abs(c[-1] - c[-10]) / np.sum(np.abs(np.diff(c[-10:]))) if np.sum(np.abs(np.diff(c[-10:]))) > 0 else 0
        sc = (eff * (2 / (3) - 2 / (31)) + 2 / (31)) ** 2
        kama = c[-10]
        for i in range(-9, 0):
            kama = kama + sc * (c[i] - kama)
        tech["KAMA10"] = float(kama)
        tech["KAMA_CROSS"] = 1 if c[-1] > kama else -1
    else:
        tech["KAMA10"] = 0
        tech["KAMA_CROSS"] = 0

    # ---- CMF21 (requires volume) ----
    if np.sum(v) > 0:
        mfm = ((c - l) - (h - c)) / (h - l + 1e-10) * v  # money flow multiplier * volume
        cmf = sma(mfm, 21) / sma(v, 21)
        tech["CMF21"] = float(cmf[-1]) if np.isfinite(cmf[-1]) else 0
    else:
        tech["CMF21"] = 0

    # ---- OBV ----
    obv = np.zeros(n)
    obv[0] = v[0]
    for i in range(1, n):
        if c[i] > c[i - 1]:
            obv[i] = obv[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            obv[i] = obv[i - 1] - v[i]
        else:
            obv[i] = obv[i - 1]
    tech["OBV"] = float(obv[-1])
    tech["OBV_MA20"] = float(sma(obv, 20)[-1]) if n >= 20 else 0

    # ---- WILLR14 ----
    h14 = max_(h, 14)
    l14 = min_(l, 14)
    tech["WILLR14"] = float((h14[-1] - c[-1]) / (h14[-1] - l14[-1] + 1e-10) * -100)

    # ---- STOCH_K5 ----
    h5 = max_(h, 5)
    l5 = min_(l, 5)
    tech["STOCH_K5"] = float((c[-1] - l5[-1]) / (h5[-1] - l5[-1] + 1e-10) * 100)

    # ---- ROC10 ----
    tech["ROC10"] = float((c[-1] / c[-11] - 1) * 100) if n >= 11 else 0

    # ---- Volume indicators ----
    v5 = np.mean(v[-5:])
    v20 = np.mean(v[-20:])
    tech["VOL_5D_RATIO"] = float(v[-1] / v5) if v5 > 0 else 1
    tech["VOL_MA20"] = float(v20)
    tech["VOL_RATIO"] = float(v[-1] / v20) if v20 > 0 else 1
    tech["VOL_PRICE_DIVERGENCE"] = (
        "negative"
        if (c[-1] < c[-5] and v[-1] > v5 * 1.2)
        else ("positive" if (c[-1] > c[-5] and v[-1] > v5 * 1.2) else "none")
    )

    # ---- Price structure ----
    tech["PRICE_CHANGE_5D"] = float((c[-1] / c[-6] - 1) * 100) if n >= 6 else 0
    tech["HIGH_60"] = float(np.max(h[-60:])) if n >= 60 else 0
    tech["MA120"] = float(sma(c, 120)[-1]) if n >= 120 else 0
    tech["NEW_HIGH_60"] = c[-1] >= tech["HIGH_60"] * 0.99
    tech["NEW_LOW_60"] = c[-1] <= np.min(l[-60:]) * 1.01 if n >= 60 else False

    # HIGHER_LOW / LOWER_HIGH (swing points, last 20 bars)
    if n >= 20:
        l20 = l[-20:]
        h20 = h[-20:]
        l_min = np.argmin(l20)
        h_max = np.argmax(h20)
        recent_l = np.min(l[-5:])
        recent_h = np.max(h[-5:])
        tech["HIGHER_LOW"] = l_min < 10 and recent_l > np.min(l20[:10]) if l_min < len(l20) else False
        tech["LOWER_HIGH"] = h_max < 10 and recent_h < np.max(h20[:10]) if h_max < len(h20) else False
    else:
        tech["HIGHER_LOW"] = False
        tech["LOWER_HIGH"] = False

    # ---- OI (持仓) related ----
    if "open_interest" in df.columns or "oi" in df.columns:
        oi_col = "open_interest" if "open_interest" in df.columns else "oi"
        oi_vals = df[oi_col].values.astype(float)
        inan = ~np.isnan(oi_vals)
        if np.sum(inan) > 0:
            oi_last = oi_vals[inan][-1]
            oi_5d = oi_vals[inan][-6] if np.sum(inan) >= 6 else oi_last
            tech["OI_CHANGE_PCT"] = float((oi_last / oi_5d - 1) * 100) if oi_5d > 0 else 0
            tech["OI_INCREASING"] = oi_last > oi_5d
            tech["OI_RATE"] = float(oi_last / oi_5d) if oi_5d > 0 else 1.0

    # ---- Misc ----
    tech["PRICE_DEVIATION_PCT"] = (
        float((c[-1] - tech.get("MA20", c[-1])) / tech.get("MA20", c[-1]) * 100) if tech.get("MA20", c[-1]) > 0 else 0
    )
    tech["last_price"] = float(c[-1])

    # ── 通达信TQ-Local桥接：覆盖DMI/RSI/CCI/MACD（精确值与通达信软件一致） ──
    tech["_tdx_patched"] = False
    tech["_tdx_fields"] = []
    if symbol:
        tdx_available = False
        try:
            from indicators.tdx_bridge import get_bridge

            bridge = get_bridge()
            status = bridge.patch_indicators(tech, symbol)
            tech["_tdx_patched"] = status["patched"]
            tech["_tdx_fields"] = status["fields"]
            tdx_available = status["patched"]
            if not status["patched"] and not bridge.available:
                tech["_tdx_note"] = "TQ-Local不可用"
        except Exception:
            tech["_tdx_note"] = "TQ-Local桥接异常"

        # ── 最后保障：technical-indicator-calc 的计算引擎（通达信公式完全对齐） ──
        if not tdx_available:
            try:
                sys.path.insert(
                    0,
                    os.path.join(
                        os.path.dirname(os.path.dirname(__file__)), "..", "technical-indicator-calc", "scripts"
                    ),
                )
                from indicators.calc_core import calculate_tdx_compatible
                import numpy as np

                fallback = calculate_tdx_compatible(
                    np.array(h[-120:], dtype=np.float64),
                    np.array(l[-120:], dtype=np.float64),
                    np.array(c[-120:], dtype=np.float64),
                    volume=np.array(v[-120:], dtype=np.float64) if v is not None else None,
                )

                # 用last-resort数值覆盖未patched的字段
                fallback_fields = 0
                for fk, tk in [
                    ("rsi", "RSI14"),
                    ("cci", "CCI20"),
                    ("adx", "ADX"),
                    ("pdi", "DMI_PDI"),
                    ("mdi", "DMI_MDI"),
                    ("macd_dif", "MACD_DIF"),
                    ("macd_dea", "MACD_DEA"),
                    ("macd_hist", "MACD_HIST"),
                    ("atr", "ATR"),
                    ("atr", "ATR14"),
                    ("kdj_k", "KDJ_K"),
                    ("kdj_d", "KDJ_D"),
                    ("kdj_j", "KDJ_J"),
                    ("mfi", "MFI"),
                    ("wr1", "WILLR"),
                    ("bbi", "BBI"),
                    ("uos", "UOS"),
                    ("mtm", "MTM"),
                    ("roc", "ROC"),
                    ("psy", "PSY"),
                    ("vr", "VR"),
                ]:
                    if fk in fallback and fallback[fk] is not None and tk not in tech.get("_tdx_fields", []):
                        tech[tk] = fallback[fk]
                        fallback_fields += 1

                tech["_tdx_fallback"] = fallback_fields > 0
                tech["_tdx_note"] = f"最后保障: {fallback_fields}字段"
            except Exception as e:
                if "_tdx_note" not in tech:
                    tech["_tdx_note"] = f"最后保障异常: {e}"

    return tech


def compute_indicators(klines, symbol: str = None) -> dict:
    """从K线数据计算技术指标。返回tech字典。优先tqsdk.ta，失败则fallback到numpy。

    Args:
        klines: K线DataFrame
        symbol: 品种代码(可选)。传入后优先用通达信TQ-Local覆盖DMI/RSI/CCI/MACD
    """
    import tqsdk.ta as ta

    tech = {}

    # MA（含长周期MA40/MA60用于趋势结构确认）
    try:
        tech["MA5"] = safe_float(ta.MA(klines, 5).iloc[-1])
        tech["MA10"] = safe_float(ta.MA(klines, 10).iloc[-1])
        tech["MA20"] = safe_float(ta.MA(klines, 20).iloc[-1])
        tech["MA40"] = safe_float(ta.MA(klines, 40).iloc[-1])
        tech["MA60"] = safe_float(ta.MA(klines, 60).iloc[-1])
    except Exception:
        pass

    # MACD（只取DIF列，严禁取histogram/macd列）
    try:
        macd = ta.MACD(klines, 12, 26, 9)
        if hasattr(macd, "columns"):
            # 严格只匹配DIF/DEA列，禁止匹配到MACD柱状图
            dif_col = None
            dea_col = None
            for col in macd.columns:
                col_lower = str(col).lower().strip()
                if col_lower in ("dif", "diff") and dif_col is None:
                    dif_col = col
                elif col_lower in ("dea", "signal") and dea_col is None:
                    dea_col = col
            if dif_col:
                tech["MACD_DIF"] = safe_float(macd[dif_col].iloc[-1])
            if dea_col:
                tech["MACD_DEA"] = safe_float(macd[dea_col].iloc[-1])
    except Exception:
        pass

    # RSI
    try:
        tech["RSI14"] = safe_float(ta.RSI(klines, 14).iloc[-1])
    except Exception:
        pass

    # DMI
    try:
        dmi = ta.DMI(klines, 14, 6)
        if hasattr(dmi, "columns"):
            for col in ["pdi", "PDI", "+DI"]:
                if col in dmi.columns:
                    tech["DMI_PDI"] = safe_float(dmi[col].iloc[-1])
                    break
            for col in ["mdi", "MDI", "-DI"]:
                if col in dmi.columns:
                    tech["DMI_MDI"] = safe_float(dmi[col].iloc[-1])
                    break
    except Exception:
        pass

    # ATR
    try:
        tech["ATR14"] = safe_float(ta.ATR(klines, 14).iloc[-1])
    except Exception:
        pass

    # OBV
    try:
        import pandas as pd

        close_prices = klines["close"]
        volumes = klines["volume"]
        obv = [0]
        for i in range(1, len(close_prices)):
            if close_prices.iloc[i] > close_prices.iloc[i - 1]:
                obv.append(obv[-1] + volumes.iloc[i])
            elif close_prices.iloc[i] < close_prices.iloc[i - 1]:
                obv.append(obv[-1] - volumes.iloc[i])
            else:
                obv.append(obv[-1])
        tech["OBV"] = obv[-1]
        obv_series = pd.Series(obv)
        if len(obv_series) >= 20:
            tech["OBV_MA20"] = safe_float(obv_series.rolling(20).mean().iloc[-1])
    except Exception:
        pass

    # ===== Bollinger Bands (20, 2) — v2.9 通道突破 =====
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 20:
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            tech["BB_UPPER"] = safe_float(bb_mid.iloc[-1] + 2 * bb_std.iloc[-1])
            tech["BB_MIDDLE"] = safe_float(bb_mid.iloc[-1])
            tech["BB_LOWER"] = safe_float(bb_mid.iloc[-1] - 2 * bb_std.iloc[-1])
            # Bollinger Bandwidth（带宽，衡量波动率压缩/扩张）
            if bb_mid.iloc[-1] > 0:
                tech["BB_WIDTH"] = safe_float(
                    (bb_mid.iloc[-1] + 2 * bb_std.iloc[-1] - (bb_mid.iloc[-1] - 2 * bb_std.iloc[-1]))
                    / bb_mid.iloc[-1]
                    * 100
                )
    except Exception:
        pass

    # ===== Donchian Channel (20) — v2.9 通道突破 =====
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        if len(high_prices) >= 20:
            tech["DC_UPPER"] = safe_float(high_prices.rolling(20).max().iloc[-1])
            tech["DC_LOWER"] = safe_float(low_prices.rolling(20).min().iloc[-1])
            dc_u = tech.get("DC_UPPER")
            dc_l = tech.get("DC_LOWER")
            if dc_u and dc_l:
                tech["DC_MID"] = safe_float((dc_u + dc_l) / 2)
    except Exception:
        pass

    # ===== Donchian Channel (55) — v2.11 长周期通道 =====
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        if len(high_prices) >= 55:
            tech["DC55_UPPER"] = safe_float(high_prices.rolling(55).max().iloc[-1])
            tech["DC55_LOWER"] = safe_float(low_prices.rolling(55).min().iloc[-1])
            dc55_u = tech.get("DC55_UPPER")
            dc55_l = tech.get("DC55_LOWER")
            if dc55_u and dc55_l:
                tech["DC55_MID"] = safe_float((dc55_u + dc55_l) / 2)
            # DC55方向：比较当前上轨与前一个55周期上轨
            if len(high_prices) >= 110:
                prev_dc55_upper = safe_float(high_prices.iloc[-110:-55].max())
                if prev_dc55_upper and dc55_u:
                    tech["DC55_TREND"] = (
                        "up" if dc55_u > prev_dc55_upper else ("down" if dc55_u < prev_dc55_upper else "flat")
                    )
    except Exception:
        pass

    # ===== Bollinger Bandwidth 百分位 + Squeeze 检测 — v2.11 =====
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 60:
            bb_mid_series = close.rolling(20).mean()
            bb_std_series = close.rolling(20).std()
            # 计算最近40根K线的带宽序列
            bb_width_series = (4 * bb_std_series / bb_mid_series * 100).dropna()
            if len(bb_width_series) >= 20:
                current_width = bb_width_series.iloc[-1]
                # 带宽百分位：当前带宽在近20日中的位置
                recent_widths = bb_width_series.tail(20)
                percentile = (recent_widths < current_width).sum() / len(recent_widths) * 100
                tech["BB_WIDTH_PCT"] = safe_float(percentile)
                # Squeeze检测：带宽处于近20日最低10%分位
                tech["BB_SQUEEZE"] = percentile <= 10
    except Exception:
        pass

    # ===== MA60/MA120 长周期均线 — v2.11 结构位置维度 =====
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 60:
            tech["MA60"] = safe_float(close.rolling(60).mean().iloc[-1])
        if len(close) >= 120:
            tech["MA120"] = safe_float(close.rolling(120).mean().iloc[-1])
    except Exception:
        pass

    # ===== 成交量均值（20日） — v2.11 量能验证维度 =====
    try:
        import pandas as pd

        volumes = klines["volume"]
        if len(volumes) >= 20:
            tech["VOL_MA20"] = safe_float(volumes.rolling(20).mean().iloc[-1])
            tech["VOL_RATIO"] = (
                safe_float(volumes.iloc[-1] / volumes.rolling(20).mean().iloc[-1])
                if volumes.rolling(20).mean().iloc[-1] > 0
                else None
            )
    except Exception:
        pass

    # ===== 近60日新高检测 — v2.11 前高突破 =====
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 60:
            high_60 = close.rolling(60).max().iloc[-1]
            tech["HIGH_60"] = safe_float(high_60)
            tech["NEW_HIGH_60"] = safe_float(close.iloc[-1]) >= safe_float(high_60) if high_60 else False
    except Exception:
        pass

    # ===== v2.12 萌芽因子指标 =====

    # MA20斜率（5日线性回归斜率，标准化为百分比）
    try:
        import pandas as pd
        import numpy as np

        close = klines["close"]
        if len(close) >= 25:
            ma20_series = close.rolling(20).mean()
            recent_ma = ma20_series.tail(5).values
            if len(recent_ma) == 5 and not np.isnan(recent_ma).any():
                # 线性回归斜率
                x = np.arange(5)
                slope = np.polyfit(x, recent_ma, 1)[0]
                # 标准化为每日变化百分比
                if recent_ma[-1] > 0:
                    tech["MA20_SLOPE"] = safe_float(slope / recent_ma[-1] * 100)
    except Exception:
        pass

    # ROC(10) — 10周期变化率
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 11:
            roc = (close.iloc[-1] - close.iloc[-11]) / close.iloc[-11] * 100
            tech["ROC10"] = safe_float(roc)
    except Exception:
        pass

    # 5日成交量比率（当前量/5日均量）
    try:
        import pandas as pd

        volumes = klines["volume"]
        if len(volumes) >= 6:
            vol_5d_avg = volumes.iloc[-6:-1].mean()
            if vol_5d_avg > 0:
                tech["VOL_5D_RATIO"] = safe_float(volumes.iloc[-1] / vol_5d_avg)
    except Exception:
        pass

    # 5日价格变化率
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 6:
            change_5d = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100
            tech["PRICE_CHANGE_5D"] = safe_float(change_5d)
    except Exception:
        pass

    # Higher Low / Lower High 检测（道氏结构）
    try:
        import pandas as pd
        import numpy as np

        close = klines["close"]
        if len(close) >= 20:
            # 将最近20根K线分为前后两段
            mid = 10
            first_half = close.iloc[-20:-mid]
            second_half = close.iloc[-mid:]

            # Higher Low: 后段低点 > 前段低点
            low1 = first_half.min()
            low2 = second_half.min()
            tech["HIGHER_LOW"] = bool(low2 > low1 * 1.003)  # 抬升0.3%以上

            # Lower High: 后段高点 < 前段高点
            high1 = first_half.max()
            high2 = second_half.max()
            tech["LOWER_HIGH"] = bool(high2 < high1 * 0.997)
    except Exception:
        pass

    # ================================================================
    # v2.13 L1/L2/L3 新增指标（早期发现趋势三层架构）
    # ================================================================

    # ===== L2: Bollinger %b — 布林带位置百分比 =====
    # %b = (Price - Lower) / (Upper - Lower)
    # %b > 0.5 = 多头胚（比价格破上轨早3-10根K）
    try:
        import pandas as pd

        close = klines["close"]
        if len(close) >= 20:
            bb_u = tech.get("BB_UPPER")
            bb_l = tech.get("BB_LOWER")
            last_p = safe_float(close.iloc[-1])
            if bb_u and bb_l and last_p and (bb_u - bb_l) > 0:
                tech["BB_PCTB"] = safe_float((last_p - bb_l) / (bb_u - bb_l))
    except Exception:
        pass

    # ===== L2: ATR相对百分位 — 波动率压缩后扩张 =====
    # ATR百分位 < 20 → 观察；刚上20 → 启动胚（比通道突破早5-15根K）
    try:
        import pandas as pd
        import numpy as np

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 35:
            # 计算ATR序列
            tr_list = []
            for i in range(1, len(close)):
                h = safe_float(high_prices.iloc[i])
                l = safe_float(low_prices.iloc[i])
                c_prev = safe_float(close.iloc[i - 1])
                if h is not None and l is not None and c_prev is not None:
                    tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
                    tr_list.append(tr)
            if len(tr_list) >= 35:
                # 14周期ATR序列
                atr_series = pd.Series(tr_list).rolling(14).mean().dropna()
                if len(atr_series) >= 21:
                    current_atr = atr_series.iloc[-1]
                    recent_atr = atr_series.tail(20)
                    percentile = (recent_atr < current_atr).sum() / len(recent_atr) * 100
                    tech["ATR_PERCENTILE"] = safe_float(percentile)
                    # ATR相对于20日均值的比率
                    atr_ma20 = recent_atr.mean()
                    if atr_ma20 > 0:
                        tech["ATR_RATIO_20"] = safe_float(current_atr / atr_ma20)
    except Exception:
        pass

    # ===== L2: CCI(20) — 商品通道指数 =====
    # CCI刚上+100 → 趋势启动胚（比突破通道早3-8根K）
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 20:
            tp = (high_prices + low_prices + close) / 3  # Typical Price
            tp_ma = tp.rolling(20).mean()
            tp_md = tp.rolling(20).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
            last_tp = safe_float(tp.iloc[-1])
            last_ma = safe_float(tp_ma.iloc[-1])
            last_md = safe_float(tp_md.iloc[-1])
            if last_tp is not None and last_ma is not None and last_md is not None and last_md > 0:
                tech["CCI20"] = safe_float((last_tp - last_ma) / (0.015 * last_md))
    except Exception:
        pass

    # ===== L2: Vortex指标 (VI+ / VI-) =====
    # VI+上穿VI- → 趋势胚（比MACD早且对方向敏感）
    try:
        import pandas as pd
        import numpy as np

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 15:
            # VM+ = |High[i] - Low[i-1]|
            # VM- = |Low[i] - High[i-1]|
            # TR = max(H-L, |H-Cprev|, |L-Cprev|)
            # VI+ = sum(VM+, 14) / sum(TR, 14)
            # VI- = sum(VM-, 14) / sum(TR, 14)
            vm_plus_list = []
            vm_minus_list = []
            tr_list = []
            for i in range(1, len(close)):
                h = safe_float(high_prices.iloc[i])
                l = safe_float(low_prices.iloc[i])
                h_prev = safe_float(high_prices.iloc[i - 1])
                l_prev = safe_float(low_prices.iloc[i - 1])
                c_prev = safe_float(close.iloc[i - 1])
                if all(v is not None for v in [h, l, h_prev, l_prev, c_prev]):
                    vm_plus_list.append(abs(h - l_prev))
                    vm_minus_list.append(abs(l - h_prev))
                    tr_list.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
            if len(vm_plus_list) >= 14:
                vm_plus_sum = sum(vm_plus_list[-14:])
                vm_minus_sum = sum(vm_minus_list[-14:])
                tr_sum = sum(tr_list[-14:])
                if tr_sum > 0:
                    tech["VI_PLUS"] = safe_float(vm_plus_sum / tr_sum)
                    tech["VI_MINUS"] = safe_float(vm_minus_sum / tr_sum)
    except Exception:
        pass

    # ===== L2: Supertrend(10, 3) — ATR通道翻色 =====
    # 翻蓝翻红那一刻就是胚（比唐奇安早2-4根K）
    try:
        import pandas as pd
        import numpy as np

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 15:
            period = 10
            multiplier = 3.0
            # 计算ATR
            tr_list = []
            for i in range(1, len(close)):
                h = safe_float(high_prices.iloc[i])
                l = safe_float(low_prices.iloc[i])
                c_prev = safe_float(close.iloc[i - 1])
                if all(v is not None for v in [h, l, c_prev]):
                    tr_list.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
            if len(tr_list) >= period:
                atr_series = pd.Series(tr_list).rolling(period).mean()
                hl2 = (high_prices.iloc[1:] + low_prices.iloc[1:]) / 2
                # Basic Upper/Lower Band
                basic_upper = hl2 + multiplier * atr_series
                basic_lower = hl2 - multiplier * atr_series
                # Final bands
                final_upper = basic_upper.copy()
                final_lower = basic_lower.copy()
                supertrend = pd.Series(0.0, index=range(len(atr_series.dropna())))
                direction = pd.Series(1, index=range(len(atr_series.dropna())))
                valid_atr = atr_series.dropna()
                for i in range(1, len(valid_atr)):
                    idx = valid_atr.index[i]
                    prev_idx = valid_atr.index[i - 1]
                    # Final Upper Band
                    if (
                        basic_upper.iloc[i] < final_upper.iloc[prev_idx]
                        or close.iloc[idx - 1] > final_upper.iloc[prev_idx]
                    ):
                        final_upper.iloc[i] = basic_upper.iloc[i]
                    else:
                        final_upper.iloc[i] = final_upper.iloc[prev_idx]
                    # Final Lower Band
                    if (
                        basic_lower.iloc[i] > final_lower.iloc[prev_idx]
                        or close.iloc[idx - 1] < final_lower.iloc[prev_idx]
                    ):
                        final_lower.iloc[i] = basic_lower.iloc[i]
                    else:
                        final_lower.iloc[i] = final_lower.iloc[prev_idx]
                    # Direction
                    if direction.iloc[prev_idx] == 1:
                        if close.iloc[idx] < final_lower.iloc[i]:
                            direction.iloc[i] = -1
                        else:
                            direction.iloc[i] = 1
                    else:
                        if close.iloc[idx] > final_upper.iloc[i]:
                            direction.iloc[i] = 1
                        else:
                            direction.iloc[i] = -1
                tech["SUPERTREND_DIR"] = int(direction.iloc[-1])  # 1=多头, -1=空头
                if len(direction) >= 2:
                    tech["SUPERTREND_JUST_FLIPPED"] = bool(direction.iloc[-1] != direction.iloc[-2])
    except Exception:
        pass

    # ===== L2: HMA (Hull Moving Average) =====
    # HMA(10)上穿HMA(20) → 比EMA快30-40%
    try:
        import pandas as pd
        import numpy as np

        close = klines["close"]
        if len(close) >= 25:

            def _hma(series, period):
                """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n))"""
                half = int(period / 2)
                sqrt_p = int(np.sqrt(period))
                wma_half = series.rolling(half).apply(
                    lambda x: np.sum(x * np.arange(1, len(x) + 1)) / np.sum(np.arange(1, len(x) + 1)), raw=True
                )
                wma_full = series.rolling(period).apply(
                    lambda x: np.sum(x * np.arange(1, len(x) + 1)) / np.sum(np.arange(1, len(x) + 1)), raw=True
                )
                diff = 2 * wma_half - wma_full
                hma = diff.rolling(sqrt_p).apply(
                    lambda x: np.sum(x * np.arange(1, len(x) + 1)) / np.sum(np.arange(1, len(x) + 1)), raw=True
                )
                return hma

            hma10 = _hma(close, 10)
            hma20 = _hma(close, 20)
            h10 = safe_float(hma10.iloc[-1])
            h20 = safe_float(hma20.iloc[-1])
            if h10 is not None and h20 is not None:
                tech["HMA10"] = h10
                tech["HMA20"] = h20
                tech["HMA_CROSS"] = "bull" if h10 > h20 else "bear"
                # 检测刚交叉（前一根HMA10<HMA20，当前HMA10>HMA20）
                if len(hma10) >= 2:
                    h10_prev = safe_float(hma10.iloc[-2])
                    h20_prev = safe_float(hma20.iloc[-2])
                    if h10_prev is not None and h20_prev is not None:
                        if h10 > h20 and h10_prev <= h20_prev:
                            tech["HMA_JUST_CROSSED"] = "bull"
                        elif h10 < h20 and h10_prev >= h20_prev:
                            tech["HMA_JUST_CROSSED"] = "bear"
    except Exception:
        pass

    # ===== L2: CMF (Chaikin Money Flow, 21) =====
    # CMF刚上0 → 资金开始净流入胚
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        volumes = klines["volume"]
        if len(close) >= 22:
            # Money Flow Multiplier = [(C-L) - (H-C)] / (H-L)
            mfm = ((close - low_prices) - (high_prices - close)) / (high_prices - low_prices)
            mfm = mfm.replace([float("inf"), float("-inf")], 0).fillna(0)
            # Money Flow Volume = MFM * Volume
            mfv = mfm * volumes
            # CMF = sum(MFV, 21) / sum(Volume, 21)
            mfv_sum = mfv.rolling(21).sum()
            vol_sum = volumes.rolling(21).sum()
            cmf = mfv_sum / vol_sum
            cmf = cmf.replace([float("inf"), float("-inf")], 0).fillna(0)
            tech["CMF21"] = safe_float(cmf.iloc[-1])
    except Exception:
        pass

    # ===== L2: 均量倍量+价格未爆 =====
    # Vol > MA(Vol,20) × 1.5 但价格涨幅 < 2% → "量动了价没动" = 胚
    try:
        volumes = klines["volume"]
        close = klines["close"]
        if len(volumes) >= 21:
            vol_ma20 = safe_float(volumes.iloc[-21:-1].mean())
            current_vol = safe_float(volumes.iloc[-1])
            if vol_ma20 and vol_ma20 > 0 and current_vol:
                vol_ratio = current_vol / vol_ma20
                # 价格涨幅（当日）
                if len(close) >= 2:
                    price_chg = (
                        abs(safe_float(close.iloc[-1]) / safe_float(close.iloc[-2]) - 1) * 100
                        if safe_float(close.iloc[-2])
                        else 0
                    )
                    tech["VOL_PRICE_DIVERGENCE"] = bool(vol_ratio >= 1.5 and price_chg < 2.0)
    except Exception:
        pass

    # ===== L3: KAMA (Kaufman Adaptive Moving Average) =====
    # 自带效率比(ER)，趋势一来立刻转方向
    try:
        import pandas as pd
        import numpy as np

        close = klines["close"]
        if len(close) >= 25:
            period = 10
            fast_sc = 2.0 / (2 + 1)
            slow_sc = 2.0 / (30 + 1)
            kama_values = [safe_float(close.iloc[0]) or 0]
            for i in range(1, len(close)):
                c = safe_float(close.iloc[i])
                if c is None:
                    kama_values.append(kama_values[-1])
                    continue
                if i < period:
                    kama_values.append(c)
                    continue
                # Efficiency Ratio
                direction = abs(c - safe_float(close.iloc[i - period]))
                volatility_sum = sum(
                    abs(safe_float(close.iloc[j]) - safe_float(close.iloc[j - 1]))
                    for j in range(i - period + 1, i + 1)
                    if safe_float(close.iloc[j]) is not None and safe_float(close.iloc[j - 1]) is not None
                )
                er = direction / volatility_sum if volatility_sum > 0 else 0
                # Smoothing Constant
                sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
                # KAMA
                kama_values.append(kama_values[-1] + sc * (c - kama_values[-1]))
            kama_val = safe_float(kama_values[-1])
            if kama_val:
                tech["KAMA10"] = kama_val
                last_p = safe_float(close.iloc[-1])
                if last_p:
                    tech["KAMA_CROSS"] = "bull" if last_p > kama_val else "bear"
    except Exception:
        pass

    # ===== L2: Stoch %K (5,3,3) 快线版 =====
    # %K刚从20下方翘 → 多头胚
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 9:
            period = 5
            high_n = high_prices.rolling(period).max()
            low_n = low_prices.rolling(period).min()
            k_raw = (close - low_n) / (high_n - low_n) * 100
            k_raw = k_raw.replace([float("inf"), float("-inf")], 50).fillna(50)
            # 3-period smoothing
            tech["STOCH_K5"] = safe_float(k_raw.rolling(3).mean().iloc[-1])
    except Exception:
        pass

    # ===== L2: Williams %R (14) =====
    # %R脱-80 → 多头胚
    try:
        import pandas as pd

        high_prices = klines["high"]
        low_prices = klines["low"]
        close = klines["close"]
        if len(close) >= 15:
            period = 14
            high_n = high_prices.rolling(period).max()
            low_n = low_prices.rolling(period).min()
            wr = (high_n - close) / (high_n - low_n) * -100
            wr = wr.replace([float("inf"), float("-inf")], -50).fillna(-50)
            tech["WILLR14"] = safe_float(wr.iloc[-1])
    except Exception:
        pass

    # ===== L1: OI信号（持仓量+价+量三角）=====
    # 注意：OI数据来自sym字典（open_interest字段），需要历史OI序列
    # 这里只计算当前OI相对于均值的比率，历史OI序列在early_signal.py中处理
    # ---- Fallback check: if tqsdk.ta failed to produce any indicators, use numpy ----
    tech_key_count = len([k for k in tech if k not in ("OI_CHANGE_PCT", "OI_INCREASING", "OI_RATE")])
    if tech_key_count < 5:
        tech = _compute_indicators_numpy(klines, symbol)
    return tech


if __name__ == "__main__":
    import sys, os
    from scoring_system import calculate_composite_score

    # 技能自包含铁律：数据必须通过 futures-data-search 调度
    sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/futures-data-search/scripts"))
    from multi_source_adapter import MultiSourceAdapter

    adapter = MultiSourceAdapter()

    TARGETS = [("SP", "纸浆"), ("RB", "螺纹钢"), ("LC", "碳酸锂"), ("PX", "PX"), ("AL", "沪铝")]

    import pandas as pd

    for pid, name in TARGETS:
        data = adapter._fetch_akshare(pid, "main", None, None)
        if not data:
            print(f"{pid} {name}: MultiSourceAdapter 返回空")
            continue
        last = data[-1]
        last_price = last.get("close", 0)
        oi = last.get("open_interest", 0)
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df = df.sort_values("date").reset_index(drop=True)
        tech = _compute_indicators_numpy(df, pid)
        if not tech or "RSI14" not in tech:
            print(f"{pid} {name}: 指标计算失败")
            continue
        s = calculate_composite_score(tech, {"last_price": last_price, "open_interest": oi})
        dim = s["dimensions"]
        print(
            f"{pid:4s} {name:6s} C={last_price:>8.0f} RSI={tech['RSI14']:5.1f} "
            f"CCI20={tech['CCI20']:5.0f} ADX={tech['ADX']:5.1f} "
            f"ST={tech['SUPERTREND_DIR']:2d}  {s['total']:3d}分 {s['grade']:6s} {s['direction']:5s}"
        )
        print(
            f"  L1={dim['L1_germination']['score']:2d} L2={dim['L2_volume_price']['score']:2d} "
            f"L3={dim['L3_structure']['score']:2d} L4={dim['L4_confirmation']['score']:2d} "
            f"V={dim['veto']['score']:2d}  Data: futures-data-search"
        )
        if dim["L1_germination"]["reasons"]:
            print(f"  L1: {'; '.join(dim['L1_germination']['reasons'][:4])}")
        if dim["L2_volume_price"]["reasons"]:
            print(f"  L2: {'; '.join(dim['L2_volume_price']['reasons'][:3])}")
        print()
