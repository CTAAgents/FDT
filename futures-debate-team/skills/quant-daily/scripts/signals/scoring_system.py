# -*- coding: utf-8 -*-
"""100分制多维打分系统 v2.17a — L1-L4四层架构（权重重分配 40/30/20/10）

v2.17a 权重重分配 (40/30/20/10)：L2 25→30 量价提权, L3 25→20 结构降权。内部子信号等比例缩放。

v2.17 权重重分配 (40/25/25/10)：L1(55->40)降噪, L2(15->25)量价提权+Vortex7/CCI5/Sup7/HMA6, L3(15->25)RSI9/DMI8/前高前低8, L4(15->10)通道4/均线3/MACD1/DC55 2
三层早期信号 + 一层确认，解决"推荐已走远品种"问题：

- L1 萌芽/资金结构维度（40分, v2.17: 权重重调)：v2.12因子+期货专属信号
  v2.12保留：MA斜率(5分)、ROC零轴(5分)、接近通道上轨(5分)、量能先兆(5分)、Higher Low(5分)
  v2.13新增：OI三角(5分)、基差走强(3分)、期限结构(3分)、跨期Spread(3分)、%b过0.5(4分)、ATR百分位(3分)、OBV/CMF(6分)、量价背离(3分)
- L2 量价领先维度（30分, v2.17a）：Vortex(7→按比例缩至30分总分)、CCI(5→缩放)、Supertrend(7→缩放)、HMA(6→缩放)
- L3 价格结构维度（20分, v2.17a）：RSI健康区(9→缩放至20分总分)、DMI方向(8→缩放)、前高突破(8→缩放)
- L4 确认维度（10分, v2.17）：通道突破(4分)、均线排列(3分)、MACD(1分)、DC55共振(2分)
- 否决维度（-20分）：ADX<15震荡、RSI极端、极度偏离、严重缩量、OI背离、结构切换预警

v2.13 变更（从v2.12升级，v2.12全部因子保留）：
- L1扩展：新增OI三角、基差、期限结构、Spread、%b、ATR百分位、OBV/CMF；v2.12因子分值不变
- 新增L2量价领先维度：Vortex、CCI、Supertrend、HMA、KAMA
- L3不变：RSI+DMI+前高突破（与v2.12结构维度完全一致）
- L4确认从35分降到15分
- 否决维度新增：OI背离、结构切换预警
"""

from typing import Dict, Optional
import math
from indicators.core import assess_trend_maturity

# ============================================================
# L1-L4 权重（模块级变量，支持外部读取/覆写）
# ============================================================
# 网格搜索最优 (2026-07-03): L1=35, L2=35, L3=20, L4=10
WL1 = 35  # L1 萌芽/资金结构
WL2 = 35  # L2 量价领先（+40% WATCH信号提升）
WL3 = 20  # L3 价格结构
WL4 = 10  # L4 确认
# 各层内部满分（已与层权重 WLx 对齐，缩放为恒等变换）
L1_INTERNAL_MAX = 35
L2_INTERNAL_MAX = 35
L3_INTERNAL_MAX = 20
L4_INTERNAL_MAX = 10

# ============================================================
# L1 萌芽/资金结构维度（40分, v2.17: clamp 40）— 最早信号层
# ============================================================

