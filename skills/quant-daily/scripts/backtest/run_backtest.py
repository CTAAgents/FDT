# -*- coding: utf-8 -*-
"""
quant-daily 完整回测引擎 v1.0
===============================
多时间截面采样 + 策略评估 + 蒙提卡罗基准对比

核心设计：
  1. 每品种取250日K线，从第80根起每10根采样一个时间截面
  2. 每个截面独立计算技术指标+评分
  3. 跟踪后N日收益率(5/10/20/30)
  4. WATCH+BUY / WEAK+SELL 策略评估
  5. 蒙提卡罗随机基准对比 (1000次)
  6. 结果持久化到 backtest/results/

用法：
  # 全量回测
  python -m scripts.backtest.run_backtest

  # 快速验证 (20品种)
  python -m scripts.backtest.run_backtest --max-symbols 20

  # 仅蒙提卡罗（已有数据）
  python -m scripts.backtest.run_backtest --monte-carlo-only
"""

import sys, os, json, time, random, math
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
from signals.scoring_system import calculate_composite_score, WL1, WL2, WL3, WL4
from config.symbols import ALL_SYMBOLS


# ============================================================
# 阶段1: 数据采集 + 多时间截面评分
# ============================================================


def collect_and_score(symbols, days=250, step=10, min_start=80):
    """采集K线并在多个时间截面评分。

    Args:
        symbols: [(sym, name), ...]
        days: 历史数据天数
        step: 采样间隔（每N根K线一个截面）
        min_start: 最少K线数（用于指标计算）

    Returns:
        observations: [{sym, date_idx, grade, direction, ret_5d, ret_10d, ret_20d, ...}, ...]
    """
    a = MultiSourceAdapter()
    observations = []
    skipped_symbols = 0

    for sym, name in symbols:
        try:
            resp = a.get_kline(variety=sym, days=days)
            if not (isinstance(resp, dict) and resp.get("success")):
                skipped_symbols += 1
                continue
            valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
            if len(valid) < min_start + 30:
                skipped_symbols += 1
                continue
            closes = [float(r["close"]) for r in valid]
            n = len(valid)

            # 多时间截面采样
            for start in range(min_start, n - 30, step):
                window = valid[: start + 1]
                wc = [float(r["close"]) for r in window]
                df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
                df["volume"] = [float(r.get("volume", 0)) for r in window]
                tech = _compute_indicators_numpy(df, sym)
                price = tech.get("last_price", float(df["close"].iloc[-1]))
                sd = {"last_price": price, "open_interest": tech.get("open_interest", 0)}
                sc = calculate_composite_score(tech, sd, 0, wc, None)

                ob = {
                    "sym": sym,
                    "name": name,
                    "date_idx": start,
                    "grade": sc["grade"],
                    "direction": sc["direction"],
                    "total": sc["total"],
                    "price": closes[start],
                }
                # 后N日收益率
                for fd in [5, 10, 20, 30]:
                    idx = start + fd
                    if idx < n:
                        ob[f"ret_{fd}d"] = (closes[idx] / closes[start] - 1) * 100
                observations.append(ob)
        except Exception:
            skipped_symbols += 1

    print(f"  [数据] {len(symbols)} 品种 → {len(observations)} 观测 ({skipped_symbols}跳过)")
    return observations


# ============================================================
# 阶段2: 策略评估
# ============================================================


def strategy_buy_watch(obs, forward_days=10):
    """策略1: WATCH信号出现时做多(BUY)，持有N日。"""
    signal_count = 0
    wins = 0
    returns = []
    key = f"ret_{forward_days}d"

    for ob in obs:
        if ob["grade"] == "WATCH" and ob["direction"] == "BUY":
            ret = ob.get(key)
            if ret is not None:
                signal_count += 1
                returns.append(ret)
                if ret > 0:
                    wins += 1

    win_rate = wins / signal_count * 100 if signal_count > 0 else 0
    avg_ret = sum(returns) / len(returns) if returns else 0
    profit = sum(1 for r in returns if r > 0)
    loss = sum(1 for r in returns if r <= 0)
    avg_win = sum(r for r in returns if r > 0) / max(profit, 1)
    avg_loss = sum(r for r in returns if r <= 0) / max(loss, 1)
    pf = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    sharpe = (avg_ret / max(np.std(returns, ddof=1), 1e-6)) if len(returns) > 1 else 0

    return {
        "signal_count": signal_count,
        "wins": wins,
        "losses": signal_count - wins,
        "win_rate": round(win_rate, 2),
        "avg_return": round(avg_ret, 3),
        "profit_factor": round(pf, 2),
        "sharpe": round(sharpe, 2),
        "max_return": round(max(returns), 3) if returns else 0,
        "min_return": round(min(returns), 3) if returns else 0,
        "std_return": round(np.std(returns, ddof=1), 3) if len(returns) > 1 else 0,
    }


