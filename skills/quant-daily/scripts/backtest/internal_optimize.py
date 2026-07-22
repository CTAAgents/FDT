# -*- coding: utf-8 -*-
"""
quant-daily 内部子信号权重优化引擎 v1.0
========================================
通过修改 INTERNAL_MULTIPLIERS 并缓存指标实现快速迭代。

一次采集62品种指标缓存，然后每轮只重新评分（约2秒/轮）。
支持25+轮迭代优化。

/loop 用法:
  /loop 循环次数 30 python -m scripts.backtest.internal_optimize
"""

import sys, os, json, time, copy
from datetime import datetime
from collections import defaultdict

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_SKILLS = os.path.dirname(SKILL_DIR)
if not os.path.isdir(PARENT_SKILLS):
    PARENT_SKILLS = os.path.join(os.path.expanduser("~"), ".skills", "skills")
    SKILL_DIR = os.path.join(PARENT_SKILLS, "quant-daily", "scripts")
for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd
import numpy as np
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy


def _load_data(days=200):
    """采集并缓存所有品种的K线+指标。"""
    a = MultiSourceAdapter()
    cache = {}
    for sym, name in [
        ("RB", "螺纹钢"),
        ("HC", "热卷"),
        ("I", "铁矿石"),
        ("CU", "沪铜"),
        ("AU", "沪金"),
        ("M", "豆粕"),
        ("Y", "豆油"),
        ("P", "棕榈油"),
        ("SR", "白糖"),
        ("CF", "棉花"),
        ("SA", "纯碱"),
        ("MA", "甲醇"),
        ("v", "PVC"),
        ("sc", "原油"),
        ("ag", "沪银"),
        ("TA", "PTA"),
        ("FG", "玻璃"),
        ("RU", "橡胶"),
        ("al", "沪铝"),
        ("zn", "沪锌"),
    ]:
        try:
            resp = a.get_kline(variety=sym, days=days)
            if not (isinstance(resp, dict) and resp.get("success")):
                continue
            valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
            if len(valid) < 80:
                continue
            df = pd.DataFrame({k: [float(r[k]) for r in valid] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in valid]
            tech = _compute_indicators_numpy(df, sym)
            price = tech.get("last_price", float(df["close"].iloc[-1]))
            cache[sym] = {
                "tech": tech,
                "sd": {"last_price": price, "open_interest": tech.get("open_interest", 0)},
                "kc": df["close"].tolist(),
                "name": name,
            }
        except Exception as e:
            pass
    return cache


def _score_all(cache):
    """使用当前 INTERNAL_MULTIPLIERS 对所有品种评分。"""
    from signals.scoring_system import calculate_composite_score

    gs = defaultdict(int)
    for sym, d in cache.items():
        sc = calculate_composite_score(d["tech"], d["sd"], 0, d["kc"], None)
        gs[sc["grade"]] += 1
    return {
        "STRONG": gs.get("STRONG", 0),
        "WATCH": gs.get("WATCH", 0),
        "WEAK": gs.get("WEAK", 0),
        "NOISE": gs.get("NOISE", 0),
        "total": sum(gs.values()),
        "quality": gs.get("STRONG", 0) * 1.5 + gs.get("WATCH", 0),
    }


def optimize_loop(baseline_bl, cache, n_iterations=30):
    """迭代优化循环。每轮调整一个子信号乘数，评分全品种，记录最优。"""
    from signals.scoring_system import INTERNAL_MULTIPLIERS
    import signals.scoring_system as ss

    # 候选参数网格
    param_grid = {}
    for k in sorted(INTERNAL_MULTIPLIERS.keys()):
        param_grid[k] = [0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0]

    best = {
        "multipliers": dict(INTERNAL_MULTIPLIERS),
        "score": baseline_bl["quality"],
        "detail": baseline_bl,
    }
    history = [{"iteration": 0, "params": dict(INTERNAL_MULTIPLIERS), "result": baseline_bl}]
    param_keys = sorted(INTERNAL_MULTIPLIERS.keys())

    print(f"\n{'=' * 60}")
    print(f"  内部权重迭代优化 | {n_iterations} 轮 | {len(param_keys)} 参数")
    print(f"  基线: STRONG={baseline_bl['STRONG']} WATCH={baseline_bl['WATCH']} 质量分={baseline_bl['quality']}")
    print(f"{'=' * 60}")

    for it in range(1, n_iterations + 1):
        key = param_keys[(it - 1) % len(param_keys)]
        old_val = INTERNAL_MULTIPLIERS[key]

        best_local = {"val": old_val, "score": baseline_bl["quality"]}

        for new_val in param_grid[key]:
            if abs(new_val - old_val) < 0.01:
                continue

            ss.INTERNAL_MULTIPLIERS[key] = new_val
            result = _score_all(cache)
            quality = result["quality"]

            if quality > best_local["score"]:
                best_local = {"val": new_val, "score": quality, "result": result}

        # 应用最优值
        ss.INTERNAL_MULTIPLIERS[key] = best_local["val"]
        current = _score_all(cache)

        history.append(
            {
                "iteration": it,
                "param": key,
                "old_val": old_val,
                "new_val": best_local["val"],
                "result": current,
            }
        )

        delta_str = ""
        if current["quality"] > best["score"]:
            best = {
                "multipliers": dict(ss.INTERNAL_MULTIPLIERS),
                "score": current["quality"],
                "detail": current,
            }
            delta_str = " ★ NEW BEST"

        print(
            f"  [{it:>2}/{n_iterations}] {key:<20} {old_val:>4.2f}→{best_local['val']:>4.2f}  "
            f"S={current['STRONG']} W={current['WATCH']} "
            f"质量={current['quality']:>4.0f}{delta_str}"
        )

    print(f"\n{'=' * 60}")
    print(f"  优化完成 | 最优:")
    print(
        f"    STRONG={best['detail']['STRONG']} WATCH={best['detail']['WATCH']} "
        f"WEAK={best['detail']['WEAK']} NOISE={best['detail']['NOISE']}"
    )
    print(f"    质量分: {best['score']}")
    print(f"    对比基线: {best['score'] - baseline_bl['quality']:+d}")
    print(f"{'=' * 60}")

    return best, history


def save_report(best, history, baseline_bl, output_dir):
    """保存优化报告JSON。"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"internal_optimize_{ts}.json")
    report = {
        "timestamp": ts,
        "baseline": baseline_bl,
        "best": best,
        "history": history,
        "n_iterations": len(history) - 1,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  报告保存: {path}")
    return path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="内部子信号权重迭代优化")
    parser.add_argument("--iterations", type=int, default=30, help="迭代次数")
    parser.add_argument("--days", type=int, default=200, help="数据天数")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    args = parser.parse_args()

    from signals.scoring_system import INTERNAL_MULTIPLIERS
    import signals.scoring_system as ss

    output_dir = args.output_dir or os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")

    # 采集
    print("Phase 1: 数据采集+指标缓存...")
    cache = _load_data(days=args.days)
    print(f"  缓存: {len(cache)} 品种")

    # 基线
    print("Phase 2: 基线评分...")
    baseline_bl = _score_all(cache)
    print(
        f"  基线: STRONG={baseline_bl['STRONG']} WATCH={baseline_bl['WATCH']} "
        f"WEAK={baseline_bl['WEAK']} NOISE={baseline_bl['NOISE']}"
    )

    # 优化
    print("\nPhase 3: 迭代优化...")
    best, history = optimize_loop(baseline_bl, cache, n_iterations=args.iterations)

    # 保存
    save_report(best, history, baseline_bl, output_dir)

    # 输出最优乘数
    print("\n  最优乘数配置:")
    for k, v in sorted(best["multipliers"].items()):
        base = INTERNAL_MULTIPLIERS.get(k, 1.0)
        change = "↑" if v > base else ("↓" if v < base else "=")
        print(f"    {k:<20} {v:.2f} {change}")


if __name__ == "__main__":
    main()
