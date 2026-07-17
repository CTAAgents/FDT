#!/usr/bin/env python3
"""
判官工具 — 闫判官的评分计算工具箱
===================================
v3.0 新增:
  - flip_proposition: 不预设正方，看双方理由后定方向
  - generate_feedback: 辩论→三路反馈回流
  - evaluate_debate: 基于StructuredDebate的完整评分

核心函数：
  compute_total_score — 加权总分（标准五维/六维）
  compute_convergence — 分歧度计算
  detect_unrebutted   — 检测未被反驳的论点
  check_convergence   — 收敛判据
  flip_proposition    — 不预设正方，双方交定正方申请书后定
  generate_feedback   — 辩论反馈→回流给观澜/探源/链证源
  evaluate_debate     — 基于结构化辩词的全流程评分
"""

import json, math
from typing import Dict, List, Optional, Tuple


def compute_total_score(scores: dict, weights: dict = None) -> dict:
    """计算加权总分。

    标准权重（六维）：
      论证逻辑 25% | 事实依据 20% | 量化一致性 15%
      反驳力 20%   | 风控意识 10% | 论述结构 10%

    返回：{score: float, dimensions: {dim: {score, weight, weighted}}, formula: str}
    """
    if weights is None:
        weights = {
            "argument_logic": 0.25,
            "evidence_sufficiency": 0.20,
            "quant_consistency": 0.15,
            "rebuttal_effectiveness": 0.20,
            "risk_awareness": 0.10,
            "presentation_structure": 0.10,
        }

    dims = {}
    total = 0.0
    for dim, weight in weights.items():
        s = scores.get(dim, 0)
        w = s * weight
        dims[dim] = {"score": s, "weight": weight, "weighted": round(w, 2)}
        total += w

    formula_parts = [f"{dim}({d['score']}×{d['weight']})" for dim, d in dims.items()]
    return {
        "score": round(total, 2),
        "dimensions": dims,
        "formula": " + ".join(formula_parts),
        "method": "加权平均 × 10归一化" if total <= 10 else "直接加权",
    }


def compute_convergence(round1_scores: dict, round2_scores: dict) -> dict:
    """计算两轮评分之间的分歧度变化。

    返回：{spread_abs, spread_pct, converging, recommended_action}
    """
    total1 = sum(round1_scores.values()) / len(round1_scores) if round1_scores else 0
    total2 = sum(round2_scores.values()) / len(round2_scores) if round2_scores else 0
    spread = abs(total1 - total2)

    if spread >= 15:
        action = "early_stop"
        reason = f"分歧度{spread:.1f}≥15，差距显著，可提前终止"
    elif spread <= 3:
        action = "converged"
        reason = f"分歧度{spread:.1f}≤3，观点已收敛"
    else:
        action = "continue"
        reason = f"分歧度{spread:.1f}，建议追加一轮辩论"

    return {
        "round1_avg": round(total1, 2),
        "round2_avg": round(total2, 2),
        "spread": round(spread, 1),
        "converging": spread <= 3,
        "action": action,
        "reason": reason,
    }


def detect_unrebutted(pro_claims: list, con_claims: list) -> list:
    """检测未被对方直接回应的论点。

    通过关键词匹配判断每个论点是否被对方提及。
    返回未被反驳的论点列表。
    """
    all_pro_text = " ".join(con_claims).lower()
    all_con_text = " ".join(pro_claims).lower()

    unrebutted = []
    for claim in pro_claims:
        keywords = set(claim.lower().split()[:5])
        if not any(kw in all_con_text for kw in keywords):
            unrebutted.append({"claim": claim, "side": "pro", "reason": "反方未回应"})

    for claim in con_claims:
        keywords = set(claim.lower().split()[:5])
        if not any(kw in all_pro_text for kw in keywords):
            unrebutted.append({"claim": claim, "side": "con", "reason": "正方未回应"})

    return unrebutted


