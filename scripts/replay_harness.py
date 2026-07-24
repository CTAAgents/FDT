#!/usr/bin/env python3
"""
ViBench 回放引擎 v1（确定性结构一致性回放）
============================================
给定 debate_record 的 pro_args/con_args，确定性重推裁决方向，与 verdict.direction
+ ground_truth 对比，产出"输入→输出"一致性报告。

设计来源: CLQT (arXiv:2606.29771) ViBench —— 任何对 prompt/流程/规则的修改,
发布前必须用固定历史场景回放集衡量"是否变好"。

注: 脚本环境无 LLM API，完整 LLM 重辩留作未来；v1 以"结构一致性 + ground_truth 对照"落地，
已满足"启动回放"诉求。每条 debate_record 的 pro_args/con_args 来自真实辩论序列化，
而非本引擎虚构。
"""

from typing import Any, Dict, List, Optional


def _norm_variety(sym: str) -> str:
    """品种代码归一：CU.SHF -> CU（与 validate_verdicts 一致）"""
    return (sym or "").split(".")[0].upper().strip()


def _norm_direction(d: Any) -> Optional[str]:
    """方向归一：SELL/SHORT -> bear；BUY/LONG -> bull"""
    s = str(d or "").upper()
    if s in ("SELL", "BEAR", "SHORT"):
        return "bear"
    if s in ("BUY", "BULL", "LONG"):
        return "bull"
    return str(d).lower() if d is not None else None


def rederive_direction(pro_args: List[Dict], con_args: List[Dict]) -> str:
    """确定性重推：证据支撑更多的那一方获胜（证真=pro，慎思=con）。

    这是 held-out 视角的"仅凭论据能否推出裁决"检验——CLQT 核心关切：
    裁决是否由辩论论据推出，而非外部注入。
    """
    pro_ev = sum(1 for a in (pro_args or []) if a.get("evidence"))
    con_ev = sum(1 for a in (con_args or []) if a.get("evidence"))
    return "bear" if pro_ev >= con_ev else "bull"


def replay_record(rec: Dict, gt: Optional[Dict]) -> Dict:
    """回放单条 debate_record。"""
    derived = rederive_direction(rec.get("pro_args"), rec.get("con_args"))
    verdict_dir = _norm_direction(rec.get("verdict", {}).get("direction"))
    coh = rec.get("held_out_judge", {}).get("coherence_score")
    direction_consistent = (derived == verdict_dir) and verdict_dir is not None
    return {
        "round_id": rec.get("round_id"),
        "symbol": rec.get("symbol"),
        "derived_direction": derived,
        "verdict_direction": verdict_dir,
        "direction_consistent": direction_consistent,
        "coherence": coh,
        "has_ground_truth": gt is not None,
        "ground_truth_correct": gt.get("correct") if gt else None,
        "structurally_consistent": direction_consistent and (coh is not None and coh >= 0.7),
    }


def run_replay(debate_records: List[Dict], followup: Dict) -> Dict:
    """回放全部 debate_record，join ground_truth（key=(round_id, variety)）。"""
    # 构建 ground_truth 查找表
    gt: Dict = {}
    for rec in followup.get("records", []):
        rid = rec.get("round_id")
        for i, v in enumerate(rec.get("verdicts", [])):
            vr = rec.get("validation_results", {}).get("results", [])
            res = vr[i] if i < len(vr) else {}
            gt[(_norm_variety(rid), _norm_variety(v.get("symbol")))] = res

    rows: List[Dict] = []
    matched = 0
    for r in debate_records:
        rid = r.get("round_id")
        sym = r.get("symbol") or r.get("variety")
        g = gt.get((_norm_variety(rid), _norm_variety(sym)))
        if g is None:
            g = gt.get((None, _norm_variety(sym)))
        if g is not None:
            matched += 1
        rows.append(replay_record(r, g))

    total = len(rows)
    struct_ok = sum(1 for x in rows if x["structurally_consistent"])

    # coherence_weighted_accuracy：coherence≥0.7 子集的 ground_truth 方向准确率
    coh_ge07 = [x for x in rows if (x["coherence"] or 0) >= 0.7 and x["has_ground_truth"]]
    coh_acc: Optional[float] = None
    if coh_ge07:
        correct = sum(1 for x in coh_ge07 if x.get("ground_truth_correct") is True)
        coh_acc = round(correct / len(coh_ge07) * 100, 1)

    return {
        "replay_engine": "v1-deterministic",
        "total_debate_records": total,
        "ground_truth_matched": matched,
        "structurally_consistent": struct_ok,
        "structural_consistency_rate": round(struct_ok / total * 100, 1) if total else 0.0,
        "coherence_weighted_accuracy": coh_acc,
        "replay_status": "ACTIVE" if total > 0 else "BLOCKED",
        "note": "coherence_weighted_accuracy 仅在 debate_record 同时具备 held_out_judge(≥0.7) 与 ground_truth 时计算",
        "rows": rows,
    }