def score_L1_germination(tech: dict, sym: dict, is_bull: bool,
                         kline_closes: list = None,
                         term_basis: dict = None) -> dict:
    """L1 萌芽/资金结构维度打分（v2.17: 三级分层, 内部满分50→缩放至30）。

    Core(27): OI(7) + HL(7) + OBV/CMF(7) + 量能先兆(6)
    Standard(14): MA斜率(4) + ROC(4) + 期限结构(3) + %b(3)
    Auxiliary(9): 基差(2) + Spread(2) + 接近通道(3) + ATR%(2)
    Penalty: OI背离(-3) + 量价背离(-2)

    v2.12全部因子保留 + v2.13新增期货专属信号：

    v2.12保留（26分）：
    - [5分] MA斜率由负转平/微翘
    - [5分] ROC(10)零轴刚上/刚下
    - [5分] 价格接近通道上轨但未突破
    - [5分] 均量倍量+价格未爆（量能先兆）
    - [6分] Higher Low / Lower High形成

    v2.13新增（29分）：
    - [5分] OI建仓胚 + OI确认胚（期货专属）
    - [3分] 基差走强/走弱（期货专属）
    - [3分] 期限结构方向（期货专属）
    - [3分] 跨期Spread加速（期货专属）
    - [4分] %b刚过0.5/刚下0.5
    - [3分] ATR百分位刚脱20
    - [6分] OBV领先价 / CMF脱零（量在价先）
    """
    score = 0
    reasons = []
    last_price = sym.get('last_price')

    # --- [7分] OI信号 (v2.17: 5→7, Core tier) ---
    oi_rate = tech.get('OI_RATE')  # OI / MA(OI, 20)
    oi_increasing = tech.get('OI_INCREASING', False)
    oi_change_pct = tech.get('OI_CHANGE_PCT', 0)
    price_change_5d = tech.get('PRICE_CHANGE_5D', 0)

    if oi_rate is not None:
        if is_bull:
            # OI建仓胚：价横±1.5% + OI/MA20_OI > 1.1
            if oi_rate > 1.1 and abs(price_change_5d) < 3.0:
                score += 4
                reasons.append(f'OI建仓胚(率={oi_rate:.2f},价横)(+3)')
            # OI确认胚：价涨 + OI↑
            elif oi_rate > 1.05 and price_change_5d > 0.5:
                score += 2
                reasons.append(f'OI确认胚(率={oi_rate:.2f},价涨{price_change_5d:.1f}%)(+2)')
            # OI背离：价涨 + OI↓ → 假突破
            elif oi_rate < 0.9 and price_change_5d > 1:
                score -= 3
                reasons.append(f'OI背离(价涨OI降,率={oi_rate:.2f})(-3)')
        else:
            if oi_rate > 1.1 and abs(price_change_5d) < 3.0:
                score += 4
                reasons.append(f'OI建仓胚(率={oi_rate:.2f},价横)(+3)')
            elif oi_rate > 1.05 and price_change_5d < -0.5:
                score += 2
                reasons.append(f'OI确认胚(率={oi_rate:.2f},价跌{price_change_5d:.1f}%)(+2)')
            elif oi_rate < 0.9 and price_change_5d < -1:
                score -= 3
                reasons.append(f'OI背离(价跌OI降,率={oi_rate:.2f})(-3)')

    # --- [2分] 基差走强/走弱 (v2.17: 4→2, Auxiliary tier) ---
    if term_basis and isinstance(term_basis, dict):
        basis_ma5 = term_basis.get('basis_ma5')
        basis_ma20 = term_basis.get('basis_ma20')
        basis_rate = term_basis.get('basis_rate')  # 基差率

        if basis_ma5 is not None and basis_ma20 is not None:
            if is_bull:
                if basis_ma5 > basis_ma20:
                    score += 2
                    reasons.append(f'基差走强(MA5>{basis_ma5:.0f}>MA20{basis_ma20:.0f})(+2)')
                elif basis_ma5 < basis_ma20 * 0.95:
                    score -= 2
                    reasons.append(f'基差走弱(-2)')
            else:
                if basis_ma5 < basis_ma20:
                    score += 2
                    reasons.append(f'基差走弱(利空)(+2)')

        # --- [3分] 期限结构方向 (v2.17: 4→3, Standard tier：Contango对空头是展期成本不应加分) ---
        term_structure = term_basis.get('term_structure')  # 'back' / 'contango' / 'flat'
        if term_structure:
            if is_bull and term_structure == 'back':
                score += 3
                reasons.append(f'期限Back(现货紧+展期收贴水,偏多)(+3)')
            elif not is_bull and term_structure == 'back':
                # v2.17 修正: Back结构空头展期收贴水=收益，应加分
                score += 3
                reasons.append(f'期限Back(空头展期收贴水,有利)(+3)')
            elif is_bull and term_structure == 'contango':
                score -= 1
                reasons.append(f'期限Contango(现货松+展期付升水,与多头矛盾)(-1)')
            elif not is_bull and term_structure == 'contango':
                # v2.17 修正: Contango空头展期需付升水=成本，不应加分
                score -= 1
                reasons.append(f'期限Contango(空头展期付升水,成本)(-1)')

        # --- [2分] 跨期Spread加速 (v2.17: 3→2, Auxiliary tier) ---
        spread_slope = term_basis.get('spread_slope_5d')  # 5日价差斜率
        if spread_slope is not None:
            if abs(spread_slope) > 0.5:
                score += 2
                reasons.append(f'Spread加速(斜率={spread_slope:.2f})(+2)')
            elif abs(spread_slope) > 0.2:
                score += 2
                reasons.append(f'Spread温和加速({spread_slope:.2f})(+2)')

    # --- [4分] ROC(10)零轴 (v2.17: 5→4, Standard tier) ---
    roc10 = tech.get('ROC10')
    if roc10 is not None:
        if is_bull:
            if 0 < roc10 <= 3:
                score += 4
                reasons.append(f'ROC10刚转正({roc10:.1f}%)(+4)')
            elif 3 < roc10 <= 8:
                score += 2
                reasons.append(f'ROC10初期({roc10:.1f}%)(+2)')
        else:
            if -3 <= roc10 < 0:
                score += 4
                reasons.append(f'ROC10刚转负({roc10:.1f}%)(+4)')
            elif -8 <= roc10 < -3:
                score += 2
                reasons.append(f'ROC10初期下跌({roc10:.1f}%)(+2)')

    # --- [3分] %b中线 (v2.17: 4→3, Standard tier) ---
    bb_pctb = tech.get('BB_PCTB')
    if bb_pctb is not None:
        if is_bull:
            if 0.45 <= bb_pctb <= 0.65:
                score += 3
                reasons.append(f'%b刚过中线({bb_pctb:.2f})(+3)')
            elif 0.65 < bb_pctb <= 0.90:
                score += 2
                reasons.append(f'%b偏强({bb_pctb:.2f})(+2)')
        else:
            if 0.35 <= bb_pctb <= 0.55:
                score += 3
                reasons.append(f'%b刚下中线({bb_pctb:.2f})(+3)')
            elif 0.15 <= bb_pctb < 0.35:
                score += 2
                reasons.append(f'%b偏弱({bb_pctb:.2f})(+2)')

    # --- [2分] ATR百分位 (v2.17: 3→2, Auxiliary tier) ---
    atr_pct = tech.get('ATR_PERCENTILE')
    atr_ratio = tech.get('ATR_RATIO_20')
    if atr_pct is not None:
        if 15 <= atr_pct <= 35:
            score += 2
            reasons.append(f'ATR百分位脱低位({atr_pct:.0f}%)(+2)')
        elif atr_pct < 15:
            score += 1
            reasons.append(f'ATR极度压缩({atr_pct:.0f}%)(+1,观察)')

    # --- [4分] MA斜率 (v2.17: 5→4, Standard tier) ---
    ma_slope = tech.get('MA20_SLOPE')
    if ma_slope is not None:
        if is_bull:
            if -0.5 <= ma_slope <= 0.5:
                score += 4
                reasons.append(f'MA20斜率转平({ma_slope:.2f})(+4)')
            elif 0.5 < ma_slope <= 2.0:
                score += 4
                reasons.append(f'MA20斜率微翘({ma_slope:.2f})(+4)')
            elif ma_slope > 2.0:
                score += 1
                reasons.append(f'MA20斜率已陡({ma_slope:.2f})(+1)')
        else:
            if -0.5 <= ma_slope <= 0.5:
                score += 4
                reasons.append(f'MA20斜率转平({ma_slope:.2f})(+4)')
            elif -2.0 <= ma_slope < -0.5:
                score += 4
                reasons.append(f'MA20斜率微降({ma_slope:.2f})(+4)')
            elif ma_slope < -2.0:
                score += 1
                reasons.append(f'MA20斜率已陡降({ma_slope:.2f})(+1)')

    # --- [7分] Higher Low / Lower High (v2.17: 6→7, Core tier) ---
    higher_low = tech.get('HIGHER_LOW')
    lower_high = tech.get('LOWER_HIGH')
    if is_bull and higher_low:
        score += 6
        reasons.append('Higher Low形成(道氏结构)(+7)')
    elif not is_bull and lower_high:
        score += 6
        reasons.append('Lower High形成(道氏结构)(+7)')
    elif kline_closes and len(kline_closes) >= 20:
        try:
            mid = len(kline_closes) // 2
            if is_bull:
                low1 = min(kline_closes[:mid])
                low2 = min(kline_closes[mid:])
                if low2 > low1 * 1.003:
                    score += 6
                    reasons.append(f'Higher Low({low1:.2f}→{low2:.2f})(+7)')
            else:
                high1 = max(kline_closes[:mid])
                high2 = max(kline_closes[mid:])
                if high2 < high1 * 0.997:
                    score += 6
                    reasons.append(f'Lower High({high1:.2f}→{high2:.2f})(+7)')
        except Exception:
            pass

    # --- [7分] OBV/CMF (v2.17: 6→7, Core tier) ---
    obv = tech.get('OBV')
    obv_ma20 = tech.get('OBV_MA20')
    cmf21 = tech.get('CMF21')

    if obv is not None and obv_ma20 is not None:
        if is_bull and obv > obv_ma20 * 1.05:
            score += 3
            reasons.append(f'OBV领先价(OBV>MA20)(+3)')
        elif not is_bull and obv < obv_ma20 * 0.95:
            score += 3
            reasons.append(f'OBV领先价(OBV<MA20)(+3)')

    if cmf21 is not None:
        if is_bull and cmf21 > 0.05:
            score += 3
            reasons.append(f'CMF脱零({cmf21:.2f})(+3)')
        elif not is_bull and cmf21 < -0.05:
            score += 3
            reasons.append(f'CMF脱零({cmf21:.2f})(+3)')

    # --- [3分] 接近通道 (v2.17: 5→3, Auxiliary tier) ---
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    if last_price and dc_upper and dc_lower and (dc_upper - dc_lower) > 0:
        if is_bull:
            dist = (dc_upper - last_price) / (dc_upper - dc_lower)
            if 0 <= dist <= 0.1:
                score += 3
                reasons.append(f'接近DC20上轨(距离{dist:.1%})(+3)')
            elif 0.1 < dist <= 0.2:
                score += 2
                reasons.append(f'较近DC20上轨(距离{dist:.1%})(+2)')
        else:
            dist = (last_price - dc_lower) / (dc_upper - dc_lower)
            if 0 <= dist <= 0.1:
                score += 3
                reasons.append(f'接近DC20下轨(距离{dist:.1%})(+3)')
            elif 0.1 < dist <= 0.2:
                score += 2
                reasons.append(f'较近DC20下轨(距离{dist:.1%})(+2)')

    # --- [6分] 量能先兆 (v2.17: 5→6, Core tier) ---
    vol_price_div = tech.get('VOL_PRICE_DIVERGENCE', False)
    vol_5d_ratio = tech.get('VOL_5D_RATIO')
    if vol_price_div and vol_5d_ratio:
        score += 6
        reasons.append(f'量能先兆(量比{vol_5d_ratio:.1f}x,价未动)(+6)')
    elif vol_5d_ratio and vol_5d_ratio >= 1.2 and abs(price_change_5d) < 3:
        score += 3
        reasons.append(f'温和放量(量比{vol_5d_ratio:.1f}x)(+3)')

    return {'score': max(0, min(40, score)), 'reasons': reasons}  # v2.17: 50→40


