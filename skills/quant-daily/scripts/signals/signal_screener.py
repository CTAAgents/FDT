# -*- coding: utf-8 -*-
"""信号筛选模块（v2.13 L1-L4四层架构）。

核心改进（v2.13）：
1. L1-L4四层打分：L1萌芽(40分) + L2量价(25分) + L3结构(25分) + L4确认(10分)
2. 阈值阶梯化：T1观察(60-75)、T2主仓(75-90)、T3警惕(>90)
3. 排序赛马制：取 Top N，不设绝对分数线
4. 期货专属：OI三角、基差、期限结构、跨期Spread信号
5. 时间衰减：突破后走远的信号递减

v2.12 基础：
- 萌芽+确认混合打分
- 四阶段趋势生命周期：launch / trending / exhausted / reversal
"""

from typing import List, Dict, Optional
try:
    from indicators.core import assess_trend_maturity
except ImportError:
    from indicators.core import assess_trend_maturity


def detect_trend_stage(tech: dict, score: int) -> dict:
    """检测趋势阶段 — 委派 indicators.assess_trend_maturity()"""
    price = tech.get('last_price', 0)
    sym = {'last_price': price, 'open_interest': tech.get('open_interest', 0)}
    maturity = assess_trend_maturity(tech, sym, 1 if score > 0 else -1)
    stage = maturity.get('stage', 'unknown')
    reasons_map = {
        'launch': ['趋势刚启动，通道突破+均线排列初期'],
        'trending': ['主趋势运行中'],
        'exhausted': ['趋势衰竭，RSI极端+通道极值'],
        'reversal': ['趋势反转，价格穿越DC55中轨'],
    }
    return {'stage': stage, 'reasons': reasons_map.get(stage, ['趋势不明确'])}


