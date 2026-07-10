"""
signal_classifier.py — 信号分级路由模块 v1.0.0
==============================================

适用范围: FDT 辩论专家团（futures-debate-team）
功能: 根据数技源 scan_all 输出，实时判定信号强度等级并路由到不同的辩论模式

等级体系:
  C1 (强信号) → fast profile, ~8min 出结论
  C2 (中信号) → 简化辩论, ~20min
  C3 (模糊信号) → 全流程, ~40min
  C4 (无信号) → 跳过辩论

用法:
  from scripts.signal_classifier import classify_signal, SignalTier

  scan_output = load_scan_result("full_scan_channel_breakout_20260711.json")
  tier = classify_signal(scan_output)
  profile = tier_to_profile(tier)
  # → profile = "fast" / "normal" / "full"
"""

from enum import Enum
from typing import Optional


class SignalTier(str, Enum):
    """信号强度等级"""
    C1 = "C1"  # 强信号 — fast profile
    C2 = "C2"  # 中信号 — 简化辩论
    C3 = "C3"  # 模糊信号 — 全流程
    C4 = "C4"  # 无信号 — 跳过


# ── 判定阈值 ──

THRESHOLDS = {
    "adx_strong": 40,         # ADX > 40 → 趋势强劲
    "rsi_lower": 25,          # RSI > 25
    "rsi_upper": 75,          # RSI < 75
    "bb_width_min": 0.2,      # BB带宽 > 0.2 → 波动扩张
    "chain_consensus_min": 0.75,  # 链一致性 > 75%
    "min_conditions_c1": 3,   # C1 需要 ≥3 条件满足
    "min_conditions_c2": 2,   # C2 需要 ≥2 条件满足
}


# ── 核心分类逻辑 ──

def classify_signal(scan_result: dict) -> SignalTier:
    """
    对单个品种的信号做强度分级。

    输入格式 (来自 scan_all 的 JSON):
    {
        "symbol": "RB",
        "signal_type": "channel_breakout" | "trend_confirmation"
                    | "bb_squeeze_prebreakout" | null,
        "adx": 52.3,
        "rsi": 42.1,
        "bb_width": 0.35,
        "bb_status": "expanding",
        "chain_consensus": 0.82,
        "dc20_position": 0.85,
        "dc55_position": 0.72,
        "volume_ratio": 1.8,
    }

    返回: SignalTier.C1 ~ C4
    """
    # 提取字段 (带默认值)
    signal_type = scan_result.get("signal_type")
    adx = scan_result.get("adx", 0) or 0
    rsi = scan_result.get("rsi", 50) or 50
    bb_width = scan_result.get("bb_width", 0) or 0
    chain_consensus = scan_result.get("chain_consensus", 0) or 0
    volume_ratio = scan_result.get("volume_ratio", 1.0) or 1.0

    # C4: 无通道突破信号 → 跳过
    if signal_type not in ("channel_breakout", "trend_confirmation",
                           "bb_squeeze_prebreakout"):
        return SignalTier.C4

    # 统计满足条件的数量
    conditions_met = 0

    if adx > THRESHOLDS["adx_strong"]:
        conditions_met += 1

    if THRESHOLDS["rsi_lower"] < rsi < THRESHOLDS["rsi_upper"]:
        conditions_met += 1

    if bb_width > THRESHOLDS["bb_width_min"]:
        conditions_met += 1

    if chain_consensus > THRESHOLDS["chain_consensus_min"]:
        conditions_met += 1

    if volume_ratio > 1.5:  # 放量确认
        conditions_met += 1

    # 路由决策（带边界保护）
    if conditions_met >= THRESHOLDS["min_conditions_c1"] and \
       signal_type == "channel_breakout":
        return SignalTier.C1

    if conditions_met >= THRESHOLDS["min_conditions_c2"]:
        # 检查是否因极端 RSI 而降级
        if rsi <= 10 or rsi >= 90:
            return SignalTier.C3  # 极端 RSI → 模糊信号
        return SignalTier.C2

    return SignalTier.C3


def tier_to_profile(tier: SignalTier) -> str:
    """信号等级 → 协调层 profile 名称"""
    mapping = {
        SignalTier.C1: "fast",
        SignalTier.C2: "normal",    # 需新建
        SignalTier.C3: "full",       # 当前 default 行为
        SignalTier.C4: "skip",
    }
    return mapping[tier]


def tier_to_debate_rounds(tier: SignalTier) -> int:
    """信号等级 → 辩论轮次"""
    mapping = {
        SignalTier.C1: 0,     # 无辩论，直接 fast
        SignalTier.C2: 2,     # 立论 + 1轮rebuttal
        SignalTier.C3: 4,     # 立论 + rebuttal + 交锋 + final
        SignalTier.C4: 0,     # 跳过
    }
    return mapping[tier]


def tier_description(tier: SignalTier) -> str:
    """信号等级 → 中文描述"""
    descriptions = {
        SignalTier.C1: "🔴 强信号 — 多因子共振，走快车道 (~8min)",
        SignalTier.C2: "🟡 中信号 — 部分条件满足，简化辩论 (~20min)",
        SignalTier.C3: "🔵 模糊信号 — 矛盾/边界, 全流程 (~40min)",
        SignalTier.C4: "⚪ 无信号 — 跳过辩论",
    }
    return descriptions.get(tier, "未知")


# ── 批量分类（全品种裁决） ──

def classify_all(scan_results: list[dict]) -> dict[str, SignalTier]:
    """
    批量分类 scan_all 输出的所有品种。
    输入: scan_all 的输出列表（每个品种一条）
    输出: { "RB": SignalTier.C1, "SC": SignalTier.C4, ... }
    """
    results = {}
    for item in scan_results:
        symbol = item.get("symbol", "")
        if symbol:
            results[symbol] = classify_signal(item)
    return results


def summarize_tiers(tier_map: dict[str, SignalTier]) -> dict:
    """汇总各等级品种数量"""
    from collections import Counter
    counts = Counter(tier_map.values())
    return {
        "total": len(tier_map),
        "C1": counts.get(SignalTier.C1, 0),
        "C2": counts.get(SignalTier.C2, 0),
        "C3": counts.get(SignalTier.C3, 0),
        "C4": counts.get(SignalTier.C4, 0),
        "fast_candidates": [k for k, v in tier_map.items() if v == SignalTier.C1],
        "skip_candidates": [k for k, v in tier_map.items() if v == SignalTier.C4],
    }
