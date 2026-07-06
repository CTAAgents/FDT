# -*- coding: utf-8 -*-
"""背离捕捉模块 — 价量背离、价持仓背离、MACD/KDJ顶底背离、RSI背离。"""

from typing import Dict, Optional


def check_divergence(
    price_trend: str = "up",
    volume_trend: Optional[str] = None,
    oi_trend: Optional[str] = None,
    macd_trend: Optional[str] = None,
    rsi_trend: Optional[str] = None,
) -> Dict:
    """多维度背离检测。

    Args:
        price_trend: 价格趋势 'up'/'down'
        volume_trend: 成交量趋势 'up'/'down'
        oi_trend: 持仓量趋势 'up'/'down'
        macd_trend: MACD柱趋势 'up'/'down'
        rsi_trend: RSI趋势 'up'/'down'

    Returns:
        dict: {divergences: list, severity, summary}
    """
    divergences = []

    # 价量背离：价↑量↓
    if price_trend == "up" and volume_trend == "down":
        divergences.append(
            {
                "type": "价量背离",
                "detail": "价格创新高但成交量萎缩，上涨动能减弱",
                "level": "日级别",
                "severity": "中",
            }
        )

    # 价量背离（跌）：价↓量↓ = 缩量下跌（可能企稳）
    if price_trend == "down" and volume_trend == "down":
        divergences.append(
            {
                "type": "缩量下跌",
                "detail": "价格下跌但成交量萎缩，抛压减弱，可能接近底部",
                "level": "日级别",
                "severity": "低",
            }
        )

    # 价持仓背离：价↑持仓↓ = 多头平仓推涨，非真买盘
    if price_trend == "up" and oi_trend == "down":
        divergences.append(
            {
                "type": "价持仓背离",
                "detail": "价格上涨但持仓减少，多头平仓推动，非新多入场",
                "level": "日级别",
                "severity": "高",
            }
        )

    # 价持仓背离（跌）：价↓持仓↓ = 空头平仓
    if price_trend == "down" and oi_trend == "down":
        divergences.append(
            {
                "type": "价持仓背离",
                "detail": "价格下跌但持仓减少，空头平仓推动，非新空入场",
                "level": "日级别",
                "severity": "中",
            }
        )

    # MACD顶背离：价创新高，MACD柱未创新高
    if price_trend == "up" and macd_trend == "down":
        divergences.append(
            {
                "type": "MACD顶背离",
                "detail": "价格创新高但MACD柱走弱，上涨动能衰竭",
                "level": "日级别",
                "severity": "高",
            }
        )

    # MACD底背离：价创新低，MACD柱未创新低
    if price_trend == "down" and macd_trend == "up":
        divergences.append(
            {
                "type": "MACD底背离",
                "detail": "价格创新低但MACD柱走强，下跌动能减弱",
                "level": "日级别",
                "severity": "高",
            }
        )

    # RSI背离
    if price_trend == "up" and rsi_trend == "down":
        divergences.append(
            {
                "type": "RSI顶背离",
                "detail": "价格创新高但RSI走弱，动量衰减",
                "level": "日级别",
                "severity": "中",
            }
        )
    if price_trend == "down" and rsi_trend == "up":
        divergences.append(
            {
                "type": "RSI底背离",
                "detail": "价格创新低但RSI走强，动量回升",
                "level": "日级别",
                "severity": "中",
            }
        )

    # 综合评估
    if not divergences:
        return {
            "divergences": [],
            "severity": "无",
            "summary": "未检测到显著背离",
        }

    high_count = sum(1 for d in divergences if d["severity"] == "高")
    mid_count = sum(1 for d in divergences if d["severity"] == "中")

    if high_count >= 2:
        severity = "严重"
    elif high_count >= 1:
        severity = "较高"
    elif mid_count >= 2:
        severity = "中等"
    else:
        severity = "轻度"

    return {
        "divergences": divergences,
        "severity": severity,
        "divergence_count": len(divergences),
        "summary": f"检测到{len(divergences)}个背离信号（高{high_count}个/中{mid_count}个）",
    }