# ============================================================
# L2 量价领先维度（25分, v2.17）— 次早信号层
# ============================================================

def score_L2_volume_price(tech: dict, sym: dict, is_bull: bool) -> dict:
    """L2 量价领先维度打分（v2.17: 满分25分，内部直接25分无需缩放）。

    - [7分] Vortex VI+/VI- 叉（比MACD早2-5根K）
    - [5分] CCI破±100（商品老派但灵，比通道突破早3-8根K）
    - [7分] Supertrend翻色（比唐奇安早2-4根K）
    - [6分] HMA交叉（比EMA快30-40%）
    """
    score = 0
    reasons = []
    last_price = sym.get('last_price')

    # --- [4分] Vortex VI+/VI- 叉 ---
    vi_plus = tech.get('VI_PLUS')
    vi_minus = tech.get('VI_MINUS')
    if vi_plus is not None and vi_minus is not None:
        if is_bull and vi_plus > vi_minus:
            score += 7
            reasons.append(f'Vortex多头(VI+={vi_plus:.3f}>VI-={vi_minus:.3f})(+7)')
        elif not is_bull and vi_minus > vi_plus:
            score += 7
            reasons.append(f'Vortex空头(VI-={vi_minus:.3f}>VI+={vi_plus:.3f})(+7)')

    # --- [3分] CCI破±100 ---
    cci = tech.get('CCI20')
    if cci is not None:
        if is_bull and 100 <= cci <= 200:
            score += 5
            reasons.append(f'CCI破+100({cci:.0f})(+5)')
        elif is_bull and cci > 200:
            score += 2
            reasons.append(f'CCI极度超买({cci:.0f})(+2)')
        elif not is_bull and -200 <= cci <= -100:
            score += 5
            reasons.append(f'CCI破-100({cci:.0f})(+5)')
        elif not is_bull and cci < -200:
            score += 2
            reasons.append(f'CCI极度超卖({cci:.0f})(+2)')

    # --- [4分] Supertrend翻色 ---
    st_dir = tech.get('SUPERTREND_DIR')
    st_flipped = tech.get('SUPERTREND_JUST_FLIPPED', False)
    if st_dir is not None:
        if is_bull and st_dir == 1:
            score += 7
            reasons.append(f'Supertrend多头(+7)')
        elif not is_bull and st_dir == -1:
            score += 7
            reasons.append(f'Supertrend空头(+7)')

    # --- [4分] HMA交叉 (v2.17: 3->4) ---
    hma_cross = tech.get('HMA_CROSS')
    hma_just = tech.get('HMA_JUST_CROSSED')
    if hma_cross:
        if is_bull and hma_cross == 'bull':
            score += 6
            reasons.append(f'HMA多头交叉(+6)')
        elif not is_bull and hma_cross == 'bear':
            score += 6
            reasons.append(f'HMA空头交叉(+6)')


    return {'score': max(0, min(25, score)), 'reasons': reasons}


