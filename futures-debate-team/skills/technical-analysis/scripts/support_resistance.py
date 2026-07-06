# -*- coding: utf-8 -*-
"""支撑/阻力位计算模块 v2.1 — 辩论系统增强版。

v2.1 新增辩论专用特征：
- 硬/软分类: VP-POC+整数关口=hard, ZigZag=medium, 趋势线+MA=soft
- ATR容差带: 每个关键位标注 x0.3~x1 ATR 的容差
- 失效条件: "若日线收盘跌破且OI增" 等可辩论条件
- 多周期共振: 不同TF的level交叉验证标签

功能：
- find_swing_points(): ZigZag算法找前高前低
- consolidate_levels(): 邻近价位聚合
- calculate_poc(): 成交量分布 POC/VAH/VAL
- classify_level_hardness(): 硬/软分类
- identify_key_levels(): 综合输出（含容差+失效条件）
- cross_validate_timeframes(): 多周期共振验证
"""

from typing import Dict, List, Optional, Tuple
import math


# ═══════════════════════════════════════════════════════════
# ZigZag拐点检测
# ═══════════════════════════════════════════════════════════


def find_swing_points(
    highs: List[float],
    lows: List[float],
    lookback: int = 3,
    deviation_pct: float = 0.3,
    rollover_indices: Optional[List[int]] = None,
) -> Dict[str, List[dict]]:
    """ZigZag拐点检测 — 找前高前低（支持换月跳空屏蔽）。

    Args:
        highs: 最高价序列（最近的在最后）
        lows: 最低价序列
        lookback: 回溯K线数
        deviation_pct: 反转确认幅度（%）
        rollover_indices: 换月跳空的K线索引列表，附近±lookback根跳过检测

    Returns:
        {"swing_highs": [...], "swing_lows": [...]}
    """
    n = len(highs)
    swing_highs, swing_lows = [], []

    # 构建换月屏蔽区间
    mask = set()
    if rollover_indices:
        for ri in rollover_indices:
            for offset in range(-lookback, lookback + 1):
                idx = ri + offset
                if 0 <= idx < n:
                    mask.add(idx)

    for i in range(lookback, n - lookback):
        if i in mask:
            continue
        is_high = all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, lookback + 1))
        if is_high:
            swing_highs.append({"idx": i, "price": highs[i], "strength": 1})
        is_low = all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, lookback + 1))
        if is_low:
            swing_lows.append({"idx": i, "price": lows[i], "strength": 1})

    filtered_highs = _filter_by_deviation(swing_highs, deviation_pct)
    filtered_lows = _filter_by_deviation(swing_lows, deviation_pct)
    _mark_strength(filtered_highs, filtered_lows)

    return {"swing_highs": filtered_highs, "swing_lows": filtered_lows}


def _filter_by_deviation(points: List[dict], dev_pct: float) -> List[dict]:
    if not points:
        return []
    filtered = [points[0]]
    for p in points[1:]:
        last = filtered[-1]
        if abs(p["price"] - last["price"]) / last["price"] * 100 >= dev_pct:
            filtered.append(p)
    return filtered


def _mark_strength(highs: List[dict], lows: List[dict]):
    for arr in [highs, lows]:
        for i, pt in enumerate(arr):
            count = 0
            for j in range(i + 1, min(i + 3, len(arr))):
                if abs(arr[j]["price"] - pt["price"]) / pt["price"] < 0.02:
                    count += 1
            pt["strength"] = max(1, count + 1)


# ═══════════════════════════════════════════════════════════
# 价位聚合
# ═══════════════════════════════════════════════════════════


def consolidate_levels(levels: List[float], merge_pct: float = 0.3) -> List[Tuple[float, int]]:
    """聚合邻近价位"""
    if not levels:
        return []
    sorted_lvls = sorted(levels)
    groups = [[sorted_lvls[0]]]
    for lvl in sorted_lvls[1:]:
        if abs(lvl - groups[-1][0]) / max(groups[-1][0], 1) * 100 <= merge_pct:
            groups[-1].append(lvl)
        else:
            groups.append([lvl])
    return [(round(sum(g) / len(g), 1), len(g)) for g in groups]