def strategy_sell_weak(obs, forward_days=10):
    """策略2: WEAK信号做空(SELL)，持有N日。"""
    signal_count = 0
    wins = 0
    returns = []
    key = f"ret_{forward_days}d"

    for ob in obs:
        if ob["grade"] == "WEAK" and ob["direction"] == "SELL":
            ret = ob.get(key)
            if ret is not None:
                signal_count += 1
                returns.append(ret)
                if ret < 0:  # 做空，价格跌=赢
                    wins += 1

    win_rate = wins / signal_count * 100 if signal_count > 0 else 0
    avg_ret = sum(returns) / len(returns) if returns else 0
    profit = sum(1 for r in returns if r < 0)
    loss = sum(1 for r in returns if r >= 0)
    avg_win = abs(sum(r for r in returns if r < 0) / max(profit, 1))
    avg_loss = sum(r for r in returns if r >= 0) / max(loss, 1)
    pf = avg_win / max(avg_loss, 1e-6) if avg_loss != 0 else float("inf")

    return {
        "signal_count": signal_count,
        "wins": wins,
        "losses": signal_count - wins,
        "win_rate": round(win_rate, 2),
        "avg_return": round(avg_ret, 3),
        "profit_factor": round(pf, 2),
        "max_return": round(max(returns), 3) if returns else 0,
        "min_return": round(min(returns), 3) if returns else 0,
    }