def check_convergence(long_score: float, short_score: float, rounds_elapsed: int, max_rounds: int = 3) -> dict:
    """收敛判据——决定辩论是否继续。

    返回：{status: str, recommendation: str}
    """
    spread = abs(long_score - short_score)

    if spread >= 15:
        return {
            "status": "early_stop",
            "recommendation": f"分歧度{spread:.0f}≥15，差距显著。建议提前认可胜方",
            "winner": "long" if long_score > short_score else "short",
        }
    if spread <= 3:
        return {
            "status": "converged",
            "recommendation": f"分歧度{spread:.0f}≤3，观点已高度趋同。建议进入下一阶段",
            "winner": None,
        }
    if rounds_elapsed >= max_rounds:
        return {
            "status": "max_reached",
            "recommendation": f"已达到最大轮数{max_rounds}轮，按当前评分直接判决",
            "winner": "long" if long_score > short_score else "short",
        }
    return {
        "status": "continue",
        "recommendation": f"分歧度{spread:.0f}，建议追加第{rounds_elapsed + 1}轮辩论",
        "winner": None,
    }


def flip_proposition(
    symbol: str,
    bull_reason: str,  # 证真写的"为什么我该当正方"
    bear_reason: str,  # 慎思写的"为什么我该当正方"
    signal: dict,  # 信号
) -> dict:
    """闫判官不预设正方——看双方申请后定。

    步骤:
    1. 比较双方理由的质量（证据充分性、逻辑一致性）
    2. 双策略信号方向（权重40%）
    3. 决定正方方向

    Returns:
        {"proposition_side": "long"/"short",
         "reason": "选择理由",
         "bull_score": int, "bear_score": int}
    """
    bull_score = _rate_application(bull_reason, is_bull=True)
    bear_score = _rate_application(bear_reason, is_bull=False)

    # 双策略信号倾向
    l1_dir = (
        1
        if l1l4_signal.get("direction") in ("bull", "BUY")
        else (-1 if l1l4_signal.get("direction") in ("bear", "SELL") else 0)
    )
    f_dir = (
        1
        if factor_signal.get("direction") in ("bull", "BUY")
        else (-1 if factor_signal.get("direction") in ("bear", "SELL") else 0)
    )
    signal_bias = l1_dir + f_dir  # 2=强烈多, -2=强烈空, 0=中性

    # 综合: 论据质量60% + 信号40%
    net = (bull_score - bear_score) * 0.6 + signal_bias * 5 * 0.4
    proposition = "long" if net > 0 else "short"

    return {
        "proposition_side": proposition,
        "reason": f"证真申请评分{bull_score}/100, 慎思申请评分{bear_score}/100, "
        f"双策略偏{'多' if signal_bias > 0 else '空' if signal_bias < 0 else '中性'} → 定正方={'多方' if proposition == 'long' else '空方'}",
        "bull_application_score": bull_score,
        "bear_application_score": bear_score,
        "signal_bias": signal_bias,
    }


def _rate_application(reason: str, is_bull: bool) -> int:
    """对正方申请书打分（0-100）。"""
    score = 60  # 基准
    # 有具体数据引用+5
    if any(c.isdigit() for c in reason):
        score += 10
    # 有逻辑推理链+10
    if any(w in reason for w in ["因为", "所以", "因此", "意味着"]):
        score += 10
    # 有风险认知+10
    if any(w in reason for w in ["风险", "但", "不过", "然而"]):
        score += 10
    # 有具体数字+5
    import re

    if re.search(r"\d+\.?\d*%", reason):
        score += 5
    if re.search(r"\d+\.?\d*元", reason):
        score += 5
    return min(100, score)


def generate_feedback(
    symbol: str,
    bull_debate: dict,  # StructuredDebate
    bear_debate: dict,  # StructuredDebate
    judge_verdict: dict,
) -> List[dict]:
    """辩论结束后，生成三路反馈回流。

    回流1: 观澜 — 支撑/阻力位评级被挑战
    回流2: 探源 — narrative被证伪/数据解读翻车
    回流3: 链证源 — 产业链骨架漏项

    Returns: [DebateFeedbackItem, ...]
    """
    feedback = []

    # 回流1: 技术位挑战
    tech_bull = bull_debate.get("evidence", {}).get("technical", [])
    tech_bear = bear_debate.get("evidence", {}).get("technical", [])
    for e in tech_bull + tech_bear:
        pt = e.get("point", "")
        if "hard" in pt and ("破" in pt or "失效" in pt or "换月" in pt):
            feedback.append(
                {
                    "target": "观澜",
                    "item": pt[:50],
                    "challenge": "技术位在辩论中被攻破",
                    "winner": "慎思" if "hard" in pt and "破" in pt else "证真",
                    "action": "同品种同类型支撑位，换月周+OI增>5%时hard降级为soft",
                }
            )

    # 回流2: 叙事挑战
    fund_bull = bull_debate.get("evidence", {}).get("fundamental", [])
    fund_bear = bear_debate.get("evidence", {}).get("fundamental", [])
    for e in fund_bull + fund_bear:
        pt = e.get("point", "")
        if "库存" in pt and ("被动" in pt or "拒收" in pt or "厂库升" in pt):
            feedback.append(
                {
                    "target": "探源",
                    "item": f"库存解读: {pt[:50]}",
                    "challenge": "库存结构解读在辩论中被挑战（厂库升+社库降=被动累）",
                    "winner": "慎思",
                    "action": "修正inventory.structure判断逻辑：厂库升+社库降=被动累，非主动去",
                }
            )

    # 回流3: 产业链漏项
    for debate in [bull_debate, bear_debate]:
        for rs in debate.get("rebuttal_strategy", []):
            ke = rs.get("key_evidence", "")
            if "焦化" in ke or "利润→开工" in ke:
                feedback.append(
                    {
                        "target": "链证源",
                        "item": "利润→开工传导timing",
                        "challenge": "辩论中发现焦化利润到高炉开工链路缺失",
                        "winner": "双方",
                        "action": "黑链产业链骨架加焦化利润到高炉开工边",
                    }
                )

    return feedback