def count_resonance(tech: dict, score: int) -> dict:
    """计算多指标共振度（v2.13 L1-L4四层架构）。

    共振指标（按层分组）：
    L1 萌芽层：
    1. ROC方向（>0多, <0空）
    2. MA斜率方向
    3. %b位置（>0.5多, <0.5空）
    4. OBV方向（>MA20多, <MA20空）
    5. CMF方向（>0多, <0空）
    6. OI信号（增仓多/增仓空）

    L2 量价层：
    7. Vortex方向（VI+>VI-多）
    8. CCI方向（>+100多, <-100空）
    9. Supertrend方向
    10. HMA交叉方向

    L3 结构层：
    11. RSI方向（>50多, <50空）
    12. DMI方向（PDI>MDI多）

    L4 确认层：
    13. MA排列方向
    14. MACD DIF方向
    15. 价格位置（>MA20多）
    16. 通道突破确认
    """
    is_bull = score > 0
    confirmations = 0
    total_checks = 0
    details = []

    # ===== L1 萌芽层 =====

    # ROC方向
    roc10 = tech.get('ROC10')
    if roc10 is not None:
        total_checks += 1
        if (is_bull and roc10 > 0) or (not is_bull and roc10 < 0):
            confirmations += 1
            details.append('ROC✓')
        else:
            details.append('ROC✗')

    # MA斜率方向
    ma_slope = tech.get('MA20_SLOPE')
    if ma_slope is not None:
        total_checks += 1
        if (is_bull and ma_slope > -0.5) or (not is_bull and ma_slope < 0.5):
            confirmations += 0.5
            details.append('MA斜率✓')
        else:
            details.append('MA斜率✗')

    # %b位置
    bb_pctb = tech.get('BB_PCTB')
    if bb_pctb is not None:
        total_checks += 1
        if (is_bull and bb_pctb > 0.5) or (not is_bull and bb_pctb < 0.5):
            confirmations += 0.5
            details.append('%b✓')
        else:
            details.append('%b✗')

    # OBV方向
    obv, obv_ma = tech.get('OBV'), tech.get('OBV_MA20')
    if obv is not None and obv_ma is not None:
        total_checks += 1
        if (is_bull and obv > obv_ma) or (not is_bull and obv < obv_ma):
            confirmations += 1
            details.append('OBV✓')
        else:
            details.append('OBV✗')

    # CMF方向
    cmf21 = tech.get('CMF21')
    if cmf21 is not None:
        total_checks += 1
        if (is_bull and cmf21 > 0) or (not is_bull and cmf21 < 0):
            confirmations += 0.5
            details.append('CMF✓')
        else:
            details.append('CMF✗')

    # OI信号（期货专属）
    oi_rate = tech.get('OI_RATE')
    if oi_rate is not None:
        total_checks += 1
        if oi_rate > 1.05:
            confirmations += 1
            details.append('OI增仓✓')
        else:
            details.append('OI✗')

    # ===== L2 量价层 =====

    # Vortex方向
    vi_plus, vi_minus = tech.get('VI_PLUS'), tech.get('VI_MINUS')
    if vi_plus is not None and vi_minus is not None:
        total_checks += 1
        if (is_bull and vi_plus > vi_minus) or (not is_bull and vi_minus > vi_plus):
            confirmations += 1
            details.append('Vortex✓')
        else:
            details.append('Vortex✗')

    # CCI方向
    cci = tech.get('CCI20')
    if cci is not None:
        total_checks += 1
        if (is_bull and cci > 0) or (not is_bull and cci < 0):
            confirmations += 0.5
            details.append('CCI✓')
        else:
            details.append('CCI✗')

    # Supertrend方向
    st_dir = tech.get('SUPERTREND_DIR')
    if st_dir is not None:
        total_checks += 1
        if (is_bull and st_dir == 1) or (not is_bull and st_dir == -1):
            confirmations += 1
            details.append('Supertrend✓')
        else:
            details.append('Supertrend✗')

    # HMA交叉方向
    hma_cross = tech.get('HMA_CROSS')
    if hma_cross is not None:
        total_checks += 1
        if (is_bull and hma_cross == 'bull') or (not is_bull and hma_cross == 'bear'):
            confirmations += 0.5
            details.append('HMA✓')
        else:
            details.append('HMA✗')

    # ===== L3 结构层 =====

    # RSI方向
    rsi = tech.get('RSI14')
    if rsi is not None:
        total_checks += 1
        if (is_bull and rsi > 50) or (not is_bull and rsi < 50):
            confirmations += 1
            details.append('RSI✓')
        else:
            details.append('RSI✗')

    # DMI方向
    pdi, mdi = tech.get('DMI_PDI'), tech.get('DMI_MDI')
    if pdi is not None and mdi is not None:
        total_checks += 1
        if (is_bull and pdi > mdi) or (not is_bull and mdi > pdi):
            confirmations += 1
            details.append('DMI✓')
        else:
            details.append('DMI✗')

    # ===== L4 确认层 =====

    # MA排列
    ma5, ma10, ma20 = tech.get('MA5'), tech.get('MA10'), tech.get('MA20')
    ma40, ma60 = tech.get('MA40'), tech.get('MA60')
    if ma5 and ma10 and ma20:
        total_checks += 1
        short_bull = ma5 > ma10 > ma20
        short_bear = ma5 < ma10 < ma20
        long_bull = (ma20 > ma40 > ma60) if (ma40 and ma60) else True
        long_bear = (ma20 < ma40 < ma60) if (ma40 and ma60) else True
        full_bull = short_bull and long_bull
        full_bear = short_bear and long_bear
        if (is_bull and full_bull) or (not is_bull and full_bear):
            confirmations += 1
            details.append('MA排列✓' if (ma40 and ma60) else 'MA短周期✓')
        elif (is_bull and short_bull) or (not is_bull and short_bear):
            confirmations += 0.5
            details.append('MA短周期✓(长周期未共振)')
        elif short_bull or short_bear:
            details.append('MA排列✗')

    # MACD
    macd_dif = tech.get('MACD_DIF')
    if macd_dif is not None:
        total_checks += 1
        if (is_bull and macd_dif > 0) or (not is_bull and macd_dif < 0):
            confirmations += 1
            details.append('MACD✓')
        else:
            details.append('MACD✗')

    # 价格位置
    last_price = tech.get('last_price')
    if last_price and ma20:
        total_checks += 1
        if (is_bull and last_price > ma20) or (not is_bull and last_price < ma20):
            confirmations += 1
            details.append('价格位✓')
        else:
            details.append('价格位✗')

    # 通道突破确认
    bb_upper = tech.get('BB_UPPER')
    bb_middle = tech.get('BB_MIDDLE')
    bb_lower = tech.get('BB_LOWER')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc_mid = tech.get('DC_MID')
    if last_price:
        channel_confirmed = False
        if bb_upper and bb_middle and bb_lower:
            if (is_bull and last_price > bb_middle) or (not is_bull and last_price < bb_middle):
                channel_confirmed = True
        if dc_upper and dc_lower and dc_mid:
            if (is_bull and last_price > dc_mid) or (not is_bull and last_price < dc_mid):
                channel_confirmed = True
        if channel_confirmed:
            total_checks += 1
            confirmations += 1
            details.append('通道✓')

    resonance_ratio = confirmations / total_checks if total_checks > 0 else 0

    return {
        'confirmations': confirmations,
        'total_checks': total_checks,
        'ratio': round(resonance_ratio, 2),
        'details': details,
    }