def benchmark_all_random(obs, forward_days=10, n_iterations=1000):
    """蒙提卡罗基准：随机抽取与策略相同数量的观测，计算胜率分布。"""
    key = f"ret_{forward_days}d"
    valid_obs = [ob for ob in obs if ob.get(key) is not None]
    if not valid_obs:
        return {"avg_win_rate": 0, "p95_win_rate": 0, "p_value": 1.0}

    # 实际策略信号数
    n_watch_buy = len(
        [ob for ob in obs if ob["grade"] == "WATCH" and ob["direction"] == "BUY" and ob.get(key) is not None]
    )
    n_weak_sell = len(
        [ob for ob in obs if ob["grade"] == "WEAK" and ob["direction"] == "SELL" and ob.get(key) is not None]
    )

    results = {"WATCH_BUY": {}, "WEAK_SELL": {}}

    for strategy_name, n_signals, is_short in [
        ("WATCH_BUY", n_watch_buy, False),
        ("WEAK_SELL", n_weak_sell, True),
    ]:
        if n_signals < 3:
            results[strategy_name] = {
                "n_actual": n_signals,
                "avg_random_win_rate": 0,
                "p95_random_win_rate": 0,
                "p_value": 1.0,
                "note": "样本不足 (n<3)",
            }
            continue

        random_win_rates = []
        for _ in range(n_iterations):
            sample = random.sample(valid_obs, min(n_signals, len(valid_obs)))
            if is_short:
                wins = sum(1 for ob in sample if ob.get(key, 0) < 0)
            else:
                wins = sum(1 for ob in sample if ob.get(key, 0) > 0)
            random_win_rates.append(wins / len(sample) * 100)

        actual_win_rate = (
            strategy_buy_watch(obs, forward_days)["win_rate"]
            if strategy_name == "WATCH_BUY"
            else strategy_sell_weak(obs, forward_days)["win_rate"]
        )

        random_win_rates.sort()
        p95 = random_win_rates[int(n_iterations * 0.95)]
        p_value = sum(1 for wr in random_win_rates if wr >= actual_win_rate) / n_iterations

        results[strategy_name] = {
            "n_actual": n_signals,
            "actual_win_rate": actual_win_rate,
            "avg_random_win_rate": round(sum(random_win_rates) / n_iterations, 2),
            "median_random_win_rate": round(random_win_rates[n_iterations // 2], 2),
            "p95_random_win_rate": round(p95, 2),
            "p_value": round(p_value, 4),
            "is_significant": p_value < 0.05,
            "n_mc_iterations": n_iterations,
        }

    return results


# ============================================================
# 阶段3: 全维度报告
# ============================================================


def full_report(obs, results_dir):
    """生成完整的回测评估报告（打印版 + JSON保存）。"""
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "weights": {"WL1": WL1, "WL2": WL2, "WL3": WL3, "WL4": WL4},
        "total_observations": len(obs),
        "grade_distribution": {},
        "strategies": {},
        "monte_carlo": {},
    }

    # 等级分布
    for grade in ["STRONG", "WATCH", "WEAK", "NOISE"]:
        count = sum(1 for ob in obs if ob["grade"] == grade)
        report["grade_distribution"][grade] = count
    report["grade_distribution"]["total"] = len(obs)

    print(f"\n{'=' * 65}")
    print(f"  quant-daily 回测报告 (权重 {WL1}/{WL2}/{WL3}/{WL4})")
    print(f"  {report['timestamp']} | 观测: {len(obs)}")
    print(f"{'=' * 65}")
    print(f"\n  等级分布:")
    for grade in ["STRONG", "WATCH", "WEAK", "NOISE"]:
        c = report["grade_distribution"][grade]
        pct = c / len(obs) * 100 if obs else 0
        print(f"    {grade:<8}: {c:>4} ({pct:>5.1f}%)")

    for fd in [5, 10, 20]:
        print(f"\n  ── 持仓 {fd}日 ──")

        # WATCH+BUY
        s1 = strategy_buy_watch(obs, forward_days=fd)
        report["strategies"][f"WATCH_BUY_{fd}d"] = s1
        print(
            f"    WATCH+BUY: 信号{s1['signal_count']:>4}次 "
            f"胜率{s1['win_rate']:>5.1f}% 均收益{s1['avg_return']:>+7.3f}% "
            f"盈亏比{s1['profit_factor']:>5.2f} Sharpe{s1['sharpe']:>5.2f}"
        )

        # WEAK+SELL
        s2 = strategy_sell_weak(obs, forward_days=fd)
        report["strategies"][f"WEAK_SELL_{fd}d"] = s2
        print(
            f"    WEAK+SELL: 信号{s2['signal_count']:>4}次 "
            f"胜率{s2['win_rate']:>5.1f}% 均收益{s2['avg_return']:>+7.3f}% "
            f"盈亏比{s2['profit_factor']:>5.2f}"
        )

    # 蒙提卡罗
    print(f"\n  ── 蒙提卡罗基准 (1000次) ──")
    mc = benchmark_all_random(obs, forward_days=10, n_iterations=1000)
    report["monte_carlo"] = mc

    for name, data in mc.items():
        if "note" in data:
            print(f"    {name}: {data['note']}")
            continue
        sig = "[OK] 显著" if data.get("is_significant") else "[xx] 不显著"
        print(
            f"    {name}: 实际胜率{data['actual_win_rate']:.1f}% vs "
            f"随机中位{data['median_random_win_rate']:.1f}% "
            f"(p={data['p_value']:.4f}) {sig}"
        )

    # 保存
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(results_dir, f"backtest_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {path}")

    return report


# ============================================================
# CLI
# ============================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="quant-daily 完整回测引擎")
    parser.add_argument("--days", type=int, default=250, help="历史数据天数")
    parser.add_argument("--step", type=int, default=10, help="时间截面采样间隔")
    parser.add_argument("--max-symbols", type=int, default=0, help="限制品种数（快速测试）")
    parser.add_argument("--symbols", default=None, help="指定品种(逗号分隔)")
    parser.add_argument("--mc-iterations", type=int, default=1000, help="蒙提卡罗迭代次数")
    args = parser.parse_args()

    results_dir = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")

    # 筛选品种
    if args.symbols:
        raw = args.symbols.split(",")
        sym_set = set(s.strip().lower() for s in raw)
        symbols = [(s, n) for s, n in ALL_SYMBOLS if s.strip().lower() in sym_set]
    elif args.max_symbols > 0:
        symbols = ALL_SYMBOLS[: args.max_symbols]
    else:
        symbols = ALL_SYMBOLS

    print(f"quant-daily 全量回测 | 品种: {len(symbols)} | 天数: {args.days} | 步长: {args.step}")
    print(f"权重 {WL1}/{WL2}/{WL3}/{WL4}")

    t0 = time.time()

    # 阶段1: 采集+评分
    print("\n[阶段1] 数据采集 + 多时间截面评分...")
    obs = collect_and_score(symbols, days=args.days, step=args.step)
    if not obs:
        print("[ERROR] 无有效观测")
        return

    # 阶段2-3: 评估+报告
    print("\n[阶段2-3] 策略评估 + 蒙提卡罗...")
    report = full_report(obs, results_dir)

    print(f"\n⏱  总耗时: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
