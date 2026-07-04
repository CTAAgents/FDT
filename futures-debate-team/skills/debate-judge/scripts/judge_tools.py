#!/usr/bin/env python3
"""
判官工具 — 闫判官的评分计算工具箱
===================================
将闫判官的评分逻辑从 prompt 内的 LLM 主观判断，
变为可验证的数学运算 + 可追溯的评分过程。

核心函数：
  compute_total_score — 加权总分（标准五维/六维）
  compute_convergence — 分歧度计算
  detect_unrebutted   — 检测未被反驳的论点
  check_convergence   — 收敛判据（决定是否提前终止或续辩）
"""

import json, math


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


def check_convergence(
    long_score: float, short_score: float,
    rounds_elapsed: int, max_rounds: int = 3
) -> dict:
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
        "recommendation": f"分歧度{spread:.0f}，建议追加第{rounds_elapsed+1}轮辩论",
        "winner": None,
    }


if __name__ == "__main__":
    # 测试
    s1 = compute_total_score({
        "argument_logic": 8.5, "evidence_sufficiency": 9.0,
        "quant_consistency": 8.0, "rebuttal_effectiveness": 7.5,
        "risk_awareness": 7.5, "presentation_structure": 8.0,
    })
    print(f"测试总分: {s1['score']} [{s1['method']}]")
    c = check_convergence(81.75, 75.00, 2)
    print(f"收敛检测: {c['status']} → {c['recommendation']}")