# ═══════════════════════════════════════════════════════════
# Volume Profile
# ═══════════════════════════════════════════════════════════


def calculate_poc(
    highs: List[float],
    lows: List[float],
    volumes: List[float],
    num_bins: int = 20,
) -> Dict:
    """计算成交量分布的 POC/VAH/VAL。"""
    if not highs or not volumes or len(highs) < 5:
        return {"poc": 0, "vah": 0, "val": 0, "valid": False}

    price_min = min(lows)
    price_max = max(highs)
    bin_width = (price_max - price_min) / num_bins if price_max > price_min else 1

    bins = [
        {"low": price_min + i * bin_width, "high": price_min + (i + 1) * bin_width, "volume": 0.0}
        for i in range(num_bins)
    ]

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

    cum, val_bin = 0, bins[0]
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
        "valid": True,
    }


# ═══════════════════════════════════════════════════════════
# 硬/软分类 + ATR容差 + 失效条件
# ═══════════════════════════════════════════════════════════


def _is_round_number(price: float, tick_size: float = 100) -> bool:
    """判断是否为整数关口（如3600, 3800等）"""
    if tick_size <= 0:
        return False
    return price % tick_size < 0.01 or abs(price % tick_size - tick_size) < 0.01


def _source_type_tag(price: float, vp: Dict, ma20: float, ma60: float) -> str:
    """追溯关键位的来源，用于辩论引用"""
    sources = []
    if vp.get("valid") and abs(price - vp.get("poc", 0)) / max(price, 1) < 0.01:
        sources.append("VP-POC")
    if vp.get("valid") and abs(price - vp.get("vah", 0)) / max(price, 1) < 0.01:
        sources.append("VP-VAH")
    if vp.get("valid") and abs(price - vp.get("val", 0)) / max(price, 1) < 0.01:
        sources.append("VP-VAL")
    if ma20 and abs(price - ma20) / max(price, 1) < 0.01:
        sources.append("MA20")
    if ma60 and abs(price - ma60) / max(price, 1) < 0.01:
        sources.append("MA60")
    return "+".join(sources) if sources else "ZigZag"


def classify_level_hardness(
    price: float,
    count: int,  # 聚合了多少价位到此点
    source_tag: str,  # 来源标签
    vp: Dict,
    tick_size: float = 100,
) -> str:
    """硬/软支撑分类规则。

    hard = Volume Profile的POC/VAH/VAL 或 整数关口 或 被≥3个价位聚合
    medium = ZigZag拐点 + 至少strength≥2
    soft = 单周期趋势线 / MA / 单前高前低
    """
    if vp.get("valid") and ("VP-" in source_tag):
        return "hard"
    if _is_round_number(price, tick_size):
        return "hard"
    if count >= 3:
        return "hard"
    if "MA" in source_tag or "ZigZag" in source_tag:
        return "medium"
    return "soft"


def _atr_tolerance(atr: float, hardness: str) -> float:
    """根据硬/软等级确定不同的ATR容差倍数"""
    factors = {"hard": 0.3, "medium": 0.5, "soft": 1.0}
    return atr * factors.get(hardness, 0.5)


def _fail_condition(price: float, is_support: bool, hardness: str) -> str:
    """生成辩论可引用的失效条件"""
    if is_support:
        if hardness == "hard":
            return f"日线实体收盘价 < {price} 且下一根K线不收回"
        elif hardness == "medium":
            return f"日线收盘价 < {price} 或 持仓量↑价格↓(多头离场确认)"
        else:
            return f"小时线收盘价 < {price} 则关注，日线收盘 < {price} 则失效"
    else:
        if hardness == "hard":
            return f"日线实体收盘价 > {price} 且下一根K线不收回"
        elif hardness == "medium":
            return f"日线收盘价 > {price} 或 持仓量↑价格↑(空头离场确认)"
        else:
            return f"小时线收盘价 > {price} 则关注，日线收盘 > {price} 则失效"


# ═══════════════════════════════════════════════════════════
# OI/成交量确认 → 关键位置信度调整
# ═══════════════════════════════════════════════════════════


