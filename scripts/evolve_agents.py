#!/usr/bin/env python3
"""
子Agent自进化引擎 — 从验证数据中提取各Agent的表现信号，驱动参数自调整。

被监控的Agent和进化维度:
  风控明:   止损触发率 → ATR乘数 / 最大仓位%
  闫判官:   方向+入场 → 仓位公式系数 / RR目标（v8.7.0 合并自原执行方案）
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

def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_or_create_profile(profiles_path: str) -> dict:
    if os.path.exists(profiles_path):
        return load_json(profiles_path)
    return {
        "_meta": {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": "1.0"},
        "闫判官": {"type": "judge", "evolution": "calibration.json（独立系统）"},
    }


def get_validated_verdicts(followup_path: str) -> list:
    """提取所有已验证的裁决（含真实stop/target触发标签）"""
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
                val = val_results[i]
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
                    "correct": val["correct"],
                    "realized_pnl_pct": val.get("realized_pnl_pct", 0),
                    "hit_stop": val.get("hit_stop", False),
                    "hit_target1": val.get("hit_target1", False),
                    "hit_target2": val.get("hit_target2", False),
                    "gap_stop": val.get("gap_stop", False),
                })
    return results


# ─── Agent1: 风控明 ─────────────────────────────────────

def evolve_risk_manager(verdicts: list, profile: dict) -> dict:
    """
    进化维度:
    - ATR乘数: 止损距 = atr_multiplier × ATR。真实止损触发率 > 15% → 放宽
    - 最大仓位%: 真实实现盈亏连续亏损 → 降低
    - veto阈值: ADX低于此值时额外审查

    衡量指标:
    - real_stop_hit_rate: 验证层检测到的真实止损触发率(理想 <15%)
    - avg_realized_pnl: 真实实现盈亏(含跳空扫损)
    """
    total = len(verdicts)
    if total < 5:
        return profile

    # 真实止损触发率
    stop_hits = sum(1 for v in verdicts if v.get("hit_stop"))
    gap_hits = sum(1 for v in verdicts if v.get("gap_stop"))
    real_stop_hit_rate = stop_hits / total if total > 0 else 0

    # 真实实现盈亏
    realized_pnls = [v.get("realized_pnl_pct", 0) for v in verdicts if v.get("realized_pnl_pct", 0)]
    avg_realized_pnl = sum(realized_pnls) / len(realized_pnls) if realized_pnls else 0

    # 止损触发率评估（替代旧的avg_stop_dist代理）
    if real_stop_hit_rate > 0.15:
        adjustment = +0.3
        reason = f"真实止损触发率{real_stop_hit_rate*100:.1f}% > 15%, 放宽ATR乘数"
    elif real_stop_hit_rate < 0.05 and total >= 10:
        adjustment = -0.2
        reason = f"真实止损触发率{real_stop_hit_rate*100:.1f}% < 5%, 收紧ATR乘数"
    else:
        adjustment = 0
        reason = f"止损触发率{real_stop_hit_rate*100:.1f}%合理, 维持不变"

    # 跳空扫损率报警
    gap_warning = ""
    gap_rate = gap_hits / total if total > 0 else 0
    if gap_rate > 0.10:
        gap_warning = f" ⚠️跳空扫损{gap_rate*100:.1f}%(>10%), 建议放宽夜盘止损距"

    # 最大仓位评估：用真实实现盈亏替代方向正确率
    wrong_costly = [v for v in verdicts if not v["correct"] and v.get("realized_pnl_pct", 0) < -2.0]
    correct_good = [v for v in verdicts if v["correct"] and v.get("realized_pnl_pct", 0) > 0]
    high_conf_total = len(wrong_costly) + len(correct_good)

    if high_conf_total >= 3:
        high_conf_pnl = sum(v.get("realized_pnl_pct", 0) for v in wrong_costly + correct_good)
        if high_conf_pnl < -5.0:  # 高置信度品种合计亏损>5%
            max_pos_adj = -1.0
            pos_reason = f"高置信度品种累计亏损{high_conf_pnl:+.1f}%, 仓位上限-1%"
        elif high_conf_pnl > 5.0:
            max_pos_adj = +0.5
            pos_reason = f"高置信度品种总盈利{high_conf_pnl:+.1f}%, 仓位上限+0.5%"
        else:
            max_pos_adj = 0
            pos_reason = f"高置信度品种累计盈亏{high_conf_pnl:+.1f}%合理"
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
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "atr_multiplier",
             "from": profile.get("atr_multiplier",1.5), "to": round(atr_mult,1),
             "reason": reason + gap_warning},
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "max_position_high",
             "from": profile.get("max_position_pct_high",5.0), "to": round(max_pos,1),
             "reason": pos_reason},
        ],
        "_stats": {
            "total_validated": total,
            "real_stop_hit_rate": round(real_stop_hit_rate * 100, 1),
            "gap_stop_rate": round(gap_rate * 100, 1),
            "avg_realized_pnl_pct": round(avg_realized_pnl, 1),
        }
    }


# ─── Agent2: 原策执远(已合并至闫判官) ────────────────────

def evolve_strategist(verdicts: list, profile: dict) -> dict:
    """
    进化维度:
    - RR目标系数: 当前RR=2.0。真实T1达标率 > 70% → 可调高
    - 仓位衰减系数: 真实实现PnL连续亏损 → 降低仓位系数
    - 分批止盈比例: T1减仓% vs T2减仓%

    衡量指标:
    - real_target_hit_rate: 验证层检测到真实触及T1的比例
    - avg_realized_pnl: 真实实现盈亏
    """
    total = len(verdicts)
    if total < 5:
        return profile

    avg_realized_pnl = sum(v.get("realized_pnl_pct", 0) for v in verdicts) / total

    # 真实T1达标率（替代旧的 change_pct > 3% 代理）
    correct = [v for v in verdicts if v["correct"]]
    target_hits = sum(1 for v in correct if v.get("hit_target1"))
    t1_ratio = target_hits / len(correct) if correct else 0

    if t1_ratio > 0.7 and avg_realized_pnl > 2.0:
        rr_adj = +0.3
        rr_reason = f"真实T1达标率{t1_ratio*100:.0f}%, 盈亏充足, RR上调"
    elif t1_ratio < 0.3:
        rr_adj = -0.3
        rr_reason = f"真实T1达标率仅{t1_ratio*100:.0f}%, RR过高, 下调"
    else:
        rr_adj = 0
        rr_reason = f"真实T1达标率{t1_ratio*100:.0f}%合理"

    # 仓位系数评估：用真实实现盈亏
    if avg_realized_pnl < -2.0:
        pos_decay = 0.9
        pos_reason = f"均实现盈亏{avg_realized_pnl:+.1f}%, 仓位系数×0.9"
    elif avg_realized_pnl > 3.0:
        pos_decay = 1.05
        pos_reason = f"均实现盈亏{avg_realized_pnl:+.1f}%, 仓位系数×1.05"
    else:
        pos_decay = 1.0
        pos_reason = f"均实现盈亏{avg_realized_pnl:+.1f}%合理"

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
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "rr_target",
             "from": profile.get("rr_target",2.0), "to": round(rr_target,1), "reason": rr_reason},
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "position_coefficient",
             "from": profile.get("position_coefficient",1.0), "to": pos_coeff, "reason": pos_reason},
        ],
        "_stats": {
            "total_validated": total,
            "real_target_hit_rate": round(t1_ratio * 100, 1),
            "avg_realized_pnl_pct": round(avg_realized_pnl, 1),
        }
    }


# ─── Agent3: 证真 + 慎思 (辩手) ─────────────────────────

def evolve_debaters(verdicts: list, profile: dict) -> dict:
    """
    进化维度:
    - bullish_argument_count: 多头辩手使用的论据数量 → 影响辩论时长
    - preference_divergence: 偏好分歧指数 → 是否需要更多轮辩论

    衡量指标:
    - direction_realized_pnl: 各方向真实实现盈亏（替代方向胜率代理）
    """
    total = len(verdicts)
    if total < 5:
        return profile

    bull_verdicts = [v for v in verdicts if v["direction"] == "bull"]
    bear_verdicts = [v for v in verdicts if v["direction"] == "bear"]

    bull_pnl = sum(v.get("realized_pnl_pct", 0) for v in bull_verdicts) if bull_verdicts else 0
    bear_pnl = sum(v.get("realized_pnl_pct", 0) for v in bear_verdicts) if bear_verdicts else 0

    bull_acc = sum(1 for v in bull_verdicts if v["correct"]) / len(bull_verdicts) * 100 if bull_verdicts else 0
    bear_acc = sum(1 for v in bear_verdicts if v["correct"]) / len(bear_verdicts) * 100 if bear_verdicts else 0

    # 证真(多方辩手)
    bull_profile = profile.get("证真", {"strategy": "默认", "confidence_boost": 0})
    if len(bull_verdicts) >= 3:
        if bull_acc > 65 and bull_pnl > 0:
            bull_boost = +1.0
            bull_note = f"胜率高({bull_acc:.0f}%)+盈利({bull_pnl:+.1f}%), 加强多头论述"
        elif bull_acc < 40 or bull_pnl < -5:
            bull_boost = -1.0
            bull_note = f"胜率{bull_acc:.0f}%或亏损{bull_pnl:+.1f}%, 收敛多头论述"
        else:
            bull_boost = 0
            bull_note = f"表现稳定(胜率{bull_acc:.0f}%, 盈亏{bull_pnl:+.1f}%)"
        bull_profile["confidence_boost"] = round(bull_profile.get("confidence_boost", 0) + bull_boost * 0.3, 1)
        bull_profile["strategy"] = "激进" if (bull_acc > 65 and bull_pnl > 0) else ("保守" if (bull_acc < 40 or bull_pnl < -5) else "默认")
        bull_profile["_win_rate"] = round(bull_acc, 1)
        bull_profile["_realized_pnl"] = round(bull_pnl, 1)
        bull_profile["_samples"] = len(bull_verdicts)
        bull_profile["_note"] = bull_note

    # 慎思(空方辩手)
    bear_profile = profile.get("慎思", {"strategy": "默认", "confidence_boost": 0})
    if len(bear_verdicts) >= 3:
        if bear_acc > 65 and bear_pnl > 0:
            bear_boost = +1.0
            bear_note = f"胜率高({bear_acc:.0f}%)+盈利({bear_pnl:+.1f}%), 加强空头论述"
        elif bear_acc < 40 or bear_pnl < -5:
            bear_boost = -1.0
            bear_note = f"胜率{bear_acc:.0f}%或亏损{bear_pnl:+.1f}%, 收敛空头论述"
        else:
            bear_boost = 0
            bear_note = f"表现稳定(胜率{bear_acc:.0f}%, 盈亏{bear_pnl:+.1f}%)"
        bear_profile["confidence_boost"] = round(bear_profile.get("confidence_boost", 0) + bear_boost * 0.3, 1)
        bear_profile["strategy"] = "激进" if (bear_acc > 65 and bear_pnl > 0) else ("保守" if (bear_acc < 40 or bear_pnl < -5) else "默认")
        bear_profile["_win_rate"] = round(bear_acc, 1)
        bear_profile["_realized_pnl"] = round(bear_pnl, 1)
        bear_profile["_samples"] = len(bear_verdicts)
        bear_profile["_note"] = bear_note

    return {
        **profile,
        "证真": bull_profile,
        "慎思": bear_profile,
        "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ─── Agent4: 链证源 ────────────────────────────────────

def evolve_chain_analyst(verdicts: list, profile: dict) -> dict:
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

def evolve_data_tech(verdicts: list, profile: dict) -> dict:
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


# ─── Agent6: 辩论五维权重 ───────────────────────────────

def evolve_debate_weights(verdicts: list, profile: dict) -> dict:
    """
    进化维度: debate_brief.py 的 compute_debate_score 五维权重。
    - signal/quality/extreme/data/chain

    衡量指标: 各维度得分和品种最终 correct 的相关性。
    维度得分高+最终正确 → 该维度预测力强 → 增加权重
    维度得分高+最终错误 → 该维度噪声大 → 降低权重

    输出: memory/debate_weights.json（被 debate_brief.py 读取）
    """
    total = len(verdicts)
    if total < 10:
        return profile

    # 按维度的breakdown 分组统计
    from collections import defaultdict
    dim_hits = defaultdict(lambda: {"total_score": 0.0, "correct_count": 0, "total_count": 0})

    for v in verdicts:
        breakdown = v.get("breakdown", {})
        if not breakdown:
            continue
        correct = v["correct"]
        for dim in ["signal", "quality", "extreme", "data", "chain"]:
            score = breakdown.get(dim, 0)
            if score > 0:
                dim_hits[dim]["total_score"] += score
                dim_hits[dim]["total_count"] += 1
                if correct:
                    dim_hits[dim]["correct_count"] += 1

    # 计算每个维度的"预测力系数"
    # 预测力 = 平均得分 × 正确率
    dim_power = {}
    for dim, s in dim_hits.items():
        if s["total_count"] >= 3:
            avg_score = s["total_score"] / s["total_count"]
            accuracy = s["correct_count"] / s["total_count"]
            dim_power[dim] = round(avg_score * accuracy, 1)

    # 按预测力调整权重：高于平均的升，低于的降
    if dim_power:
        avg_power = sum(dim_power.values()) / len(dim_power)
        current = profile.get("weights", {
            "signal": 40.0, "quality": 25.0, "extreme": 20.0,
            "data": 10.0, "chain": 5.0,
        })
        adjustments = {}
        for dim, power in dim_power.items():
            if power > avg_power * 1.2:
                adjustments[dim] = +2.0
            elif power < avg_power * 0.8:
                adjustments[dim] = -2.0
            else:
                adjustments[dim] = 0

        new_weights = {}
        for dim in ["signal", "quality", "extreme", "data", "chain"]:
            new_weights[dim] = max(1.0, min(60.0,
                current.get(dim, 20.0) + adjustments.get(dim, 0)))

        # 保存到 debate_weights.json
        script_dir = Path(__file__).parent.parent
        weights_path = script_dir / "memory" / "debate_weights.json"
        weights_data = {
            "_meta": {
                "version": "v1",
                "description": "由 evolve_debate_weights 自动更新",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "total_samples": total,
            },
            "weights": new_weights,
        }
        save_json(str(weights_path), weights_data)

        return {
            **profile,
            "weights": new_weights,
            "_last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "_evolution_log": [
                {"time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "action": f"权重更新: {dim_power}",
                 "to": new_weights,
                 "reason": f"{len(verdicts)}条样本, 均预测力{avg_power:.1f}"},
            ],
            "_stats": {
                "dim_power": dim_power,
                "avg_power": round(avg_power, 1),
            }
        }

    return profile


# ─── Agent7: 探源(基本面研究员) ─────────────────────────

def evolve_fundamental_researcher(verdicts: list, profile: dict) -> dict:
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
    consistent_pnl = 0
    inconsistent_pnl = 0
    for v in verdicts:
        ft_dir = v.get("ft_dir", "neutral")
        direction = v["direction"]
        realized = v.get("realized_pnl_pct", 0)
        # FT方向与真实盈亏一致 → 基本面有帮助
        if ft_dir == direction and v["correct"]:
            consistent += 1
            consistent_pnl += realized
        elif ft_dir != "neutral" and ft_dir != direction and v["correct"]:
            inconsistent += 1
            inconsistent_pnl += realized

    total_relevant = consistent + inconsistent
    if total_relevant < 5:
        return profile

    consistency = consistent / total_relevant
    pnl_diff = consistent_pnl - inconsistent_pnl  # 一致方向与反方向的盈亏差

    if consistency > 0.7 and pnl_diff > 0:
        weight_adj = +0.05
        reason = f"基本面一致性{consistency*100:.0f}%+方向盈亏{pnl_diff:+.1f}%, 增加权重"
    elif consistency < 0.5 or pnl_diff < -5:
        weight_adj = -0.05
        reason = f"基本面一致性{consistency*100:.0f}%或方向亏损{pnl_diff:+.1f}%, 降低权重"
    else:
        weight_adj = 0
        reason = f"基本面一致性{consistency*100:.0f}%+盈亏差{pnl_diff:+.1f}%合理"

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
            "ft_pnl_diff": round(pnl_diff, 1),
            "relevant_samples": total_relevant,
        }
    }


# ─── Agent7: 观澜(技术面研究员) ─────────────────────────

def evolve_technical_researcher(verdicts: list, profile: dict) -> dict:
    """
    进化维度:
    - atr_period: ATR计算周期（影响支撑/阻力区间宽度）
    - signal_lag_tolerance: 信号延迟容忍度

    衡量指标:
    - 技术分析评分信号方向与价格方向的一致性
    - ADX作为趋势识别有效性的代理

    注: 观澜基于技术分析评分数据做技术面分析。
    进化通过: 技术分析评分信号准确率反馈调整技术分析参数。
    """
    total = len(verdicts)
    if total < 5:
        return profile

    # 用真实实现盈亏替代方向正负判准
    strong_trend = [v for v in verdicts if v["adx"] >= 50]
    weak_trend = [v for v in verdicts if v["adx"] < 50]

    strong_pnl = sum(v.get("realized_pnl_pct", 0) for v in strong_trend) if strong_trend else 0
    weak_pnl = sum(v.get("realized_pnl_pct", 0) for v in weak_trend) if weak_trend else 0
    strong_n = len(strong_trend)
    weak_n = len(weak_trend)

    # 强趋势品种平均实现盈亏应显著高于弱趋势
    if strong_n >= 5 and weak_n >= 5:
        avg_strong = strong_pnl / strong_n
        avg_weak = weak_pnl / weak_n
        gap = avg_strong - avg_weak
        if gap > 0.5:  # 强趋势平均盈亏比弱趋势高0.5%以上
            atr_period = profile.get("atr_period", 14)
            lag_adj = 0
            reason = f"强趋势均盈{avg_strong:.2f}% vs 弱趋势{avg_weak:.2f}%, 区分度好"
        elif gap < -0.3:  # 强趋势比弱趋势还差
            atr_period = profile.get("atr_period", 14) + 2
            lag_adj = +1
            reason = f"强趋势均盈{avg_strong:.2f}% < 弱趋势{avg_weak:.2f}%, 增加ATR周期"
        else:
            atr_period = profile.get("atr_period", 14)
            lag_adj = 0
            reason = f"强弱差{gap:.2f}%合理"
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
            "strong_trend_avg_pnl": round(strong_pnl / strong_n, 2) if strong_n else None,
            "weak_trend_avg_pnl": round(weak_pnl / weak_n, 2) if weak_n else None,
            "strong_n": strong_n,
            "weak_n": weak_n,
        }
    }


# ─── 知识萃取（从已验证裁决中提取品种知识）──────────

def extract_knowledge_from_validated_verdicts(followup_path: str) -> int:
    """从已验证裁决中提取品种知识并写入 knowledge/ 目录。

    在 Agent 进化完成后自动调用。从 debate_journal.json 中查找对应品种的
    完整辩论记录（含 pro_args/con_args），然后调用 extract_knowledge 入库。

    Returns:
        成功萃取的知识条目数
    """
    script_dir = Path(__file__).parent.parent
    journal_path = script_dir / "memory" / "debate_journal.json"
    if not journal_path.exists():
        return 0

    try:
        from scripts.extract_knowledge import KnowledgeExtractor
        extractor = KnowledgeExtractor()
    except ImportError:
        print("  ⚠️ extract_knowledge 模块不可用（可能是首次部署），跳过知识萃取")
        return 0

    # 读取辩论记录
    journal = load_json(str(journal_path))
    entries = journal.get("entries", [])

    # 读取已验证裁决
    if not os.path.exists(followup_path):
        return 0
    followup = load_json(followup_path)
    records = followup.get("records", [])

    # 提取已验证的 round_id + symbol 集合
    validated_rounds = set()
    for record in records:
        vr = record.get("validation_results", {})
        if vr.get("validatable") and record.get("validated"):
            for v in record.get("verdicts", []):
                symbol = v.get("symbol", "").lower()
                round_id = record.get("round", v.get("round", ""))
                if symbol and round_id:
                    validated_rounds.add((round_id, symbol))

    if not validated_rounds:
        return 0

    # 从 journal 中查找 debate_record 条目
    extracted_count = 0
    debate_records_map = {}
    for entry in entries:
        if entry.get("action") != "debate_record":
            continue
        rid = entry.get("round_id", "")
        sym = entry.get("symbol", "").lower()
        if (rid, sym) in validated_rounds:
            debate_records_map[(rid, sym)] = entry

    for (round_id, symbol), debate_record in debate_records_map.items():
        verdict = {
            "round_id": round_id,
            "direction": debate_record.get("verdict", {}).get("direction", ""),
            "confidence": debate_record.get("verdict", {}).get("confidence", 0),
            "winner": debate_record.get("verdict", {}).get("winner", ""),
            "reasoning": debate_record.get("verdict", {}).get("reasoning", ""),
        }
        try:
            result = extractor.extract_from_debate(
                variety=symbol,
                debate_record=debate_record,
                verdict=verdict,
                bypass_quality_gate=False,
            )
            if result.get("patterns_added", 0) > 0:
                extracted_count += result["patterns_added"]
                print(f"  📖 {symbol}: 新增 {result['patterns_added']} 个论证模式")
            elif result.get("key_levels_added"):
                extracted_count += 1
                print(f"  📖 {symbol}: 关键价位已更新")
            else:
                reason = result.get("skipped_reason", "无更新")
                if reason:
                    print(f"  📖 {symbol}: 跳过萃取 ({reason})")
        except Exception as e:
            print(f"  ⚠️ {symbol} 知识萃取异常: {e}")

    if extracted_count > 0:
        print(f"  ✅ 知识萃取完成: {extracted_count} 条目更新")
    return extracted_count


# ─── 主程序 ───────────────────────────────────────────

def main() -> None:
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
        ("闫判官", evolve_strategist, {"rr_target": 2.0, "position_coefficient": 1.0}),
        ("链证源", evolve_chain_analyst, {"dedup_threshold": 0.80, "max_chain_reps": 1}),
        ("数技源", evolve_data_tech, {"source_priority": ["通达信", "东方财富", "AKShare"], "retry_limit": 3}),
        ("训辩权重", evolve_debate_weights, {"weights": {"signal": 40.0, "quality": 25.0, "extreme": 20.0, "data": 10.0, "chain": 5.0}}),
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
            def _fmt_num(v: float, suffix: str = "") -> str:
                try:
                    return f"{float(v):+.1f}{suffix}"
                except (ValueError, TypeError):
                    return f"{v}{suffix}"
            print(f"  {name}: 策略={p.get('strategy','?')}, "
                  f"胜率={p.get('_win_rate','?')}%, "
                  f"实现盈亏={_fmt_num(p.get('_realized_pnl','?'), '%')}, "
                  f"置信度偏移={_fmt_num(p.get('confidence_boost',0))}")

    profiles["_meta"]["last_evolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    profiles["_meta"]["total_samples"] = len(verdicts)

    save_json(profiles_path, profiles)
    print(f"\n✅ Agent进化配置已保存: {profiles_path}")

    # ── 知识萃取（非阻断） ──
    print(f"\n{'='*50}")
    print("📖 品种知识萃取:")
    extract_knowledge_from_validated_verdicts(followup_path)

    # ── 技能层进化（Skillevolver，非阻断） ──
    print(f"\n{'='*50}")
    print("🧬 技能层进化 (Skillevolver):")
    try:
        from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor
        from scripts.skillevolver_evolution import SkillEvolver

        debate_json = script_dir / "data" / "debate_results.json"
        if debate_json.exists():
            debate_data = load_json(str(debate_json))
            analyzer = TrajectoryAnalyzer(script_dir)
            attributor = FaultAttributor()
            evolver = SkillEvolver(script_dir)

            trajectory = analyzer.parse({"debate_results": debate_data})
            if trajectory:
                faults = attributor.attribute(trajectory)
                high_conf = [f for f in faults if f.get("confidence", 0) >= 0.8]

                if high_conf:
                    print(f"  High-confidence faults detected: {len(high_conf)}")
                    validated = evolver.run_evolution_cycle(faults=high_conf, dry_run=True)
                    ready = [u for u in validated if u.get("status") == "ready"]
                    print(f"  Patches generated: {len(ready)}")
                    for r in ready:
                        print(f"    → {r.get('target_file', '?')}")
                else:
                    print(f"  No high-confidence faults (total: {len(faults)})")
            else:
                print("  No trajectory data.")
    except ImportError as exc:
        print(f"  ⏭ 技能层进化模块未就绪: {exc}")
    except Exception as exc:
        print(f"  ⚠️ 技能层进化异常(非阻断): {exc}")


if __name__ == "__main__":
    main()
