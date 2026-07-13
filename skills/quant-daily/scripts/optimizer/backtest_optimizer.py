"""Walk-Forward 回测优化器 — 用历史数据训练+测试参数

三阶段方法:
  1. 数据准备: 加载历史K线, 采样多个时间截面, 每个截面计算指标
  2. Walk-Forward: 按时间分割训练集/测试集, 网格搜索最优参数
  3. 评估+写入: 在测试集验证, 写入 per_symbol / per_period 层

用法:
  python -m scripts.optimizer.run --backtest                          # 全品种日线
  python -m scripts.optimizer.run --backtest --period daily           # 全品种日线
  python -m scripts.optimizer.run --backtest --symbol rb              # 单品种
  python -m scripts.optimizer.run --backtest --period 60m             # 全品种60分钟
  python -m scripts.optimizer.run --backtest --auto-write             # 优化后自动写入
"""

import sys, os, json, math
from datetime import datetime
from copy import deepcopy
from typing import Optional

import numpy as np
import pandas as pd

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from config.symbols import ALL_SYMBOLS, SYMBOL_DETAILS
from config.settings import (
    SYMBOL_CHAIN_MAP,
    CHANNEL_BREAKOUT_CONFIG,
    set_param_overrides,
    clear_param_overrides,
    DEBATE_ENTRY_MIN_ABS,
)
# MultiSourceAdapter 已废弃 — scan_all.py 直调 FDC
from scan_all import collect_kline_for_all
from indicators.calc_core import calculate_tdx_compatible
from strategies.registry import get_strategy


# ─── 可优化参数空间（与 param_optimizer.py 保持同步）───
# 格式: (section, key, 候选值列表, 中文名)
PARAM_CANDIDATES = [
    ("adx", "exhaustion_threshold", [50, 55, 60, 65, 70, 75], "ADX衰竭阈值"),
    ("adx", "trend_threshold", [20, 25, 30, 35], "ADX趋势阈值"),
    ("adx", "exhaustion_penalty", [3.0, 5.0, 7.0, 10.0], "衰竭惩罚分"),
    ("adx", "trend_bonus", [2.0, 3.0, 5.0, 7.0], "趋势健康加分"),
    ("dc20", "break_base_score", [20.0, 25.0, 30.0, 35.0, 40.0], "DC20突破基础分"),
    ("dc20", "break_strong_pct", [0.5, 1.0, 1.5, 2.0], "大幅突破阈值%"),
    ("dc20", "break_strong_bonus", [5.0, 10.0, 15.0], "大幅突破加减分"),
    ("volume", "explosive_ratio", [1.3, 1.5, 1.8, 2.0, 2.5], "放量爆发阈值"),
    ("volume", "explosive_score", [8.0, 10.0, 12.0, 15.0], "放量爆发评分"),
    ("volume", "weak_penalty", [-5.0, -3.0, -2.0, -1.0], "缩量惩罚分"),
    ("dc55", "trend_base_score", [5.0, 10.0, 15.0, 20.0], "DC55趋势基分"),
    ("dc55", "divergence_penalty", [5.0, 10.0, 15.0, 20.0], "趋势分歧惩罚"),
    ("bb", "width_high_score", [4.0, 6.0, 8.0, 10.0], "布林带宽高分"),
    ("bb", "squeeze_bonus", [1.0, 2.0, 3.0, 5.0], "布林挤压加分"),
    ("bb", "dc_consistency_bonus", [1.0, 2.0, 3.0, 5.0], "DC-BB一致加分"),
]

# 首批优化参数（覆盖面最广的4项）
PRIMARY_PARAMS = [
    ("adx", "exhaustion_threshold"),
    ("volume", "explosive_ratio"),
    ("dc20", "break_base_score"),
    ("dc55", "trend_base_score"),
]

# ─── Walk-Forward 结构配置（冻结 + 版本化）───
# ⚠ 结构变更铁律: 任何结构常量(窗口/采样/前瞻/阈值/分级/滞后)的修改,
#    视为"结构变更", 必须全量重基线 + 更新下方 WF_CHANGELOG, 否则相邻两次
#    wf_accuracy 不可比(尺子被换)。版本号须递增。
WF_CONFIG_VERSION = "1.0.0"

