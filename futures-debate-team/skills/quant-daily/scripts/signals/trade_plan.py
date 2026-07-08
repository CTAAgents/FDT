# -*- coding: utf-8 -*-
"""交易方案生成：置信度、盈亏比、综合排序。"""


def calc_confidence(
    symbol_score: int,
    tech_indicators: dict,
    chain_direction: str,
    term_basis: dict = None,
    composite_score: dict = None,
) -> float:
    """计算品种置信度 (0.0 ~ 1.0)（v2.13 L1-L4四层架构）。

    v2.13 公式：
    - L1-L4四层得分 50%（L1萌芽40% + L2量价20% + L3结构15% + L4确认15% + 否决10%，归一化到0-1）
    - 产业链验证 20%
    - 期限/基差 20%（期货专属，已内置在L1中）
    - L1萌芽加成 10%（萌芽因子得分高→额外加分）

    v2.17维度满分：L1=40, L2=25, L3=25, L4=10, 否决=-20

    如果有 composite_score（来自v2.13打分系统），直接使用四层得分。
    否则降级到v2.11逻辑（兼容性）。
    """
    is_bullish = symbol_score > 0

    # --- L1-L4四层得分（v2.13优先） ---
    if composite_score and isinstance(composite_score, dict) and "dimensions" in composite_score:
        dims = composite_score["dimensions"]
        # 兼容v2.12和v2.13两种dimension key
        l1_score = dims.get("L1_germination", dims.get("germination", {})).get("score", 0)
        l2_score = dims.get("L2_volume_price", {}).get("score", 0)
        l3_score = dims.get("L3_structure", dims.get("structure", {})).get("score", 0)
        l4_score = dims.get("L4_confirmation", dims.get("confirmation", {})).get("score", 0)
        veto_score = dims.get("veto", {}).get("score", 0)

        # 归一化到0-1（v2.17：L1=40, L2=25, L3=25, L4=10）
        l1_norm = l1_score / 40.0  # L1满分40
        l2_norm = l2_score / 25.0  # L2满分25
        l3_norm = l3_score / 25.0  # L3满分25
        l4_norm = l4_score / 10.0  # L4满分10
        veto_norm = max(0, (veto_score + 20) / 20.0)

        # 四层加权：L1(40%) + L2(20%) + L3(15%) + L4(15%) + 否决(10%)
        # L1权重最高，因为这是v2.13的核心——最早信号层
        four_dim_score = 0.40 * l1_norm + 0.20 * l2_norm + 0.15 * l3_norm + 0.15 * l4_norm + 0.10 * veto_norm

        # L1萌芽加成：萌芽因子得分高→额外加分（最多+10%）
        germination_bonus = min(0.10, l1_norm * 0.15)
    else:
        # 降级到v2.11逻辑
        signal_strength = abs(symbol_score) / 100.0

        confirmations = 0
        if is_bullish:
            if tech_indicators.get("RSI14", 50) > 50:
                confirmations += 1
            if tech_indicators.get("MACD_DIF", 0) > 0:
                confirmations += 1
            if tech_indicators.get("DMI_PDI", 0) > tech_indicators.get("DMI_MDI", 0):
                confirmations += 1
        else:
            if tech_indicators.get("RSI14", 50) < 50:
                confirmations += 1
            if tech_indicators.get("MACD_DIF", 0) < 0:
                confirmations += 1
            if tech_indicators.get("DMI_MDI", 0) > tech_indicators.get("DMI_PDI", 0):
                confirmations += 1

        indicator_resonance = confirmations / 3.0
        four_dim_score = 0.40 * signal_strength + 0.60 * indicator_resonance
        germination_bonus = 0

    # --- 产业链验证（20%）---
    chain_base = 0.5
    if chain_direction in ["多头趋势", "空头趋势"]:
        aligned = (is_bullish and chain_direction == "多头趋势") or (not is_bullish and chain_direction == "空头趋势")
        chain_adjustment = 0.20 if aligned else -0.10
    else:
        chain_adjustment = 0.0

    # --- 期限/基差维度（20%）---
    term_basis_score = 0.5
    if term_basis is not None and isinstance(term_basis, dict):
        term_signal = term_basis.get("term_signal", 0)
        term_weight = 0.10
        basis_signal = term_basis.get("basis_signal", 0)
        spot_source = term_basis.get("data_source_spot", "")
        if spot_source and "降级" in spot_source:
            basis_weight = 0.07
        elif term_basis.get("spot_price") is not None:
            basis_weight = 0.10
        else:
            basis_weight = 0.0
        term_basis_score = term_weight * (0.5 + term_signal) + basis_weight * (0.5 + basis_signal)
        total_weight = term_weight + basis_weight
        if total_weight > 0:
            term_basis_score = term_basis_score / total_weight
        else:
            term_basis_score = 0.5

    confidence = (
        0.50 * four_dim_score
        + 0.20 * (chain_base + chain_adjustment)
        + 0.20 * term_basis_score
        + 0.10 * germination_bonus
    )

    # ================================================================
    # 趋势成熟度调整（v2.12 已内置在四维度中，额外安全阀）
    # ================================================================
    last_price = tech_indicators.get("last_price")
    ma20 = tech_indicators.get("MA20")
    rsi = tech_indicators.get("RSI14")
    adx = tech_indicators.get("ADX")

    if last_price and ma20 and ma20 > 0:
        price_deviation_pct = (last_price - ma20) / ma20 * 100
        if is_bullish:
            if price_deviation_pct > 15:
                confidence *= 0.5
            elif price_deviation_pct > 10:
                confidence *= 0.7
            elif price_deviation_pct > 5:
                confidence *= 0.85
        else:
            if price_deviation_pct < -15:
                confidence *= 0.5
            elif price_deviation_pct < -10:
                confidence *= 0.7
            elif price_deviation_pct < -5:
                confidence *= 0.85

    if rsi is not None:
        if is_bullish and rsi > 75:
            confidence *= 0.7
        elif not is_bullish and rsi < 25:
            confidence *= 0.7

    if adx is not None and adx > 50:
        confidence *= 0.8

    return round(min(max(confidence, 0.0), 1.0), 3)