# ============================================================
# L3 价格结构维度（25分, v2.17）— 价格结构
# ============================================================

def score_L3_structure(tech: dict, is_bull: bool) -> dict:
    """L3 价格结构维度打分（目标满分25分，内部满分25分，由 calculate_composite_score 缩放至25分）。

    v2.17 修正：移除RSI极端反转加分（与趋势跟踪定位冲突），重新分配权重。
    - [14分] RSI健康区间（趋势有空间）
    - [6分] DMI方向确认
    - [5分] 前高/前低突破
    """
    score = 0
    reasons = []

    rsi = tech.get('RSI14')
    pdi = tech.get('DMI_PDI')
    mdi = tech.get('DMI_MDI')
    new_high_60 = tech.get('NEW_HIGH_60', False)

    # [9分] RSI健康区间 (v2.17: 14→9)
    if rsi is not None:
        if is_bull:
            if 40 <= rsi <= 65:
                score += 9
                reasons.append(f'RSI={rsi:.0f}健康区(+9)')
            elif 65 < rsi <= 75:
                score += 5
                reasons.append(f'RSI={rsi:.0f}偏强(+5)')
            elif 30 <= rsi < 40:
                score += 5
                reasons.append(f'RSI={rsi:.0f}偏弱(+5)')
        else:
            if 35 <= rsi <= 60:
                score += 9
                reasons.append(f'RSI={rsi:.0f}健康区(+9)')
            elif 25 <= rsi < 35:
                score += 5
                reasons.append(f'RSI={rsi:.0f}偏弱(+5)')
            elif 60 < rsi <= 70:
                score += 5
                reasons.append(f'RSI={rsi:.0f}偏强(+5)')

    # [8分] DMI方向 (v2.17: 6→8)
    if pdi is not None and mdi is not None:
        if (is_bull and pdi > mdi) or (not is_bull and mdi > pdi):
            score += 8
            reasons.append(f'DMI方向确认(+8)')

    # [8分] 前高/前低突破 (v2.17: 5→8, 空头侧补全)
    new_low_60 = tech.get('NEW_LOW_60', False)
    if is_bull and new_high_60:
        score += 8
        reasons.append(f'突破60日新高(+8)')
    elif not is_bull and new_low_60:
        score += 8
        reasons.append(f'跌破60日新低(+8)')

    return {'score': max(0, min(25, score)), 'reasons': reasons}


# ============================================================
# L4 确认维度（10分, v2.17）— 降权到确认信号最低权重
# ============================================================

