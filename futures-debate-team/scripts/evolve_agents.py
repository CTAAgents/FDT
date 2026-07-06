#!/usr/bin/env python3
"""
子Agent自进化引擎 — 从验证数据中提取各Agent的表现信号，驱动参数自调整。

被监控的Agent和进化维度:
  风控明:   止损触发率 → ATR乘数 / 最大仓位%
  策执远:   方向+入场 → 仓位公式系数 / RR目标
  证真/慎思: 辩论胜率 → 论据策略权重
  链证源:   去重准确率 → 相关系数阈值

用法:
  python evolve_agents.py

输入: execution_followup.json + calibration.json
输出: memory/agent_profiles.json (更新)
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict


# ─── 工具函数 ───────────────────────────────────────────

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_or_create_profile(profiles_path):
    if os.path.exists(profiles_path):
        return load_json(profiles_path)
    return {
        "_meta": {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": "1.0"},
        "闫判官": {"type": "judge", "evolution": "calibration.json（独立系统）"},
    }


def get_validated_verdicts(followup_path):
    """提取所有已验证的裁决（正确/错误）"""
    followup = load_json(followup_path)
    results = []
    for record in followup["records"]:
        if not record.get("validated"):
            continue
        vr = record.get("validation_results", {})
        if not vr.get("validatable"):
            continue
        verdicts = record["verdicts"]
        val_results = vr.get("results", [])
        for i, v in enumerate(verdicts):
            if i < len(val_results) and val_results[i].get("correct") is not None:
                results.append({
                    "symbol": v.get("symbol",""),
                    "direction": v.get("direction",""),
                    "confidence": v.get("confidence","中"),
                    "adx": v.get("adx",0),
                    "rsi": v.get("rsi",50),
                    "entry_price": v.get("entry_price",0),
                    "stop_loss": v.get("stop_loss",0),
                    "target1": v.get("target_price",0),
                    "target2": v.get("target2_price",0),
                    "position_pct": v.get("position_pct",0),
                    "chain": v.get("chain",""),
                    "conflict": v.get("conflict",False),
                    "correct": val_results[i]["correct"],
                    "change_pct": val_results[i].get("change_pct",0),
                    "pnl_pct": val_results[i].get("pnl_pct",0),
                })
    return results


# ─── Agent1: 风控明 ─────────────────────────────────────

def evolve_risk_manager(verdicts, profile):
    """
    进化维度:
    - ATR乘数: 止损距 = atr_multiplier × ATR。止损频率过高→放宽, 过低→收紧
    - 最大仓位%: 高置信度品种上限。连续亏损→降低
    - veto阈值: ADX低于此值时额外审查

    衡量指标:
    - stop_hit_rate: 方向对了但被止损扫出的比例（理想: <15%）
    - max_drawdown_pct: 单品种最大亏损%
    """
    total = len(verdicts)
    if total < 5:
        return profile

    # 计算止损触发预估（方向正确但日内触及止损价的比例）
    # 简化: 用 (stop_loss - entry) / entry 来衡量止损紧张度
    tight_stops = []
    for v in verdicts:
        if v["entry_price"] > 0:
            stop_dist = abs(v["stop_loss"] - v["entry_price"]) / v["entry_price"]
            tight_stops.append(stop_dist)

    avg_stop_dist = sum(tight_stops) / len(tight_stops) if tight_stops else 0.025

    # 止损距离评估
    if avg_stop_dist < 0.02:
        # 止损太紧 → 放宽
        adjustment = +0.2
        reason = f"平均止损距仅{avg_stop_dist*100:.1f}%, 放宽ATR乘数"
    elif avg_stop_dist > 0.045:
        adjustment = -0.2
        reason = f"平均止损距{avg_stop_dist*100:.1f}%, 收紧ATR乘数"
    else:
        adjustment = 0
        reason = f"止损距{avg_stop_dist*100:.1f}%合理, 维持不变"

    # 最大仓位评估
    wrong_high_conf = [v for v in verdicts if v["confidence"] == "高" and not v["correct"]]
    correct_high_conf = [v for v in verdicts if v["confidence"] == "高" and v["correct"]]
    high_conf_total = len(wrong_high_conf) + len(correct_high_conf)
    
    if high_conf_total >= 3:
        high_conf_acc = len(correct_high_conf) / high_conf_total
        if high_conf_acc < 0.5:
            max_pos_adj = -1.0
            pos_reason = f"高置信度准确率仅{high_conf_acc*100:.0f}%, 仓位上限-1%"
        elif high_conf_acc > 0.75:
            max_pos_adj = +0.5
            pos_reason = f"高置信度准确率{high_conf_acc*100:.0f}%, 仓位上限+0.5%"
        else:
            max_pos_adj = 0
            pos_reason = f"高置信度准确率{high_conf_acc*100:.0f}%合理"
    else:
        max_pos_adj = 0
        pos_reason = "样本不足"

    atr_mult = profile.get("atr_multiplier", 1.5) + adjustment
    atr_mult = max(0.8, min(2.5, atr_mult))

    max_pos = profile.get("max_position_pct_high", 5.0) + max_pos_adj
    max_pos = max(2.0, min(8.0, max_pos))

    return {
        **profile,
        "atr_multiplier": round(atr_mult, 1),
        "max_position_pct_high": round(max_pos, 1),
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "atr_multiplier", "from": profile.get("atr_multiplier",1.5), "to": round(atr_mult,1), "reason": reason},
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "max_position_high", "from": profile.get("max_position_pct_high",5.0), "to": round(max_pos,1), "reason": pos_reason},
        ],
        "_stats": {
            "total_validated": total,
            "avg_stop_distance_pct": round(avg_stop_dist * 100, 1),
            "high_conf_accuracy": round(high_conf_acc * 100, 1) if high_conf_total >= 3 else None,
        }
    }


# ─── Agent2: 策执远 ─────────────────────────────────────

def evolve_strategist(verdicts, profile):
    """
    进化维度:
    - RR目标系数: 当前RR=2.0。如果达到T1的比例太低 → 提高RR
    - 仓位衰减系数: 连续亏损 → 降低仓位系数
    - 分批止盈比例: T1减仓% vs T2减仓%

    衡量指标:
    - hit_rate_t1: 方向正确品种中达到T1的比例
    - avg_pnl: 平均单品种盈亏%
    """
    total = len(verdicts)
    if total < 5:
        return profile

    correct = [v for v in verdicts if v["correct"]]
    avg_pnl = sum(v["pnl_pct"] for v in verdicts) / total

    # RR评估: 检查T1 target是否合理
    # 如果大部分正确品种已经过了T1 → RR可能太保守, 可调高
    # 如果正确品种都A不到T1 → RR太激进
    t1_hits = 0
    for v in correct:
        if v["direction"] == "bear" and v["change_pct"] < -0.03:
            t1_hits += 1
        elif v["direction"] == "bull" and v["change_pct"] > 0.03:
            t1_hits += 1

    t1_ratio = t1_hits / len(correct) if correct else 0

    if t1_ratio > 0.7 and avg_pnl > 2.0:
        rr_adj = +0.3
        rr_reason = f"T1达标率{t1_ratio*100:.0f}%, 盈亏充足, RR上调"
    elif t1_ratio < 0.3:
        rr_adj = -0.3
        rr_reason = f"T1达标率仅{t1_ratio*100:.0f}%, RR过高, 下调"
    else:
        rr_adj = 0
        rr_reason = f"T1达标率{t1_ratio*100:.0f}%合理"

    # 仓位系数评估
    if avg_pnl < -2.0:
        pos_decay = 0.9  # 整体亏损 → 仓位×0.9
        pos_reason = f"整体均亏{avg_pnl:+.1f}%, 仓位系数×0.9"
    elif avg_pnl > 3.0:
        pos_decay = 1.05
        pos_reason = f"整体均盈{avg_pnl:+.1f}%, 仓位系数×1.05"
    else:
        pos_decay = 1.0
        pos_reason = f"均盈亏{avg_pnl:+.1f}%合理"

    rr_target = profile.get("rr_target", 2.0) + rr_adj
    rr_target = max(1.5, min(3.0, rr_target))

    pos_coeff = round(profile.get("position_coefficient", 1.0) * pos_decay, 2)
    pos_coeff = max(0.5, min(1.5, pos_coeff))

    return {
        **profile,
        "rr_target": round(rr_target, 1),
        "position_coefficient": pos_coeff,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "rr_target", "from": profile.get("rr_target",2.0), "to": round(rr_target,1), "reason": rr_reason},
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "position_coefficient", "from": profile.get("position_coefficient",1.0), "to": pos_coeff, "reason": pos_reason},
        ],
        "_stats": {
            "total_validated": total,
            "correct_count": len(correct),
            "t1_hit_ratio": round(t1_ratio * 100, 1),
            "avg_pnl_pct": round(avg_pnl, 1),
        }
    }


# ─── Agent3: 证真 + 慎思 (辩手) ─────────────────────────

def evolve_debaters(verdicts, profile):
    """
    进化维度:
    - bullish_argument_count: 多头辩手使用的论据数量 → 影响辩论时长
    - preference_divergence: 偏好分歧指数 → 是否需要更多轮辩论

    衡量指标:
    - direction_win_rate: 辩论方向的胜率
    - 从闫判官的评分中提取辩手表现

    注: 辩手进化依赖辩论日志中的详细评分数据。
    当前只有方向正确性, 没有辩论过程评分, 用方向胜率作为代理指标。
    """
    total = len(verdicts)
    if total < 5:
        return profile

    bull_verdicts = [v for v in verdicts if v["direction"] == "bull"]
    bear_verdicts = [v for v in verdicts if v["direction"] == "bear"]

    bull_correct = sum(1 for v in bull_verdicts if v["correct"])
    bear_correct = sum(1 for v in bear_verdicts if v["correct"])

    bull_acc = bull_correct / len(bull_verdicts) * 100 if bull_verdicts else 0
    bear_acc = bear_correct / len(bear_verdicts) * 100 if bear_verdicts else 0

    # 证真(多方辩手)
    bull_profile = profile.get("证真", {"strategy": "默认", "confidence_boost": 0})
    if len(bull_verdicts) >= 3:
        if bull_acc > 65:
            bull_boost = +1.0
            bull_note = "胜率高, 加强多头论述"
        elif bull_acc < 40:
            bull_boost = -1.0
            bull_note = "胜率低, 收敛多头论述"
        else:
            bull_boost = 0
            bull_note = "表现稳定"
        bull_profile["confidence_boost"] = round(bull_profile.get("confidence_boost", 0) + bull_boost * 0.3, 1)
        bull_profile["strategy"] = "激进" if bull_acc > 65 else ("保守" if bull_acc < 40 else "默认")
        bull_profile["_win_rate"] = round(bull_acc, 1)
        bull_profile["_samples"] = len(bull_verdicts)
        bull_profile["_note"] = bull_note

    # 慎思(空方辩手)
    bear_profile = profile.get("慎思", {"strategy": "默认", "confidence_boost": 0})
    if len(bear_verdicts) >= 3:
        if bear_acc > 65:
            bear_boost = +1.0
            bear_note = "胜率高, 加强空头论述"
        elif bear_acc < 40:
            bear_boost = -1.0
            bear_note = "胜率低, 收敛空头论述"
        else:
            bear_boost = 0
            bear_note = "表现稳定"
        bear_profile["confidence_boost"] = round(bear_profile.get("confidence_boost", 0) + bear_boost * 0.3, 1)
        bear_profile["strategy"] = "激进" if bear_acc > 65 else ("保守" if bear_acc < 40 else "默认")
        bear_profile["_win_rate"] = round(bear_acc, 1)
        bear_profile["_samples"] = len(bear_verdicts)
        bear_profile["_note"] = bear_note

    return {
        **profile,
        "证真": bull_profile,
        "慎思": bear_profile,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ─── Agent4: 链证源 ────────────────────────────────────

def evolve_chain_analyst(verdicts, profile):
    """
    进化维度:
    - dedup_threshold: 链内去重相关系数阈值（默认0.80）
    - max_chain_reps: 每条链最多保留代表数

    衡量指标:
    - dedup_accuracy: 去重保留的代表品种方向是否正确
      若代表品种方向正确 且 被去重品种也正确 → dedup无损失
      若代表品种方向正确 但 被去重品种错误 → dedup有价值
      若代表品种方向错误 但 被去重品种正确 → dedup误删有用信号（收紧阈值）
    """
    total = len(verdicts)
    if total < 10:
        return profile

    # 按产业链分组验证
    chain_results = defaultdict(list)
    for v in verdicts:
        chain_results[v["chain"]].append(v["correct"])

    # 计算各链准确率
    chain_accuracies = {}
    for chain, results in chain_results.items():
        if len(results) >= 3:
            chain_accuracies[chain] = sum(results) / len(results)

    if not chain_accuracies:
        return profile

    avg_chain_acc = sum(chain_accuracies.values()) / len(chain_accuracies)

    # 如果大多数链准确率>70% → 链分析有效 → 可以收紧去重（信任链内一致性）
    # 如果大多数链准确率<50% → 链分析无效 → 放宽去重（多保留品种避免误删）
    if avg_chain_acc > 0.70:
        threshold_adj = +0.03
        reps_adj = 0
        reason = f"链准确率{avg_chain_acc*100:.0f}%, 去重有效, 收紧阈值"
    elif avg_chain_acc < 0.55:
        threshold_adj = -0.05
        reps_adj = +1
        reason = f"链准确率仅{avg_chain_acc*100:.0f}%, 去重可能误删, 放宽阈值+增加代表"
    else:
        threshold_adj = 0
        reps_adj = 0
        reason = f"链准确率{avg_chain_acc*100:.0f}%合理"

    dedup_threshold = profile.get("dedup_threshold", 0.80) + threshold_adj
    dedup_threshold = max(0.65, min(0.90, dedup_threshold))

    max_reps = profile.get("max_chain_reps", 1) + reps_adj
    max_reps = max(1, min(3, max_reps))

    return {
        **profile,
        "dedup_threshold": round(dedup_threshold, 2),
        "max_chain_reps": max_reps,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "dedup_threshold",
             "from": profile.get("dedup_threshold",0.80), "to": round(dedup_threshold,2), "reason": reason},
        ],
        "_stats": {
            "chains_analyzed": len(chain_accuracies),
            "avg_chain_accuracy": round(avg_chain_acc * 100, 1),
        }
    }


# ─── Agent5: 数技源 ────────────────────────────────────

def evolve_data_tech(verdicts, profile):
    """
    进化维度:
    - source_priority: 数据源优先级 [通达信, 东方财富, AKShare]
    - retry_limit: 数据获取重试次数

    衡量指标:
    - data_freshness_tdx: 通达信数据覆盖率和延迟
    - 从执行日志推断数据源可用性

    注: 数技源是确定性pipeline，进化空间有限。
    主要通过数据源可用性统计调整优先级链。
    """
    # 由于数技源不直接参与裁决验证，使用间接指标
    # 如果有verified裁决数据 → 说明数据采集正常 → 维护当前配置
    total = len(verdicts)
    if total < 10:
        return profile

    # 简化: 所有裁决都有validated结果 → 说明数据采集流程健康
    success_rate = len(verdicts) / max(total, 1)

    if success_rate > 0.9:
        retry_limit = profile.get("retry_limit", 3)  # 运行良好, 维持
        reason = "数据采集流程健康, 维持配置"
    else:
        retry_limit = min(5, profile.get("retry_limit", 3) + 1)
        reason = "数据采集偶有失败, 增加重试"

    return {
        **profile,
        "retry_limit": retry_limit,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "retry_limit",
             "from": profile.get("retry_limit",3), "to": retry_limit, "reason": reason},
        ],
        "_stats": {"data_success_rate": round(success_rate * 100, 1)}
    }


# ─── Agent6: 探源(基本面研究员) ─────────────────────────

def evolve_fundamental_researcher(verdicts, profile):
    """
    进化维度:
    - fundamental_weight: 基本面在综合评分中的权重
    - search_keyword_priority: WebSearch关键词优先级

    衡量指标:
    - 基本面方向与价格方向的一致性
    用FT(因子择时)的g_group作为基本面的代理指标

    注: 探源使用WebSearch搜集基本面数据。进化主要通过:
    若基本面信号(g_group)与最终价格一致 → 增加基本面权重
    若基本面信号与价格反向 → 降低基本面权重
    """
    total = len(verdicts)
    if total < 5:
        return profile

    # 用verdicts的ft_dir作为基本面信号的代理
    consistent = 0
    inconsistent = 0
    for v in verdicts:
        ft_dir = v.get("ft_dir", "neutral")
        direction = v["direction"]
        correct = v["correct"]
        # FT方向与最终价格方向一致 → 基本面有帮助
        if ft_dir == direction and correct:
            consistent += 1
        elif ft_dir != "neutral" and ft_dir != direction and correct:
            # FT方向错误但价格跟着核心方向走 → 基本面信号有问题
            inconsistent += 1

    total_relevant = consistent + inconsistent
    if total_relevant < 5:
        return profile

    consistency = consistent / total_relevant

    if consistency > 0.7:
        weight_adj = +0.05
        reason = f"基本面一致性{consistency*100:.0f}%, 增加权重"
    elif consistency < 0.5:
        weight_adj = -0.05
        reason = f"基本面一致性仅{consistency*100:.0f}%, 降低权重"
    else:
        weight_adj = 0
        reason = f"基本面一致性{consistency*100:.0f}%合理"

    weight = round(profile.get("fundamental_weight", 0.15) + weight_adj, 2)
    weight = max(0.05, min(0.30, weight))

    return {
        **profile,
        "fundamental_weight": weight,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "fundamental_weight",
             "from": profile.get("fundamental_weight",0.15), "to": weight, "reason": reason},
        ],
        "_stats": {
            "ft_consistency": round(consistency * 100, 1),
            "relevant_samples": total_relevant,
        }
    }


# ─── Agent7: 观澜(技术面研究员) ─────────────────────────

def evolve_technical_researcher(verdicts, profile):
    """
    进化维度:
    - atr_period: ATR计算周期（影响支撑/阻力区间宽度）
    - signal_lag_tolerance: 信号延迟容忍度

    衡量指标:
    - L1-L4信号方向与价格方向的一致性
    - ADX作为趋势识别有效性的代理

    注: 观澜基于L1-L4数据做技术面分析。
    进化通过: L1-L4信号准确率反馈调整技术分析参数。
    """
    total = len(verdicts)
    if total < 5:
        return profile

    # 用ADX分层统计L1-L4信号效率
    # ADX≥50: 强趋势品种, L1-L4应该最准
    strong_trend = [v for v in verdicts if v["adx"] >= 50 and v["direction"] == "bear"]
    weak_trend = [v for v in verdicts if v["adx"] < 50 and v["direction"] == "bear"]

    strong_acc = sum(1 for v in strong_trend if v["correct"]) / len(strong_trend) if strong_trend else 0
    weak_acc = sum(1 for v in weak_trend if v["correct"]) / len(weak_trend) if weak_trend else 0

    # 强趋势准确率应显著高于弱趋势
    # 如果差异太小 → 技术分析区分度不够 → 调整ATR周期
    if len(strong_trend) >= 5 and len(weak_trend) >= 5:
        gap = strong_acc - weak_acc
        if gap > 0.3:
            atr_period = profile.get("atr_period", 14)  # 区分度好, 维持
            lag_adj = 0
            reason = f"强趋势vs弱趋势精度差{gap*100:.0f}%, 区分度好"
        elif gap < 0.1:
            atr_period = profile.get("atr_period", 14) + 2
            lag_adj = +1
            reason = f"强弱趋势精度差仅{gap*100:.0f}%, 增加ATR周期提升区分度"
        else:
            atr_period = profile.get("atr_period", 14)
            lag_adj = 0
            reason = f"精度差{gap*100:.0f}%合理"
    else:
        atr_period = profile.get("atr_period", 14)
        lag_adj = 0
        reason = "样本不足"

    return {
        **profile,
        "atr_period": atr_period,
        "signal_lag_tolerance": profile.get("signal_lag_tolerance", 2) + lag_adj,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_evolution_log": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "atr_period",
             "from": profile.get("atr_period",14), "to": atr_period, "reason": reason},
        ],
        "_stats": {
            "strong_trend_accuracy": round(strong_acc * 100, 1) if strong_trend else None,
            "weak_trend_accuracy": round(weak_acc * 100, 1) if weak_trend else None,
        }
    }


# ─── 主程序 ───────────────────────────────────────────

def main():
    script_dir = Path(__file__).parent.parent
    followup_path = str(script_dir / "memory" / "execution_followup.json")
    profiles_path = str(script_dir / "memory" / "agent_profiles.json")

    verdicts = get_validated_verdicts(followup_path)
    print(f"已验证裁决: {len(verdicts)}条")

    if len(verdicts) < 5:
        print(f"⚠️ 样本不足({len(verdicts)}<5), 所有Agent跳过进化")
        return

    profiles = load_or_create_profile(profiles_path)

    # 按顺序进化
    for agent_name, evolve_fn, default_profile in [
        ("风控明", evolve_risk_manager, {"atr_multiplier": 1.5, "max_position_pct_high": 5.0}),
        ("策执远", evolve_strategist, {"rr_target": 2.0, "position_coefficient": 1.0}),
        ("链证源", evolve_chain_analyst, {"dedup_threshold": 0.80, "max_chain_reps": 1}),
        ("数技源", evolve_data_tech, {"source_priority": ["通达信", "东方财富", "AKShare"], "retry_limit": 3}),
        ("探源", evolve_fundamental_researcher, {"fundamental_weight": 0.15}),
        ("观澜", evolve_technical_researcher, {"atr_period": 14, "signal_lag_tolerance": 2}),
    ]:
        current = profiles.get(agent_name, default_profile)
        new_profile = evolve_fn(verdicts, current)
        profiles[agent_name] = new_profile
        print(f"\n{'='*50}")
        print(f"🤖 {agent_name} 进化:")
        for log in new_profile.get("_evolution_log", []):
            sign = "+" if log["to"] > log["from"] else ""
            print(f"  {log['action']}: {log['from']} → {sign}{log['to']}  ({log['reason']})")

    # 辩手进化
    debater_default = {"证真": {}, "慎思": {}}
    current = profiles.get("辩手", debater_default)
    new_profiles = evolve_debaters(verdicts, current)
    profiles["辩手"] = new_profiles

    print(f"\n🤖 辩手进化:")
    for name in ["证真", "慎思"]:
        p = new_profiles.get(name, {})
        if p:
            print(f"  {name}: 策略={p.get('strategy','?')}, 胜率={p.get('_win_rate','?')}%, "
                  f"置信度偏移={p.get('confidence_boost',0):+.1f}, {p.get('_note','')}")

    profiles["_meta"]["last_evolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    profiles["_meta"]["total_samples"] = len(verdicts)

    save_json(profiles_path, profiles)
    print(f"\n✅ Agent进化配置已保存: {profiles_path}")


if __name__ == "__main__":
    main()
