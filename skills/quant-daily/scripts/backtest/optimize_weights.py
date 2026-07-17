# -*- coding: utf-8 -*-
"""
quant-daily 权重网格搜索 v1.0
==============================
基于 commodity-trend-signal backtest/optimize_weights.py 迁移

一次采集全品种K线+指标缓存，然后对每个权重组合快速评分。

使用方法：
  # 全品种优化（默认）
  python -m scripts.backtest.optimize_weights

  # 快速测试：只跑10个代表品种
  python -m scripts.backtest.optimize_weights --max-symbols 10

  # 自定义品种
  python -m scripts.backtest.optimize_weights --symbols RB,HC,I,AU,AG
"""

import sys, os, json, time
from datetime import datetime
from collections import defaultdict

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_SKILLS = os.path.dirname(SKILL_DIR)
if not os.path.isdir(PARENT_SKILLS):
    PARENT_SKILLS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")
    SKILL_DIR = os.path.join(PARENT_SKILLS, "quant-daily", "scripts")
for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd
import numpy as np
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy
from config.symbols import ALL_SYMBOLS


# ============================================================
# 权重组合生成
# ============================================================


def generate_grid():
    """生成权重组合网格。"""
    combos = []
    for l1 in range(30, 55, 5):
        for l2 in range(20, 40, 5):
            for l3 in range(10, 30, 5):
                l4 = 100 - l1 - l2 - l3
                if l4 < 5 or l4 > 25:
                    continue
                if not (l1 >= l2 >= l3 >= l4):
                    continue
                combos.append({"L1": l1, "L2": l2, "L3": l3, "L4": l4})
    return combos


# ============================================================
# 多品种分组（交叉验证用）
# ============================================================

# 工业品 vs 农产品分组
INDUSTRIAL_SYMBOLS = [
    "rb",
    "hc",
    "i",
    "j",
    "jm",
    "SF",
    "SM",  # 黑色
    "sc",
    "lu",
    "fu",
    "bu",
    "pg",
    "PX",  # 能源
    "TA",
    "PF",
    "PR",
    "eg",
    "eb",  # 聚酯
    "v",
    "pp",
    "l",
    "MA",  # 塑化
    "SH",
    "SA",
    "UR",  # 化工
    "cu",
    "al",
    "zn",
    "pb",
    "ni",
    "sn",
    "ao",
    "SS",  # 有色
    "au",
    "ag",  # 贵金属
    "FG",
    "ru",
    "nr",
    "br",
    "sp",
    "op",  # 建材化工
    "lc",
    "si",
    "ps",  # 新能源
    "ec",  # 航运
]
AGRICULTURAL_SYMBOLS = [
    "a",
    "b",
    "m",
    "y",
    "p",
    "OI",
    "RM",
    "PK",  # 油脂油料
    "c",
    "cs",
    "SR",
    "CF",
    "jd",
    "lh",  # 农产品
    "AP",
    "CJ",  # 果蔬
    "rr",  # 其他
]


def filter_symbols(symbols_to_use):
    """过滤ALL_SYMBOLS只保留指定品种。"""
    sym_set = set(s.lower() for s in symbols_to_use)
    return [(s, n) for s, n in ALL_SYMBOLS if s.lower() in sym_set]


# ============================================================
# 数据采集 + 指标缓存（一次采集，复用评分）
# ============================================================


def collect_and_cache(adapter, symbols=None, days=120):
    """采集K线 + 计算技术指标并缓存。"""
    if symbols is None:
        symbols = ALL_SYMBOLS
    cache = {}
    for i, (sym, name) in enumerate(symbols):
        try:
            resp = adapter.get_kline(variety=sym, days=days)
            if not (isinstance(resp, dict) and resp.get("success")):
                continue
            valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
            if len(valid) < 60:
                continue
            df = pd.DataFrame({k: [float(r[k]) for r in valid] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in valid]
            tech = _compute_indicators_numpy(df, sym)
            price = tech.get("last_price", float(df["close"].iloc[-1]))
            cache[sym] = {
                "tech": tech,
                "sd": {"last_price": price, "open_interest": tech.get("open_interest", 0)},
                "kc": df["close"].tolist(),
            }
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f"  [{i + 1}/{len(symbols)}] {len(cache)} cached", flush=True)
    return cache


def score_with_cache(cache, w1, w2, w3, w4):
    """使用缓存数据 + 指定权重快速评分。"""
    import signals.scoring_system as ss

    old = (ss.WL1, ss.WL2, ss.WL3, ss.WL4)
    ss.WL1, ss.WL2, ss.WL3, ss.WL4 = w1, w2, w3, w4
    gs = defaultdict(int)
    for d in cache.values():
        sc = ss.calculate_composite_score(d["tech"], d["sd"], 0, d["kc"], None)
        gs[sc["grade"]] += 1
    ss.WL1, ss.WL2, ss.WL3, ss.WL4 = old
    return dict(gs)


