# -*- coding: utf-8 -*-
"""逻辑审计模块 — 叙事概率检查、rebuttal 质量评估、尾端风险识别。
"""

from typing import Dict, List, Optional


def check_narrative_probability(
    claim: str,
    assumed_probability: float,
    actual_probability: float,
) -> Dict:
    """叙事概率检查：辩手是否把低概率事件当基准情景使用。

    Args:
        claim: 叙事描述（如"供给短缺"、"需求崩塌"）
        assumed_probability: 辩手隐含使用的概率（0.0~1.0）
        actual_probability: 该叙事的合理概率（0.0~1.0）

    Returns:
        dict: {issue, severity, gap, detail}
    """
    gap = assumed_probability - actual_probability
    if actual_probability < 0.10 and assumed_probability >= 0.50:
        return {
            "issue": "尾部当基准",
            "severity": "red",
            "gap": round(gap, 2),
            "detail": f"'{claim}'实际概率<10%，但辩手以{assumed_probability:.0%}概率使用，差距{gap:.0%}",
        }
    elif actual_probability < 0.10 and assumed_probability >= 0.30:
        return {
            "issue": "尾部概率高估",
            "severity": "yellow",
            "gap": round(gap, 2),
            "detail": f"'{claim}'实际<10%，辩手用{assumed_probability:.0%}，高估{gap:.0%}",
        }
    elif gap > 0.30:
        return {
            "issue": "概率偏差",
            "severity": "yellow",
            "gap": round(gap, 2),
            "detail": f"'{claim}'的概率高估{gap:.0%}",
        }
    return {
        "issue": "none",
        "severity": "green",
        "gap": round(gap, 2),
        "detail": "叙事概率合理",
    }


def assess_rebuttal_quality(
    quality: str,
) -> Dict:
    """评估 rebuttal 质量等级。

    Args:
        quality: '接住'/'部分接住'/'糊弄'

    Returns:
        dict: {score, is_acceptable, detail}
    """
    levels = {
        '接住': {'score': 1.0, 'acceptable': True, 'detail': '准确引用了证据和数据'},
        '部分接住': {'score': 0.5, 'acceptable': True, 'detail': '有论点但证据不够充分'},
        '糊弄': {'score': 0.0, 'acceptable': False, 'detail': '无实质反驳或逻辑跳跃'},
    }
    return levels.get(quality, {'score': 0.0, 'acceptable': False, 'detail': '未知质量'})


def run_logic_audit(
    dimensions: List[Dict],
) -> Dict:
    """对多方辩论维度执行逻辑审计。

    Args:
        dimensions: 辩论维度列表，每项含 {dim, claim, ruling, rebuttal_quality}

    Returns:
        dict: {dimension_count, exclude_count, watch_count, acceptable, issues}
    """
    issues = []
    exclude_count = 0
    watch_count = 0
    acceptable_quality_count = 0
    bad_quality = []

    for d in dimensions:
        ruling = d.get('ruling', 'include')
        quality = d.get('rebuttal_quality', '糊弄')
        dim_name = d.get('dim', 'unknown')

        if ruling == 'exclude':
            exclude_count += 1
        elif ruling == 'watch':
            watch_count += 1

        q_result = assess_rebuttal_quality(quality)
        if q_result['acceptable']:
            acceptable_quality_count += 1
        else:
            bad_quality.append({
                "dim": dim_name,
                "ruling": ruling,
                "rebuttal_quality": quality,
                "detail": q_result['detail'],
            })

    if exclude_count == 0 and watch_count == 0:
        issues.append({
            "level": "yellow",
            "msg": "所有维度均为 include，无 exlude 或 watch，可能过于乐观",
        })
    if len(bad_quality) == 0:
        issues.append({
            "level": "yellow",
            "msg": "所有 rebuttal 均为'接住'，可能存在乐观偏差",
        })

    return {
        "dimension_count": len(dimensions),
        "exclude_count": exclude_count,
        "watch_count": watch_count,
        "include_count": len(dimensions) - exclude_count - watch_count,
        "acceptable_quality_count": acceptable_quality_count,
        "bad_quality": bad_quality,
        "issues": issues,
        "overall_pass": exclude_count >= 1 or watch_count >= 2,
    }
