#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keltner 通道参数 Walk-Forward 训练器
======================================
对 Keltner Channel 的 period / atr_mult 两参数做网格搜索 +
Walk-Forward 训练/测试分割，产出最优参数组合。

参数空间:
  period:   [10, 15, 20, 25, 30, 40]
  atr_mult: [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]
  共 6 × 9 = 54 种组合

用法:
  python -m scripts.optimizer.keltner_wf --symbols RB,HC,I
  python -m scripts.optimizer.keltner_wf --all
  python -m scripts.optimizer.keltner_wf --all --auto-write
  python -m scripts.optimizer.keltner_wf --all --top-n 5
"""

import json
import os
import sys
from datetime import datetime
from typing import Optional

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from config.settings import DEBATE_ENTRY_MIN_ABS, TREND_G30_CONFIG
from config.symbols import ALL_SYMBOLS, SYMBOL_DETAILS
from scan_all import collect_kline_for_all

from futures_data_core.indicators.tdx_compat import calculate_keltner

# ─── Keltner 参数候选空间 ───
KELTNER_PERIOD_CANDIDATES = [10, 15, 20, 25, 30, 40]
KELTNER_ATR_MULT_CANDIDATES = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]

# ─── Walk-Forward 结构 ───
WF_TRAIN_PCT = 0.7
WF_TEST_PCT = 0.3
LOOKAHEAD_BARS = 5
MIN_BARS = 80
# TDX 主力连续合约 L8 硬限 ~200 根 K线（约 1 年），无法通过 days 突破。
# 改用加密采样：SAMPLE_INTERVAL=1 使每个品种截面从 ~60 提升到 ~140（~140% 增长），
# 等价于"向前多取 200 根 K线"的统计效能。
SAMPLE_INTERVAL = 1
DAYS_OF_DATA = 400


def _score_keltner_signal(close: float, kc_u: float, kc_l: float, kc_m: float):
    """Keltner 通道突破打分（与 trend_following_strategy._score_keltner 一致）。"""
    if kc_u <= 0 or kc_l <= 0 or kc_u <= kc_l or kc_m <= 0:
        return 0.0, "neutral"
    half = (kc_u - kc_m) + 1e-9
    if close > kc_u:
        return min(1.0, (close - kc_u) / half), "bull"
    if close < kc_l:
        return min(1.0, (kc_l - close) / half), "bear"
    return 0.0, "neutral"


def _build_snapshots(symbol: str, name: str, kline_data: dict) -> list:
    """为一个品种构建历史截面。"""
    if symbol not in kline_data:
        return []
    _, dlist = kline_data[symbol]
    if len(dlist) < MIN_BARS:
        return []

    opens = np.array([float(r["open"]) for r in dlist])
    highs = np.array([float(r["high"]) for r in dlist])
    lows = np.array([float(r["low"]) for r in dlist])
    closes = np.array([float(r["close"]) for r in dlist])
    volumes = np.array([float(r.get("volume", 0)) for r in dlist])
    n = len(closes)

    snapshots = []
    for i in range(MIN_BARS, n - LOOKAHEAD_BARS, SAMPLE_INTERVAL):
        close_i = closes[:i + 1]
        high_i = highs[:i + 1]
        low_i = lows[:i + 1]
        vol_i = volumes[:i + 1]
        open_i = opens[:i + 1]

        last_price = float(close_i[-1])
        future_closes = closes[i + 1:i + 1 + LOOKAHEAD_BARS]
        future_changes = [(fc / last_price - 1) * 100 for fc in future_closes]
        future_avg = float(np.mean(future_changes)) if future_changes else 0.0
        future_dir = "bull" if future_avg > 0 else "bear"

        snapshots.append({
            "bar_idx": i,
            "high": high_i,
            "low": low_i,
            "close": close_i,
            "last_price": last_price,
            "future_avg_change": future_avg,
            "future_direction": future_dir,
        })
    return snapshots


def _evaluate_params(snapshots: list, period: int, atr_mult: float) -> dict:
    """用指定 period/atrmult 在全部截面上评估 Keltner 信号准确率。"""
    correct = 0
    total = 0
    pnl = 0.0
    for snap in snapshots:
        h = snap["high"]
        l = snap["low"]
        c = snap["close"]
        if len(c) < period:
            continue

        kc_u, kc_l, kc_m = calculate_keltner(h, l, c, period=period, atr_mult=atr_mult)
        if not np.isfinite(kc_u[-1]) or not np.isfinite(kc_l[-1]):
            continue

        score, direction = _score_keltner_signal(
            snap["last_price"], float(kc_u[-1]), float(kc_l[-1]), float(kc_m[-1])
        )
        # 仅统计有效信号（score > 0 即突破通道）
        if direction == "neutral" or score <= 0:
            continue

        # 与 _score_keltner 打分一致：score 映射到 abs_score = score * 100
        abs_score = score * 100
        if abs_score < DEBATE_ENTRY_MIN_ABS:
            continue

        total += 1
        hit = (direction == snap["future_direction"])
        if hit:
            correct += 1
            pnl += abs(snap["future_avg_change"])
        else:
            pnl -= abs(snap["future_avg_change"])

    return {
        "signals": total,
        "correct": correct,
        "accuracy": correct / max(total, 1),
        "avg_pnl": pnl / max(total, 1),
    }


def walk_forward_keltner(
    symbol: str,
    snapshots: list,
    verbose: bool = True,
) -> Optional[dict]:
    """对一个品种做 Keltner 参数的 Walk-Forward 训练+测试。"""
    if not snapshots or len(snapshots) < 10:
        if verbose:
            print(f"  ⚠ {symbol}: 截面不足 ({len(snapshots) if snapshots else 0}), 跳过")
        return None

    n = len(snapshots)
    split = int(n * WF_TRAIN_PCT)
    train_snaps = snapshots[:split]
    test_snaps = snapshots[split:]

    if len(train_snaps) < 5 or len(test_snaps) < 3:
        if verbose:
            print(f"  ⚠ {symbol}: 训练={len(train_snaps)} 测试={len(test_snaps)}, 跳过")
        return None

    if verbose:
        print(f"\n  ── {symbol} Keltner WF ──")
        print(f"  截面: {n}, 训练: {len(train_snaps)}, 测试: {len(test_snaps)}")

    # ── 训练: 完整网格搜索 + 鲁棒评分 ──
    # 先对所有 54 种组合计算原始得分
    raw_scores = {}  # (period, atr_mult) -> composite
    all_metrics = {}  # (period, atr_mult) -> metric_dict
    total_combos = 0
    for period in KELTNER_PERIOD_CANDIDATES:
        for atr_mult in KELTNER_ATR_MULT_CANDIDATES:
            total_combos += 1
            m = _evaluate_params(train_snaps, period, atr_mult)
            all_metrics[(period, atr_mult)] = m
            if m["signals"] == 0:
                raw_scores[(period, atr_mult)] = 0.0
            else:
                # 原始综合评分 = accuracy * (avg_pnl + 1) * 100
                raw_scores[(period, atr_mult)] = m["accuracy"] * (m["avg_pnl"] + 1) * 100

    # 对每个组合计算鲁棒评分: 30% 峰值得分 + 70% 3×3 邻域均值
    # 邻域均值越高 → 参数平原越广阔
    robust_scores = {}
    for period in KELTNER_PERIOD_CANDIDATES:
        for atr_mult in KELTNER_ATR_MULT_CANDIDATES:
            peak = raw_scores[(period, atr_mult)]
            # 收集 3×3 邻域内有效（非零）得分
            p_idx = KELTNER_PERIOD_CANDIDATES.index(period)
            m_idx = KELTNER_ATR_MULT_CANDIDATES.index(atr_mult)
            neighbor_vals = []
            for di in [-1, 0, 1]:
                for dj in [-1, 0, 1]:
                    pi = p_idx + di
                    mj = m_idx + dj
                    if 0 <= pi < len(KELTNER_PERIOD_CANDIDATES) and 0 <= mj < len(KELTNER_ATR_MULT_CANDIDATES):
                        pk = KELTNER_PERIOD_CANDIDATES[pi]
                        mk = KELTNER_ATR_MULT_CANDIDATES[mj]
                        neighbor_vals.append(raw_scores[(pk, mk)])
            neighbor_mean = np.mean(neighbor_vals) if neighbor_vals else 0.0
            # 鲁棒评分: 权重 0.1 峰值得分 + 0.9 邻域均值（强力偏好广阔平原）
            # 邻域均值 ≥ 0.85×峰值 → 高平原, 邻域均值 < 0.5×峰值 → 尖峰惩罚
            robust = 0.1 * peak + 0.9 * neighbor_mean
            robust_scores[(period, atr_mult)] = robust

    # 选鲁棒评分最高的组合
    best_key = max(robust_scores, key=lambda k: robust_scores[k])
    best = {
        "score": round(robust_scores[best_key], 1),
        "peak_score": round(raw_scores[best_key], 1),
        "period": best_key[0],
        "atr_mult": best_key[1],
        "train": all_metrics[best_key],
    }

    if best["period"] is None:
        if verbose:
            print(f"  ⚠ {symbol}: 训练集无有效参数组合")
        return None

    if verbose:
        print(f"  搜索组合: {total_combos}")
        print(f"  最优(鲁棒评分): period={best['period']} atr_mult={best['atr_mult']} "
              f"鲁棒评分={best['score']} 峰值得分={best['peak_score']}")
        # 显示邻域健康状况
        p_idx = KELTNER_PERIOD_CANDIDATES.index(best["period"])
        m_idx = KELTNER_ATR_MULT_CANDIDATES.index(best["atr_mult"])
        neighbors_in = 0
        neighbors_tot = 0
        for di in [-1, 0, 1]:
            for dj in [-1, 0, 1]:
                if di == 0 and dj == 0:
                    continue
                pi = p_idx + di
                mj = m_idx + dj
                if 0 <= pi < len(KELTNER_PERIOD_CANDIDATES) and 0 <= mj < len(KELTNER_ATR_MULT_CANDIDATES):
                    neighbors_tot += 1
                    pk = KELTNER_PERIOD_CANDIDATES[pi]
                    mk = KELTNER_ATR_MULT_CANDIDATES[mj]
                    ns = raw_scores.get((pk, mk), 0.0)
                    if ns >= 0.5 * best["peak_score"]:
                        neighbors_in += 1
        print(f"  邻域: {neighbors_in}/{neighbors_tot}(≥50%峰值) 邻域均值={best['score']:.0f}")

    # ── 测试: 最优参数在测试集验证 ──
    test_m = _evaluate_params(test_snaps, best["period"], best["atr_mult"])
    best["test"] = test_m

    if verbose:
        print(f"  训练: 准确率={best['train']['accuracy']:.0%} "
              f"({best['train']['correct']}/{best['train']['signals']}) "
              f"pnl={best['train']['avg_pnl']:.2f}")
        print(f"  测试: 准确率={test_m['accuracy']:.0%} "
              f"({test_m['correct']}/{test_m['signals']}) "
              f"pnl={test_m['avg_pnl']:.2f}")

    return best


def run_keltner_wf(
    symbols: list = None,
    auto_write: bool = False,
    top_n: int = 0,
    verbose: bool = True,
) -> list:
    """运行 Keltner Walk-Forward 参数训练。

    Args:
        symbols: [(sym, name), ...] 品种列表，None 则全品种
        auto_write: 是否将最优参数回写到 TREND_G30_CONFIG
        top_n: 显示前 N 名品种汇总，0=全部
        verbose: 打印详情

    Returns:
        结果列表
    """
    if symbols is None:
        symbols = ALL_SYMBOLS

    print(f"\n{'=' * 55}")
    print("  Keltner 通道 Walk-Forward 参数训练")
    print(f"  period: {KELTNER_PERIOD_CANDIDATES}")
    print(f"  atr_mult: {KELTNER_ATR_MULT_CANDIDATES}")
    print(f"  组合数: {len(KELTNER_PERIOD_CANDIDATES) * len(KELTNER_ATR_MULT_CANDIDATES)}")
    print(f"{'=' * 55}")

    # 1. 加载数据
    print("\n[1/3] 加载历史数据...")
    kline_data = collect_kline_for_all(
        symbols, days=DAYS_OF_DATA, min_bars=MIN_BARS, period="daily"
    )
    print(f"  有效品种: {len(kline_data)}/{len(symbols)}")

    # 2. 构建截面
    print("\n[2/3] 构建历史截面...")
    all_snapshots = {}
    for sym, name in symbols:
        snaps = _build_snapshots(sym, name, kline_data)
        if snaps:
            all_snapshots[sym] = snaps

    print(f"  有效截面品种: {len(all_snapshots)}/{len(symbols)}")

    # 3. Walk-Forward
    print("\n[3/3] Walk-Forward 训练+测试...")
    results = []
    for sym, name in symbols:
        snaps = all_snapshots.get(sym, [])
        result = walk_forward_keltner(sym, snaps, verbose=verbose)
        if result:
            result["symbol"] = sym
            result["name"] = name
            results.append(result)

    # 4. 汇总
    if not results:
        print("\n⚠ 无有效结果")
        return []

    # 按测试准确率排序
    results.sort(key=lambda r: r["test"]["accuracy"], reverse=True)

    # 统计参数分布
    period_dist = {}
    mult_dist = {}
    for r in results:
        p, m = r["period"], r["atr_mult"]
        period_dist[p] = period_dist.get(p, 0) + 1
        mult_dist[m] = mult_dist.get(m, 0) + 1

    # 众数（出现最多的参数）
    mode_period = max(period_dist, key=period_dist.get)
    mode_mult = max(mult_dist, key=mult_dist.get)

    # 加权平均（按测试信号数加权）
    total_sig = sum(r["test"]["signals"] for r in results)
    if total_sig > 0:
        wavg_period = sum(r["period"] * r["test"]["signals"] for r in results) / total_sig
        wavg_mult = sum(r["atr_mult"] * r["test"]["signals"] for r in results) / total_sig
    else:
        wavg_period = 20
        wavg_mult = 2.25

    print(f"\n{'=' * 55}")
    print("  Keltner WF 结果汇总")
    print(f"{'=' * 55}")
    print(f"  有效品种: {len(results)}/{len(symbols)}")
    print(f"\n  period 分布: {dict(sorted(period_dist.items()))}")
    print(f"  atr_mult 分布: {dict(sorted(mult_dist.items()))}")
    print(f"  众数: period={mode_period}, atr_mult={mode_mult}")
    print(f"  信号加权均值: period={wavg_period:.1f}, atr_mult={wavg_mult:.2f}")

    # 前N名
    show = results[:top_n] if top_n > 0 else results
    print(f"\n  {'品种':4s} | {'period':>6s} | {'atrmult':>7s} | {'鲁棒评分':>8s} | {'训练准确率':>8s} | {'测试准确率':>8s} | {'测试信号':>6s}")
    print(f"  {'─' * 70}")
    for r in show:
        tr = r["train"]
        te = r["test"]
        rob = r.get("score", 0)
        print(f"  {r['symbol']:4s} | {r['period']:6d} | {r['atr_mult']:7.2f} | {rob:8.1f} | "
              f"{tr['accuracy']:7.0%} | {te['accuracy']:7.0%} | {te['signals']:6d}")

    # 5. 写入
    if auto_write:
        _write_results(results, mode_period, mode_mult, wavg_period, wavg_mult)

    # 保存 JSON
    out_dir = os.path.join(_SCRIPTS_DIR, "optimizer")
    out_path = os.path.join(out_dir, "keltner_wf_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "param_space": {
                "period_candidates": KELTNER_PERIOD_CANDIDATES,
                "atr_mult_candidates": KELTNER_ATR_MULT_CANDIDATES,
                "total_combinations": len(KELTNER_PERIOD_CANDIDATES) * len(KELTNER_ATR_MULT_CANDIDATES),
            },
            "summary": {
                "valid_symbols": len(results),
                "total_symbols": len(symbols),
                "mode_period": mode_period,
                "mode_atr_mult": mode_mult,
                "wavg_period": round(wavg_period, 1),
                "wavg_atr_mult": round(wavg_mult, 2),
            },
            "per_symbol": [
                {
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "best_period": r["period"],
                    "best_atr_mult": r["atr_mult"],
                    "robust_score": r.get("score", 0),
                    "peak_score": r.get("peak_score", 0),
                    "train_accuracy": round(r["train"]["accuracy"], 3),
                    "train_signals": r["train"]["signals"],
                    "test_accuracy": round(r["test"]["accuracy"], 3),
                    "test_signals": r["test"]["signals"],
                    "test_avg_pnl": round(r["test"]["avg_pnl"], 3),
                }
                for r in results
            ],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  📁 {out_path}")

    return results


def _write_results(results: list, mode_period: int, mode_mult: float,
                   wavg_period: float, wavg_mult: float):
    """将训练结果回写到配置。"""
    # 1. 更新 TREND_G30_CONFIG.keltner — 使用众数
    old_p = TREND_G30_CONFIG["keltner"]["period"]
    old_m = TREND_G30_CONFIG["keltner"]["atr_mult"]

    # 选择回写策略：众数优先（代表多数品种的最优），加权均值作参考
    new_p = mode_period
    new_m = mode_mult

    TREND_G30_CONFIG["keltner"]["period"] = new_p
    TREND_G30_CONFIG["keltner"]["atr_mult"] = new_m

    print("\n  ✅ TREND_G30_CONFIG.keltner 已更新:")
    print(f"     period: {old_p} → {new_p}")
    print(f"     atr_mult: {old_m} → {new_m}")
    print(f"     (加权均值参考: period={wavg_period:.1f}, atr_mult={wavg_mult:.2f})")

    # 2. 更新 legacy_numpy.py 中的硬编码参数
    _patch_legacy_numpy(new_p, new_m)


def _patch_legacy_numpy(period: int, atr_mult: float):
    """更新 legacy_numpy.py 中 _compute_indicators_numpy 的 Keltner 参数。"""
    legacy_path = os.path.join(
        os.path.dirname(_SCRIPTS_DIR), "..", "..", "..",
        "futures_data_core", "indicators", "legacy_numpy.py"
    )
    # 解析为绝对路径
    legacy_path = os.path.normpath(legacy_path)
    if not os.path.isfile(legacy_path):
        print(f"  ⚠ 未找到 legacy_numpy.py: {legacy_path}")
        return

    with open(legacy_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 替换 calculate_keltner 调用参数
    import re
    old_pattern = r'calculate_keltner\(h,\s*l,\s*c,\s*period=\d+,\s*atr_mult=[\d.]+\)'
    new_call = f'calculate_keltner(h, l, c, period={period}, atr_mult={atr_mult})'
    new_content = re.sub(old_pattern, new_call, content)

    if new_content != content:
        with open(legacy_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  ✅ legacy_numpy.py 已更新: period={period}, atr_mult={atr_mult}")
    else:
        print("  ℹ legacy_numpy.py 无需变更（参数已一致）")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Keltner 通道参数 Walk-Forward 训练")
    parser.add_argument("--symbols", "-s", type=str, default=None,
                        help="品种列表(逗号分隔), 不传则 --all")
    parser.add_argument("--all", action="store_true",
                        help="全品种训练")
    parser.add_argument("--auto-write", "-w", action="store_true",
                        help="将最优参数回写到 TREND_G30_CONFIG + legacy_numpy.py")
    parser.add_argument("--top-n", type=int, default=10,
                        help="汇总显示前N名品种(默认10, 0=全部)")
    args = parser.parse_args()

    if args.symbols:
        syms = [s.strip().lower() for s in args.symbols.split(",")]
        sym_names = []
        for s in syms:
            name = SYMBOL_DETAILS.get(s, {}).get("name", s.upper())
            sym_names.append((s, name))
    elif args.all:
        sym_names = list(ALL_SYMBOLS)
    else:
        parser.error("请指定 --symbols 或 --all")

    run_keltner_wf(
        symbols=sym_names,
        auto_write=args.auto_write,
        top_n=args.top_n,
        verbose=True,
    )


if __name__ == "__main__":
    main()
