# -*- coding: utf-8 -*-
"""
True Layered Scoring (真分层打分) v2.0 — 修复版
==============================================

v2.0 修复（2026-07-04）：
  1. [OK] 数据质量检查（DQCB）：缺失数据的因子自动排除，不全的品种降权
  2. [OK] 否决降权层：ADX震荡、RSI极端、偏离极端 → 排名分×惩罚系数
  3. [OK] 趋势成熟度感知：launch/trending/exhausted/reversal 阶段修正
  4. [OK] 自适应因子维度：数据不可用的因子从等权平均中移除

学术正统：
  portfolio sort — 截面排序 → 秩变换 → 等权/加权汇总 → 择优
"""
from statistics import mean


# ============================================================
# 因子定义：法官席（每法官=一个独立排序维度）
# ============================================================

FACTOR_DEFINITIONS = [
    # ─── 风格A: 趋势追踪 (1位) ───
    {
        'name': 'D1_趋势_动量',
        'desc': 'ROC10 — 趋势方向强度',
        'key': 'ROC10',
        'transform': lambda v: v,
        'weight': 1,
        'required_fields': ['ROC10'],
        'style': 'trend',
    },
    # ─── 风格B: 均值回归 (2位) ───
    {
        'name': 'D2_回归_乖离率',
        'desc': '-BIAS — BIAS>15%超买(排低) BIAS<-10%超卖(排高)',
        'key': None,
        'transform': lambda tech: -(tech.get('PRICE_DEVIATION_PCT', 0)),
        'weight': 1,
        'required_fields': ['PRICE_DEVIATION_PCT'],
        'style': 'reversion',
    },
    {
        'name': 'D3_回归_RSI反向',
        'desc': '-(RSI14-50) — RSI>80超买(排低) RSI<20超卖(排高)',
        'key': 'RSI14',
        'transform': lambda v: -(v - 50),
        'weight': 1,
        'required_fields': ['RSI14'],
        'style': 'reversion',
    },
    # ─── 风格C: 资金流 (2位, 全风格) ───
    {
        'name': 'D4_资金_持仓OI',
        'desc': 'OI变化率 — 持仓量方向',
        'key': 'OI_CHANGE_PCT',
        'transform': lambda v: v if abs(v or 0) < 30 else (30 if (v or 0) > 0 else -30),
        'weight': 1,
        'required_fields': ['OI_CHANGE_PCT'],
        'style': 'all',
    },
    {
        'name': 'D5_资金_净流CMF',
        'desc': 'CMF21 — 资金净流入',
        'key': 'CMF21',
        'transform': lambda v: v,
        'weight': 1,
        'required_fields': ['CMF21'],
        'style': 'all',
    },
    # ─── 风格D: 量价确认 (1位, 全风格) ───
    {
        'name': 'D6_确认_量价',
        'desc': '放量×方向 — 量在价先',
        'key': None,
        'transform': lambda tech: (tech.get('VOL_RATIO', 1) - 1) * (1 if tech.get('PRICE_CHANGE_5D', 0) > 0 else -1),
        'weight': 1,
        'required_fields': ['VOL_RATIO', 'PRICE_CHANGE_5D'],
        'style': 'all',
    },
    # ─── 风格E: 期限结构 (1位, 全风格·期货专用) ───
    {
        'name': 'D7_期限_基差',
        'desc': 'term_signal 期限结构方向（contango=-1~backwardation=+1）',
        'key': 'TERM_SIGNAL',
        'transform': lambda v: v * 100 if v is not None else None,
        'weight': 1,
        'required_fields': ['TERM_SIGNAL'],
        'style': 'all',
    },
]


# ============================================================
# Step 0: 数据质量检查 (DQCB)
# ============================================================


