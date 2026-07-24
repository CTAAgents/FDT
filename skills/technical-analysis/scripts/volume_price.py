# -*- coding: utf-8 -*-
"""量价分析模块 — 持仓变化解读、仓价配合、成交量分布、真假突破验证。

v2.0 改进：
- OI/价格阈值改为动态：按近20日ATR的百分比计算
- 移除 "偏多/偏空" 偏见标签，改为中性描述
- check_fake_breakout 增加自动 price_confirmation 计算
"""

import math
from typing import Dict, List, Optional


def _estimate_dynamic_threshold(prices: List[float] = None) -> float:
    """估算动态阈值：若无ATR数据返回默认值1.0%"""
    if not prices or len(prices) < 5:
        return 1.0
    diffs = [abs(prices[i] - prices[i - 1]) / prices[i - 1] * 100 for i in range(1, len(prices))]
    if not diffs:
        return 1.0
    avg = sum(diffs) / len(diffs)
    return round(max(0.3, min(avg * 1.5, 5.0)), 2)


def analyze_volume_price(
    oi_change_pct: Optional[float] = None,
    price_change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    reference_prices: Optional[List[float]] = None,
) -> Dict:
    """分析量价配合关系（动态阈值版）。

    阈值 = 根据品种近20日平均波幅动态计算，不硬编码。

    Args:
        oi_change_pct: 持仓量变化百分比（%）
        price_change_pct: 价格变化百分比（%）
        volume_ratio: 成交量相对均量倍数（>1 = 放量）
        reference_prices: 参考价格序列（用于计算动态阈值）

    Returns:
        dict: {oi_price_interpretation, volume_status, detail}
    """
    result = {}
    detail_parts = []
    threshold = _estimate_dynamic_threshold(reference_prices)
    oi_threshold = max(threshold * 2, 1.0)  # OI阈值 = 2倍价格波动阈值
    price_threshold = max(threshold * 0.8, 0.3)

    # 仓价配合解读（中性化描述）
    if oi_change_pct is not None and price_change_pct is not None:
        if oi_change_pct > oi_threshold and price_change_pct > price_threshold:
            result["oi_price_interpretation"] = "增量上涨：持仓与价格同步上升"
            detail_parts.append(f"总持仓↑{oi_change_pct:+.1f}% 价↑{price_change_pct:+.1f}%=资金入场推涨")
        elif oi_change_pct > oi_threshold and price_change_pct < -price_threshold:
            result["oi_price_interpretation"] = "增量下跌：持仓上升价格下跌"
            detail_parts.append(f"总持仓↑{oi_change_pct:+.1f}% 价↓{price_change_pct:+.1f}%=空头主动加仓")
        elif oi_change_pct < -oi_threshold and price_change_pct > price_threshold:
            result["oi_price_interpretation"] = "减量上涨：持仓下降价格上涨"
            detail_parts.append(f"总持仓↓{oi_change_pct:+.1f}% 价↑{price_change_pct:+.1f}%=空头减仓推动")
        elif oi_change_pct < -oi_threshold and price_change_pct < -price_threshold:
            result["oi_price_interpretation"] = "减量下跌：持仓与价格同步下降"
            detail_parts.append(f"总持仓↓{oi_change_pct:+.1f}% 价↓{price_change_pct:+.1f}%=多头减仓回落")
        else:
            result["oi_price_interpretation"] = "仓价变化不显著（未超动态阈值）"
            detail_parts.append(f"持仓{oi_change_pct:+.1f}% 价{price_change_pct:+.1f}%=变动在阈值{threshold}%范围内")

    result["_dynamic_threshold"] = round(threshold, 2)

    # 成交量判断
    if volume_ratio is not None:
        if volume_ratio >= 2.0:
            result["volume_status"] = "显著放量"
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=显著放量")
        elif volume_ratio >= 1.5:
            result["volume_status"] = "温和放量"
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=温和放量")
        elif volume_ratio <= 0.5:
            result["volume_status"] = "显著缩量"
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=显著缩量")
        else:
            result["volume_status"] = "正常"
            detail_parts.append(f"成交量{volume_ratio:.1f}倍均量=正常水平")

    result["detail"] = "；".join(detail_parts) if detail_parts else "数据不足"
    return result