def _check_oi_confirmation(
    price: float,
    closes: List[float],
    oi_series: Optional[List[float]],
    volume_series: Optional[List[float]],
    lookback_bars: int = 10,
    is_support: bool = True,
) -> dict:
    """检查关键位附近的OI/成交量配合情况。

    规则（源自规范）：
    - 涨到压力位 OI大增+放量滞涨 → 真压力
    - 跌到支撑位 OI大增+放量止跌 → 真支撑
    - 跌到支撑位 OI减+空平 → 支撑有效（但偏弱）
    - 压力/支撑位附近缩量 → 该级别置信度降低

    Returns:
        {"oi_confirm": "confirmed"|"neutral"|"contradict",
         "volume_confirm": "confirmed"|"neutral"|"contradict",
         "nearby_bars": int, "oi_trend": str, "vol_trend": str}
    """
    result = {
        "nearby_bars": 0,
        "oi_confirm": "neutral",
        "volume_confirm": "neutral",
        "oi_trend": "unknown",
        "vol_trend": "unknown",
    }

    if not closes or len(closes) < lookback_bars:
        return result

    # 找最近lookback_bars中接近关键位的K线
    nearby = []
    for i in range(max(0, len(closes) - lookback_bars * 3), len(closes)):
        dist = abs(closes[i] - price) / max(price, 1) * 100
        if dist < 1.0:  # 1%以内的接近
            nearby.append(i)

    result["nearby_bars"] = len(nearby)
    if len(nearby) < 2:
        return result

    # 检查OI趋势
    if oi_series and len(oi_series) > nearby[0]:
        oi_vals = [oi_series[i] if i < len(oi_series) else oi_series[-1] for i in nearby]
        if len(oi_vals) >= 2:
            oi_change = (oi_vals[-1] - oi_vals[0]) / max(oi_vals[0], 1) * 100
            result["oi_trend"] = f"{oi_change:+.1f}%"
            if is_support:
                # 跌到支撑 OI增 = 真支撑（有人接）；OI减 = 空平反弹
                if oi_change > 3:
                    result["oi_confirm"] = "confirmed"
                elif oi_change < -3:
                    result["oi_confirm"] = "confirmed"
                else:
                    result["oi_confirm"] = "neutral"
            else:
                # 涨到压力 OI大增+滞涨 = 真压力
                if oi_change > 3:
                    result["oi_confirm"] = "confirmed"
                elif oi_change < -3:
                    result["oi_confirm"] = "contradict"  # 减仓上涨 → 假突破可能
                else:
                    result["oi_confirm"] = "neutral"

    # 检查成交量趋势
    if volume_series and len(volume_series) > nearby[0]:
        vol_vals = [volume_series[i] if i < len(volume_series) else volume_series[-1] for i in nearby]
        if len(vol_vals) >= 2:
            avg_vol_before = sum(vol_vals[: len(vol_vals) // 2]) / max(len(vol_vals) // 2, 1)
            avg_vol_after = sum(vol_vals[len(vol_vals) // 2 :]) / max(len(vol_vals) - len(vol_vals) // 2, 1)
            vol_ratio = avg_vol_after / max(avg_vol_before, 1)
            result["vol_trend"] = f"{vol_ratio:.1f}x"
            if vol_ratio >= 1.5:
                result["volume_confirm"] = "confirmed"
            elif vol_ratio <= 0.6:
                result["volume_confirm"] = "contradict"

    return result


def _adjust_hardness_with_oi(
    base_hardness: str,
    oi_check: dict,
) -> str:
    """根据OI/成交量配合度调整hardness"""
    order = {"hard": 3, "medium": 2, "soft": 1}
    base = order.get(base_hardness, 2)

    confirms = 0
    if oi_check.get("oi_confirm") == "confirmed":
        confirms += 1
    if oi_check.get("volume_confirm") == "confirmed":
        confirms += 1
    if oi_check.get("oi_confirm") == "contradict":
        confirms -= 1
    if oi_check.get("volume_confirm") == "contradict":
        confirms -= 1

    adjusted = base + confirms
    adjusted = max(1, min(3, adjusted))
    rev_map = {3: "hard", 2: "medium", 1: "soft"}
    return rev_map[adjusted]


# ═══════════════════════════════════════════════════════════
# 主入口：综合识别关键位
# ═══════════════════════════════════════════════════════════


def identify_key_levels(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    lookback: int = 3,
    merge_pct: float = 0.3,
    atr: Optional[float] = None,
    tick_size: float = 100,
    current_price: Optional[float] = None,
    session: str = "daily",
    rollover_indices: Optional[List[int]] = None,
    oi_series: Optional[List[float]] = None,
) -> Dict:
    """综合识别支撑阻力位 — 含换月屏蔽 + OI/成交量确认。

    Args:
        highs/lows/closes/volumes: K线数据
        ma20/ma60: 均线
        lookback/merge_pct: ZigZag参数
        atr: ATR值（用于容差带）
        tick_size: 整数关口判定粒度（如100=3600/3700）
        session: 时间框架标签
        rollover_indices: 换月跳空K线索引（用于屏蔽伪拐点）
        oi_series: 持仓量序列（用于OI/量能确认）

    Returns:
        {"support_levels": [...], "resistance_levels": [...],
         "poc/vah/val": float, "current_price": float,
         "method": "..."}
    """
    # 1. ZigZag（含换月屏蔽）
    sw = find_swing_points(highs, lows, lookback=lookback, rollover_indices=rollover_indices)

    # 2. Volume Profile
    vp = calculate_poc(highs, lows, volumes)

    # 3. 收集原始价位
    swing_supports = [l["price"] for l in sw["swing_lows"]]
    swing_resistances = [h["price"] for h in sw["swing_highs"]]

    near_poc_support = [vp["val"]] if vp.get("valid") else []
    near_poc_resistance = [vp["vah"]] if vp.get("valid") else []
    all_supports = swing_supports + near_poc_support + ([ma20] if ma20 else [])
    all_resistances = swing_resistances + near_poc_resistance + ([ma60] if ma60 else [])

    # 加近期极值
    all_supports.append(min(lows[-5:]) if len(lows) >= 5 else min(lows))
    all_resistances.append(max(highs[-5:]) if len(highs) >= 5 else max(highs))

    # 4. 聚合
    raw_supports = consolidate_levels(all_supports, merge_pct)
    raw_resistances = consolidate_levels(all_resistances, merge_pct)

    _cp = current_price or (closes[-1] if closes else (highs[-1] + lows[-1]) / 2)
    atr = atr or (max(highs[-14:]) - min(lows[-14:])) * 0.1 if len(highs) >= 14 else 0

    # 检查是否有换月附近的价位
    rollover_near = set()
    if rollover_indices:
        # 找出换月附近的close价格用于标记
        for ri in rollover_indices:
            for offset in range(-lookback, lookback + 1):
                idx = ri + offset
                if 0 <= idx < len(closes):
                    rollover_near.add(closes[idx])

    # 5. 构建带辩论属性的level
    def _build_level(price, count, is_support):
        src = _source_type_tag(price, vp, ma20 or 0, ma60 or 0)
        base_hd = classify_level_hardness(price, count, src, vp, tick_size)

        # OI/成交量确认（调整hardness）
        oi_check = _check_oi_confirmation(price, closes, oi_series, volumes, is_support=is_support)
        hd = _adjust_hardness_with_oi(base_hd, oi_check)

        tol = _atr_tolerance(atr, hd)
        near_rollover = any(abs(price - rp) / max(price, 1) * 100 < 1.0 for rp in rollover_near)

        return {
            "price": round(price, 1),
            "count": count,
            "hardness": hd,
            "base_hardness": base_hd,
            "tolerance": round(tol, 1),
            "tolerance_pct": round(tol / max(_cp, 1) * 100, 2),
            "source": src,
            "fail_condition": _fail_condition(price, is_support, hd),
            "tf": session,
            "near_rollover": near_rollover,
            "oi_check": {
                "nearby_bars": oi_check["nearby_bars"],
                "oi_confirm": oi_check["oi_confirm"],
                "volume_confirm": oi_check["volume_confirm"],
                "oi_trend": oi_check.get("oi_trend", "unknown"),
                "vol_trend": oi_check.get("vol_trend", "unknown"),
            },
        }

    supports = [_build_level(p, c, True) for p, c in raw_supports]
    resistances = [_build_level(p, c, False) for p, c in raw_resistances]

    supports.sort(key=lambda x: abs(x["price"] - _cp))
    resistances.sort(key=lambda x: abs(x["price"] - _cp))

    return {
        "support_levels": supports[:5],
        "resistance_levels": resistances[:5],
        "poc": round(vp["poc"], 1) if vp.get("valid") else None,
        "vah": round(vp["vah"], 1) if vp.get("valid") else None,
        "val": round(vp["val"], 1) if vp.get("valid") else None,
        "current_price": round(_cp, 1),
        "atr": round(atr, 2),
        "method": "zigzag+volume_profile+debate_enhanced+v2.2",
    }


# ═══════════════════════════════════════════════════════════
# 多周期共振验证
# ═══════════════════════════════════════════════════════════


def cross_validate_timeframes(
    daily_levels: Dict,
    h1_levels: Optional[Dict] = None,
    m15_levels: Optional[Dict] = None,
    merge_pct: float = 0.5,
) -> Dict:
    """多周期共振验证 — 不同TF的level互相打"共振"标签。

    规则：
    1. 如果某个价位在≥2个周期都出现 → resonance="confirmed"（共振确认）
    2. 只在1个周期出现 → resonance="single"（单周期，权重低）
    3. 硬/软分类取更硬的那个

    Returns:
        对 daily_levels 中的每个level增加 resonance 字段
    """
    all_tf = {"daily": daily_levels}
    if h1_levels:
        all_tf["h1"] = h1_levels
    if m15_levels:
        all_tf["m15"] = m15_levels

    # 收集所有TF的所有价位
    all_prices = {}
    for tf_name, levels in all_tf.items():
        for side in ["support_levels", "resistance_levels"]:
            for lvl in levels.get(side, []):
                p = lvl.get("price", 0)
                found = False
                for existing in all_prices.get(side, []):
                    if abs(existing["price"] - p) / max(existing["price"], 1) * 100 <= merge_pct:
                        existing["tfs"].append(tf_name)
                        existing["hardness"] = _pick_harder(
                            existing.get("hardness", "soft"), lvl.get("hardness", "soft")
                        )
                        found = True
                        break
                if not found:
                    all_prices.setdefault(side, []).append(
                        {
                            "price": p,
                            "tfs": [tf_name],
                            "hardness": lvl.get("hardness", "soft"),
                        }
                    )

    # 给daily_levels打共振标签
    def _apply_resonance(levels_list, side):
        for lvl in levels_list:
            match = [
                x
                for x in all_prices.get(side, [])
                if abs(x["price"] - lvl["price"]) / max(lvl["price"], 1) * 100 <= merge_pct
            ]
            if match:
                m = match[0]
                lvl["resonance"] = "confirmed" if len(m["tfs"]) >= 2 else "single"
                lvl["tfs"] = m["tfs"]
                lvl["hardness"] = m["hardness"]
        return levels_list

    daily_levels["support_levels"] = _apply_resonance(daily_levels["support_levels"], "support_levels")
    daily_levels["resistance_levels"] = _apply_resonance(daily_levels["resistance_levels"], "resistance_levels")
    daily_levels["resonance_summary"] = _resonance_summary(daily_levels)
    return daily_levels


def _pick_harder(a: str, b: str) -> str:
    order = {"hard": 3, "medium": 2, "soft": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _resonance_summary(levels: Dict) -> str:
    confirmed = 0
    for side in ["support_levels", "resistance_levels"]:
        confirmed += sum(1 for l in levels.get(side, []) if l.get("resonance") == "confirmed")
    total = sum(len(levels.get(s, [])) for s in ["support_levels", "resistance_levels"])
    if total == 0:
        return "无关键位"
    ratio = confirmed / total
    if ratio >= 0.5:
        return f"多周期共振强（{confirmed}/{total}个关键位跨TF确认）"
    elif ratio >= 0.2:
        return f"部分共振（{confirmed}/{total}个关键位跨TF确认）"
    else:
        return f"缺乏多周期共振（仅{confirmed}/{total}个跨TF确认）"