def _validate_tech(tech: dict) -> dict:
    """检查单品种数据质量，返回各维度有效性标志。
    
    返回: {factor_name: True/False}
    """
    valid = {}
    for factor in FACTOR_DEFINITIONS:
        fields = factor.get('required_fields', [])
        if factor['key'] is not None:
            # 单字段因子
            v = tech.get(factor['key'])
            valid[factor['name']] = v is not None
        else:
            # 组合字段因子：所有required字段均需有效
            all_ok = all(tech.get(f) is not None for f in fields)
            valid[factor['name']] = all_ok
    return valid


def compute_factor_validity(all_techs: list) -> dict:
    """计算全市场各因子数据可用率。
    
    返回: {factor_name: {'valid_ct': int, 'valid_rate': float, 'usable': bool}}
    """
    n = len(all_techs)
    factor_valid_counts = {f['name']: 0 for f in FACTOR_DEFINITIONS}

    for tech in all_techs:
        v = _validate_tech(tech)
        for fname, is_valid in v.items():
            if is_valid:
                factor_valid_counts[fname] += 1

    result = {}
    for fname, ct in factor_valid_counts.items():
        rate = ct / max(n, 1)
        # 因子可用判定：全市场>50%品种有该数据
        usable = rate >= 0.5
        result[fname] = {'valid_ct': ct, 'valid_rate': round(rate, 3), 'usable': usable}
    return result


# ============================================================
# Step 0.5: 否决降权层 (veto → 惩罚系数, 不是扣分)
# ============================================================

def _compute_veto_penalty(tech: dict) -> float:
    """计算否决降权系数。返回 0~1 之间的乘数。
    
    与 L1-L4 扣分不同：这里用乘法，直接压缩排名分。
    乘法的好处是不破坏排名序，极端情况下至少保留少量分数。
    
    规则（与 scoring_system 对齐）：
    - ADX<15 震荡 → ×0.5
    - ADX<15 + Squeeze → ×0.3
    - RSI>80(多头方向) / RSI<20(空头方向) → ×0.5
    - 偏离MA20>15% → ×0.6
    - 严重缩量(VOL<0.5) → ×0.7
    """
    penalty = 1.0
    reasons = []

    adx = tech.get('ADX')
    rsi = tech.get('RSI14')
    last_price = tech.get('last_price')
    ma20 = tech.get('MA20')
    vol_ratio = tech.get('VOL_RATIO')

    # ADX震荡
    if adx is not None and adx < 15:
        bb_squeeze = tech.get('BB_SQUEEZE', False)
        if bb_squeeze:
            penalty *= 0.3
            reasons.append(f'ADX={adx:.0f}+Squeeze纯震荡(×0.3)')
        else:
            penalty *= 0.5
            reasons.append(f'ADX={adx:.0f}趋势弱(×0.5)')

    # RSI极端（双向检测）
    if rsi is not None:
        if rsi > 80:
            penalty *= 0.5
            reasons.append(f'RSI={rsi:.0f}>80超买(×0.5)')
        elif rsi < 20:
            penalty *= 0.5
            reasons.append(f'RSI={rsi:.0f}<20超卖(×0.5)')

    # 偏离MA20
    if last_price and ma20 and ma20 > 0:
        deviation = abs((last_price - ma20) / ma20 * 100)
        if deviation > 15:
            penalty *= 0.6
            reasons.append(f'偏离MA20={deviation:.0f}%>15%(×0.6)')

    # 严重缩量
    if vol_ratio is not None and vol_ratio < 0.5:
        penalty *= 0.7
        reasons.append(f'缩量={vol_ratio:.1f}x(×0.7)')

    return penalty, reasons


# ============================================================
# Step 0.6: 趋势成熟度感知 (maturity)
# ============================================================

