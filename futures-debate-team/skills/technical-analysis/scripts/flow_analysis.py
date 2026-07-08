# -*- coding: utf-8 -*-
"""席位资金流分析模块 — 前20席位净持仓变化、多空比、风向标席位。"""

from typing import Dict, Optional


def analyze_seat_flow(
    top20_net_long: float,
    top20_net_long_change: float,
    price_direction: str = "up",
    bellwether_seats: Optional[Dict[str, float]] = None,
) -> Dict:
    """解读前20席位资金流向。

    Args:
        top20_net_long: 前20净多持仓（正=净多，负=净空）
        top20_net_long_change: 前20净多变化
        price_direction: 价格方向 'up'/'down'
        bellwether_seats: 可选，风向标席位净持仓 {席位名: 净多量}

    Returns:
        dict: {net_long_position, change_interpretation, details}
    """
    result = {
        "top20_net_long": round(top20_net_long, 0),
        "top20_net_long_change": round(top20_net_long_change, 0),
    }

    # 净多/净空判断
    if top20_net_long > 0:
        result["net_position"] = "净多"
        result["net_ratio"] = f"前20净多{abs(top20_net_long):.0f}手"
    else:
        result["net_position"] = "净空"
        result["net_ratio"] = f"前20净空{abs(top20_net_long):.0f}手"

    # 变化解读
    if top20_net_long_change > 0:
        result["change_direction"] = "多头加仓"
        if price_direction == "up":
            result["change_interpretation"] = "多空同步增仓"
        else:
            result["change_interpretation"] = "多头抄底，需谨慎"
    elif top20_net_long_change < 0:
        result["change_direction"] = "空头加仓"
        if price_direction == "down":
            result["change_interpretation"] = "空头持续加仓"
        else:
            result["change_interpretation"] = "空头逢高加仓"
    else:
        result["change_direction"] = "不变"
        result["change_interpretation"] = "持仓结构稳定"

    # 风向标席位
    if bellwether_seats:
        seat_details = []
        for name, net in bellwether_seats.items():
            direction = "净多" if net > 0 else "净空"
            seat_details.append(f"{name}{direction}{abs(net):.0f}手")
        result["bellwether_seats"] = bellwether_seats
        result["bellwether_summary"] = "；".join(seat_details)

    return result


def estimate_long_short_ratio(long_volume: float, short_volume: float) -> Dict:
    """估算多空成交比。

    Args:
        long_volume: 多方成交量
        short_volume: 空方成交量

    Returns:
        dict: {ratio, interpretation}
    """
    if short_volume == 0:
        return {"ratio": None, "interpretation": "数据不足"}

    ratio = long_volume / short_volume
    if ratio >= 1.5:
        interp = "多方优势明显"
    elif ratio >= 1.2:
        interp = "多方略占优势"
    elif ratio <= 0.67:
        interp = "空方优势明显"
    elif ratio <= 0.83:
        interp = "空方略占优势"
    else:
        interp = "多空均衡"

    return {"ratio": round(ratio, 2), "interpretation": interp}
