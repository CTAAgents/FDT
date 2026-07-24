#!/usr/bin/env python3
"""
证据加权评分引擎（辩论质量v2）
=================================
替代闫判官的5维度平权评分，改为基于证据质量的自动加权计算。

核心函数:
- score_evidence(claims): 基于证据要素加权计算
- score_inline(debater_output): 直接对辩手输出评分
- generate_judge_prompt(scores): 生成闫判官最终评分的参考

用法:
    from scripts.evidence_scorer import score_debate
    result = score_debate(bull_output, bear_output)
    # → {"winner": "bull", "scores": {...}, "decision_support": {...}}
"""

import re
from datetime import datetime
from typing import Any, Dict, List


def _extract_claims(debater_output: dict) -> List[dict]:
    """从辩手输出中提取所有论点。"""
    claims = []
    evidence = debater_output.get("evidence", {})
    for category in ["technical", "fundamental", "chain"]:
        items = evidence.get(category, [])
        for item in items:
            claims.append(
                {
                    "claim_id": item.get("claim_id", ""),
                    "point": item.get("point", ""),
                    "evidence_value": item.get("evidence_value", ""),
                    "evidence_source": item.get("evidence_source", ""),
                    "evidence_date": item.get("evidence_date", ""),
                    "impact_level": item.get("impact_level", "MEDIUM"),
                    "logical_fallacy": item.get("logical_fallacy", ""),
                    "rebuttal_to": item.get("rebuttal_to", ""),
                }
            )
    return claims


def score_single_claim(claim: dict) -> float:
    """对单个论点进行证据质量打分（0-1）。"""
    score = 0.0

    # 1. 有具体数值（+2分）
    if claim.get("evidence_value") and re.search(r"\d+", str(claim["evidence_value"])):
        score += 2.0

    # 2. 有数据来源（+1分）
    source = claim.get("evidence_source", "")
    if source:
        # 官方数据源额外加分
        high_quality = ["交易所", "统计局", "Mysteel", "SMM", "中钢协", "OPEC", "EIA", "USDA"]
        if any(q in source for q in high_quality):
            score += 2.0
        else:
            score += 1.0

    # 3. 有数据日期且较新（+1分）
    date_str = claim.get("evidence_date", "")
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (datetime.now() - d).days
            if days_ago <= 7:
                score += 2.0  # 一周内：高质量
            elif days_ago <= 30:
                score += 1.5  # 一个月内：可用
            else:
                score += 0.5  # 较旧：低质量
        except ValueError:
            score += 0.5  # 日期格式错误但仍给出

    # 4. 有论点ID（+0.5分，表明结构完整）
    if claim.get("claim_id"):
        score += 0.5

    # 5. 反驳时标注了逻辑漏洞类型（+1分）
    if claim.get("logical_fallacy"):
        valid_fallacies = ["因果倒置", "数据过时", "样本偏差", "推理跳跃", "忽视反证"]
        if claim["logical_fallacy"] in valid_fallacies:
            score += 1.0

    # 6. 影响程度加分
    impact = claim.get("impact_level", "MEDIUM")
    if impact == "HIGH":
        score += 1.0
    elif impact == "LOW":
        score += 0.3

    return min(score / 8.0, 1.0)  # 归一化到 0-1