def _assess_maturity_stage(tech: dict) -> dict:
    """评估趋势成熟度阶段。
    
    简化版（不依赖 indicators.core.assess_trend_maturity 的完整逻辑，
    直接用 tech 字段判断，避免循环依赖）。
    
    返回: {'stage': str, 'multiplier': float}
    """
    rsi = tech.get('RSI14', 50)
    adx = tech.get('ADX', 0)
    last_price = tech.get('last_price')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    ma20 = tech.get('MA20')
    new_high = tech.get('NEW_HIGH_60', False)

    # 反转期: RSI反向极端 + 价格穿越均线
    if rsi > 75 and last_price and ma20 and last_price < ma20:
        return {'stage': 'reversal', 'multiplier': 0.3}
    if rsi < 25 and last_price and ma20 and last_price > ma20:
        return {'stage': 'reversal', 'multiplier': 0.3}

    # 衰竭期: RSI极端 + ADX高位
    if (rsi > 75 or rsi < 25) and adx > 50:
        return {'stage': 'exhausted', 'multiplier': 0.5}
    if new_high and rsi > 75:
        return {'stage': 'exhausted', 'multiplier': 0.5}

    # 启动期: 刚从通道突破
    if dc_upper and dc_lower and last_price:
        mid = (dc_upper + dc_lower) / 2
        if adx < 30 and dc_upper > dc_lower:
            # 价格在上轨附近但ADX还不高 = 可能刚启动
            if last_price > dc_upper * 0.98:
                return {'stage': 'launch', 'multiplier': 1.0}

    # 趋势运行
    if adx >= 25:
        return {'stage': 'trending', 'multiplier': 0.95}

    return {'stage': 'unknown', 'multiplier': 0.85}


# ============================================================
# Step 1: 截面排序 → 秩变换 (rank percentile)
# ============================================================

