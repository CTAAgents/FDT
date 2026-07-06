# -*- coding: utf-8 -*-
"""
quant-daily 历史回放评估框架 v1.0
=================================
基于 commodity-trend-signal backtest/evaluate.py 迁移

5步工作流：
  Step 1: 全品种扫描 (scan_all.py)
  Step 2: 传统回放 baseline (--no-split)
  Step 3: 样本外验证 (--split)
  Step 4: 权重网格搜索 (optimize_weights.py)
  Step 5: 应用最优权重

用法：
  python -m scripts.backtest.evaluate --no-split --days 120 --forward 5 --mode eval
  python -m scripts.backtest.evaluate --split --train-ratio 0.7
"""

import sys, os, json, time, math
from datetime import datetime
from collections import defaultdict

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
PARENT_SKILLS = os.path.dirname(SKILL_DIR)  # ~/.workbuddy/skills/ (fallback)
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
from signals.scoring_system import calculate_composite_score, WL1, WL2, WL3, WL4
from config.symbols import ALL_SYMBOLS


# ============================================================
# 数据采集
# ============================================================


def collect_data(days=120):
    """采集所有品种的K线数据，返回 {sym: (name, klines)}"""
    print(f"[COLLECT] 采集 {len(ALL_SYMBOLS)} 品种, days={days}...")
    adapter = MultiSourceAdapter()
    data = {}
    for i, (sym, name) in enumerate(ALL_SYMBOLS):
        try:
            resp = adapter.get_kline(variety=sym, days=days)
            if isinstance(resp, dict) and resp.get("success"):
                valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
                if len(valid) >= 60:
                    data[sym] = (name, valid)
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f"  [{i + 1}/{len(ALL_SYMBOLS)}] {len(data)} OK", flush=True)
    print(f"  完成: {len(data)}/{len(ALL_SYMBOLS)}")
    return data, adapter


# ============================================================
# 历史回放评分
# ============================================================


def replay_scores(all_data, step=5):
    """在历史K线上逐段回放评分（所有数据用于评分 + 收益计算在同一窗口内）。

    step=5 表示每5天回放一次，加速回测。
    """
    print(f"\n[REPLAY] 历史回放评分 (step={step})...")
    all_scores = []
    skipped = 0

    for sym, (name, klines) in sorted(all_data.items()):
        closes = [float(r["close"]) for r in klines]
        if len(closes) < 80:
            skipped += 1
            continue

        sym_scoring = {"last_price": closes[-1], "open_interest": klines[-1].get("open_interest", 0)}

        # 沿时间轴滑动
        for start in range(40, len(klines) - 20, step):
            window = klines[: start + 1]
            if len(window) < 50:
                continue
            w_closes = [float(r["close"]) for r in window]
            df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in window]

            tech = _compute_indicators_numpy(df, sym)
            current_price = tech.get("last_price", float(df["close"].iloc[-1]))
            sd = {"last_price": current_price, "open_interest": tech.get("open_interest", 0)}

            sc = calculate_composite_score(tech, sd, 0, w_closes, None)

            # 后 N 日收益率
            future_returns = {}
            for fd in [3, 5, 10, 20]:
                idx = start + fd
                if idx < len(closes):
                    ret = (closes[idx] / closes[start] - 1) * 100
                    future_returns[f"ret_{fd}d"] = ret
            if not future_returns:
                continue

            all_scores.append(
                {
                    "sym": sym,
                    "date": window[-1].get("date", ""),
                    "total": sc["total"],
                    "grade": sc["grade"],
                    "direction": sc["direction"],
                    "l1": sc.get("L1_score", 0),
                    "l2": sc.get("L2_score", 0),
                    "l3": sc.get("L3_score", 0),
                    "l4": sc.get("L4_score", 0),
                    "veto": sc.get("veto_score", 0),
                    **future_returns,
                }
            )

    print(f"  完成: {len(all_scores)} 个信号样本 (跳过{skipped}个品种)")
    return all_scores


# ============================================================
# 样本外分割回放
# ============================================================