def score_L4_confirmation(tech: dict, sym: dict, is_bull: bool,
                           days_since_breakout: int = 0) -> dict:
    """L4 确认维度打分（v2.17: 满分10分，含时间衰减）。

    - [4分] 通道突破（带时间衰减）
    - [3分] 均线排列（带时间衰减）
    - [1分] MACD确认
    - [2分] DC55共振
    """
    score = 0
    reasons = []
    last_price = sym.get('last_price')

    decay = _calc_time_decay(days_since_breakout)

    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc55_trend = tech.get('DC55_TREND')

    if not last_price or not dc_upper or not dc_lower:
        return {'score': 0, 'reasons': ['通道数据不足'], 'decay': decay}

    # --- [6分] 通道突破（带衰减）---
    breakout_score = 0
    if is_bull:
        if last_price > dc_upper:
            breakout_score = 4
            reasons.append(f'突破DC20上轨(+3×{decay:.0%})')
        elif last_price > dc_upper * 0.99:
            breakout_score = 2
            reasons.append(f'接近DC20上轨(+2)')
    else:
        if last_price < dc_lower:
            breakout_score = 4
            reasons.append(f'跌破DC20下轨(+3×{decay:.0%})')
        elif last_price < dc_lower * 1.01:
            breakout_score = 2
            reasons.append(f'接近DC20下轨(+2)')

    if breakout_score == 4:
        breakout_score = int(breakout_score * decay)
    score += breakout_score

    # --- [4分] 均线排列（带衰减）---
    ma5 = tech.get('MA5')
    ma10 = tech.get('MA10')
    ma20 = tech.get('MA20')

    ma_score = 0
    if last_price and ma20:
        if is_bull:
            if ma5 and ma10 and ma5 > ma10 > ma20 and last_price > ma20:
                ma_score = 3
                reasons.append(f'均线多头排列(+3×{decay:.0%})')
            elif last_price > ma20:
                ma_score = 1
                reasons.append(f'价格>MA20(+1)')
        else:
            if ma5 and ma10 and ma5 < ma10 < ma20 and last_price < ma20:
                ma_score = 3
                reasons.append(f'均线空头排列(+3×{decay:.0%})')
            elif last_price < ma20:
                ma_score = 1
                reasons.append(f'价格<MA20(+1)')

    if ma_score == 3:
        ma_score = int(ma_score * decay)
    score += ma_score

    # --- [2分] MACD确认 ---
    macd_dif = tech.get('MACD_DIF')
    macd_dea = tech.get('MACD_DEA')
    if macd_dif is not None:
        if is_bull:
            if macd_dif > 0 and (macd_dea is None or macd_dif > macd_dea):
                score += 1
                reasons.append(f'MACD多头(+1)')
            elif macd_dif > 0:
                score += 1
                reasons.append(f'MACD零轴上(+1)')
        else:
            if macd_dif < 0 and (macd_dea is None or macd_dif < macd_dea):
                score += 1
                reasons.append(f'MACD空头(+1)')
            elif macd_dif < 0:
                score += 1
                reasons.append(f'MACD零轴下(+1)')

    # --- [3分] 通道共振 ---
    if dc55_trend:
        if (is_bull and dc55_trend == 'up') or (not is_bull and dc55_trend == 'down'):
            score += 2
            reasons.append(f'DC55同步扩张(+2)')

    return {'score': max(0, min(10, score)), 'reasons': reasons, 'decay': decay}


# ============================================================
# 否决维度（-20分）— 一票否决
# ============================================================

def score_veto_dimension(tech: dict, sym: dict, is_bull: bool,
                         term_basis: dict = None) -> dict:
    """否决维度打分（v2.17: ADX分层+CCI极值+移除OI重复, 最多-20）。

    - [-6] ADX<15+Squeeze  - [-3] ADX<15无Squeeze
    - [-6] RSI极端(>80/<20)  - [-5] CCI极端(>200/<-200)
    - [-4] 价格偏离MA20>15%  - [-4] 严重缩量  - [-4] 结构切换预警
    """
    score = 0
    reasons = []

    adx = tech.get('ADX')
    bb_squeeze = tech.get('BB_SQUEEZE', False)
    rsi = tech.get('RSI14')
    last_price = sym.get('last_price')
    ma20 = tech.get('MA20')
    vol_ratio = tech.get('VOL_RATIO')
    oi_rate = tech.get('OI_RATE')

    # ADX分层 (v2.17)
    if adx is not None and adx < 15:
        if bb_squeeze:
            score -= 6
            reasons.append(f'ADX={adx:.0f}+Squeeze纯震荡(-6)')
        else:
            score -= 3
            reasons.append(f'ADX={adx:.0f}趋势力度不足(-3)')

    # [-6分] RSI极端
    if rsi is not None:
        if is_bull and rsi > 80:
            score -= 6
            reasons.append(f'RSI={rsi:.0f}严重超买(-6)')
        elif not is_bull and rsi < 20:
            score -= 6
            reasons.append(f'RSI={rsi:.0f}严重超卖(-6)')

    # [-5分] CCI极端 (v2.17新增)
    cci = tech.get('CCI20')
    if cci is not None:
        if is_bull and cci > 200:
            score -= 5
            reasons.append(f'CCI={cci:.0f}极端超买(-5)')
        elif not is_bull and cci < -200:
            score -= 5
            reasons.append(f'CCI={cci:.0f}极端超卖(-5)')

    # [-4分] 价格极度偏离MA20
    if last_price and ma20 and ma20 > 0:
        deviation = abs((last_price - ma20) / ma20 * 100)
        if deviation > 15:
            score -= 4
            reasons.append(f'偏离MA20={deviation:.1f}%>15%(-4)')
        elif deviation > 10:
            score -= 2
            reasons.append(f'偏离MA20={deviation:.1f}%>10%(-2)')

    # [-2分] 严重缩量
    if vol_ratio is not None and vol_ratio < 0.5:
        score -= 4
        reasons.append(f'严重缩量({vol_ratio:.1f}x)(-4)')



    # [-2分] 结构切换预警（期货专属）
    if term_basis and isinstance(term_basis, dict):
        structure_alert = term_basis.get('structure_alert')  # 'super_back_to_flat' / 'super_contango_to_flat'
        if structure_alert:
            score -= 4
            reasons.append(f'结构切换预警({structure_alert})(-4)')

    return {'score': max(-20, min(0, score)), 'reasons': reasons}