def calc_adaptive_target(
    current_price: float, atr_value: float, daily_volatility: float, direction: str, tech_data: dict = None
) -> float:
    """按品种波动率分档计算目标价。目标至少为ATR×2.5，确保盈亏比≥1.25。"""
    # 波动率分档：高波动率→更大目标空间（更精细的分档）
    if daily_volatility > 0.04:
        base_pct = 0.10  # 极高波动率：10%
    elif daily_volatility > 0.03:
        base_pct = 0.08  # 高波动率：8%
    elif daily_volatility > 0.02:
        base_pct = 0.06  # 中高波动率：6%
    elif daily_volatility > 0.015:
        base_pct = 0.05  # 中波动率：5%
    elif daily_volatility > 0.01:
        base_pct = 0.04  # 中低波动率：4%
    else:
        base_pct = 0.035  # 低波动率：3.5%

    # ADX趋势强度调整：强趋势→更大目标（更平滑的调整）
    adx = (tech_data or {}).get("ADX", 25)
    if adx > 40:
        adx_mult = 1.6  # 极强趋势：目标放大60%
    elif adx > 35:
        adx_mult = 1.4  # 强趋势：目标放大40%
    elif adx > 30:
        adx_mult = 1.2  # 中强趋势：目标放大20%
    elif adx > 25:
        adx_mult = 1.1  # 中等趋势：目标放大10%
    elif adx > 20:
        adx_mult = 1.0  # 弱趋势：标准目标
    elif adx > 15:
        adx_mult = 0.9  # 震荡偏弱：目标缩小10%
    else:
        adx_mult = 0.8  # 震荡市：目标缩小20%

    base_target = current_price * base_pct * adx_mult

    # ATR基准目标：ATR×2.5，确保盈亏比≥1.25（止损=ATR×2）
    # 这是最低目标，确保即使技术位太近也有合理盈亏比
    atr_target = atr_value * 2.5 if atr_value > 0 else 0
    base_target = max(base_target, atr_target)

    # 关键技术位：优先使用有意义的技术位
    tech_targets = []
    if tech_data:
        # 使用更全面的技术位
        for key in ["recent_high", "recent_low", "MA20", "MA60", "MA40"]:
            val = tech_data.get(key)
            if val is None:
                continue
            if direction == "BUY" and val > current_price:
                tech_targets.append(val - current_price)
            elif direction == "SELL" and val < current_price:
                tech_targets.append(current_price - val)

    # 如果有技术位，使用技术位（但不能太近，至少ATR×1.5）
    if tech_targets:
        min_tech_target = min(tech_targets)
        # 技术位不能太近，至少ATR×1.5
        min_allowed = atr_value * 1.5 if atr_value > 0 else base_target * 0.5
        if min_tech_target >= min_allowed:
            target_dist = min_tech_target
        else:
            # 技术位太近，使用ATR目标
            target_dist = base_target
    else:
        target_dist = base_target

    return round(current_price + target_dist if direction == "BUY" else current_price - target_dist, 2)