def evaluate_debate(
    bull: dict,
    bear: dict,
    flip_result: Optional[dict] = None,
) -> dict:
    """基于StructuredDebate的全流程评分。

    评分维度（扩展5维）:
    1. 论点清晰度(thesis): 是否一句话说清楚
    2. 证据质量(evidence): 是否具体、可核验、来源明确
    3. 风险意识(risk): 是否主动列counter_risks
    4. 反驳预判(rebuttal): 是否预判对方攻击方向
    5. 方案可执行性(plan): entry_plan是否合理

    Returns: {"bull_score": float, "bear_score": float,
              "verdict": str, "feedback": [...]}
    """
    bull_scores = _score_dimensions(bull)
    bear_scores = _score_dimensions(bear)
    weights = {"thesis": 0.25, "evidence": 0.25, "risk": 0.20, "rebuttal": 0.15, "plan": 0.15}

    bull_total = sum(bull_scores[k] * weights[k] for k in weights)
    bear_total = sum(bear_scores[k] * weights[k] for k in weights)
    spread = bull_total - bear_total

    if abs(spread) < 3:
        verdict = "draw"
    elif spread > 0:
        verdict = "bull"
    else:
        verdict = "bear"

    return {
        "bull_score": round(bull_total, 1),
        "bear_score": round(bear_total, 1),
        "spread": round(spread, 1),
        "verdict": verdict,
        "bull_detail": bull_scores,
        "bear_detail": bear_scores,
        "method": "StructuredDebate 5维加权",
    }


def _score_dimensions(debate: dict) -> dict:
    """对StructuredDebate的5个维度分别打分(0-100)。"""
    scores = {"thesis": 60, "evidence": 60, "risk": 60, "rebuttal": 60, "plan": 60}
    thesis = debate.get("thesis", "")
    if len(thesis) > 15 and len(thesis) < 100:
        scores["thesis"] += 15
    if "三重共振" in thesis or "共振" in thesis:
        scores["thesis"] += 10

    tech_n = len(debate.get("evidence", {}).get("technical", []))
    fund_n = len(debate.get("evidence", {}).get("fundamental", []))
    scores["evidence"] = min(100, 60 + tech_n * 5 + fund_n * 5)

    risks = debate.get("counter_risks", [])
    scores["risk"] = min(100, 60 + len(risks) * 10)

    rebuttals = debate.get("rebuttal_strategy", [])
    scores["rebuttal"] = min(100, 60 + len(rebuttals) * 10)

    plan = debate.get("entry_plan")
    if plan and plan.get("price_zone"):
        scores["plan"] = 80
    if plan and plan.get("risk_reward"):
        scores["plan"] += 10

    return scores


if __name__ == "__main__":
    # 测试
    s1 = compute_total_score(
        {
            "argument_logic": 8.5,
            "evidence_sufficiency": 9.0,
            "quant_consistency": 8.0,
            "rebuttal_effectiveness": 7.5,
            "risk_awareness": 7.5,
            "presentation_structure": 8.0,
        }
    )
    print(f"测试总分: {s1['score']} [{s1['method']}]")
    c = check_convergence(81.75, 75.00, 2)
    print(f"收敛检测: {c['status']} → {c['recommendation']}")
