# -*- coding: utf-8 -*-
"""产业链验证模块：检查品种信号是否与产业链方向一致。

从原 screen.py 拆分而来，负责产业链层面的信号验证逻辑。
"""

from typing import Optional


def get_chain_for_symbol(product_id: str) -> Optional[str]:
    """O(1)查找品种所属产业链（从chains.py缓存读取）"""
    from .chains import get_chain_for_symbol as _cached_lookup
    return _cached_lookup(product_id)


def chain_verification(candidate: dict, chain_results: dict) -> dict:
    """产业链验证：检查品种信号是否与产业链方向一致。

    一致 → 加分（+0.15 置信度）
    背离 → 减分（-0.10 置信度）
    产业链震荡 → 不加不减
    """
    chain_name = get_chain_for_symbol(candidate['product_id'])
    if not chain_name or chain_name not in chain_results:
        return {
            'chain_name': chain_name or '未知',
            'chain_trend': '未知',
            'aligned': False,
            'confidence_adjustment': 0,
            'detail': '未找到产业链数据',
        }

    chain = chain_results[chain_name]
    chain_trend = chain['overall_trend']
    is_bull_signal = candidate['direction'] == 'BUY'

    # 判断是否对齐
    if chain_trend in ['多头趋势', '偏多震荡']:
        aligned = is_bull_signal
        if aligned:
            adj = 0.15
            detail = f'多头信号与{chain_name}多头趋势一致，置信度+15%'
        else:
            adj = -0.10
            detail = f'空头信号与{chain_name}多头趋势背离，置信度-10%'
    elif chain_trend in ['空头趋势', '偏空震荡']:
        aligned = not is_bull_signal
        if aligned:
            adj = 0.15
            detail = f'空头信号与{chain_name}空头趋势一致，置信度+15%'
        else:
            adj = -0.10
            detail = f'多头信号与{chain_name}空头趋势背离，置信度-10%'
    else:
        aligned = True  # 震荡市不惩罚
        adj = 0.0
        detail = f'{chain_name}处于震荡状态，不做方向性调整'

    # 产业链共振加分：同链多个品种同向
    same_direction_count = sum(
        1 for m in chain['members']
        if (candidate['direction'] == 'BUY' and m['score'] > 0) or
           (candidate['direction'] == 'SELL' and m['score'] < 0)
    )
    chain_ratio = same_direction_count / chain['count'] if chain['count'] > 0 else 0
    if chain_ratio >= 0.6:
        adj += 0.05
        detail += f'，同链{same_direction_count}/{chain["count"]}品种同向，共振+5%'

    return {
        'chain_name': chain_name,
        'chain_trend': chain_trend,
        'aligned': aligned,
        'confidence_adjustment': round(adj, 2),
        'detail': detail,
        'chain_avg_score': chain['avg_score'],
        'same_direction_ratio': round(chain_ratio, 2),
    }
