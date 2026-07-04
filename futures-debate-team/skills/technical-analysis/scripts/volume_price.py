# -*- coding: utf-8 -*-
"""量价分析模块 — 持仓变化解读、仓价配合、成交量分布。

核心判断逻辑：
- 总持仓↑ 价格↑ = 资金真进，多头主动加仓
- 总持仓↑ 价格↓ = 空头主动加仓
- 总持仓↓ 价格↑ = 空头平仓反弹
- 总持仓↓ 价格↓ = 多头平仓回落
"""

from typing import Dict, Optional


def analyze_volume_price(
    oi_change_pct: Optional[float] = None,
    price_change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
) -> Dict:
    """分析量价配合关系。

    Args:
        oi_change_pct: 持仓量变化百分比（%）
        price_change_pct: 价格变化百分比（%）
        volume_ratio: 成交量相对均量倍数（>1 = 放量）

    Returns:
        dict: {oi_price_interpretation, volume_status, detail}
    """
    result = {}
    detail_parts = []

    # 仓价配合解读
    if oi_change_pct is not None and price_change_pct is not None:
        if oi_change_pct > 2 and price_change_pct > 1:
            result['oi_price_interpretation'] = '资金真进，多头主动加仓'
            result['oi_price_direction'] = '偏多'
            detail_parts.append(f"总持仓↑{oi_change_pct:+.1f}% 价↑{price_change_pct:+.1f}%=多头增仓")
        elif oi_change_pct > 2 and price_change_pct < -1:
            result['oi_price_interpretation'] = '空头主动加仓'
            result['oi_price_direction'] = '偏空'
            detail_parts.append(f"总持仓↑{oi_change_pct:+.1f}% 价↓{price_change_pct:+.1f}%=空头增仓")
        elif oi_change_pct < -2 and price_change_pct > 1:
            result['oi_price_interpretation'] = '空头平仓反弹'
            result['oi_price_direction'] = '偏多（空平反弹谨慎）'
            detail_parts.append(f"总持仓↓{oi_change_pct:+.1f}% 价↑{price_change_pct:+.1f}%=空头减仓")
        elif oi_change_pct < -2 and price_change_pct < -1:
            result['oi_price_interpretation'] = '多头平仓回落'
            result['oi_price_direction'] = '偏空（多平回落谨慎）'
            detail_parts.append(f"总持仓↓{oi_change_pct:+.1f}% 价↓{price_change_pct:+.1f}%=多头减仓")
        else:
            result['oi_price_interpretation'] = '仓价变化不显著'
            result['oi_price_direction'] = '中性'
            detail_parts.append(f"持仓{oi_change_pct:+.1f}% 价{price_change_pct:+.1f}%=变动温和")

    # 成交量判断
    if volume_ratio is not None:
        if volume_ratio >= 2.0:
            result['volume_status'] = '显著放量'
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=显著放量")
        elif volume_ratio >= 1.5:
            result['volume_status'] = '温和放量'
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=温和放量")
        elif volume_ratio <= 0.5:
            result['volume_status'] = '显著缩量'
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=显著缩量")
        else:
            result['volume_status'] = '正常'
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=正常水平")

    result['detail'] = '；'.join(detail_parts) if detail_parts else '数据不足'
    return result


def check_fake_breakout(
    breakout_direction: str,
    volume_ratio: float,
    price_confirmation: bool,
    prior_resistance_tested: int = 0,
) -> Dict:
    """突破真假验证：带量突破 vs 缩量假突破。

    Args:
        breakout_direction: 'up' 或 'down'
        volume_ratio: 成交量相对均量倍数
        price_confirmation: 突破后是否站稳/跌破确认位
        prior_resistance_tested: 前期测试该关键位的次数

    Returns:
        dict: {is_fake, confidence, reason}
    """
    clues = []

    if breakout_direction == 'up':
        if volume_ratio >= 2.0 and price_confirmation:
            return {"is_fake": False, "confidence": "高", "reason": f"带量{volume_ratio:.1f}倍突破+确认站稳=真突破"}
        elif volume_ratio >= 2.0 and not price_confirmation:
            return {"is_fake": True, "confidence": "中", "reason": f"虽有量{volume_ratio:.1f}倍但未确认站稳=暂判定假突破"}
        elif volume_ratio < 1.5:
            return {"is_fake": True, "confidence": "高", "reason": f"缩量{volume_ratio:.1f}倍突破=假突破概率大"}
        else:
            return {"is_fake": True, "confidence": "低-中", "reason": f"量能不足{volume_ratio:.1f}倍+待确认=疑似假突破"}
    else:
        if volume_ratio >= 2.0 and price_confirmation:
            return {"is_fake": False, "confidence": "高", "reason": f"带量{volume_ratio:.1f}倍下破+确认跌破=真突破"}
        elif volume_ratio >= 2.0 and not price_confirmation:
            return {"is_fake": True, "confidence": "中", "reason": f"有量{volume_ratio:.1f}倍但未确认跌破=暂判定假突破"}
        elif volume_ratio < 1.5:
            return {"is_fake": True, "confidence": "高", "reason": f"缩量{volume_ratio:.1f}倍下破=假突破概率大"}
        else:
            return {"is_fake": True, "confidence": "低-中", "reason": f"量能不足{volume_ratio:.1f}倍+待确认=疑似假突破"}