# ============================================================
# 单组优化
# ============================================================


def run_optimization(symbols=None, days=120):
    """执行单组权重优化：采集 → 基准 → 网格搜索。"""
    combos = generate_grid()
    print(f"权重组合: {len(combos)}")

    adapter = MultiSourceAdapter()
    sel_symbols = symbols or ALL_SYMBOLS
    print(f"Phase 1: 数据采集+指标缓存 ({len(sel_symbols)} 品种)...")
    t0 = time.time()
    cache = collect_and_cache(adapter, sel_symbols, days=days)
    print(f"  缓存: {len(cache)} 品种 ({time.time() - t0:.0f}s)")

    import signals.scoring_system as ss

    # 基准
    print("Phase 2: 基准评分 (40/30/20/10)...")
    bl = score_with_cache(cache, 40, 30, 20, 10)
    print(f"  Baseline: {bl}")

    # 网格搜索
    print("Phase 3: 网格搜索...")
    t0 = time.time()
    results = []
    for i, c in enumerate(combos):
        gs = score_with_cache(cache, c["L1"], c["L2"], c["L3"], c["L4"])
        results.append({"L1": c["L1"], "L2": c["L2"], "L3": c["L3"], "L4": c["L4"], **gs})
        if (i + 1) % 5 == 0:
            print(
                f"  [{i + 1}/{len(combos)}] {c['L1']}/{c['L2']}/{c['L3']}/{c['L4']} "
                f"S={gs.get('STRONG', 0)} W={gs.get('WATCH', 0)}",
                flush=True,
            )

    results.sort(key=lambda x: x.get("STRONG", 0) * 1.5 + x.get("WATCH", 0), reverse=True)

    print(f"\n{'=' * 50}")
    print(f"=== TOP 10 ===")
    print(f"{'L1':>3} {'L2':>3} {'L3':>3} {'L4':>3}  S  W  WK  N  得分")
    for r in results[:10]:
        sc = r.get("STRONG", 0) * 1.5 + r.get("WATCH", 0)
        print(
            f"{r['L1']:>3} {r['L2']:>3} {r['L3']:>3} {r['L4']:>3}  "
            f"{r.get('STRONG', 0):>1} {r.get('WATCH', 0):>2} {r.get('WEAK', 0):>2} "
            f"{r.get('NOISE', 0):>2}  {sc:>4.1f}"
        )
    print(f"Baseline 40/30/20/10: {bl}")
    print(f"Time: {time.time() - t0:.0f}s")

    # 保存
    out_dir = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"optimize_weights_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "baseline": bl,
                "top10": results[:10],
                "total_combos": len(combos),
                "total_symbols": len(cache),
                "timestamp": ts,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n结果已保存: {path}")
    return results


# ============================================================
# 交叉验证（工业品 vs 农产品）
# ============================================================