WF_CONFIG = {
    "version": WF_CONFIG_VERSION,
    "data": {
        "days_of_data": 400,
        "min_bars": 80,
        "sample_interval": 5,
    },
    "walk_forward": {
        "train_pct": 0.7,
        "test_pct": 0.3,
        "lookahead_bars": 5,
    },
    # 分级阈值(准确率下限% , 基于置信下界判定)
    "tiers": {
        "daily": {"good": 50, "medium": 40},
    },
    "hysteresis_weeks": 3,           # 纳入/剔除需连续 N 周一致才生效
    "ci_z": 1.96,                    # 置信区间 z 值 (95% CI)
    "min_test_signals_for_ci": 10,   # 测试信号数低于此 → 定级 unknown(未知带)
    "core_universe": [               # 稳定核心宇宙(结构适合趋势跟踪, 永不自动剔除)
        "rb", "hc", "i", "j", "jm", "sc", "fu", "bu", "lu", "pg",
        "ta", "ma", "v", "pp", "l", "eg", "cu", "al", "zn", "au",
        "ag", "c", "m", "y", "p", "a", "rm", "oi", "sr", "cf", "ru", "sp",
    ],
}
WF_CHANGELOG = [
    "1.0.0 (2026-07-11): 初始冻结版本。整合原分散常量 + 新增滞后确认/置信下界定级/稳定核心宇宙。",
]

# ─── 向后兼容别名(旧代码/其他模块引用) ───
DAYS_OF_DATA = WF_CONFIG["data"]["days_of_data"]
MIN_BARS = WF_CONFIG["data"]["min_bars"]
SAMPLE_INTERVAL = WF_CONFIG["data"]["sample_interval"]
WF_TRAIN_PCT = WF_CONFIG["walk_forward"]["train_pct"]
WF_TEST_PCT = WF_CONFIG["walk_forward"]["test_pct"]
LOOKAHEAD_BARS = WF_CONFIG["walk_forward"]["lookahead_bars"]


def wilson_ci_lower(successes: int, n: int, z: float = 1.96) -> float:
    """Wilson 置信区间下界 (返回 0-1)。小样本下比 ±正态近似 更保守。"""
    if n == 0:
        return 0.0
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return max(0.0, center - margin)


def classify_tier(period: str, accuracy: float, test_signals: int,
                  wf_config: dict = WF_CONFIG) -> str:
    """基于置信下界(而非点估计)定级, 小样本落入 unknown(未知带)。

    period: 'daily'
    accuracy: 0-1 测试集准确率点估计
    test_signals: 测试集有效信号数
    """
    t = wf_config["tiers"][period]
    if test_signals < wf_config["min_test_signals_for_ci"]:
        return "unknown"
    lower = wilson_ci_lower(int(round(accuracy * test_signals)), test_signals,
                            wf_config["ci_z"])
    lower_pct = lower * 100.0
    if lower_pct >= t["good"]:
        return "good"
    elif lower_pct >= t["medium"]:
        return "medium"
    else:
        return "weak"