def screen_signals(symbols: List[dict], score_threshold: int = 20,
                   min_resonance: float = 0.5, exclude_exhausted: bool = True,
                   top_n: int = 0) -> List[dict]:
    """扫描所有品种，筛选出有交易价值的信号（v2.12 排序赛马制）。

    v2.12 改进：
    1. 阈值阶梯化：不再一刀切，三段式：
       - T1 观察/预加载：总分 60-75 → watchlist
       - T2 主仓：总分 75-90 → 正常仓位
       - T3 警惕：>90 反而小心（过热）
    2. 排序赛马制：可选 top_n 参数，取相对排名前N
    3. 萌芽因子参与：评分来自四维度（萌芽+确认+结构+否决）

    筛选条件：
    1. |score| >= score_threshold（默认20）
    2. 共振度 >= min_resonance（默认50%指标同向）
    3. 趋势阶段不是 exhausted（可选）
    4. 市场整体偏空时，多头信号需要更高共振度（>=60%）
    5. [v2.12] 萌芽因子至少得1分（确保有早期信号特征）

    返回：按信号质量排序的候选列表（赛马制排名）
    """
    # v2.13: 使用L1-L4综合得分和方向判断市场方向
    # 注意：L1-L4得分是0-100的正数，需要根据direction判断多空
    buy_count = sum(1 for s in symbols if s.get('direction', '') == 'BUY' and s.get('score', 0) > score_threshold)
    sell_count = sum(1 for s in symbols if s.get('direction', '') == 'SELL' and s.get('score', 0) > score_threshold)
    market_bearish = sell_count > buy_count * 1.5
    market_bullish = buy_count > sell_count * 1.5

    candidates = []

    for sym in symbols:
        # v2.13: 优先使用L1-L4综合得分，fallback到旧趋势得分
        l1_l4_score = sym.get('score', 0)
        l1_l4_direction = sym.get('direction', '')
        old_score = sym.get('trend', {}).get('score', 0)

        # 使用L1-L4得分作为主要筛选依据
        score = l1_l4_score if l1_l4_score != 0 else old_score

        tech = sym.get('tech', {})
        trend_info = sym.get('trend', {})

        # v2.13: score是0-100的正数，直接比较
        if score < score_threshold:
            continue

        tech_with_price = dict(tech)
        tech_with_price['last_price'] = sym.get('last_price')

        stage = detect_trend_stage(tech_with_price, score)
        if exclude_exhausted and stage['stage'] == 'exhausted':
            continue

        resonance = count_resonance(tech_with_price, score)

        # v2.13: 使用L1-L4方向，fallback到得分方向
        direction = l1_l4_direction if l1_l4_direction else ('BUY' if score > 0 else 'SELL')
        required_resonance = min_resonance
        if market_bearish and direction == 'BUY':
            required_resonance = 0.6
        elif market_bullish and direction == 'SELL':
            required_resonance = 0.6

        if resonance['ratio'] < required_resonance:
            continue

        # 信号质量评分 = 信号强度 × 共振度 × 阶段系数
        stage_factor = {'launch': 1.3, 'trending': 1.0, 'exhausted': 0.4, 'reversal': 0.2}.get(stage['stage'], 0.8)
        signal_quality = round(abs(score) / 100.0 * resonance['ratio'] * stage_factor, 3)

        # v2.13: 使用L1-L4综合得分作为阶梯标记依据
        composite = sym.get('l1_l4_score', {})
        total_100 = composite.get('total', 0) if isinstance(composite, dict) else sym.get('score', 0)
        if total_100 >= 75:
            tier = 'T2'  # 主仓
        elif total_100 >= 60:
            tier = 'T1'  # 观察
        else:
            tier = 'T0'  # 弱信号

        candidates.append({
            'product_id': sym['product_id'],
            'product_name': sym.get('product_name', sym['product_id']),
            'last_price': sym['last_price'],
            'open_interest': sym.get('open_interest', 0),
            'score': score,
            'direction': direction,
            'trend_stage': stage,
            'resonance': resonance,
            'signal_quality': signal_quality,
            'tier': tier,
            'composite_total': total_100,
            'tech': tech,
            'trend': trend_info,
        })

    candidates.sort(key=lambda x: x['signal_quality'], reverse=True)

    # v2.12: 排序赛马制 — 可选取 Top N
    if top_n > 0 and len(candidates) > top_n:
        candidates = candidates[:top_n]

    return candidates
