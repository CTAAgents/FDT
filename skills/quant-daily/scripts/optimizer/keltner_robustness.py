#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keltner 通道参数鲁棒性分析器
================================
对指定品种跑完整 54 种参数组合网格搜索，评估：
  1. 参数平原（parameter plateau）— 最优参数邻域的得分分布
  2. 鲁棒性 — 参数微小扰动时的性能衰减
  3. 平坦区域占比 — 得分在 top-90% 的组合比例

输出:
  - 控制台表格（品种 × 鲁棒性指标）
  - JSON 详细数据（含完整得分网格）
"""

import sys
import os
import json
import math
from collections import defaultdict

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from optimizer.keltner_wf import (
    KELTNER_PERIOD_CANDIDATES,
    KELTNER_ATR_MULT_CANDIDATES,
    _evaluate_params,
    walk_forward_keltner,
)
from scan_all import _fdc_get_kline_sync


def _make_snapshots(sym, days=400):
    """为指定品种构造加密采样的历史截面。"""
    r = _fdc_get_kline_sync(variety=sym, days=days, period='daily')
    if not r.get('success'):
        return []
    dlist = r['data']
    if len(dlist) < 80:
        return []

    opens = np.array([float(x['open']) for x in dlist])
    highs = np.array([float(x['high']) for x in dlist])
    lows = np.array([float(x['low']) for x in dlist])
    closes = np.array([float(x['close']) for x in dlist])
    LOOKAHEAD = 5
    snaps = []
    for i in range(80, len(closes) - LOOKAHEAD):
        fc = closes[i + 1:i + 1 + LOOKAHEAD]
        fac = float(np.mean((fc / closes[i] - 1) * 100)) if len(fc) else 0.0
        snaps.append({
            "bar_idx": i,
            "high": highs[:i + 1],
            "low": lows[:i + 1],
            "close": closes[:i + 1],
            "last_price": float(closes[i]),
            "future_avg_change": fac,
            "future_direction": "bull" if fac > 0 else "bear",
        })
    return snaps


def analyze_robustness(symbol: str, snapshots: list, verbose: bool = True):
    """对一个品种做完整网格搜索 + 鲁棒性分析。"""
    if not snapshots or len(snapshots) < 10:
        return None

    # ── 完整网格搜索 ──
    grid = {}  # (period, atr_mult) -> composite_score
    raw_metrics = {}  # (period, atr_mult) -> {signals, accuracy, avg_pnl}
    for period in KELTNER_PERIOD_CANDIDATES:
        for atr_mult in KELTNER_ATR_MULT_CANDIDATES:
            m = _evaluate_params(snapshots, period, atr_mult)
            composite = m["accuracy"] * (m["avg_pnl"] + 1) * 100
            grid[(period, atr_mult)] = composite
            raw_metrics[(period, atr_mult)] = m

    # ── 找到最优参数 ──
    best_key = max(grid, key=lambda k: grid[k])
    best_score = grid[best_key]
    best_period, best_mult = best_key

    # ── 邻域鲁棒性（一步邻域）──
    neighbors = []
    neighbor_keys = []
    p_idx = KELTNER_PERIOD_CANDIDATES.index(best_period)
    m_idx = KELTNER_ATR_MULT_CANDIDATES.index(best_mult)
    for di in [-1, 0, 1]:
        for dj in [-1, 0, 1]:
            if di == 0 and dj == 0:
                continue
            pi = p_idx + di
            mj = m_idx + dj
            if 0 <= pi < len(KELTNER_PERIOD_CANDIDATES) and 0 <= mj < len(KELTNER_ATR_MULT_CANDIDATES):
                pk = KELTNER_PERIOD_CANDIDATES[pi]
                mk = KELTNER_ATR_MULT_CANDIDATES[mj]
                neighbors.append(grid[(pk, mk)])
                neighbor_keys.append((pk, mk))

    neighbor_mean = np.mean(neighbors) if neighbors else 0.0
    neighbor_std = np.std(neighbors) if neighbors else 0.0

    # 鲁棒性得分 = 邻域均值 / 最优得分（越接近 1 越鲁棒）
    robustness = neighbor_mean / max(best_score, 1e-9) if best_score > 0 else 0.0

    # ── 平原度分析 ──
    # 定义 top-90% 阈值：得分 >= 0.9 * best_score 的组合为"平坦区域"
    threshold = 0.9 * best_score
    plateau_count = sum(1 for v in grid.values() if v >= threshold)
    plateau_ratio = plateau_count / len(grid)

    # 平原覆盖范围：最优参数邻域（3×3 九宫格）内有多少在阈值上
    local_3x3 = []
    for di in [-1, 0, 1]:
        for dj in [-1, 0, 1]:
            pi = p_idx + di
            mj = m_idx + dj
            if 0 <= pi < len(KELTNER_PERIOD_CANDIDATES) and 0 <= mj < len(KELTNER_ATR_MULT_CANDIDATES):
                pk = KELTNER_PERIOD_CANDIDATES[pi]
                mk = KELTNER_ATR_MULT_CANDIDATES[mj]
                local_3x3.append(grid[(pk, mk)])
    local_in_plateau = sum(1 for v in local_3x3 if v >= threshold)
    local_plateau_ratio = local_in_plateau / len(local_3x3) if local_3x3 else 0.0

    # ── 次优差距 ──
    sorted_scores = sorted(grid.values(), reverse=True)
    second_best = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    gap_ratio = (best_score - second_best) / max(best_score, 1e-9)

    # ── 熵（得分分布集中度）──
    # 将得分归一化后计算熵，越低说明越集中在少数参数
    vals = np.array(list(grid.values()))
    if vals.max() > 0:
        probs = vals / vals.sum()
        probs = probs[probs > 0]
        entropy = -np.sum(probs * np.log(probs))
        max_entropy = np.log(len(grid))
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        normalized_entropy = 1.0

    result = {
        "symbol": symbol,
        "best_period": best_period,
        "best_atr_mult": best_mult,
        "best_score": round(best_score, 2),
        "second_best_score": round(second_best, 2),
        "gap_ratio": round(gap_ratio, 3),
        "neighbor_mean": round(neighbor_mean, 2),
        "neighbor_std": round(neighbor_std, 2),
        "robustness_score": round(robustness, 3),
        "plateau_ratio": round(plateau_ratio, 3),
        "local_plateau_ratio": round(local_plateau_ratio, 3),
        "plateau_count": plateau_count,
        "normalized_entropy": round(normalized_entropy, 3),
        "total_combinations": len(grid),
        "signals": raw_metrics[best_key]["signals"],
        "accuracy": raw_metrics[best_key]["accuracy"],
        "avg_pnl": round(raw_metrics[best_key]["avg_pnl"], 3),
        "grid": {f"{k[0]}_{k[1]}": round(v, 2) for k, v in grid.items()},
    }

    if verbose:
        print(f"  {symbol:4s} | best(p={best_period:2d},m={best_mult:4.2f}) score={best_score:6.1f} | "
              f"robust={robustness:.2f} | plateau={plateau_ratio:.0%}({plateau_count}/{len(grid)}) | "
              f"gap={gap_ratio:.2f} | entropy={normalized_entropy:.2f}")

    return result


def run_robustness_analysis(symbols: list, output_path: str = None, verbose: bool = True):
    """对多个品种运行鲁棒性分析。"""
    print(f"\n{'=' * 80}")
    print(f"  Keltner 通道参数鲁棒性分析")
    print(f"  参数空间: {len(KELTNER_PERIOD_CANDIDATES)} × {len(KELTNER_ATR_MULT_CANDIDATES)} = {len(KELTNER_PERIOD_CANDIDATES)*len(KELTNER_ATR_MULT_CANDIDATES)} 种组合")
    print(f"{'=' * 80}")

    results = []
    for sym, name in symbols:
        snaps = _make_snapshots(sym)
        if not snaps:
            if verbose:
                print(f"  {sym:4s} | 数据不足, 跳过")
            continue
        res = analyze_robustness(sym, snaps, verbose=verbose)
        if res:
            res["name"] = name
            results.append(res)

    if not results:
        print("⚠ 无有效结果")
        return []

    # ── 全局统计 ──
    print(f"\n{'=' * 80}")
    print(f"  鲁棒性汇总")
    print(f"{'=' * 80}")
    print(f"  分析品种: {len(results)}")
    print(f"  平均 robustness_score: {np.mean([r['robustness_score'] for r in results]):.3f}")
    print(f"  平均 plateau_ratio:    {np.mean([r['plateau_ratio'] for r in results]):.1%}")
    print(f"  平均 gap_ratio:        {np.mean([r['gap_ratio'] for r in results]):.3f}")
    print(f"  平均 entropy:          {np.mean([r['normalized_entropy'] for r in results]):.3f}")

    # 鲁棒性分级
    robust_high = sum(1 for r in results if r['robustness_score'] >= 0.85)
    robust_mid = sum(1 for r in results if 0.6 <= r['robustness_score'] < 0.85)
    robust_low = sum(1 for r in results if r['robustness_score'] < 0.6)
    print(f"\n  鲁棒性分级:")
    print(f"    高(≥0.85): {robust_high} 品种")
    print(f"    中(0.6~0.85): {robust_mid} 品种")
    print(f"    低(<0.6): {robust_low} 品种")

    # 平原度分级
    plateau_high = sum(1 for r in results if r['plateau_ratio'] >= 0.15)
    plateau_low = sum(1 for r in results if r['plateau_ratio'] < 0.15)
    print(f"\n  平原度分级:")
    print(f"    宽阔(≥15%组合在top-90%): {plateau_high} 品种")
    print(f"    狭窄(<15%): {plateau_low} 品种")

    # ── 详细表格 ──
    print(f"\n  {'品种':4s} | {'period':>6s} | {'atrmult':>7s} | {'score':>6s} | {'robust':>6s} | {'plateau':>7s} | {'gap':>5s} | {'entropy':>7s} | {'signals':>7s}")
    print(f"  {'─' * 70}")
    results.sort(key=lambda r: r['robustness_score'], reverse=True)
    for r in results:
        print(f"  {r['symbol']:4s} | {r['best_period']:6d} | {r['best_atr_mult']:7.2f} | "
              f"{r['best_score']:6.1f} | {r['robustness_score']:6.2f} | "
              f"{r['plateau_ratio']:6.0%} | {r['gap_ratio']:5.2f} | "
              f"{r['normalized_entropy']:7.2f} | {r['signals']:7d}")

    # 保存 JSON
    out_path = output_path or os.path.join(_SCRIPTS_DIR, "optimizer", "keltner_robustness.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  📁 {out_path}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Keltner 参数鲁棒性分析")
    parser.add_argument("--symbols", "-s", type=str, required=True,
                        help="品种列表(逗号分隔)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="输出 JSON 路径")
    args = parser.parse_args()

    syms = [s.strip().lower() for s in args.symbols.split(",")]
    from config.symbols import SYMBOL_DETAILS
    sym_names = [(s, SYMBOL_DETAILS.get(s, {}).get("name", s.upper())) for s in syms]

    run_robustness_analysis(sym_names, output_path=args.output, verbose=True)


if __name__ == "__main__":
    main()