# ============================================================
# 时间衰减函数
# ============================================================

def _calc_time_decay(days: int) -> float:
    """计算信号新鲜度衰减系数。"""
    if days <= 0:
        return 1.0
    elif days <= 3:
        return 1.0 - days * 0.033
    elif days <= 7:
        return 0.9 - (days - 3) * 0.05
    elif days <= 14:
        return 0.7 - (days - 7) * 0.029
    elif days <= 20:
        return 0.5 - (days - 14) * 0.033
    else:
        return 0.3


def estimate_days_since_breakout(tech: dict, is_bull: bool) -> int:
    """估算突破后的天数。"""
    dc_pos = tech.get('DC_POS')
    deviation = tech.get('PRICE_DEVIATION_PCT', 0)
    last_price = tech.get('last_price')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')

    is_breakout = False
    if last_price and dc_upper and dc_lower:
        if is_bull and last_price > dc_upper:
            is_breakout = True
        elif not is_bull and last_price < dc_lower:
            is_breakout = True

    if not is_breakout:
        return 0

    if abs(deviation) > 12:
        return 18
    elif abs(deviation) > 8:
        return 12
    elif abs(deviation) > 5:
        return 7
    elif abs(deviation) > 3:
        return 4
    elif abs(deviation) > 1:
        return 2
    return 1


# ============================================================
# 综合打分（v2.13 L1-L4四层架构）
# ============================================================

def _determine_direction(tech: dict, sym: dict, score_direction: int = 0) -> bool:
    """基于技术指标综合判断方向（v2.13改进，含硬约束）。

    硬约束（一票否决）：
    1. 价格低于MA20超过2% → 强制空头
    2. MA空头排列（MA5<MA10<MA20）→ 强制空头
    3. Supertrend空头 + 价格低于MA20 → 强制空头

    软约束（投票）：
    - MACD方向（权重2）
    - RSI位置（权重1）
    - DMI方向（权重2）
    - Vortex方向（权重1）
    - ROC方向（权重1）

    返回：True=多头, False=空头
    """
    ma5 = tech.get('MA5')
    ma10 = tech.get('MA10')
    ma20 = tech.get('MA20')
    last_price = sym.get('last_price')
    macd_dif = tech.get('MACD_DIF')
    rsi = tech.get('RSI14')
    pdi = tech.get('DMI_PDI')
    mdi = tech.get('DMI_MDI')
    vi_plus = tech.get('VI_PLUS')
    vi_minus = tech.get('VI_MINUS')
    st_dir = tech.get('SUPERTREND_DIR')
    roc10 = tech.get('ROC10')

    # ===== 硬约束（一票否决）=====

    # 硬约束1: 价格低于MA20超过2% → 强制空头
    if last_price and ma20 and ma20 > 0:
        price_below_ma20_pct = (ma20 - last_price) / ma20
        if price_below_ma20_pct > 0.02:  # 价格低于MA20超过2%
            return False

    # 硬约束2: MA空头排列（MA5<MA10<MA20）→ 强制空头
    if ma5 and ma10 and ma20:
        if ma5 < ma10 < ma20:
            return False

    # 硬约束3: Supertrend空头 + 价格低于MA20 → 强制空头
    if st_dir == -1 and last_price and ma20 and last_price < ma20:
        return False

    # 硬约束4: MACD空头 + DMI空头 + ROC空头 + 价格低于BB中轨 → 强制空头（四个指标共振）
    bb_middle = tech.get('BB_MIDDLE')
    if (macd_dif is not None and macd_dif < 0 and 
        pdi is not None and mdi is not None and pdi < mdi and 
        roc10 is not None and roc10 < 0 and
        bb_middle and last_price and last_price < bb_middle):
        return False

    # ===== 软约束（投票）=====

    votes_bull = 0
    votes_bear = 0

    # MACD方向（权重2）
    if macd_dif is not None:
        if macd_dif > 0:
            votes_bull += 2
        else:
            votes_bear += 2

    # RSI位置（权重1）
    if rsi is not None:
        if rsi > 55:
            votes_bull += 1
        elif rsi < 45:
            votes_bear += 1

    # DMI方向（权重2）
    if pdi is not None and mdi is not None:
        if pdi > mdi:
            votes_bull += 2
        else:
            votes_bear += 2

    # 价格相对MA20位置（权重1）
    if last_price and ma20 and ma20 > 0:
        if last_price > ma20 * 1.005:
            votes_bull += 1
        elif last_price < ma20 * 0.995:
            votes_bear += 1

    # Vortex方向（权重1）
    if vi_plus is not None and vi_minus is not None:
        if vi_plus > vi_minus:
            votes_bull += 1
        else:
            votes_bear += 1

    # Supertrend方向（权重1）
    if st_dir is not None:
        if st_dir == 1:
            votes_bull += 1
        elif st_dir == -1:
            votes_bear += 1

    # ROC方向（权重1）
    if roc10 is not None:
        if roc10 > 0:
            votes_bull += 1
        else:
            votes_bear += 1

    # 投票决定方向
    total_votes = votes_bull + votes_bear
    if total_votes == 0:
        # 无指标数据，使用旧得分作为fallback
        return score_direction > 0

    # 多头需要超过60%的投票（更严格的多头确认）
    bull_ratio = votes_bull / total_votes
    if bull_ratio >= 0.6:
        return True
    elif bull_ratio <= 0.4:
        return False
    else:
        # 投票接近时（40%-60%），使用价格位置判断
        # 如果价格在MA20和BB中轨上方，判为多头（震荡偏多）
        if last_price and ma20 and last_price > ma20:
            bb_middle = tech.get('BB_MIDDLE')
            if bb_middle and last_price > bb_middle:
                return True  # 价格在MA20和BB中轨上方，震荡偏多
        # 否则使用旧得分作为参考
        return score_direction > 0


