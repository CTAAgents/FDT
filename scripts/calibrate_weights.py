#!/usr/bin/env python3
"""
评分权重自校准器 — 从历史验证结果学习，调整裁决评分权重。
在每次 validate_verdicts.py 之后运行。

核心逻辑:
  验证统计 → 分组实际准确率 → 偏离基准的程度 → 权重修正量
  修正量反哺给裁决评分公式 → 下次类似配置的品种自动加分/扣分

用法:
  python calibrate_weights.py [--min-samples 5] [--lr 0.3]

输出:
  memory/calibration.json — 当前生效的权重修正表
"""
from __future__ import annotations

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict


# ─── 基础配置 ───────────────────────────────────────────

BASELINE_ACCURACY = 0.60      # 基准准确率（高于此值加分，低于此值扣分）
LEARNING_RATE = 0.30          # 学习率（保守：0.2-0.3）
MIN_SAMPLES = 5               # 最少样本数（低于此不校准）


# ─── 维度定义 ───────────────────────────────────────────

def get_adx_range(adx: float) -> str:
    if adx >= 70: return "ADX≥70"
    if adx >= 50: return "50≤ADX<70"
    if adx >= 30: return "30≤ADX<50"
    return "ADX<30"


def get_rsi_range(direction: str, rsi: float) -> str:
    if direction == "bear":
        if rsi < 30: return "RSI<30超卖"
        if rsi < 35: return "30≤RSI<35"
        if rsi < 40: return "35≤RSI<40"
        if rsi < 45: return "40≤RSI<45"
        return "RSI≥45"
    else:
        if rsi > 70: return "RSI>70超买"
        if rsi > 65: return "65<RSI≤70"
        if rsi > 60: return "60<RSI≤65"
        if rsi > 55: return "55<RSI≤60"
        return "RSI≤55"


# ─── 主校准逻辑 ─────────────────────────────────────────

def collect_dimensions(followup_path: str) -> dict:
    """从 execution_followup.json 收集所有已验证裁决的维度标签"""
    with open(followup_path, 'r', encoding='utf-8') as f:
        followup = json.load(f)

    dims = {
        "confidence": defaultdict(list),
        "direction": defaultdict(list),
        "adx_range": defaultdict(list),
        "rsi_range": defaultdict(list),
        "conflict": defaultdict(list),
        "chain": defaultdict(list),
    }

    total_validated = 0
    for record in followup["records"]:
        if not record.get("validated"):
            continue
        vr = record.get("validation_results", {})
        if not vr.get("validatable"):
            continue

        verdicts = record["verdicts"]
        results = vr.get("results", [])

        for i, v in enumerate(verdicts):
            if i >= len(results):
                continue
            r = results[i]
            correct = r.get("correct")
            if correct is None:
                continue

            total_validated += 1
            dims["confidence"][v.get("confidence","中")].append(correct)
            dims["direction"][v.get("direction","neutral")].append(correct)
            dims["adx_range"][get_adx_range(v.get("adx",0))].append(correct)
            dims["rsi_range"][get_rsi_range(v.get("direction",""), v.get("rsi",50))].append(correct)
            dims["conflict"]["conflict" if v.get("conflict") else "no_conflict"].append(correct)
            dims["chain"][v.get("chain","其他")].append(correct)

    return dims, total_validated