def _build_tech(close, high, low, volume, open_price, symbol, name):
    """从K线数据+指标引擎构建 tech dict（与 scan_all.py 一致）"""
    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    # 使用 calc_core 计算指标
    ind = calculate_tdx_compatible(
        high=np.array(high, dtype=float),
        low=np.array(low, dtype=float),
        close=np.array(close, dtype=float),
        open_price=np.array(open_price, dtype=float) if open_price is not None else None,
        volume=np.array(volume, dtype=float) if volume is not None else None,
    )
    tech = dict(ind)
    tech["symbol"] = symbol
    tech["name"] = name
    tech["last_price"] = float(close[-1])
    tech["price"] = float(close[-1])
    price = float(close[-1])
    prev = float(close[-2]) if len(close) > 1 else price
    tech["change_pct"] = (price / prev - 1) * 100
    tech["volume"] = int(round(float(volume[-1]))) if volume is not None and len(volume) > 0 else 0
    # 唐奇安通道
    dc20_period = min(20, len(close) - 1)
    if dc20_period >= 10:
        tech["DC20_UPPER"] = float(np.max(high[-dc20_period:]))
        tech["DC20_LOWER"] = float(np.min(low[-dc20_period:]))
        tech["DC20_POS"] = (close[-1] - tech["DC20_LOWER"]) / (tech["DC20_UPPER"] - tech["DC20_LOWER"] + 1e-10)
    dc55_period = min(55, len(close) - 1)
    if dc55_period >= 30:
        tech["DC55_UPPER"] = float(np.max(high[-dc55_period:]))
        tech["DC55_LOWER"] = float(np.min(low[-dc55_period:]))
        tech["DC55_MID"] = (tech["DC55_UPPER"] + tech["DC55_LOWER"]) / 2
        tech["DC55_POS"] = (close[-1] - tech["DC55_LOWER"]) / (tech["DC55_UPPER"] - tech["DC55_LOWER"] + 1e-10)
        half = dc55_period // 2
        mid_first = (np.max(high[-dc55_period:-half]) + np.min(low[-dc55_period:-half])) / 2
        mid_last = (np.max(high[-half:]) + np.min(low[-half:])) / 2
        tech["DC55_TREND"] = "up" if mid_last > mid_first else "down"
    # 布林带
    bb20 = min(20, len(close) - 1)
    if bb20 >= 10 and ind.get("boll_upper") is not None:
        tech["BB_UPPER"] = ind["boll_upper"]
        tech["BB_MIDDLE"] = ind["boll_mid"]
        tech["BB_LOWER"] = ind["boll_lower"]
        bu, bl = ind["boll_upper"], ind["boll_lower"]
        tech["BB_POS"] = (close[-1] - bl) / (bu - bl + 1e-10) if (bu - bl) != 0 else 0.5
        tech["BB_WIDTH_PCT"] = (bu - bl) / ((bu + bl) / 2 + 1e-10) * 100 if (bu + bl) > 0 else 0
        # BB squeeze: 带宽小于过去20日的均值
        if len(close) > 40:
            widths = []
            for i in range(-40, 0):
                bu_i = float(np.max(high[i-20:i])) if i-20 >= 0 else tech["BB_UPPER"]
                bl_i = float(np.min(low[i-20:i])) if i-20 >= 0 else tech["BB_LOWER"]
                widths.append((bu_i - bl_i) / ((bu_i + bl_i) / 2 + 1e-10) * 100)
            avg_width = np.mean(widths) if widths else 0
            tech["BB_SQUEEZE"] = bool(tech["BB_WIDTH_PCT"] < avg_width * 0.8)
        else:
            tech["BB_SQUEEZE"] = False
    # dc20_break
    if tech.get("DC20_UPPER") and tech.get("DC20_LOWER"):
        if close[-1] > tech["DC20_UPPER"]:
            tech["dc20_break"] = "up"
        elif close[-1] < tech["DC20_LOWER"]:
            tech["dc20_break"] = "down"
        else:
            tech["dc20_break"] = "none"
    # 补充字段
    tech["ADX"] = ind.get("adx", 0)
    tech["RSI14"] = ind.get("rsi", 50)
    tech["ATR"] = ind.get("atr", 0)
    tech["ma_align"] = "mixed"
    tech["stage"] = "unknown"
    tech["Z_SCORE"] = 0.0
    tech["z_score"] = 0.0
    return tech, df


def load_historical_data(symbols_with_names: list, period: str = "daily", days: int = DAYS_OF_DATA) -> dict:
    """加载多品种历史K线数据"""
    print(f"  [加载数据] {period} | 品种: {len(symbols_with_names)} | {days}天")
    from scan_all import collect_kline_for_all
    kline_data = collect_kline_for_all(symbols_with_names, days=days, min_bars=MIN_BARS, period=period)
    print(f"  [完成] {len(kline_data)}/{len(symbols_with_names)} 品种数据就绪")
    return kline_data