def replay_scores_split(all_data, step=5, train_ratio=0.7):
    """严格时间分割：前 train_ratio 用于评分，后 (1-train_ratio) 用于收益验证。"""
    print(f"\n[SPLIT] 样本外分割回放 (train={train_ratio:.0%}, step={step})...")
    train_scores = []
    test_scores = []

    for sym, (name, klines) in sorted(all_data.items()):
        closes = [float(r["close"]) for r in klines]
        if len(closes) < 80:
            continue

        split_idx = int(len(klines) * train_ratio)
        train_klines = klines[:split_idx]
        test_klines = klines[split_idx:]
        train_closes = closes[:split_idx]

        if len(train_klines) < 50 or len(test_klines) < 20:
            continue

        # 训练期评分
        for start in range(40, len(train_klines) - 1, step):
            window = train_klines[: start + 1]
            if len(window) < 50:
                continue
            w_closes = [float(r["close"]) for r in window]
            df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in window]
            tech = _compute_indicators_numpy(df, sym)
            current_price = tech.get("last_price", float(df["close"].iloc[-1]))
            sd = {"last_price": current_price, "open_interest": tech.get("open_interest", 0)}
            sc = calculate_composite_score(tech, sd, 0, w_closes, None)

            train_scores.append(
                {
                    "sym": sym,
                    "date": window[-1].get("date", ""),
                    "total": sc["total"],
                    "grade": sc["grade"],
                    "direction": sc["direction"],
                    "set": "train",
                }
            )

        # 测试期评分（K线从训练+测试拼接）
        full_until_test = train_klines + test_klines
        for start in range(len(train_klines), len(full_until_test) - 1, step):
            window = full_until_test[: start + 1]
            if len(window) < 50:
                continue
            w_closes = [float(r["close"]) for r in window]
            df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in window]
            tech = _compute_indicators_numpy(df, sym)
            current_price = tech.get("last_price", float(df["close"].iloc[-1]))
            sd = {"last_price": current_price, "open_interest": tech.get("open_interest", 0)}
            sc = calculate_composite_score(tech, sd, 0, w_closes, None)

            # 测试期收益
            future_returns = {}
            for fd in [3, 5]:
                idx = start + fd
                if idx < len(closes):
                    ret = (closes[idx] / closes[start] - 1) * 100
                    future_returns[f"ret_{fd}d"] = ret
            if not future_returns:
                continue

            test_scores.append(
                {
                    "sym": sym,
                    "date": window[-1].get("date", ""),
                    "total": sc["total"],
                    "grade": sc["grade"],
                    "direction": sc["direction"],
                    "set": "test",
                    **future_returns,
                }
            )

    print(f"  训练期: {len(train_scores)} 信号 | 测试期: {len(test_scores)} 信号")
    return train_scores, test_scores


# ============================================================
# 绩效评估
# ============================================================


def evaluate_performance(scores, forward_days=5):
    """按等级统计胜率、均收益、盈亏比。"""
    ret_key = f"ret_{forward_days}d"
    by_grade = defaultdict(list)
    by_dir = defaultdict(list)

    for s in scores:
        ret = s.get(ret_key)
        if ret is None:
            continue
        by_grade[s["grade"]].append(ret)
        by_dir[s["direction"]].append(ret)

    stats = {"by_grade": {}, "by_direction": {}, "summary": {}}
    total = 0

    for grade in ["STRONG", "WATCH", "WEAK", "NOISE"]:
        arr = by_grade.get(grade, [])
        if not arr:
            continue
        wins = [r for r in arr if r > 0]
        total += len(arr)
        avg_ret = sum(arr) / len(arr)
        win_rate = len(wins) / len(arr) * 100 if arr else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(r for r in arr if r <= 0) / max(len([r for r in arr if r <= 0]), 1)
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        stats["by_grade"][grade] = {
            "count": len(arr),
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
            "profit_factor": round(profit_factor, 2),
        }

    for direction in ["BUY", "SELL"]:
        arr = by_dir.get(direction, [])
        if not arr:
            continue
        wins = [r for r in arr if r > 0]
        avg_ret = sum(arr) / len(arr)
        win_rate = len(wins) / len(arr) * 100 if arr else 0
        stats["by_direction"][direction] = {
            "count": len(arr),
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
        }

    stats["summary"] = {"total_signals": total, "forward_days": forward_days}
    return stats


# ============================================================
# 权重优化（轻量版，采集一次指标缓存后针对各权重组合只做评分）
# ============================================================


def generate_grid():
    """生成L1-L4权重组合网格。"""
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


def optimize_weights(scores, forward_days=5, metric="profit_factor", baseline=(40, 30, 20, 10)):
    """对已有评分数据做重加权优化。"""
    ret_key = f"ret_{forward_days}d"
    combos = generate_grid()
    print(f"  权重组合: {len(combos)}")

    # 过滤有效信号
    valid = [s for s in scores if s.get(ret_key) is not None]
    if not valid:
        print("  [WARN] 无有效收益数据")
        return []

    results = []
    for c in combos:
        # 重计算总分
        total_scaled = 0
        weighted = {"STRONG": 0, "WATCH": 0, "WEAK": 0, "NOISE": 0}
        for s in valid:
            w1 = c["L1"]
            w2 = c["L2"]
            w3 = c["L3"]
            w4 = c["L4"]
            # 从已存的l1~l4原始分重算
            l1r = s.get("l1", 0)
            l2r = s.get("l2", 0)
            l3r = s.get("l3", 0)
            l4r = s.get("l4", 0)
            v = s.get("veto", 0)
            # 反算原始内部分
            l1_raw = round(l1r * 40.0 / baseline[0]) if baseline[0] > 0 else l1r
            l2_raw = round(l2r * 25.0 / baseline[1]) if baseline[1] > 0 else l2r
            l3_raw = round(l3r * 25.0 / baseline[2]) if baseline[2] > 0 else l3r
            l4_raw = round(l4r * 10.0 / baseline[3]) if baseline[3] > 0 else l4r
            # 按新权重重算
            wl1 = c["L1"]
            wl2 = c["L2"]
            wl3 = c["L3"]
            wl4 = c["L4"]
            l1s = round(min(l1_raw, 40) * wl1 / 40.0)
            l2s = round(l2_raw * wl2 / 25.0)
            l3s = round(l3_raw * wl3 / 25.0)
            l4s = round(l4_raw * wl4 / 10.0)
            total = l1s + l2s + l3s + l4s + v
            total = max(0, min(100, total))

            if total >= 75:
                weighted["STRONG"] += 1
            elif total >= 60:
                weighted["WATCH"] += 1
            elif total >= 40:
                weighted["WEAK"] += 1
            else:
                weighted["NOISE"] += 1

        results.append(
            {
                "L1": c["L1"],
                "L2": c["L2"],
                "L3": c["L3"],
                "L4": c["L4"],
                **weighted,
                "signal_ratio": round((weighted["STRONG"] + weighted["WATCH"]) / len(valid), 3),
                "total_signals": len(valid),
            }
        )

    results.sort(key=lambda x: x["STRONG"] * 1.5 + x["WATCH"], reverse=True)
    return results


