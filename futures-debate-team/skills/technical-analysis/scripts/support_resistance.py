# -*- coding: utf-8 -*-
"""支撑/阻力位计算模块 — ZigZag拐点检测 + 成交密集区(VP)识别。

替代LLM"肉眼扫K线"的关键位识别方式，改为数学精确的算法识别。

功能：
- find_swing_points(): ZigZag算法找前高前低
- consolidate_levels(): 邻近价位聚合
- identify_key_levels(): 综合输出支撑阻力位
"""

from typing import Dict, List, Optional, Tuple
import math


def find_swing_points(
    highs: List[float],
    lows: List[float],
    lookback: int = 3,
    deviation_pct: float = 0.3,
) -> Dict[str, List[dict]]:
    """ZigZag拐点检测 — 找前高前低。

    Args:
        highs: 最高价序列（最近的在最后）
        lows: 最低价序列（最近的在最后）
        lookback: 回溯K线数（默认5，越大拐点越少）
        deviation_pct: 反转确认幅度（%），如0.5=需反向波动0.5%才确认拐点

    Returns:
        {"swing_highs": [{"idx": int, "price": float, "strength": int}],
         "swing_lows":  [{"idx": int, "price": float, "strength": int}]}
        strength: 该拐点经过多少次确认（越多次越重要）
    """
    n = len(highs)
    swing_highs = []
    swing_lows = []

    for i in range(lookback, n - lookback):
        # 前高：当前最高价 > 前后各lookback根
        is_high = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_high = False
                break
        if is_high:
            swing_highs.append({"idx": i, "price": highs[i], "strength": 1})

        # 前低：当前最低价 < 前后各lookback根
        is_low = True
        for j in range(1, lookback + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_low = False
                break
        if is_low:
            swing_lows.append({"idx": i, "price": lows[i], "strength": 1})

    # 过滤：用deviation_pct剔除小幅波动
    filtered_highs = _filter_by_deviation(swing_highs, highs, deviation_pct, is_high=True)
    filtered_lows = _filter_by_deviation(swing_lows, lows, deviation_pct, is_high=False)

    # 标记强度：被多次确认的拐点
    _mark_strength(filtered_highs, filtered_lows)

    return {"swing_highs": filtered_highs, "swing_lows": filtered_lows}


def _filter_by_deviation(
    points: List[dict], prices: List[float], dev_pct: float, is_high: bool
) -> List[dict]:
    """用最小波动幅度过滤拐点"""
    if not points:
        return []
    ref_price = prices[-1] if prices else 1
    filtered = [points[0]]
    for p in points[1:]:
        last = filtered[-1]
        change = abs(p["price"] - last["price"]) / ref_price * 100
        if change >= dev_pct:
            filtered.append(p)
    return filtered


def _mark_strength(highs: List[dict], lows: List[dict]):
    """标记拐点强度：被后续拐点确认的次数越多越重要"""
    for i, h in enumerate(highs):
        count = 0
        for j in range(i + 1, min(i + 3, len(highs))):
            if abs(highs[j]["price"] - h["price"]) / h["price"] < 0.02:
                count += 1
        h["strength"] = max(1, count + 1)
    for i, l in enumerate(lows):
        count = 0
        for j in range(i + 1, min(i + 3, len(lows))):
            if abs(lows[j]["price"] - l["price"]) / l["price"] < 0.02:
                count += 1
        l["strength"] = max(1, count + 1)


def consolidate_levels(
    levels: List[float], merge_pct: float = 0.3
) -> List[Tuple[float, int]]:
    """聚合邻近价位 — 将merge_pct范围内的价位合并为一个。

    Args:
        levels: 价位列表
        merge_pct: 合并阈值（百分比）

    Returns:
        [(price, count), ...] — count表示多少个价位聚合到此点
    """
    if not levels:
        return []
    sorted_levels = sorted(levels)
    groups = [[sorted_levels[0]]]

    for lvl in sorted_levels[1:]:
        if abs(lvl - groups[-1][0]) / groups[-1][0] * 100 <= merge_pct:
            groups[-1].append(lvl)
        else:
            groups.append([lvl])

    result = []
    for g in groups:
        avg = sum(g) / len(g)
        result.append((round(avg, 1), len(g)))
    return result


def calculate_poc(
    highs: List[float],
    lows: List[float],
    volumes: List[float],
    num_bins: int = 20,
) -> Dict:
    """计算成交量分布（Volume Profile）的POC/VAH/VAL。

    Args:
        highs: 最高价序列
        lows: 最低价序列
        volumes: 成交量序列
        num_bins: 价格区间分桶数

    Returns:
        {"poc": float, "vah": float, "val": float, "bins": [...], "valid": bool}
    """
    if not highs or not volumes or len(highs) < 5:
        return {"poc": 0, "vah": 0, "val": 0, "bins": [], "valid": False}

    price_min = min(lows)
    price_max = max(highs)
    bin_width = (price_max - price_min) / num_bins if price_max > price_min else 1

    bins = [{"low": price_min + i * bin_width, "high": price_min + (i + 1) * bin_width, "volume": 0.0}
            for i in range(num_bins)]

    for i in range(len(highs)):
        for b in bins:
            if lows[i] <= b["high"] and highs[i] >= b["low"]:
                overlap = min(highs[i], b["high"]) - max(lows[i], b["low"])
                if overlap > 0:
                    ratio = overlap / (highs[i] - lows[i]) if highs[i] > lows[i] else 1
                    b["volume"] += volumes[i] * ratio

    poc_bin = max(bins, key=lambda b: b["volume"])
    poc = (poc_bin["low"] + poc_bin["high"]) / 2

    total_vol = sum(b["volume"] for b in bins)

    # 简化VAH/VAL：用70%成交量覆盖区间
    cum = 0
    for b in bins:
        cum += b["volume"]
        if cum >= total_vol * 0.15:
            val_bin = b
            break
    cum = 0
    for b in reversed(bins):
        cum += b["volume"]
        if cum >= total_vol * 0.15:
            vah_bin = b
            break

    return {
        "poc": round(poc, 1),
        "vah": round((vah_bin["low"] + vah_bin["high"]) / 2, 1),
        "val": round((val_bin["low"] + val_bin["high"]) / 2, 1),
        "bins": [{"low": round(b["low"], 1), "high": round(b["high"], 1), "volume": round(b["volume"], 0)}
                 for b in bins],
        "valid": True,
    }


def identify_key_levels(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    lookback: int = 5,
    merge_pct: float = 0.3,
) -> Dict:
    """综合识别支撑阻力位 — 聚合多种方法的结果。

    Args:
        highs: 最高价序列（最近的在最后）
        lows: 最低价序列
        closes: 收盘价序列
        volumes: 成交量序列
        ma20: MA20当前值
        ma60: MA60当前值
        lookback: ZigZag回溯K线数
        merge_pct: 价位聚合百分比

    Returns:
        {
            "support_levels": [(price, strength), ...],
            "resistance_levels": [(price, strength), ...],
            "poc": float,
            "vah": float,
            "val": float,
            "current_price": float,
            "method": "zigzag+volume_profile"
        }
    """
    # 1. ZigZag拐点
    sw = find_swing_points(highs, lows, lookback=lookback)
    swing_supports = [l["price"] for l in sw["swing_lows"]]
    swing_resistances = [h["price"] for h in sw["swing_highs"]]

    # 2. Volume Profile
    vp = calculate_poc(highs, lows, volumes)
    near_poc_support = [vp["val"]] if vp["valid"] else []
    near_poc_resistance = [vp["vah"]] if vp["valid"] else []

    # 3. MA作为动态支撑阻力
    ma_supports = [ma20] if ma20 else []
    ma_resistances = [ma60] if ma60 else []

    # 4. 最近低点/高点
    near_term_low = min(lows[-5:]) if len(lows) >= 5 else min(lows)
    near_term_high = max(highs[-5:]) if len(highs) >= 5 else max(highs)

    # 聚合
    all_supports = swing_supports + near_poc_support + ma_supports + [near_term_low]
    all_resistances = swing_resistances + near_poc_resistance + ma_resistances + [near_term_high]

    support_levels = consolidate_levels(all_supports, merge_pct)
    resistance_levels = consolidate_levels(all_resistances, merge_pct)

    current_price = closes[-1] if closes else (highs[-1] + lows[-1]) / 2

    # 按价位排序（最近的支撑/阻力优先）
    support_levels.sort(key=lambda x: abs(x[0] - current_price))
    resistance_levels.sort(key=lambda x: abs(x[0] - current_price))

    return {
        "support_levels": support_levels[:5],
        "resistance_levels": resistance_levels[:5],
        "poc": round(vp["poc"], 1) if vp["valid"] else None,
        "vah": round(vp["vah"], 1) if vp["valid"] else None,
        "val": round(vp["val"], 1) if vp["valid"] else None,
        "current_price": round(current_price, 1),
        "method": "zigzag+volume_profile",
    }