def score_debate(bull_output: dict, bear_output: dict) -> Dict[str, Any]:
    """对一场辩论进行证据加权评分。

    Args:
        bull_output: 证真的 StructuredDebate 输出
        bear_output: 慎思的 StructuredDebate 输出

    Returns:
        {"winner": str, "scores": dict, "details": dict}
    """
    bull_claims = _extract_claims(bull_output)
    bear_claims = _extract_claims(bear_output)

    # 计算证据质量
    bull_scores = [score_single_claim(c) for c in bull_claims]
    bear_scores = [score_single_claim(c) for c in bear_claims]

    bull_avg = sum(bull_scores) / max(len(bull_scores), 1)
    bear_avg = sum(bear_scores) / max(len(bear_scores), 1)

    # 统计
    bull_high = sum(1 for c in bull_claims if c.get("impact_level") == "HIGH")
    bear_high = sum(1 for c in bear_claims if c.get("impact_level") == "HIGH")

    bull_with_evidence = sum(1 for c in bull_claims if c.get("evidence_value"))
    bear_with_evidence = sum(1 for c in bear_claims if c.get("evidence_value"))

    # 反驳质量检查
    bull_rebuttals = sum(1 for c in bull_claims if c.get("rebuttal_to"))
    bear_rebuttals = sum(1 for c in bear_claims if c.get("rebuttal_to"))

    bull_fallacies = sum(1 for c in bull_claims if c.get("logical_fallacy"))
    bear_fallacies = sum(1 for c in bear_claims if c.get("logical_fallacy"))

    # 综合评分
    bull_total = (
        bull_avg * 0.4
        + min(bull_high * 0.1, 0.2)
        + (bull_with_evidence / max(len(bull_claims), 1)) * 0.2
        + (bull_rebuttals / max(len(bull_claims), 1)) * 0.1
        + (bull_fallacies / max(len(bull_claims), 1)) * 0.1
    )
    bear_total = (
        bear_avg * 0.4
        + min(bear_high * 0.1, 0.2)
        + (bear_with_evidence / max(len(bear_claims), 1)) * 0.2
        + (bear_rebuttals / max(len(bear_claims), 1)) * 0.1
        + (bear_fallacies / max(len(bear_claims), 1)) * 0.1
    )

    winner = "bull" if bull_total > bear_total else "bear"
    if abs(bull_total - bear_total) < 0.05:
        winner = "pending"  # 接近平局，需闫判官裁决

    return {
        "winner": winner,
        "auto_score": True,
        "scores": {
            "bull": round(bull_total, 4),
            "bear": round(bear_total, 4),
        },
        "details": {
            "bull": {
                "claims": len(bull_claims),
                "avg_evidence_quality": round(bull_avg, 3),
                "high_impact": bull_high,
                "with_evidence": bull_with_evidence,
                "rebuttals": bull_rebuttals,
                "fallacies_labeled": bull_fallacies,
            },
            "bear": {
                "claims": len(bear_claims),
                "avg_evidence_quality": round(bear_avg, 3),
                "high_impact": bear_high,
                "with_evidence": bear_with_evidence,
                "rebuttals": bear_rebuttals,
                "fallacies_labeled": bear_fallacies,
            },
        },
        "decision_support": {
            "auto_winner": winner,
            "confidence": round(abs(bull_total - bear_total) * 5, 2),
            "note": "证据加权自动评分，闫判官可做 ±10% 微调",
        },
    }


if __name__ == "__main__":
    # 测试
    bull = {
        "evidence": {
            "technical": [
                {
                    "claim_id": "证真-D1",
                    "point": "螺纹趋势向上",
                    "evidence_value": "ADX=28",
                    "evidence_source": "技术分析评分",
                    "evidence_date": "2026-07-05",
                    "impact_level": "HIGH",
                },
                {
                    "claim_id": "证真-D2",
                    "point": "成交量放大确认",
                    "evidence_value": "成交量+15%",
                    "evidence_source": "交易所",
                    "evidence_date": "2026-07-04",
                    "impact_level": "MEDIUM",
                },
            ],
            "fundamental": [
                {
                    "claim_id": "证真-D3",
                    "point": "库存低位",
                    "evidence_value": "社库352万吨",
                    "evidence_source": "Mysteel",
                    "evidence_date": "2026-07-03",
                    "impact_level": "HIGH",
                    "rebuttal_to": "慎思-D1",
                    "logical_fallacy": "数据过时",
                },
            ],
            "chain": [],
        }
    }
    bear = {
        "evidence": {
            "technical": [
                {
                    "claim_id": "慎思-D1",
                    "point": "RSI超买",
                    "evidence_value": "RSI=72",
                    "evidence_source": "技术分析评分",
                    "evidence_date": "2026-07-05",
                    "impact_level": "HIGH",
                },
            ],
            "fundamental": [],
            "chain": [],
        }
    }
    result = score_debate(bull, bear)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