def normalize_risk_reward(rr: float) -> float:
    """盈亏比标准化到 0-1。"""
    return min(rr / 3.0, 1.0)


def calc_recommend_score(confidence: float, rr: float) -> float:
    """推荐分 = 置信度×0.7 + 盈亏比标准化×0.3。"""
    return round(confidence * 0.70 + normalize_risk_reward(rr) * 0.30, 3)


def generate_trade_plan(
    symbol_data: dict,
    chain_direction: str,
    tech_data: dict = None,
    term_basis: dict = None,
    composite_score: dict = None,
) -> dict:
    """生成交易方案（v2.13 L1-L4四层架构）。

    v2.13 变更：
    - 接收 composite_score 参数（四维度打分结果）
    - 使用composite_score中的direction字段判断方向（不再依赖score正负）
    - 置信度计算使用四维度得分
    - 支持阶梯化阈值（T1/T2/T3）
    """
    price = symbol_data["price"]
    score = symbol_data["score"]
    atr = symbol_data.get("atr", 0)
    daily_vol = symbol_data.get("volatility", 0.02)

    # v2.13: 使用composite_score中的direction判断方向
    if composite_score and isinstance(composite_score, dict) and "direction" in composite_score:
        direction = composite_score["direction"]
    else:
        # 降级到v2.12逻辑（score正负判断）
        if score >= 20:
            direction = "BUY"
        elif score <= -20:
            direction = "SELL"
        else:
            return {
                "pid": symbol_data["pid"],
                "decision": "HOLD",
                "confidence": 0,
                "recommend_score": 0,
                "reason": f"信号强度不足(|得分|={abs(score)}<20)",
            }

    if score < 20:
        return {
            "pid": symbol_data["pid"],
            "decision": "HOLD",
            "confidence": 0,
            "recommend_score": 0,
            "reason": f"信号强度不足(得分={score}<20)",
        }

    confidence = calc_confidence(score, tech_data or {}, chain_direction, term_basis, composite_score)
    if confidence < 0.4:
        return {
            "pid": symbol_data["pid"],
            "decision": "HOLD",
            "confidence": confidence,
            "recommend_score": 0,
            "reason": f"置信度过低({confidence:.1%}<40%)",
        }

    # 止损（动态调整：根据波动率和ADX）
    # 基础止损：ATR×2.0
    base_stop_atr = atr * 2.0 if atr > 0 else 0

    # 波动率调整：高波动率→更宽止损
    if daily_vol > 0.03:
        vol_stop_mult = 1.2  # 高波动率：止损放大20%
    elif daily_vol > 0.02:
        vol_stop_mult = 1.1  # 中高波动率：止损放大10%
    elif daily_vol > 0.015:
        vol_stop_mult = 1.0  # 标准波动率
    else:
        vol_stop_mult = 0.9  # 低波动率：止损缩小10%

    # ADX调整：强趋势→更紧止损
    adx = (tech_data or {}).get("ADX", 25)
    if adx > 35:
        adx_stop_mult = 0.9  # 强趋势：止损缩小10%（更紧）
    elif adx > 25:
        adx_stop_mult = 1.0  # 中等趋势：标准止损
    elif adx > 20:
        adx_stop_mult = 1.1  # 弱趋势：止损放大10%
    else:
        adx_stop_mult = 1.2  # 震荡市：止损放大20%

    # 计算最终止损距离
    stop_distance = base_stop_atr * vol_stop_mult * adx_stop_mult

    # 确保止损距离合理（至少价格的1%，最多5%）
    min_stop = price * 0.01
    max_stop = price * 0.05
    stop_distance = max(min(stop_distance, max_stop), min_stop)

    if direction == "BUY":
        entry = price
        stop_loss = price - stop_distance
    else:
        entry = price
        stop_loss = price + stop_distance

    # 目标价
    target = calc_adaptive_target(price, atr, daily_vol, direction, tech_data)

    # 盈亏比计算（允许目标价基于技术位，不强制等于止损距离）
    reward = abs(target - entry)
    risk = abs(entry - stop_loss)

    # 计算实际盈亏比
    rr = round(reward / risk, 2) if risk > 0 else 0

    # 动态盈亏比阈值：根据置信度和ADX趋势强度调整
    # 基础阈值：根据置信度调整
    if confidence > 0.8:
        base_min_rr = 0.6  # 高置信度：允许较低盈亏比
    elif confidence > 0.7:
        base_min_rr = 0.7  # 较高置信度
    elif confidence > 0.6:
        base_min_rr = 0.8  # 中等置信度
    elif confidence > 0.5:
        base_min_rr = 0.9  # 较低置信度
    else:
        base_min_rr = 1.0  # 低置信度：需要较高盈亏比

    # ADX趋势强度调整：强趋势→允许更低盈亏比
    adx = (tech_data or {}).get("ADX", 25)
    if adx > 35:
        adx_rr_mult = 0.8  # 强趋势：阈值降低20%
    elif adx > 25:
        adx_rr_mult = 0.9  # 中等趋势：阈值降低10%
    elif adx > 20:
        adx_rr_mult = 1.0  # 弱趋势：标准阈值
    else:
        adx_rr_mult = 1.2  # 震荡市：阈值提高20%

    # 波动率调整：高波动率→需要更高盈亏比
    if daily_vol > 0.03:
        vol_rr_mult = 1.2  # 高波动率：阈值提高20%
    elif daily_vol > 0.02:
        vol_rr_mult = 1.1  # 中高波动率：阈值提高10%
    elif daily_vol > 0.015:
        vol_rr_mult = 1.0  # 标准波动率
    else:
        vol_rr_mult = 0.9  # 低波动率：阈值降低10%

    min_rr = base_min_rr * adx_rr_mult * vol_rr_mult

    # 如果盈亏比不足，但置信度足够高，可以接受较低盈亏比
    if rr < min_rr:
        # 检查是否可以通过调整仓位来补偿
        # 如果盈亏比接近阈值（差距<0.2），且置信度高，可以接受
        if rr >= min_rr - 0.2 and confidence > 0.6:
            pass  # 接受较低盈亏比，通过仓位控制风险
        else:
            return {
                "pid": symbol_data["pid"],
                "decision": "HOLD",
                "confidence": confidence,
                "recommend_score": 0,
                "reason": f"盈亏比不足({rr}:1<{min_rr}:1)，置信度{confidence:.1%}不足以补偿",
            }

    recommend_score = calc_recommend_score(confidence, rr)

    # v2.12: 阶梯标记
    composite_total = composite_score.get("total", 0) if isinstance(composite_score, dict) else 0
    if composite_total >= 90:
        tier = "T3"  # 警惕过热
    elif composite_total >= 75:
        tier = "T2"  # 主仓
    elif composite_total >= 60:
        tier = "T1"  # 观察
    else:
        tier = "T0"  # 弱信号

    # 仓位计算：基于置信度、盈亏比、波动率、ADX趋势强度四维调整
    # v2.12: 阶梯化仓位
    base = 5.0
    if tier == "T3":
        base = 3.0  # 过热信号，减仓
    elif tier == "T1":
        base = 3.0  # 观察信号，轻仓

    # 置信度调整：高置信度→更大仓位（更精细的分档）
    if confidence > 0.85:
        pos_mult = 1.5  # 极高置信度：+50%
    elif confidence > 0.8:
        pos_mult = 1.4  # 高置信度：+40%
    elif confidence > 0.7:
        pos_mult = 1.2  # 较高置信度：+20%
    elif confidence > 0.6:
        pos_mult = 1.0  # 标准置信度
    elif confidence > 0.5:
        pos_mult = 0.9  # 较低置信度：-10%
    elif confidence > 0.4:
        pos_mult = 0.8  # 低置信度：-20%
    else:
        pos_mult = 0.6  # 极低置信度：-40%

    # 盈亏比调整：高盈亏比→更大仓位（更精细的分档）
    if rr >= 2.5:
        rr_mult = 1.4  # 极高盈亏比：+40%
    elif rr >= 2.0:
        rr_mult = 1.3  # 高盈亏比：+30%
    elif rr >= 1.5:
        rr_mult = 1.1  # 较高盈亏比：+10%
    elif rr >= 1.2:
        rr_mult = 1.0  # 标准盈亏比
    elif rr >= 1.0:
        rr_mult = 0.9  # 较低盈亏比：-10%
    elif rr >= 0.8:
        rr_mult = 0.8  # 低盈亏比：-20%
    else:
        rr_mult = 0.7  # 极低盈亏比：-30%

    # 波动率调整：高波动率→更小仓位（更精细的分档）
    if daily_vol > 0.04:
        vol_mult = 0.5  # 极高波动率：-50%
    elif daily_vol > 0.03:
        vol_mult = 0.6  # 高波动率：-40%
    elif daily_vol > 0.02:
        vol_mult = 0.8  # 中等波动率：-20%
    elif daily_vol > 0.015:
        vol_mult = 1.0  # 标准波动率
    elif daily_vol > 0.01:
        vol_mult = 1.1  # 中低波动率：+10%
    else:
        vol_mult = 1.2  # 低波动率：+20%

    # ADX趋势强度调整：强趋势→更大仓位（新增维度）
    adx = (tech_data or {}).get("ADX", 25)
    if adx > 40:
        adx_mult = 1.3  # 极强趋势：+30%
    elif adx > 35:
        adx_mult = 1.2  # 强趋势：+20%
    elif adx > 30:
        adx_mult = 1.1  # 中强趋势：+10%
    elif adx > 25:
        adx_mult = 1.0  # 中等趋势：标准
    elif adx > 20:
        adx_mult = 0.9  # 弱趋势：-10%
    elif adx > 15:
        adx_mult = 0.8  # 震荡偏弱：-20%
    else:
        adx_mult = 0.7  # 震荡市：-30%

    pos = round(min(max(base * pos_mult * rr_mult * vol_mult * adx_mult, 2.0), 10.0), 1)

    return {
        "pid": symbol_data["pid"],
        "decision": direction,
        "entry_price": round(entry, 2),
        "target_price": target,
        "stop_loss": round(stop_loss, 2),
        "risk_reward_ratio": rr,
        "confidence": confidence,
        "recommend_score": recommend_score,
        "position_size": f"{pos}%",
        "validity": "1-3日",
        "tier": tier,  # v2.12: T1/T2/T3阶梯
        "composite_total": composite_total,
        # v2.11 移动止损 + 阶段止盈
        "trailing_stop": calc_trailing_stop(price, atr, direction, tech_data or {}),
        "stage_exits": calc_stage_exits(price, atr, direction, tech_data or {}),
    }