# ============================================================
# 结果保存
# ============================================================


def save_results(data, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"evaluate_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  结果保存: {path}")


# ============================================================
# CLI 入口
# ============================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="quant-daily 历史回放评估 v1.0")
    parser.add_argument("--days", type=int, default=120, help="历史数据天数")
    parser.add_argument("--forward", type=int, default=5, help="后N日收益窗口")
    parser.add_argument("--step", type=int, default=5, help="回放步长")
    parser.add_argument("--mode", default="full", choices=["collect", "eval", "optimize", "full"], help="运行模式")
    parser.add_argument("--split", action="store_true", default=False, help="启用样本外分割验证")
    parser.add_argument(
        "--no-split", action="store_true", default=False, help="禁用分割（默认false，使用--no-split开关）"
    )
    parser.add_argument("--train-ratio", type=float, default=0.7, help="训练集比例（--split时生效）")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    args = parser.parse_args()

    output_dir = args.output_dir or os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")
    os.makedirs(output_dir, exist_ok=True)

    all_data, collector = collect_data(days=args.days)

    if args.mode in ("collect", "full"):
        if args.split:
            train_s, test_s = replay_scores_split(all_data, step=args.step, train_ratio=args.train_ratio)
            stats = evaluate_performance(test_s, forward_days=args.forward)
            print("\n=== 样本外验证 (测试集) ===")
            for g in ["STRONG", "WATCH", "WEAK", "NOISE"]:
                gs = stats["by_grade"].get(g, {})
                if gs.get("count", 0) > 0:
                    print(f"  {g}: {gs['count']}次 胜率{gs['win_rate']}% 均收益{gs['avg_return']}%")
            save_results(
                {"mode": "split", "performance": stats, "train_count": len(train_s), "test_count": len(test_s)},
                output_dir,
            )
        else:
            scores = replay_scores(all_data, step=args.step)
            print(f"  总信号: {len(scores)}")
            save_results({"mode": "collect", "count": len(scores), "scores": scores[:100]}, output_dir)
    else:
        # 没有持久化时直接运行
        if args.split:
            train_s, test_s = replay_scores_split(all_data, step=args.step, train_ratio=args.train_ratio)
            scores = test_s
        else:
            scores = replay_scores(all_data, step=args.step)

    if args.mode in ("eval", "full") and scores:
        stats = evaluate_performance(scores, forward_days=args.forward)
        print("\n=== 绩效评估 ===")
        for g in ["STRONG", "WATCH", "WEAK", "NOISE"]:
            gs = stats["by_grade"].get(g, {})
            if gs.get("count", 0) > 0:
                pf = gs.get("profit_factor", "∞")
                print(
                    f"  {g}: {gs['count']:>4}次 胜率{gs['win_rate']:>5.1f}%  "
                    f"均收益{gs['avg_return']:>+6.2f}% 盈亏比{pf}"
                )
        print(f"  总信号: {stats['summary']['total_signals']} | 窗口: {args.forward}日")
        save_results({"mode": "eval", "performance": stats}, output_dir)

    if args.mode in ("optimize", "full") and scores:
        opt = optimize_weights(scores, forward_days=args.forward)
        if opt:
            print("\n=== 权重Top5 ===")
            print(f"  L1  L2  L3  L4  STRONG WATCH WEAK NOISE  信噪比")
            print(f"  {'-' * 42}")
            for r in opt[:5]:
                print(
                    f"  {r['L1']:>3} {r['L2']:>3} {r['L3']:>3} {r['L4']:>3}  "
                    f"{r['STRONG']:>5} {r['WATCH']:>5} {r['WEAK']:>4} {r['NOISE']:>5}  "
                    f"{r['signal_ratio']:>6.1%}"
                )
            save_results({"mode": "optimize", "top5": opt[:5]}, output_dir)

    print(f"\n[OK] 完成")


if __name__ == "__main__":
    main()