def load_hallucination_stats(hallucination_stats_path: str) -> Optional[dict]:
    """加载 LLM 幻觉统计数据"""
    if not hallucination_stats_path or not os.path.exists(hallucination_stats_path):
        return None
    try:
        with open(hallucination_stats_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def compute_adjustments(dims: dict, total: int, min_samples: int, learning_rate: float,
                        hallucination_stats: Optional[dict] = None) -> dict:
    """将准确率偏差转化为权重修正量"""

    adjustments = {
        "confidence": {},
        "adx_range": {},
        "rsi_range": {},
        "conflict": {},
        "direction_bias": 0,
        "chains": {},
        "hallucination_adjustment": 0,
        "_meta": {
            "calibrated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_samples": total,
            "baseline": BASELINE_ACCURACY,
            "learning_rate": learning_rate,
            "min_samples": min_samples,
            "hallucination_rate": None,
        }
    }

    for dim_name in ["confidence", "adx_range", "rsi_range", "conflict"]:
        for bucket, samples in dims[dim_name].items():
            if len(samples) < min_samples:
                adjustments[dim_name][bucket] = 0
                continue

            accuracy = sum(samples) / len(samples)
            deviation = accuracy - BASELINE_ACCURACY
            adj = round(deviation * 100 * learning_rate)
            adj = max(-10, min(10, adj))

            adjustments[dim_name][bucket] = {
                "adj": adj,
                "samples": len(samples),
                "accuracy": round(accuracy * 100, 1),
            }

    for chain, samples in dims["chain"].items():
        if len(samples) < min_samples:
            adjustments["chains"][chain] = 0
            continue
        accuracy = sum(samples) / len(samples)
        adj = round((accuracy - BASELINE_ACCURACY) * 100 * learning_rate)
        adj = max(-8, min(8, adj))
        adjustments["chains"][chain] = {
            "adj": adj,
            "samples": len(samples),
            "accuracy": round(accuracy * 100, 1),
        }

    bear_samples = dims["direction"].get("bear", [])
    bull_samples = dims["direction"].get("bull", [])
    if bear_samples and bull_samples and len(bear_samples) >= min_samples and len(bull_samples) >= min_samples:
        bear_acc = sum(bear_samples) / len(bear_samples)
        bull_acc = sum(bull_samples) / len(bull_samples)
        bias = round((bear_acc - bull_acc) * 100 * learning_rate)
        adjustments["direction_bias"] = max(-5, min(5, bias))
    else:
        adjustments["direction_bias"] = 0

    # 幻觉率校准（G92 Phase B）
    if hallucination_stats:
        hallucination_rate = hallucination_stats.get("hallucination_rate", 0)
        adjustments["_meta"]["hallucination_rate"] = hallucination_rate
        adjustments["_meta"]["max_deviation_rate"] = hallucination_stats.get("max_deviation_rate", 0)
        adjustments["_meta"]["confidence_issues"] = hallucination_stats.get("confidence_issues", 0)

        if hallucination_rate > 10:
            adjustments["hallucination_adjustment"] = -3
        elif hallucination_rate > 5:
            adjustments["hallucination_adjustment"] = -1
        elif hallucination_rate < 2:
            adjustments["hallucination_adjustment"] = +1
        else:
            adjustments["hallucination_adjustment"] = 0

    return adjustments


def compute_effective_adjustment(verdict: dict, calibrations: dict) -> int:
    """
    计算单条裁决的净修正分。
    每个匹配的维度桶贡献其adj值，所有维度叠加。
    返回修正总分（可正可负，钳制在 ±15）
    """
    total_adj = 0

    conf = verdict.get("confidence", "中")
    ca = calibrations.get("confidence", {}).get(conf, 0)
    total_adj += ca if isinstance(ca, int) else ca.get("adj", 0)

    adx_range = get_adx_range(verdict.get("adx", 0))
    aa = calibrations.get("adx_range", {}).get(adx_range, 0)
    total_adj += aa if isinstance(aa, int) else aa.get("adj", 0)

    rsi_range = get_rsi_range(verdict.get("direction", ""), verdict.get("rsi", 50))
    ra = calibrations.get("rsi_range", {}).get(rsi_range, 0)
    total_adj += ra if isinstance(ra, int) else ra.get("adj", 0)

    conflict_key = "conflict" if verdict.get("conflict") else "no_conflict"
    co = calibrations.get("conflict", {}).get(conflict_key, 0)
    total_adj += co if isinstance(co, int) else co.get("adj", 0)

    chain = verdict.get("chain", "其他")
    ch = calibrations.get("chains", {}).get(chain, 0)
    total_adj += ch if isinstance(ch, int) else ch.get("adj", 0)

    if verdict.get("direction") == "bear":
        total_adj += calibrations.get("direction_bias", 0)

    total_adj += calibrations.get("hallucination_adjustment", 0)

    return max(-15, min(15, total_adj))


# ─── 可视化 ───────────────────────────────────────────

def print_calibration(calibrations: dict) -> None:
    """打印校准表"""
    meta = calibrations["_meta"]
    print(f"校准时间: {meta['calibrated_at']}")
    print(f"总样本: {meta['total_samples']}, 基准={meta['baseline']}, 学习率={meta['learning_rate']}")
    print()

    sections = [
        ("置信度", "confidence"),
        ("ADX区间", "adx_range"),
        ("RSI区间(空头)", "rsi_range"),
        ("冲突状态", "conflict"),
        ("产业链", "chains"),
    ]

    for label, key in sections:
        data = calibrations.get(key, {})
        if not data:
            continue
        print(f"\n{'─'*50}")
        print(f"  {label}:")
        for bucket, val in sorted(data.items()):
            if isinstance(val, dict):
                adj = val["adj"]
                acc = val["accuracy"]
                n = val["samples"]
                sign = "+" if adj > 0 else ""
                color = "🟢" if adj >= 3 else ("🟡" if adj >= -3 else "🔴")
                print(f"    {color} {bucket:20s}  adj={sign}{adj:2d}  准确率={acc:5.1f}%  n={n}")
            else:
                print(f"    {bucket:20s}  adj={val:2d}")

    bias = calibrations.get("direction_bias", 0)
    if bias != 0:
        print(f"\n  方向偏置: bear {'+' if bias>0 else ''}{bias}分")

    hallucination_adj = calibrations.get("hallucination_adjustment", 0)
    if hallucination_adj != 0 or calibrations["_meta"].get("hallucination_rate") is not None:
        hr = calibrations["_meta"].get("hallucination_rate")
        print(f"\n  幻觉率校准: 率={hr}%, 修正={hallucination_adj:+d}分")


# ─── 主程序 ───────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="评分权重自校准器")
    parser.add_argument("--min-samples", type=int, default=5, help="最少样本数")
    parser.add_argument("--lr", type=float, default=0.3, help="学习率")
    parser.add_argument("--followup", default=None)
    parser.add_argument("--hallucination-stats", default=None,
                        help="LLM幻觉统计文件路径（llm_hallucination_stats.json）")
    args = parser.parse_args()

    min_samples = args.min_samples
    learning_rate = args.lr

    if args.followup is None:
        script_dir = Path(__file__).parent.parent
        args.followup = str(script_dir / "memory" / "execution_followup.json")

    dims, total = collect_dimensions(args.followup)

    if total < min_samples:
        print(f"⚠️ 已验证样本量不足 ({total} < {min_samples})，跳过校准")
        return

    hallucination_stats = load_hallucination_stats(args.hallucination_stats)
    calibrations = compute_adjustments(dims, total, min_samples, learning_rate, hallucination_stats)
    print_calibration(calibrations)

    # 保存
    calib_path = str(Path(args.followup).parent / "calibration.json")
    with open(calib_path, 'w', encoding='utf-8') as f:
        json.dump(calibrations, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 校准表已保存: {calib_path}")

    # 打印示例：对当前最高分品种计算修正后的分数
    print(f"\n{'='*50}")
    print("📐 修正示例: 当前Top5品种的评分偏移")
    print(f"{'='*50}")

    # 读取最新裁决作为示例
    with open(args.followup, 'r', encoding='utf-8') as f:
        followup = json.load(f)
    if followup["records"]:
        latest = followup["records"][-1]
        verdicts_by_score = sorted(latest["verdicts"], key=lambda v: v.get("score",0), reverse=True)
        print(f"{'品种':8s} {'原评分':6s} {'修正':5s} {'→':2s} {'校准后':6s} {'原因'}")
        print('-'*55)
        for v in verdicts_by_score[:10]:
            adj = compute_effective_adjustment(v, calibrations)
            orig = v.get("score", 0)
            calibrated = orig + adj
            sign = "+" if adj > 0 else ""
            reasons = []
            for dim_name, dim_data in [
                ("conf", v.get("confidence","")),
                ("ADX", get_adx_range(v.get("adx",0))),
                ("RSI", get_rsi_range(v.get("direction",""), v.get("rsi",50))),
                ("conflict", "conflict" if v.get("conflict") else "no_conflict"),
                ("chain", v.get("chain","")),
            ]:
                if dim_name != "conf" and dim_name != "chain" and dim_name != "conflict":
                    data = calibrations.get({"conf":"confidence","ADX":"adx_range","RSI":"rsi_range","conflict":"conflict","chain":"chains"}[dim_name], {}).get(dim_data, 0)
                else:
                    data = calibrations.get({"conf":"confidence","conflict":"conflict","chain":"chains"}[dim_name], {}).get(dim_data, 0)
                val = data if isinstance(data, int) else data.get("adj", 0) if isinstance(data, dict) else 0
                if val != 0:
                    reasons.append(f"{dim_name}:{val:+d}")
            print(f"{v.get('name',''):8s} {orig:6.1f} {sign}{adj:4d} {'→':2s} {calibrated:6.1f}  {', '.join(reasons) if reasons else '（无历史数据）'}")


if __name__ == "__main__":
    main()