def calc_trailing_stop(price: float, atr: float, direction: str, tech: dict) -> dict:
    """计算ATR移动止损策略（v2.11）。

    初始止损：入场价 ± 1.5倍ATR
    主升期移动止损：DC20下轨（多头）/ DC20上轨（空头）
    """
    atr_mult = 1.5  # 初始止损ATR倍数

    if atr <= 0:
        atr = price * 0.02  # 默认2%

    initial_stop = price - atr * atr_mult if direction == "BUY" else price + atr * atr_mult

    # 移动止损参考：DC20下轨（多头）/ DC20上轨（空头）
    dc_upper = tech.get("DC_UPPER")
    dc_lower = tech.get("DC_LOWER")
    trailing_ref = None
    if direction == "BUY" and dc_lower:
        trailing_ref = dc_lower
    elif direction == "SELL" and dc_upper:
        trailing_ref = dc_upper

    return {
        "initial_stop": round(initial_stop, 2),
        "trailing_ref": round(trailing_ref, 2) if trailing_ref else None,
        "trailing_type": "DC20轨道" if trailing_ref else "ATR固定",
        "atr_mult": atr_mult,
    }


def calc_stage_exits(price: float, atr: float, direction: str, tech: dict) -> dict:
    """计算阶段止盈策略（v2.11）。

    第一阶段（减仓30%）：RSI>85出现顶背离 / RSI<15出现底背离
    第二阶段（减仓50%）：价格跌破DC20上轨（多头）/ 突破DC20下轨（空头）
    清仓：价格跌破DC55中轨 / Boll中轨
    """
    if atr <= 0:
        atr = price * 0.02

    bb_middle = tech.get("BB_MIDDLE")
    dc_mid = tech.get("DC_MID")
    dc55_mid = tech.get("DC55_MID")

    # 阶段1止盈参考：RSI极端
    stage1_trigger = "RSI>85顶背离" if direction == "BUY" else "RSI<15底背离"
    stage1_action = "减仓30%"

    # 阶段2止盈参考：跌破DC20上轨
    dc_upper = tech.get("DC_UPPER")
    dc_lower = tech.get("DC_LOWER")
    if direction == "BUY" and dc_upper:
        stage2_level = dc_upper
        stage2_trigger = f"跌破DC20上轨({dc_upper:.2f})"
    elif direction == "SELL" and dc_lower:
        stage2_level = dc_lower
        stage2_trigger = f"突破DC20下轨({dc_lower:.2f})"
    else:
        stage2_level = None
        stage2_trigger = "DC20轨道"

    # 清仓参考：跌破DC55中轨或Boll中轨
    clear_level = dc55_mid or bb_middle
    clear_trigger = "跌破DC55中轨" if dc55_mid else "跌破Boll中轨"

    return {
        "stage1": {
            "trigger": stage1_trigger,
            "action": stage1_action,
        },
        "stage2": {
            "trigger": stage2_trigger,
            "level": round(stage2_level, 2) if stage2_level else None,
            "action": "减仓50%",
        },
        "clear": {
            "trigger": clear_trigger,
            "level": round(clear_level, 2) if clear_level else None,
            "action": "清仓",
        },
    }


def rank_all_candidates(all_plans: list) -> dict:
    """按推荐分排序，输出 Top 5 多头/空头。"""
    actionable = [p for p in all_plans if p["decision"] != "HOLD"]
    bullish = sorted(
        [p for p in actionable if p["decision"] == "BUY"], key=lambda x: x["recommend_score"], reverse=True
    )[:5]
    bearish = sorted(
        [p for p in actionable if p["decision"] == "SELL"], key=lambda x: x["recommend_score"], reverse=True
    )[:5]
    return {"bullish_top5": bullish, "bearish_top5": bearish}