def calculate_composite_score(tech: dict, sym: dict, score_direction: int = 0,
                               kline_closes: list = None,
                               term_basis: dict = None) -> dict:
    """计算100分制综合得分（v2.13 L1-L4四层架构）。

    参数：
        tech: 技术指标字典
        sym: 品种信息字典（含last_price, open_interest）
        score_direction: 基础趋势方向得分（>0多头，<0空头），仅作参考
        kline_closes: 收盘价序列
        term_basis: 期限结构/基差数据（期货专属）

    返回：
        {'total': int, 'grade': str, 'tier': str, 'dimensions': {...}, 'reasons': [...]}
    """
    # v2.13改进：基于技术指标综合判断方向，不依赖旧趋势得分
    # 使用多个指标投票决定方向
    is_bull = _determine_direction(tech, sym, score_direction)

    # 计算DC位置并注入tech
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    last_price = sym.get('last_price')
    if dc_upper and dc_lower and last_price and (dc_upper - dc_lower) > 0:
        if is_bull:
            tech['DC_POS'] = (last_price - dc_lower) / (dc_upper - dc_lower)
        else:
            tech['DC_POS'] = (dc_upper - last_price) / (dc_upper - dc_lower)

    # 计算偏离度并注入tech
    ma20 = tech.get('MA20')
    if last_price and ma20 and ma20 > 0:
        tech['PRICE_DEVIATION_PCT'] = (last_price - ma20) / ma20 * 100

    # 注入last_price到tech
    tech['last_price'] = last_price

    # 计算OI_RATE（如果tech中没有，从sym中计算）
    oi = sym.get('open_interest', 0)
    if oi and 'OI_RATE' not in tech:
        # 需要历史OI均值，这里用简单估算
        # 实际应该从历史数据计算MA(OI, 20)
        tech['OI_RATE'] = None  # 暂时跳过，需要历史数据

    # 估算突破天数
    days_since = estimate_days_since_breakout(tech, is_bull)

    # 四层打分（各层内部仍用旧满分制，下面统一缩放）
    l1_raw = score_L1_germination(tech, sym, is_bull, kline_closes, term_basis)
    l2_raw = score_L2_volume_price(tech, sym, is_bull)
    l3_raw = score_L3_structure(tech, is_bull)
    l4_raw = score_L4_confirmation(tech, sym, is_bull, days_since)
    l4_raw['_pre_maturity_score'] = l4_raw['score']
    veto = score_veto_dimension(tech, sym, is_bull, term_basis)

    # === v2.17: 趋势成熟度调整 ===
    maturity = assess_trend_maturity(tech, sym, 1 if is_bull else -1)
    stage = maturity.get('stage', 'unknown')
    maturity_adjust = 0
    maturity_reason = ''

    if stage == 'exhausted':
        # 衰竭期：确认信号不可靠，降权 L4
        l4_raw['score'] = int(l4_raw['score'] * 0.5)
        veto['score'] -= 3
        veto['reasons'].append(f'趋势衰竭(成熟度={stage})(-3)')
    elif stage == 'reversal':
        # 反转期：方向信号可能失效
        veto['score'] -= 6
        veto['reasons'].append(f'趋势反转风险(成熟度={stage})(-6)')

    maturity_adjust = l4_raw['score'] - l4_raw.get('_pre_score', l4_raw['score'])
    # 保存 L4 原始分供报告
    l4_raw['_pre_maturity_score'] = l4_raw.get('_pre_maturity_score', l4_raw['score'])

    # v2.17 权重重分配: 40/30/20/10 (2026-07-03: L2 25→30, L3 25→20)
    # 各层内部满分已与WLx对齐 → 缩放简化为恒等变换
    l1_scaled = min(l1_raw['score'], L1_INTERNAL_MAX)
    l2_scaled = min(l2_raw['score'], L2_INTERNAL_MAX)
    l3_scaled = min(l3_raw['score'], L3_INTERNAL_MAX)
    l4_scaled = min(l4_raw['score'], L4_INTERNAL_MAX)

    # 保留原始得分用于报告展示
    l1 = {'score': l1_scaled, 'raw_score': l1_raw['score'], 'reasons': l1_raw['reasons']}
    l2 = {'score': l2_scaled, 'raw_score': l2_raw['score'], 'reasons': l2_raw['reasons']}
    l3 = {'score': l3_scaled, 'raw_score': l3_raw['score'], 'reasons': l3_raw['reasons']}
    l4 = {'score': l4_scaled, 'raw_score': l4_raw['score'], 'reasons': l4_raw['reasons']}

    total = l1_scaled + l2_scaled + l3_scaled + l4_scaled + veto['score']
    total = max(0, min(100, total))

    # 各层分数（用于报告）

    # 评级（阶梯化）
    if total >= 75:
        grade = 'STRONG'
    elif total >= 60:
        grade = 'WATCH'
    elif total >= 40:
        grade = 'WEAK'
    else:
        grade = 'NOISE'

    # 合并所有reasons
    all_reasons = []
    all_reasons.extend([f'[L1萌芽] {r}' for r in l1['reasons']])
    all_reasons.extend([f'[L2量价] {r}' for r in l2['reasons']])
    all_reasons.extend([f'[L3结构] {r}' for r in l3['reasons']])
    all_reasons.extend([f'[L4确认] {r}' for r in l4['reasons']])
    all_reasons.extend([f'[否决] {r}' for r in veto['reasons']])
    if stage != 'unknown' and stage != 'trending':
        all_reasons.append(f'[成熟度] {stage}')

    return {
        'total': total,
        'grade': grade,
        'maturity': {'stage': stage, 'adjustment': -veto['score'] if 'veto' in dir() else 0},
        'direction': 'BUY' if is_bull else 'SELL',
        'days_since_breakout': days_since,
        'decay_factor': l4.get('decay', 1.0),
        'dimensions': {
            'L1_germination': l1,
            'L2_volume_price': l2,
            'L3_structure': l3,
            'L4_confirmation': l4,
            'veto': veto,
        },
        'reasons': all_reasons,
        # 各层分数（用于报告）
        'L1_score': l1['score'],
        'L2_score': l2['score'],
        'L3_score': l3['score'],
        'L4_score': l4['score'],
        'veto_score': veto['score'],
    }