def prepare_snapshots(symbol: str, name: str, kline_data: dict,
                      period: str = "daily") -> list:
    """对一个品种的历史K线采样时间截面

    返回: [(bar_index, tech_dict, df, next_N_prices, next_N_change_pct), ...]
    """
    if symbol not in kline_data:
        return []

    _, dlist = kline_data[symbol]
    if len(dlist) < MIN_BARS:
        return []

    # 转为numpy数组
    opens = np.array([float(r["open"]) for r in dlist])
    highs = np.array([float(r["high"]) for r in dlist])
    lows = np.array([float(r["low"]) for r in dlist])
    closes = np.array([float(r["close"]) for r in dlist])
    volumes = np.array([float(r.get("volume", 0)) for r in dlist])

    n = len(closes)
    snapshots = []

    # 从 MIN_BARS 开始, 每隔 SAMPLE_INTERVAL 采样一个截面
    for i in range(MIN_BARS, n - LOOKAHEAD_BARS, SAMPLE_INTERVAL):
        # 取到 i 为止的数据
        close_i = closes[:i+1]
        high_i = highs[:i+1]
        low_i = lows[:i+1]
        vol_i = volumes[:i+1]
        open_i = opens[:i+1]

        # 当前截面技术指标
        tech, df = _build_tech(close_i, high_i, low_i, vol_i, open_i, symbol, name)

        # 后续 N 根K线的价格变化（用于评估信号方向正确性）
        future_closes = closes[i+1:i+1+LOOKAHEAD_BARS]
        future_changes = []
        for j, fc in enumerate(future_closes):
            change = (fc / float(close_i[-1]) - 1) * 100
            future_changes.append(float(change))

        # 未来方向：正=涨，负=跌
        future_direction = "bull" if (np.mean(future_changes) > 0 if future_changes else 0) else "bear"

        snapshots.append({
            "bar_idx": i,
            "tech": tech,
            "df": df,
            "last_price": float(close_i[-1]),
            "future_changes": future_changes,
            "future_direction": future_direction,
            "future_avg_change": float(np.mean(future_changes)) if future_changes else 0,
        })

    return snapshots


def run_strategy_with_overrides(tech_list, df_map, period, overrides: dict) -> list:
    """用指定参数覆盖运行策略评分"""
    if overrides:
        set_param_overrides(overrides)
    try:
        strategy = get_strategy("channel_breakout")
        result = strategy.score(
            tech_list, mode="full", df_map=df_map,
            period=period, window_mode="fixed"
        )
        return result.get("all_ranked", [])
    finally:
        clear_param_overrides()


def evaluate_signal_accuracy(all_ranked, snapshots_dict) -> dict:
    """评估策略信号的准确性

    对每个品种, 检查信号方向 vs 实际价格方向
    返回: {symbol: {total_signals, correct, wrong, accuracy, ...}}
    """
    results = {}
    for item in all_ranked:
        sym = item["symbol"]
        snapshots = snapshots_dict.get(sym, [])
        if not snapshots:
            continue

        total = item.get("total", 0)
        direction = item.get("direction", "neutral")
        grade = item.get("grade", "NOISE")

        # 仅保留达到统一辩论入口阈值(DEBATE_ENTRY_MIN_ABS)的信号, 过滤 NOISE 级
        # 阈值由 config/settings.py 统一配置, 禁止在此写死 grade 元组
        if abs(total) < DEBATE_ENTRY_MIN_ABS:
            continue

        # 找到对应的 snapshot（按 bar_idx 最近的）
        # 实际上 all_ranked 里没有 bar_idx, 所以只能评估这个截面的信号
        # 这里简化: 用 snapshots 中最后一个截面的未来方向
        latest = snapshots[-1]
        correct = (
            (direction == "bull" and latest["future_direction"] == "bull") or
            (direction == "bear" and latest["future_direction"] == "bear")
        )
        results[sym] = {
            "signal": total,
            "direction": direction,
            "grade": grade,
            "actual_direction": latest["future_direction"],
            "correct": correct,
            "future_avg_change": latest["future_avg_change"],
        }

    return results


def _build_override(param_list: list, values: list) -> dict:
    """从参数列表和值列表构建 override dict"""
    override = {}
    for (section, key), val in zip(param_list, values):
        if section not in override:
            override[section] = {}
        override[section][key] = val
    return override


def _param_value_iterator(param_list):
    """生成所有候选值的笛卡尔积"""
    candidates = []
    for section, key in param_list:
        vals = None
        for s, k, vlist, *_ in PARAM_CANDIDATES:
            if s == section and k == key:
                vals = vlist
                break
        if not vals:
            return  # 跳过找不到的参数
        candidates.append(vals)

    # 递归生成笛卡尔积
    def _product(lists, prefix=None):
        if prefix is None:
            prefix = []
        if not lists:
            yield prefix
            return
        for v in lists[0]:
            yield from _product(lists[1:], prefix + [v])

    yield from _product(candidates)


