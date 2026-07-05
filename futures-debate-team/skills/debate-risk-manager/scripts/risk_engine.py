# -*- coding: utf-8 -*-
"""风险引擎 v2.0 — 风控明吃技术Agent输出，实现完整的止损锚+仓位+动态调整+反馈闭环。

功能：
- select_stop_anchor(): 从技术Agent的supports中智能选锚（0.8~2.5×ATR）
- calculate_position(): 基于confidence+止损距反推仓位
- dynamic_adjustments(): 逻辑止损、ATR扩张、trailing
- special_scenario_override(): 换月/交割/夜盘/宏观事件覆写
- feedback_log(): 反馈闭环数据结构

依赖：calc_position.py（基本风控数学）
契约：对接 technical-analysis 的 support_resistance.py v2.1 输出
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math


# ═══════════════════════════════════════════════════════════
# 一、止损锚选择算法
# ═══════════════════════════════════════════════════════════

def select_stop_anchor(
    current_price: float,
    supports: List[Dict],
    atr: float,
    direction: str = "long",
) -> Dict:
    """从技术 Agent 的支撑位列表中智能选锚。

    规则（源自掌柜规范）：
    1. 过滤：只保留 hardness="hard" + price < current_price（多单）
    2. 排序：距当前价从近到远
    3. 优先选"距离在 0.8~2.5×ATR 之间"的那根
    4. 兜底：都没命中则取最近硬支撑 - 0.5×ATR

    Args:
        current_price: 当前价
        supports: 技术Agent吐的支撑位列表 [{"price", "hardness", "source", ...}]
        atr: ATR值（来自技术Agent）
        direction: "long" 或 "short"

    Returns:
        {"anchor_price": float, "stop_price": float, "distance": float,
         "atr_ratio": float, "source": str, "hardness": str}
    """
    if not supports or atr <= 0:
        return {"anchor_price": current_price - atr, "stop_price": current_price - 1.5 * atr,
                "distance": 1.5 * atr, "atr_ratio": 1.5, "source": "atr_default", "hardness": "soft"}

    if direction == "long":
        valid = [s for s in supports if s.get("hardness") in ("hard", "medium") and s.get("price", 0) < current_price]
        valid.sort(key=lambda x: current_price - x["price"])
        for s in valid:
            dist = current_price - s["price"]
            atr_ratio = dist / max(atr, 1)
            if 0.8 <= atr_ratio <= 2.5:
                tolerance = 0.4 * atr if s.get("hardness") == "hard" else 0.5 * atr
                stop = s["price"] - tolerance
                # 避开整数关口
                stop = _avoid_round_number(stop)
                return {
                    "anchor_price": round(s["price"], 1),
                    "stop_price": round(stop, 1),
                    "distance": round(dist, 1),
                    "atr_ratio": round(atr_ratio, 2),
                    "source": s.get("source", "unknown"),
                    "hardness": s.get("hardness", "unknown"),
                    "fail_condition": s.get("fail_condition", ""),
                }
        # 兜底：取最近硬支撑降低容差
        nearest = valid[0]
        fallback_stop = nearest["price"] - 0.5 * atr
        return {
            "anchor_price": round(nearest["price"], 1),
            "stop_price": round(fallback_stop, 1),
            "distance": round(current_price - fallback_stop, 1),
            "atr_ratio": round((current_price - fallback_stop) / max(atr, 1), 2),
            "source": nearest.get("source", "fallback"),
            "hardness": nearest.get("hardness", "hard"),
            "note": "兜底选锚：距当前价<0.8ATR或>2.5ATR"
        }
    else:
        # 空单：用resistance选锚
        valid = [s for s in supports if s.get("hardness") in ("hard", "medium") and s.get("price", 0) > current_price]
        valid.sort(key=lambda x: x["price"] - current_price)
        for s in valid:
            dist = s["price"] - current_price
            atr_ratio = dist / max(atr, 1)
            if 0.8 <= atr_ratio <= 2.5:
                tolerance = 0.4 * atr if s.get("hardness") == "hard" else 0.5 * atr
                stop = s["price"] + tolerance
                stop = _avoid_round_number(stop)
                return {
                    "anchor_price": round(s["price"], 1),
                    "stop_price": round(stop, 1),
                    "distance": round(dist, 1),
                    "atr_ratio": round(atr_ratio, 2),
                    "source": s.get("source", "unknown"),
                    "hardness": s.get("hardness", "unknown"),
                }
        nearest = valid[0]
        fallback_stop = nearest["price"] + 0.5 * atr
        return {
            "anchor_price": round(nearest["price"], 1),
            "stop_price": round(fallback_stop, 1),
            "distance": round(fallback_stop - current_price, 1),
            "atr_ratio": round((fallback_stop - current_price) / max(atr, 1), 2),
            "source": nearest.get("source", "fallback"),
            "hardness": nearest.get("hardness", "hard"),
            "note": "兜底选锚"
        }


def _avoid_round_number(price: float) -> float:
    """避开整数关口 — 6850→6842，防止程序化扫单"""
    rounded = round(price / 10) * 10
    if abs(price - rounded) < 8:  # 太接近整数
        offset = 7 if price > rounded else -7
        return round(price + offset, 1)
    return round(price, 1)


# ═══════════════════════════════════════════════════════════
# 二、仓位计算（置信度 + 止损距反推）
# ═══════════════════════════════════════════════════════════

def _confidence_discount(confidence: float) -> float:
    """根据技术Agent置信度做仓位折减"""
    if confidence >= 80:
        return 1.0
    elif confidence >= 65:
        return 0.8
    elif confidence >= 50:
        return 0.5
    else:
        return 0.0


def _pattern_risk_override(pattern_risk: Optional[str]) -> float:
    """反转模式覆写 — 如果技术Agent标注了反转形态在酝酿，砍仓位"""
    high_risk_patterns = ["双顶", "双底", "头肩", "上升楔形", "下降楔形",
                          "扩张三角形", "M头", "W底", "黄昏星", "启明星"]
    if not pattern_risk:
        return 1.0
    for p in high_risk_patterns:
        if p in pattern_risk:
            return 0.7  # 砍30%
    return 1.0


def calculate_position(
    entry_price: float,
    stop_price: float,
    equity: float,
    risk_per_trade: float = 0.01,
    multiplier: int = 10,
    confidence: float = 72,
    pattern_risk: Optional[str] = None,
    is_left_signal: bool = False,
) -> Dict:
    """根据止损距反推最大仓位，再按confidence折减。

    Args:
        entry_price: 入场价
        stop_price: 止损价
        equity: 账户权益
        risk_per_trade: 单笔风险比例（默认1%）
        multiplier: 合约乘数
        confidence: 技术Agent置信度（0-100）
        pattern_risk: 技术Agent标注的反转形态（如"双顶雏形"）
        is_left_signal: 是否为左侧信号

    Returns:
        {"max_lots": int, "final_lots": int,
         "confidence_discount": float, "pattern_discount": float,
         "loss_per_lot": float, "stop_distance": float, "flags": [...]}
    """
    stop_distance = abs(entry_price - stop_price)
    loss_per_lot = stop_distance * multiplier

    if loss_per_lot <= 0:
        return {"max_lots": 0, "final_lots": 0, "error": "止损距为零"}

    risk_budget = equity * risk_per_trade
    max_lots = int(risk_budget / loss_per_lot)

    # confidence折减
    conf_discount = _confidence_discount(confidence)
    pattern_discount = _pattern_risk_override(pattern_risk)
    total_discount = min(conf_discount, pattern_discount)

    final_lots = max(0, int(max_lots * total_discount))

    # 左侧信号额外砍半
    if is_left_signal:
        final_lots = max(1, final_lots // 2)

    flags = []
    if conf_discount < 1.0:
        flags.append({"level": "yellow", "msg": f"置信度{confidence}，仓位折减{conf_discount*100:.0f}%"})
    if pattern_discount < 1.0:
        flags.append({"level": "yellow", "msg": f"反转形态'{pattern_risk}'，仓位再砍30%"})
    if is_left_signal:
        flags.append({"level": "yellow", "msg": "左侧信号，仓位已自动减半"})

    return {
        "max_lots": max_lots,
        "final_lots": final_lots,
        "confidence_discount": round(conf_discount, 2),
        "pattern_discount": round(pattern_discount, 2),
        "loss_per_lot": round(loss_per_lot, 2),
        "stop_distance": round(stop_distance, 1),
        "risk_budget": round(risk_budget, 0),
        "flags": flags,
    }


# ═══════════════════════════════════════════════════════════
# 三、动态调整
# ═══════════════════════════════════════════════════════════

def evaluate_dynamic_adjustments(
    current_price: float,
    entry_price: float,
    current_stop: float,
    atr: float,
    new_atr: Optional[float] = None,
    new_supports: Optional[List[Dict]] = None,
    support_broken: Optional[bool] = None,
    is_long: bool = True,
) -> Dict:
    """评估是否需要动态调整止损。

    三种场景:
    1. 支撑被技术性破位 → 逻辑止损先行
    2. ATR扩张 >30% → 重算止损
    3. 出现新支撑 → trailing上移止损

    Args:
        current_price: 当前价
        entry_price: 入场价
        current_stop: 当前止损价
        atr: 基准ATR
        new_atr: 新计算的ATR（如有变化）
        new_supports: 技术Agent新吐的支撑位
        support_broken: 技术Agent判定的关键位是否被破
        is_long: 是否多单

    Returns:
        {"action": "hold"|"stop_now"|"move_stop"|"trailing"|"widen",
         "new_stop": float, "reason": str}
    """
    result = {"action": "hold", "new_stop": current_stop, "reason": "无变化"}

    # 场景1: 技术性破位 → 不等价格打到，立即逻辑止损
    if support_broken is True:
        return {
            "action": "stop_now",
            "new_stop": current_price,
            "reason": "技术性破位：关键支撑已被判定失效，不等价格打到止损，立即市价砍"
        }

    # 场景2: ATR扩张 >30%
    if new_atr and atr > 0:
        atr_expansion = (new_atr - atr) / atr
        if atr_expansion > 0.3:
            new_stop = entry_price - 2.5 * new_atr if is_long else entry_price + 2.5 * new_atr
            return {
                "action": "widen",
                "new_stop": round(new_stop, 1),
                "reason": f"ATR扩张{atr_expansion*100:.0f}%（{atr}→{new_atr}），止损按新ATR重算至2.5倍"
            }

    # 场景3: 技术Agent吐出新支撑 → trailing止损
    if new_supports and is_long:
        # 选硬支撑中低于当前价但高于当前止损的（即能上移止损）
        candidates = [s for s in new_supports
                      if s.get("hardness") == "hard"
                      and s.get("price", 0) > current_stop
                      and s.get("price", 0) < current_price]
        if candidates:
            best = max(candidates, key=lambda s: s["price"])
            new_stop = best["price"] - 0.3 * atr
            if new_stop > current_stop:
                return {
                    "action": "trailing",
                    "new_stop": round(new_stop, 1),
                    "anchor_price": best["price"],
                    "reason": f"新hard支撑{best['price']}出现，trailing止损从{current_stop}→{round(new_stop,1)}"
                }

    return result


# ═══════════════════════════════════════════════════════════
# 四、特殊场景覆写
# ═══════════════════════════════════════════════════════════

SPECIAL_CALENDAR_EVENTS = {
    "FOMC": ["美联储", "FOMC", "利率决议"],
    "NFP": ["非农", "失业率"],
    "USDA": ["USDA", "月度供需", "种植面积"],
    "EIA": ["EIA", "原油库存"],
    "CPI": ["CPI", "通胀", "PPI"],
    "PBOC": ["央行", "MLF", "LPR", "降准"],
}


def special_scenario_override(
    symbol: str,
    current_price: float,
    atr: float,
    equity: float,
    days_to_rollover: Optional[int] = None,
    days_to_delivery: Optional[int] = None,
    is_night_session: bool = False,
    upcoming_events: Optional[List[str]] = None,
    current_lots: int = 0,
) -> Dict:
    """特殊场景覆写 — 换月/交割/夜盘/宏观事件。

    Args:
        symbol: 品种代码
        current_price: 当前价
        atr: ATR
        equity: 账户权益
        days_to_rollover: 距主力换月天数
        days_to_delivery: 距交割天数
        is_night_session: 是否夜盘
        upcoming_events: 即将发生的宏观事件列表
        current_lots: 当前持仓手数

    Returns:
        {"override_active": bool, "suggested_lots": int,
         "stop_tolerance": float, "stop_method": str, "reasons": [...]}
    """
    reasons = []
    suggested_lots = current_lots
    stop_tolerance = 0.4  # 默认0.4×ATR

    # 1. 换月周
    if days_to_rollover is not None and days_to_rollover <= 5:
        suggested_lots = max(1, int(current_lots * 0.5))
        stop_tolerance = 1.0  # 放宽到1ATR
        reasons.append(f"距换月{days_to_rollover}天，降仓50%，hard支撑降级为soft")

    # 2. 交割月前
    if days_to_delivery is not None and days_to_delivery <= 5:
        suggested_lots = min(suggested_lots, max(1, int(equity * 0.05) // 10000))
        reasons.append(f"距交割{days_to_delivery}天，强制降仓至30%以下")

    # 3. 夜盘低流动性
    if is_night_session:
        stop_tolerance = max(stop_tolerance, 0.6)
        reasons.append("夜盘低流动性，止损放宽0.5ATR")

    # 4. 宏观事件日
    if upcoming_events:
        found_events = []
        for event_type, keywords in SPECIAL_CALENDAR_EVENTS.items():
            for ev in upcoming_events:
                for kw in keywords:
                    if kw in ev:
                        found_events.append(ev)
                        break
        if found_events:
            suggested_lots = max(1, int(suggested_lots * 0.3))
            reasons.append(f"宏观事件{found_events}临近，降仓70%，技术置信度打折50%")

    return {
        "override_active": len(reasons) > 0,
        "suggested_lots": suggested_lots,
        "stop_tolerance": round(stop_tolerance, 2),
        "reasons": reasons,
    }


# ═══════════════════════════════════════════════════════════
# 五、反馈闭环
# ═══════════════════════════════════════════════════════════

def build_feedback_entry(
    symbol: str,
    anchor_price: float,
    anchor_source: str,
    stop_hit: bool,
    hit_scenario: str,
    outcome: str,
) -> Dict:
    """构建反馈闭环的日志条目 — 风控明→技术Agent的回流数据。

    Args:
        symbol: 品种代码
        anchor_price: 选用的止损锚价位
        anchor_source: 锚来源（如"volume_profile_POC"）
        stop_hit: 是否被打到
        hit_scenario: "假破_OI未增_30min收回" | "实破_OI增" | "逻辑止损"
        outcome: "扫损后反弹" | "破位续跌" | "假破收回"

    Returns:
        dict: 格式化的反馈条目
    """
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "anchor_price": anchor_price,
        "anchor_source": anchor_source,
        "stop_hit": stop_hit,
        "hit_scenario": hit_scenario,
        "outcome": outcome,
    }


def aggregate_feedback(feedback_entries: List[Dict]) -> Dict:
    """汇总反馈条目，生成技术Agent可用统计。

    Returns:
        {"total_stops": int, "fake_break_pct": float,
         "real_break_pct": float, "worst_sources": [...],
         "suggestions": [...]}
    """
    if not feedback_entries:
        return {"total_stops": 0, "fake_break_pct": 0, "real_break_pct": 0}

    total = len(feedback_entries)
    fake = sum(1 for e in feedback_entries if "假破" in e.get("hit_scenario", ""))
    real = sum(1 for e in feedback_entries if "实破" in e.get("hit_scenario", ""))
    logic = sum(1 for e in feedback_entries if "逻辑止损" in e.get("hit_scenario", ""))

    # 分析不同来源的锚的假破率
    source_stats = {}
    for e in feedback_entries:
        src = e.get("anchor_source", "unknown")
        if src not in source_stats:
            source_stats[src] = {"total": 0, "fake": 0, "real": 0}
        source_stats[src]["total"] += 1
        if "假破" in e.get("hit_scenario", ""):
            source_stats[src]["fake"] += 1
        if "实破" in e.get("hit_scenario", ""):
            source_stats[src]["real"] += 1

    worst = sorted(source_stats.items(),
                   key=lambda x: x[1]["fake"] / max(x[1]["total"], 1),
                   reverse=True)[:3]

    suggestions = []
    for src, stats in worst:
        if stats["fake"] / max(stats["total"], 1) > 0.6:
            suggestions.append(f"{src}假破率{stats['fake']/stats['total']*100:.0f}%，建议下次同类型加容差至0.6ATR")

    return {
        "total_stops": total,
        "fake_break_pct": round(fake / max(total, 1) * 100, 1),
        "real_break_pct": round(real / max(total, 1) * 100, 1),
        "logic_stop_ct": logic,
        "worst_sources": [{"source": s, "fake_pct": round(st["fake"]/max(st["total"],1)*100,1)}
                          for s, st in worst],
        "suggestions": suggestions,
    }