# ============================================================
# v2.14 趋势成熟度罚分 + 早期信号排序（方案D：双排行）
# ============================================================

def compute_maturity_penalty(l1: int, l2: int, l3: int, l4: int, rsi: float, adx: float) -> tuple:
    """计算趋势成熟度罚分。
    
    成熟趋势（RSI极端、ADX过高、L4确认层满分）得分高但已走很远。
    此函数计算罚分，使早期信号能在排序中排在成熟信号前面。
    
    Args:
        l1,l2,l3,l4: L1-L4各层原始分数（含正负号）
        rsi: RSI(14) 值
        adx: ADX(14) 值
    
    Returns:
        (penalty: int, reasons: list[str]) 罚分总是正数，从early_score中扣除
    """
    penalty = 0
    reasons = []
    
    abs_l4 = abs(l4)
    abs_l3 = abs(l3)
    
    # RSI极端罚分
    if rsi < 20 or rsi > 80:
        penalty += 12; reasons.append(f'RSI极端({rsi:.0f}, -12)')
    elif rsi < 25 or rsi > 75:
        penalty += 8; reasons.append(f'RSI超买/超卖({rsi:.0f}, -8)')
    elif rsi < 30 or rsi > 70:
        penalty += 4; reasons.append(f'RSI偏高({rsi:.0f}, -4)')
    
    # ADX成熟度罚分
    if adx > 70:
        penalty += 6; reasons.append(f'ADX极强(趋势末端, {adx:.0f}, -6)')
    elif adx > 55:
        penalty += 3; reasons.append(f'ADX强趋势(偏晚, {adx:.0f}, -3)')
    elif adx < 15:
        penalty += 4; reasons.append(f'ADX震荡(信号不可靠, {adx:.0f}, -4)')
    
    # L4确认层罚分（L4满分说明趋势已完成确认阶段）
    if abs_l4 >= 16:
        penalty += 4; reasons.append(f'L4确认层满分(-4)')
    elif abs_l4 >= 12:
        penalty += 2; reasons.append(f'L4确认层偏高(-2)')
    
    # L3结构层满分的趋势也偏晚
    if abs_l3 >= 15:
        penalty += 2; reasons.append(f'L3结构层满分(-2)')
    
    return penalty, reasons


def compute_early_score(l1: int, l2: int, l3: int, l4: int, rsi: float, adx: float) -> tuple:
    """计算早期趋势得分：abs(L1+L2) - 成熟度罚分。
    
    早期信号偏好：
    - L1（萌芽）和 L2（量价领先）是较早的信号层
    - L3（价格结构）和 L4（确认）是较晚的信号层
    - 罚分降低已走远品种的排序
    
    Returns:
        (early_score: float, maturity_penalty: int, reasons: list[str])
    """
    penalty, reasons = compute_maturity_penalty(l1, l2, l3, l4, rsi, adx)
    early_raw = abs(l1) + abs(l2)
    early_score = early_raw - penalty
    return early_score, penalty, reasons