def walk_forward_optimize(
    symbol: str,
    period: str = "daily",
    snapshots: list = None,
    param_list: list = None,
    verbose: bool = True,
) -> Optional[dict]:
    """对一个品种执行 Walk-Forward 参数优化

    流程:
      1. 按时间分割训练集(前70%)和测试集(后30%)
      2. 在训练集上网格搜索最优参数组合
      3. 在测试集上验证最优组合的准确率
      4. 返回优化结果

    Args:
        symbol: 品种代码
        period: 周期
        snapshots: 该品种的历史截面列表
        param_list: 要优化的参数列表, 默认 PRIMARY_PARAMS

    Returns:
        {best_params, train_score, test_score, ...} or None
    """
    if not snapshots or len(snapshots) < 10:
        if verbose:
            print(f"  ⚠ {symbol} ({period}): 截面不足 ({len(snapshots) if snapshots else 0}), 跳过")
        return None

    param_list = param_list or PRIMARY_PARAMS

    # ── 按时间分割 ──
    n = len(snapshots)
    split = int(n * WF_TRAIN_PCT)
    train_snapshots = snapshots[:split]
    test_snapshots = snapshots[split:]

    if len(train_snapshots) < 5 or len(test_snapshots) < 3:
        if verbose:
            print(f"  ⚠ {symbol}: 训练集={len(train_snapshots)} 测试集={len(test_snapshots)}, 跳过")
        return None

    if verbose:
        print(f"\n  ── {symbol} ({period}) WF优化 ──")
        print(f"  总截面: {n}, 训练: {len(train_snapshots)}, 测试: {len(test_snapshots)}")

    # ── 训练: 网格搜索 ──
    best_overall = {"score": -999, "params": None, "train_metrics": None}
    total_combos = 0

    for values in _param_value_iterator(param_list):
        override = _build_override(param_list, values)
        total_combos += 1

        # 在训练集上评分
        train_correct = 0
        train_total = 0
        train_pnl = 0

        for snap in train_snapshots:
            tech = snap["tech"]
            # 用当前参数运行评分
            result_item = _score_single(tech, snap["df"], period, override)
            if result_item is None:
                continue
            grade = result_item.get("grade", "NOISE")
            direction = result_item.get("direction", "neutral")

            # 仅保留达到统一辩论入口阈值(DEBATE_ENTRY_MIN_ABS)的信号, 过滤 NOISE 级
            if abs(result_item.get("total", 0)) < DEBATE_ENTRY_MIN_ABS:
                continue

            train_total += 1
            correct = (
                (direction == "bull" and snap["future_avg_change"] > 0) or
                (direction == "bear" and snap["future_avg_change"] < 0)
            )
            if correct:
                train_correct += 1
                train_pnl += abs(snap["future_avg_change"])
            else:
                train_pnl -= abs(snap["future_avg_change"])

        accuracy = train_correct / max(train_total, 1)
        avg_pnl = train_pnl / max(train_total, 1)
        score = accuracy * (avg_pnl + 1) * 100  # 综合评分

        if score > best_overall["score"]:
            best_overall = {
                "score": round(score, 1),
                "params": {s: dict(v) for s, v in override.items()},
                "train_metrics": {
                    "signals": train_total,
                    "correct": train_correct,
                    "accuracy": round(accuracy, 3),
                    "avg_pnl": round(avg_pnl, 3),
                },
            }

    if verbose:
        print(f"  搜索组合: {total_combos}")
        print(f"  最优(训练): {best_overall['params']}")
        print(f"  训练准确率: {best_overall['train_metrics']['accuracy']:.0%} "
              f"({best_overall['train_metrics']['correct']}/{best_overall['train_metrics']['signals']})")

    if best_overall["params"] is None:
        if verbose:
            print(f"  ⚠ {symbol}: 未找到有效参数组合")
        return None

    # ── 测试: 用最优参数在测试集上验证 ──
    test_correct = 0
    test_total = 0
    test_pnl = 0

    for snap in test_snapshots:
        tech = snap["tech"]
        result_item = _score_single(tech, snap["df"], period, best_overall["params"])
        if result_item is None:
            continue
        grade = result_item.get("grade", "NOISE")
        direction = result_item.get("direction", "neutral")

        # 仅保留达到统一辩论入口阈值(DEBATE_ENTRY_MIN_ABS)的信号, 过滤 NOISE 级
        if abs(result_item.get("total", 0)) < DEBATE_ENTRY_MIN_ABS:
            continue

        test_total += 1
        correct = (
            (direction == "bull" and snap["future_avg_change"] > 0) or
            (direction == "bear" and snap["future_avg_change"] < 0)
        )
        if correct:
            test_correct += 1
            test_pnl += abs(snap["future_avg_change"])
        else:
            test_pnl -= abs(snap["future_avg_change"])

    test_accuracy = test_correct / max(test_total, 1)
    test_avg_pnl = test_pnl / max(test_total, 1)

    best_overall["test_metrics"] = {
        "signals": test_total,
        "correct": test_correct,
        "accuracy": round(test_accuracy, 3),
        "avg_pnl": round(test_avg_pnl, 3),
    }

    if verbose:
        print(f"  测试准确率: {test_accuracy:.0%} "
              f"({test_correct}/{test_total})  avg_pnl={test_avg_pnl:.2f}")

    return best_overall