def check_fake_breakout(
    breakout_direction: str,
    volume_ratio: float,
    price_confirmation: Optional[bool] = None,
    prior_resistance_tested: int = 0,
    closes_after_breakout: Optional[List[float]] = None,
    breakout_price: Optional[float] = None,
    confirmation_bars: int = 3,
) -> Dict:
    """突破真假验证 — 支持自动计算确认位（不再依赖外部传入）。

    Args:
        breakout_direction: 'up' 或 'down'
        volume_ratio: 成交量相对均量倍数
        price_confirmation: 可选，外部传入的确认判断
        prior_resistance_tested: 前期测试该关键位次数
        closes_after_breakout: 突破后N根K线的收盘价（用于自动判定）
        breakout_price: 突破时的价位
        confirmation_bars: 需要多少根K线确认（默认3）

    Returns:
        dict: {is_fake, confidence, reason}
    """
    # 自动计算 price_confirmation（如提供K线数据）
    if price_confirmation is None and closes_after_breakout and breakout_price:
        if breakout_direction == "up":
            holds = sum(1 for c in closes_after_breakout[:confirmation_bars] if c > breakout_price)
            price_confirmation = holds >= math.ceil(confirmation_bars * 0.6)
        else:
            holds = sum(1 for c in closes_after_breakout[:confirmation_bars] if c < breakout_price)
            price_confirmation = holds >= math.ceil(confirmation_bars * 0.6)

    # 仍无法判定时，默认保守处理
    if price_confirmation is None:
        price_confirmation = False

    # 多次测试突破 = 更有意义
    test_score = min(prior_resistance_tested / 3, 1.0)
    vol_score = min(volume_ratio / 2.0, 1.0)
    combined_score = (vol_score + test_score) / 2

    if breakout_direction == "up":
        if volume_ratio >= 2.0 and price_confirmation:
            return {
                "is_fake": False,
                "confidence": "高",
                "reason": f"带量{volume_ratio:.1f}倍突破+{confirmation_bars}根确认站稳=真突破",
            }
        elif volume_ratio >= 2.0 and not price_confirmation:
            return {
                "is_fake": True,
                "confidence": "中",
                "reason": f"有量{volume_ratio:.1f}倍但{confirmation_bars}根未确认=暂判定假突破",
            }
        elif volume_ratio < 1.5 and prior_resistance_tested == 0:
            return {
                "is_fake": True,
                "confidence": "高",
                "reason": f"缩量{volume_ratio:.1f}倍突破+首次测试=假突破概率大",
            }
        else:
            return {
                "is_fake": combined_score < 0.5,
                "confidence": "低-中",
                "reason": f"量能{volume_ratio:.1f}倍+测试{prior_resistance_tested}次+确认={price_confirmation}=疑似假突破",
            }
    else:
        if volume_ratio >= 2.0 and price_confirmation:
            return {
                "is_fake": False,
                "confidence": "高",
                "reason": f"带量{volume_ratio:.1f}倍下破+{confirmation_bars}根确认跌破=真突破",
            }
        elif volume_ratio >= 2.0 and not price_confirmation:
            return {
                "is_fake": True,
                "confidence": "中",
                "reason": f"有量{volume_ratio:.1f}倍但{confirmation_bars}根未确认=暂判定假突破",
            }
        elif volume_ratio < 1.5 and prior_resistance_tested == 0:
            return {
                "is_fake": True,
                "confidence": "高",
                "reason": f"缩量{volume_ratio:.1f}倍下破+首次测试=假突破概率大",
            }
        else:
            return {
                "is_fake": combined_score < 0.5,
                "confidence": "低-中",
                "reason": f"量能{volume_ratio:.1f}倍+测试{prior_resistance_tested}次+确认={price_confirmation}=疑似假突破",
            }