def rank_percentile(values: list) -> list:
    """将一维数组转为 0-100 的 rank percentile。
    
    排序 → 排名 → 归一化到 0-100。
    与 Z-score 关键差异：不保留数值间距（极端值被拍平成相邻排名）。
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]

    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1])

    ranks = [0] * n
    for rank, (original_idx, _) in enumerate(indexed):
        ranks[original_idx] = rank / (n - 1) * 100.0

    return ranks


# ============================================================
# Step 2: 核心入口
# ============================================================

def compute_true_layered_score(all_techs: list) -> dict:
    """对全品种列表执行真分层打分（修复版 v2.0）。
    
    流程：
      0. DQCB + 否决降权 + 趋势成熟度
      1. 各因子提取原始值
      2. 每个因子做截面排序 → 秩变换
      3. 各品种：可用因子等权平均排名分
      4. 应用否决降权 × 成熟度修正
      5. 返回排名
    """
    n = len(all_techs)
    if n == 0:
        return {'factors': [], 'ranked': [], 'meta': {'n_contracts': 0, 'n_factors': 0}}

    # Step 0: 数据有效性全局评估
    factor_validity = compute_factor_validity(all_techs)
    usable_factors = [f for f in FACTOR_DEFINITIONS if factor_validity[f['name']]['usable']]
    n_factors = len(usable_factors)

    if n_factors == 0:
        return {'factors': [], 'ranked': [],
                'meta': {'n_contracts': n, 'n_factors': 0, 'error': '无可用因子'}}

    # Step 0.5: 预计算每个品种的否决降权和成熟度
    veto_penalties = []
    maturity_stages = []
    for tech in all_techs:
        p, reasons = _compute_veto_penalty(tech)
        m = _assess_maturity_stage(tech)
        veto_penalties.append({'penalty': p, 'reasons': reasons})
        maturity_stages.append(m)

    # Step 1: 各因子提取原始值
    factor_rawnames = [f['name'] for f in usable_factors]
    factor_raws = []
    for factor in usable_factors:
        if factor['key'] is not None:
            raw = []
            for tech in all_techs:
                v = tech.get(factor['key'])
                if v is not None:
                    try:
                        raw.append(factor['transform'](v))
                    except (TypeError, ValueError):
                        raw.append(0.0)
                else:
                    raw.append(0.0)
        else:
            raw = []
            for tech in all_techs:
                # 安全提取组合因子
                all_fields = tech.get(factor['required_fields'][0]) if factor.get('required_fields') else None
                # 检查是否所有 required_fields 都有值
                fields_ok = all(tech.get(f) is not None for f in factor.get('required_fields', []))
                if fields_ok:
                    try:
                        raw.append(factor['transform'](tech))
                    except (TypeError, ValueError):
                        raw.append(0.0)
                else:
                    raw.append(0.0)
        factor_raws.append(raw)

    # Step 2: 每个因子做秩变换
    factor_rank_percentiles = [rank_percentile(r) for r in factor_raws]

    # Step 3: 等权汇总（ADX风格感知 → 趋势和均值回归不同时投票）
    ranked_contracts = []
    for i in range(n):
        sym = all_techs[i].get('symbol', f'contract_{i}')
        tech = all_techs[i]
        adx = tech.get('ADX', 20)
        
        # 该品种各维度有效性
        v = _validate_tech(tech)
        
        # 风格感知：根据ADX选择该品种的活跃因子（趋势vs均值回归不混投）
        regime = 'trend' if adx >= 25 else ('reversion' if adx < 20 else 'mixed')
        active_factor_idxs = []
        for j, factor in enumerate(usable_factors):
            if not v.get(factor['name'], False):
                continue
            style = factor.get('style', 'all')
            if regime == 'trend' and style in ('trend', 'all'):
                active_factor_idxs.append(j)
            elif regime == 'reversion' and style in ('reversion', 'all'):
                active_factor_idxs.append(j)
            elif regime == 'mixed':
                active_factor_idxs.append(j)

        # 如果品种没有任何维度可用 → 最低排名
        if not active_factor_idxs:
            ranked_contracts.append({
                'symbol': sym,
                'avg_rank': 0.0,
                'net_rank': -50.0,
                'active_dims': 0,
                'dimensions': {},
                'raws': {},
                'veto_penalty': 0.0,
                'maturity': {'stage': 'nodata', 'multiplier': 0.3},
                'regime': regime,
            })
            continue

        active_ranks = [factor_rank_percentiles[j][i] for j in active_factor_idxs]
        avg_rank = mean(active_ranks)

        # Step 4: 应用否决降权 × 成熟度修正
        veto_p = veto_penalties[i]['penalty']
        maturity_m = maturity_stages[i]['multiplier']
        adjusted = avg_rank * veto_p * maturity_m

        # 各维度排名分（用于报告）
        dims = {}
        raws = {}
        for j, factor in enumerate(usable_factors):
            dims[factor['name']] = round(factor_rank_percentiles[j][i], 1)
            raws[factor['name']] = round(factor_raws[j][i], 2)

        ranked_contracts.append({
            'symbol': sym,
            'avg_rank': round(avg_rank, 1),
            'net_rank': round(avg_rank - 50.0, 1),
            'adjusted_rank': round(adjusted, 1),
            'active_dims': len(active_factor_idxs),
            'dimensions': dims,
            'raws': raws,
            'veto_penalty': round(veto_p, 3),
            'veto_reasons': veto_penalties[i]['reasons'],
            'maturity': maturity_stages[i],
            'regime': regime,
        })

    # 按调整后分降序排列
    ranked_contracts.sort(key=lambda x: x['adjusted_rank'], reverse=True)
    for i, c in enumerate(ranked_contracts):
        c['rank'] = i + 1

    return {
        'factors': [{
            'name': f['name'],
            'desc': f['desc'],
            'weight': f['weight'],
            'valid_ct': factor_validity[f['name']]['valid_ct'],
            'valid_rate': factor_validity[f['name']]['valid_rate'],
            'usable': factor_validity[f['name']]['usable'],
        } for f in FACTOR_DEFINITIONS],
        'ranked': ranked_contracts,
        'meta': {
            'n_contracts': n,
            'n_factors_total': len(FACTOR_DEFINITIONS),
            'n_factors_usable': n_factors,
            'method': 'true_layered_scoring_v2',
            'features': ['dqcb', 'veto_mult', 'maturity', 'adaptive_dims'],
        },
    }