def _score_single(tech: dict, df, period: str, override: dict) -> Optional[dict]:
    """用指定参数对一个截面评分"""
    if override:
        set_param_overrides(override)
    try:
        strategy = get_strategy("channel_breakout")
        # 单品种评分
        result = strategy.score(
            [tech], mode="full", df_map={tech.get("symbol", ""): df},
            period=period, window_mode="fixed"
        )
        ranked = result.get("all_ranked", [])
        if ranked:
            return ranked[0]
        return None
    except Exception:
        return None
    finally:
        clear_param_overrides()


def optimize_period(
    period: str = "daily",
    symbols: list = None,
    auto_write: bool = False,
    verbose: bool = True,
) -> list:
    """优化某个周期下所有品种的参数

    Args:
        period: "daily" 或 "60m"
        symbols: 品种列表, 默认全品种
        auto_write: 是否自动写入 per_symbol

    Returns:
        优化结果列表
    """
    if symbols is None:
        symbols = ALL_SYMBOLS

    print(f"\n{'='*55}")
    print(f"  Walk-Forward 参数优化 — {period}")
    print(f"{'='*55}")

    # 1. 加载历史数据
    sym_names = [(s, n) for s, n in symbols]
    kline_data = load_historical_data(sym_names, period=period)

    # 2. 为每个品种准备时间截面
    all_snapshots = {}
    for sym, name in sym_names:
        snaps = prepare_snapshots(sym, name, kline_data, period=period)
        if snaps:
            all_snapshots[sym] = snaps

    print(f"  有效截面品种: {len(all_snapshots)}/{len(sym_names)}")

    # 3. Walk-Forward 优化
    results = []
    for sym, name in sym_names:
        snaps = all_snapshots.get(sym, [])
        result = walk_forward_optimize(sym, period, snaps, verbose=verbose)
        if result:
            result["symbol"] = sym
            result["name"] = name
            result["period"] = period
            results.append(result)

            # 4. 自动写入（要求测试信号数 ≥ min_test_signals_for_ci，防小样本过拟合）
            tm = result.get("test_metrics", {})
            test_signals = tm.get("signals", 0)
            test_accuracy = tm.get("accuracy", 0)
            if (auto_write and test_accuracy > 0.5
                    and test_signals >= WF_CONFIG["min_test_signals_for_ci"]):
                params = result["params"]
                chain_name = SYMBOL_CHAIN_MAP.get(sym, "其他")
                _write_to_per_symbol(sym, period, params)
                if verbose:
                    print(f"  ✅ 已写入 per_symbol['{sym}']['{period}'] (信号{test_signals}个)")

    # 汇总（与写入条件一致：accuracy>0.5 + signals >= min_test_signals_for_ci）
    min_sig = WF_CONFIG["min_test_signals_for_ci"]
    improved = sum(
        1 for r in results
        if r.get("test_metrics", {}).get("accuracy", 0) > 0.5
        and r.get("test_metrics", {}).get("signals", 0) >= min_sig
    )
    print(f"\n  优化完成: {len(results)}/{len(sym_names)} 品种有结果, {improved} 个写入（信号≥{min_sig}）")
    return results


def _write_to_per_symbol(symbol: str, period: str, params: dict):
    """写入优化结果到 per_symbol 层"""
    if symbol not in CHANNEL_BREAKOUT_CONFIG["per_symbol"]:
        CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol] = {}
    if period not in CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol]:
        CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol][period] = {}

    for section, overrides in params.items():
        if section not in CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol][period]:
            CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol][period][section] = {}
        CHANNEL_BREAKOUT_CONFIG["per_symbol"][symbol][period][section].update(overrides)