def run_cross_validation(days=120):
    """双组交叉验证：工业品 vs 农产品，找两组Top5都靠前的组合。"""
    adapter = MultiSourceAdapter()

    ind_syms = filter_symbols(INDUSTRIAL_SYMBOLS)
    agr_syms = filter_symbols(AGRICULTURAL_SYMBOLS)

    print(f"工业品: {len(ind_syms)} 品种")
    print(f"农产品: {len(agr_syms)} 品种")

    # 采集+缓存
    print("\nPhase 1: 数据采集...")
    t0 = time.time()
    cache_ind = collect_and_cache(adapter, ind_syms, days=days)
    cache_agr = collect_and_cache(adapter, agr_syms, days=days)
    print(f"  采集完成 ({time.time() - t0:.0f}s)")

    combos = generate_grid()
    print(f"权重组合: {len(combos)}")

    print("\nPhase 2: 网格搜索 (两组并行)...")
    t0 = time.time()
    results_ind, results_agr = [], []
    for i, c in enumerate(combos):
        gs_i = score_with_cache(cache_ind, c["L1"], c["L2"], c["L3"], c["L4"])
        gs_a = score_with_cache(cache_agr, c["L1"], c["L2"], c["L3"], c["L4"])
        results_ind.append({"L1": c["L1"], "L2": c["L2"], "L3": c["L3"], "L4": c["L4"], **gs_i})
        results_agr.append({"L1": c["L1"], "L2": c["L2"], "L3": c["L3"], "L4": c["L4"], **gs_a})
        if (i + 1) % 5 == 0:
            print(f"  [{i + 1}/{len(combos)}]", flush=True)

    # 分别排序
    def sort_key(x):
        return x.get("STRONG", 0) * 1.5 + x.get("WATCH", 0)

    results_ind.sort(key=sort_key, reverse=True)
    results_agr.sort(key=sort_key, reverse=True)

    # 找交叉组合（两组Top5中都出现的权重）
    top5_ind = {(r["L1"], r["L2"], r["L3"], r["L4"]) for r in results_ind[:5]}
    top5_agr = {(r["L1"], r["L2"], r["L3"], r["L4"]) for r in results_agr[:5]}
    crossing = top5_ind & top5_agr

    # 合并评分
    combined = []
    for c in combos:
        gs_i = next(
            r
            for r in results_ind
            if r["L1"] == c["L1"] and r["L2"] == c["L2"] and r["L3"] == c["L3"] and r["L4"] == c["L4"]
        )
        gs_a = next(
            r
            for r in results_agr
            if r["L1"] == c["L1"] and r["L2"] == c["L2"] and r["L3"] == c["L3"] and r["L4"] == c["L4"]
        )
        total_s = gs_i.get("STRONG", 0) + gs_a.get("STRONG", 0)
        total_w = gs_i.get("WATCH", 0) + gs_a.get("WATCH", 0)
        combined.append(
            {
                "L1": c["L1"],
                "L2": c["L2"],
                "L3": c["L3"],
                "L4": c["L4"],
                "STRONG": total_s,
                "WATCH": total_w,
                "ind_STRONG": gs_i.get("STRONG", 0),
                "ind_WATCH": gs_i.get("WATCH", 0),
                "agr_STRONG": gs_a.get("STRONG", 0),
                "agr_WATCH": gs_a.get("WATCH", 0),
                "cross": (c["L1"], c["L2"], c["L3"], c["L4"]) in crossing,
            }
        )
    combined.sort(key=lambda x: x["STRONG"] * 1.5 + x["WATCH"], reverse=True)

    # 输出
    print(f"\n{'=' * 55}")
    print(f"=== 交叉验证结果 ===")
    print(
        f"{'L1':>3} {'L2':>3} {'L3':>3} {'L4':>3}  "
        f"{'S总':>3} {'W总':>3}  {'S工':>3} {'W工':>3} {'S农':>3} {'W农':>3}  {'★':>3}"
    )
    print(f"{'-' * 55}")
    for r in combined[:10]:
        tag = " ★" if r["cross"] else ""
        print(
            f"{r['L1']:>3} {r['L2']:>3} {r['L3']:>3} {r['L4']:>3}  "
            f"{r['STRONG']:>3} {r['WATCH']:>3}  "
            f"{r['ind_STRONG']:>3} {r['ind_WATCH']:>3} {r['agr_STRONG']:>3} {r['agr_WATCH']:>3}"
            f"  {tag}"
        )

    # 基准
    bl_i = score_with_cache(cache_ind, 40, 30, 20, 10)
    bl_a = score_with_cache(cache_agr, 40, 30, 20, 10)
    print(f"\nBaseline 40/30/20/10:")
    print(f"  工业品: {bl_i}")
    print(f"  农产品: {bl_a}")
    print(f"  Time: {time.time() - t0:.0f}s")

    # 保存
    out_dir = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"optimize_cross_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "baseline": {"industrial": bl_i, "agricultural": bl_a},
                "crossing": list(crossing),
                "top10": combined[:10],
                "total_combos": len(combos),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n结果已保存: {path}")
    return combined


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="quant-daily 权重网格搜索 v1.0")
    parser.add_argument("--symbols", default=None, help="指定品种(逗号分隔)")
    parser.add_argument("--days", type=int, default=120, help="历史数据天数")
    parser.add_argument("--max-symbols", type=int, default=0, help="限制品种数量（快速测试用）")
    parser.add_argument("--cross", action="store_true", default=True, help="交叉验证（默认开启）")
    parser.add_argument("--single", action="store_true", default=False, help="单组搜索（不交叉验证）")
    args = parser.parse_args()

    if args.single:
        if args.symbols:
            raw = args.symbols.split(",")
            symbols = [(s.upper(), "") for s in raw]
            symbols = [(s, n) for s, n in symbols if any(s == x[0].upper() for x in ALL_SYMBOLS)]
        else:
            symbols = ALL_SYMBOLS[: args.max_symbols] if args.max_symbols > 0 else ALL_SYMBOLS
        run_optimization(symbols=symbols, days=args.days)
    else:
        run_cross_validation(days=args.days)
