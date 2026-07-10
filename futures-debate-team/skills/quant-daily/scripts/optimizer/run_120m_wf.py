"""120m Walk-Forward 参数优化（自含，不依赖 strategies 包 import 链）

流程：
  1. 从TDX获取60m K线 → 重采样120m
  2. 每隔5根K线采样一个时间截面
  3. 前70%训练 → 网格搜索最优参数
  4. 后30%测试 → 验证准确率
  5. 输出品种级训练/测试对比

用法:
  python scripts/optimizer/run_120m_wf.py [--symbols PX,TA,...]
"""

import sys, os, json, itertools, math
from datetime import datetime
from itertools import product

import numpy as np
import pandas as pd

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from config.symbols import ALL_SYMBOLS
from config.settings import resolve_param, SYMBOL_CHAIN_MAP, SIGNAL_GRADE_THRESHOLDS, \
    CHANNEL_BREAKOUT_CONFIG, set_param_overrides, clear_param_overrides
from data.multi_source_adapter import MultiSourceAdapter
from indicators.calc_core import calculate_tdx_compatible

# ── 参数 ──
WATCH_THRESHOLD = SIGNAL_GRADE_THRESHOLDS["watch"]  # 40
WEAK_THRESHOLD = SIGNAL_GRADE_THRESHOLDS["weak"]    # 20
WF_TRAIN_PCT = 0.7
SAMPLE_INTERVAL = 5
LOOKAHEAD_BARS = 3      # 120m: 3根=6h后市
MIN_BARS = 60
DAYS_60M = 200          # 拉取200天60m数据
GRADE_MIN = "WEAK"       # 只统计 WEAK+ 信号

# 可优化参数（与 backtest_optimizer 一致）
PARAM_CANDIDATES = [
    ("adx", "exhaustion_threshold", [50, 55, 60, 65, 70, 75], "ADX衰竭阈值"),
    ("adx", "trend_threshold", [20, 25, 30, 35], "ADX趋势阈值"),
    ("volume", "explosive_ratio", [1.3, 1.5, 1.8, 2.0, 2.5], "放量爆发阈值"),
    ("dc20", "break_base_score", [20.0, 25.0, 30.0, 35.0, 40.0], "DC20突破基础分"),
    ("dc55", "trend_base_score", [5.0, 10.0, 15.0, 20.0], "DC55趋势基分"),
]
PRIMARY_PARAMS = [
    ("adx", "exhaustion_threshold"),
    ("volume", "explosive_ratio"),
    ("dc20", "break_base_score"),
    ("dc55", "trend_base_score"),
]

HOURLY_SYMBOLS = ["PX","PR","V","L","TA","EG","SA","PB","NI","AG",
                  "M","Y","RM","C","SR","CF","JD","AP","FG","OP","LC"]


def _get_chain(sym):
    return SYMBOL_CHAIN_MAP.get(sym, "其他")


def resample_60m_to_120m(df_60m):
    """60m→120m合并 — 会话感知: 仅在同一交易时段内合并, 不跨夜盘/午休边界

    交易所默认120m划分规则(以主力品种夜盘23:00收盘为例):
      夜盘:   21:00-23:00 → 60m bar×2 → 合并为1根120m bar
      上午:   9:00-11:30  → 60m bar×2 → 合并为1根120m bar
      下午:   13:30-15:00 → 60m bar×2 → 合并为1根120m bar

    检测方式: 相邻bar时间差>120分钟 → 会话边界 → 不合并
    """
    if df_60m is None or len(df_60m) < 2:
        return pd.DataFrame()
    df = df_60m.copy()
    if "datetime" in df.columns:
        df["_dt"] = pd.to_datetime(df["datetime"])
    elif "date" in df.columns:
        df["_dt"] = pd.to_datetime(df["date"])
    else:
        return pd.DataFrame()
    df = df.sort_values("_dt").reset_index(drop=True)

    # ── 按会话分组 ──
    sessions = []
    current_session = [0]
    for i in range(1, len(df)):
        gap_min = (df["_dt"].iloc[i] - df["_dt"].iloc[i-1]).total_seconds() / 60
        if gap_min > 120:
            sessions.append(current_session)
            current_session = [i]
        else:
            current_session.append(i)
    sessions.append(current_session)

    bars = []
    for sess_indices in sessions:
        n = len(sess_indices)
        m = (n // 2) * 2
        for j in range(0, m, 2):
            b1, b2 = df.iloc[sess_indices[j]], df.iloc[sess_indices[j+1]]
            bars.append({"date": b1["_dt"], "open": float(b1["open"]),
                         "high": max(float(b1["high"]), float(b2["high"])),
                         "low": min(float(b1["low"]), float(b2["low"])),
                         "close": float(b2["close"]),
                         "volume": float(b1["volume"]) + float(b2["volume"]),
                         "oi": float(b2.get("oi", 0)), "settle": float(b2.get("settle", 0))})
        if n % 2 == 1:
            b = df.iloc[sess_indices[-1]]
            bars.append({"date": b["_dt"], "open": float(b["open"]),
                         "high": float(b["high"]), "low": float(b["low"]),
                         "close": float(b["close"]), "volume": float(b["volume"]),
                         "oi": float(b.get("oi", 0)), "settle": float(b.get("settle", 0))})
    return pd.DataFrame(bars)


def fetch_120m_kline(variety, days=DAYS_60M):
    """从TDX 60m获取→重采样120m→返回记录列表"""
    adapter = MultiSourceAdapter()
    result = adapter.get_kline(variety, days=days, period="60m")
    if not result or not result.get("success"):
        return None
    raw = result.get("data", [])
    if len(raw) < 60:
        return None
    df_60m = pd.DataFrame(raw)
    if "date" not in df_60m.columns:
        return None
    df_60m["date"] = pd.to_datetime(df_60m["date"], errors="coerce")
    df_60m = df_60m.dropna(subset=["date"])
    df_60m = df_60m.sort_values("date").reset_index(drop=True)

    df_120m = resample_60m_to_120m(df_60m)
    if len(df_120m) < MIN_BARS:
        return None
    return df_120m


def build_tech_snapshot(df_120m, symbol, name):
    """从120m DataFrame构建tech dict（兼容channel_breakout评分）"""
    closes = df_120m["close"].values.astype(float)
    highs = df_120m["high"].values.astype(float)
    lows = df_120m["low"].values.astype(float)
    volumes = df_120m["volume"].values.astype(float) if "volume" in df_120m.columns else None
    opens = df_120m["open"].values.astype(float)

    tech = {"symbol": symbol, "name": name}
    tech["last_price"] = float(closes[-1])
    tech["price"] = float(closes[-1])
    tech["change_pct"] = (closes[-1]/closes[-2]-1)*100 if len(closes)>1 else 0
    tech["volume"] = int(volumes[-1]) if volumes is not None else 0

    # DC通道
    dc20_upper = float(np.max(highs[-20:])) if len(highs)>=20 else 0
    dc20_lower = float(np.min(lows[-20:])) if len(lows)>=20 else 0
    tech["DC20_UPPER"] = dc20_upper
    tech["DC20_LOWER"] = dc20_lower
    tech["DC20_POS"] = (closes[-1]-dc20_lower)/(dc20_upper-dc20_lower+1e-10) if dc20_upper>0 else 0.5

    dc55_upper = float(np.max(highs[-55:])) if len(highs)>=55 else 0
    dc55_lower = float(np.min(lows[-55:])) if len(lows)>=55 else 0
    tech["DC55_UPPER"] = dc55_upper
    tech["DC55_LOWER"] = dc55_lower
    tech["DC55_MID"] = (dc55_upper+dc55_lower)/2 if dc55_upper>0 else 0
    tech["DC55_POS"] = (closes[-1]-dc55_lower)/(dc55_upper-dc55_lower+1e-10) if dc55_upper>0 else 0.5
    half = min(28, len(closes)//2)
    mid_first = float(np.max(highs[-55:-half])+np.min(lows[-55:-half]))/2 if half>0 and len(highs)>=55 else (dc55_upper+dc55_lower)/2
    mid_last = float(np.max(highs[-half:])+np.min(lows[-half:]))/2 if half>0 and len(highs)>=55 else (dc55_upper+dc55_lower)/2
    tech["DC55_TREND"] = "up" if mid_last > mid_first else "down"

    # calc_core
    try:
        ind = calculate_tdx_compatible(high=highs, low=lows, close=closes,
                                       open_price=opens, volume=volumes)
        for k, v in ind.items():
            if k not in tech:
                tech[k] = v
    except Exception:
        pass

    # BB
    if tech.get("boll_upper") is not None:
        bu, bl = tech["boll_upper"], tech["boll_lower"]
        tech["BB_UPPER"] = bu
        tech["BB_LOWER"] = bl
        tech["BB_MIDDLE"] = tech.get("boll_mid", (bu+bl)/2)
        tech["BB_POS"] = (closes[-1]-bl)/(bu-bl+1e-10) if (bu-bl)!=0 else 0.5
        tech["BB_WIDTH_PCT"] = (bu-bl)/((bu+bl)/2+1e-10)*100
        # squeeze
        if len(highs) > 40:
            widths = []
            for i in range(-40, 0):
                bu_i = float(np.max(highs[-20:]))  # simplified
                bl_i = float(np.min(lows[-20:]))
                widths.append((bu_i-bl_i)/((bu_i+bl_i)/2+1e-10)*100)
            avg_w = np.mean(widths) if widths else 0
            tech["BB_SQUEEZE"] = bool(tech["BB_WIDTH_PCT"] < avg_w * 0.8)
        else:
            tech["BB_SQUEEZE"] = False

    # dc20_break
    if dc20_upper > 0 and dc20_lower > 0:
        if closes[-1] > dc20_upper:
            tech["dc20_break"] = "up"
        elif closes[-1] < dc20_lower:
            tech["dc20_break"] = "down"
        else:
            tech["dc20_break"] = "none"
    else:
        tech["dc20_break"] = "none"

    # vol_ratio
    if volumes is not None and len(volumes) >= 20:
        avg_vol = float(np.mean(volumes[-20:]))
        tech["vol_ratio"] = volumes[-1]/avg_vol if avg_vol > 0 else 1.0
    else:
        tech["vol_ratio"] = 1.0

    tech["ADX14"] = tech.pop("adx", tech.get("ADX14", 0)) if "adx" in tech else tech.get("ADX14", 0)
    tech["RSI14"] = tech.pop("rsi", tech.get("RSI14", 50)) if "rsi" in tech else tech.get("RSI14", 50)
    tech["ADX"] = tech.get("ADX14", 0)
    tech["ATR"] = tech.get("atr", tech.get("ATR", 0))
    tech["ma_align"] = "mixed"
    tech["stage"] = "unknown"
    tech["z_score"] = 0.0

    return tech


def score_single(tech, period="120m", override=None):
    """用当前参数对一个截面评分（自含评分逻辑）"""
    if override:
        set_param_overrides(override)

    _r = lambda sec, key: resolve_param(sec, key, tech.get("symbol",""), _get_chain(tech.get("symbol","")), period)

    price = tech.get("last_price", 0)
    adx_val = tech.get("ADX14", tech.get("adx", 0))
    dc20_pos = tech.get("DC20_POS")
    dc55_pos = tech.get("DC55_POS")
    dc55_trend = tech.get("DC55_TREND", "flat")
    bb_width = tech.get("BB_WIDTH_PCT", 0)
    bb_squeeze = tech.get("BB_SQUEEZE", False)
    vol_ratio = tech.get("vol_ratio", 1.0)
    dc20_break = tech.get("dc20_break", "none")
    dc20_upper = tech.get("DC20_UPPER")
    dc20_lower = tech.get("DC20_LOWER")

    # DC20
    dc20_score = 0.0
    if dc20_break == "up" and dc20_upper and price:
        dc20_score += _r("dc20","break_base_score")
        if (price/dc20_upper-1)*100 > _r("dc20","break_strong_pct"):
            dc20_score += _r("dc20","break_strong_bonus")
        elif (price/dc20_upper-1)*100 > _r("dc20","break_moderate_pct"):
            dc20_score += _r("dc20","break_moderate_bonus")
        if dc20_pos is not None and dc20_pos > _r("dc20","pos_upper_threshold"):
            dc20_score += _r("dc20","pos_upper_bonus")
        if adx_val > _r("adx","exhaustion_threshold"):
            dc20_score -= _r("adx","exhaustion_penalty")
        elif adx_val >= _r("adx","trend_threshold"):
            dc20_score += _r("adx","trend_bonus")
    elif dc20_break == "down" and dc20_lower and price:
        dc20_score -= _r("dc20","break_base_score")
        if (dc20_lower/price-1)*100 > _r("dc20","break_strong_pct"):
            dc20_score -= _r("dc20","break_strong_bonus")
        elif (dc20_lower/price-1)*100 > _r("dc20","break_moderate_pct"):
            dc20_score -= _r("dc20","break_moderate_bonus")
        if dc20_pos is not None and dc20_pos < _r("dc20","pos_lower_threshold"):
            dc20_score += _r("dc20","pos_lower_bonus")
        if adx_val > _r("adx","exhaustion_threshold"):
            dc20_score += _r("adx","exhaustion_penalty")
        elif adx_val >= _r("adx","trend_threshold"):
            dc20_score -= _r("adx","trend_bonus")

    # DC55
    dc55_score = 0.0
    if dc55_pos is not None:
        for pt in _r("dc55","pos_thresholds"):
            if "min" in pt and dc55_pos > pt["min"]:
                dc55_score += pt["score"]
                break
            if "max" in pt and dc55_pos < pt["max"]:
                dc55_score += pt["score"]
                break
    if dc55_trend in ("up","down"):
        dc55_score += _r("dc55","trend_base_score")

    # BB
    bb_score = 0.0
    if bb_width:
        if bb_width > _r("bb","width_high_threshold"):
            bb_score += _r("bb","width_high_score")
        elif bb_width > _r("bb","width_moderate_threshold"):
            bb_score += _r("bb","width_moderate_score")
    if bb_squeeze:
        bb_score += _r("bb","squeeze_bonus")

    # Volume
    vol_score = 0.0
    if vol_ratio > _r("volume","explosive_ratio"):
        vol_score += _r("volume","explosive_score")
    elif vol_ratio > _r("volume","elevated_ratio"):
        vol_score += _r("volume","elevated_score")
    elif vol_ratio < _r("volume","normal_lower_ratio"):
        vol_score += _r("volume","weak_penalty")

    total = dc20_score + dc55_score + bb_score + vol_score
    direction = "bull" if total > 0 else ("bear" if total < 0 else "neutral")
    abs_total = abs(total)
    if abs_total >= SIGNAL_GRADE_THRESHOLDS["strong"]:
        grade = "STRONG"
    elif abs_total >= WATCH_THRESHOLD:
        grade = "WATCH"
    elif abs_total >= WEAK_THRESHOLD:
        grade = "WEAK"
    else:
        grade = "NOISE"

    if override:
        clear_param_overrides()

    return {"total": round(total), "direction": direction, "grade": grade}


def prepare_120m_snapshots(symbol, name):
    """获取120m数据→采样多个时间截面"""
    df_120m = fetch_120m_kline(symbol)
    if df_120m is None or len(df_120m) < MIN_BARS:
        return None

    closes = df_120m["close"].values.astype(float)
    highs = df_120m["high"].values.astype(float)
    lows = df_120m["low"].values.astype(float)

    snapshots = []
    n = len(closes)

    for i in range(MIN_BARS, n - LOOKAHEAD_BARS, SAMPLE_INTERVAL):
        sub_df = df_120m.iloc[:i+1].copy().reset_index(drop=True)
        tech = build_tech_snapshot(sub_df, symbol, name)

        # 后市N根K线变化
        future_closes = closes[i+1:i+1+LOOKAHEAD_BARS]
        future_avg = float(np.mean(future_closes / closes[i] - 1)) * 100 if len(future_closes) > 0 else 0

        snapshots.append({
            "bar_idx": i,
            "tech": tech,
            "last_price": float(closes[i]),
            "future_avg_change": future_avg,
            "future_direction": "bull" if future_avg > 0 else "bear",
        })

    return snapshots


def walk_forward_optimize_120m(symbol, snapshots, verbose=True):
    """对一个品种执行120m WF参数优化"""
    if not snapshots or len(snapshots) < 10:
        if verbose:
            print(f"  ⚠ {symbol}: 截面不足({len(snapshots) if snapshots else 0}), 跳过")
        return None

    n = len(snapshots)
    split = int(n * WF_TRAIN_PCT)
    train_snaps = snapshots[:split]
    test_snaps = snapshots[split:]

    if len(train_snaps) < 5 or len(test_snaps) < 3:
        if verbose:
            print(f"  ⚠ {symbol}: 训练{len(train_snaps)} 测试{len(test_snaps)}, 跳过")
        return None

    if verbose:
        print(f"  ── {symbol} 120m WF ── 总{n}, 训练{len(train_snaps)}, 测试{len(test_snaps)}")

    # 收集参数候选值
    param_sections = []
    param_keys = []
    candidates = []
    for s, k, vals, *_ in PARAM_CANDIDATES:
        for ps, pk in PRIMARY_PARAMS:
            if s == ps and k == pk:
                param_sections.append(s)
                param_keys.append(k)
                candidates.append(vals)
                break

    # 网格搜索训练集
    best = {"score": -999, "params": None}
    total_combos = 0

    for values in product(*candidates):
        override = {}
        for sec, key, val in zip(param_sections, param_keys, values):
            if sec not in override:
                override[sec] = {}
            override[sec][key] = val
        total_combos += 1

        train_correct = 0
        train_total = 0
        train_pnl = 0.0

        for snap in train_snaps:
            tech = snap["tech"]
            # 同步DC通道数值到tech（snapshot里已有）
            res = score_single(tech, period="120m", override=override)
            if res["grade"] not in ("STRONG", "WATCH", "WEAK"):
                continue
            train_total += 1
            correct = (res["direction"] == "bull" and snap["future_avg_change"] > 0) or \
                      (res["direction"] == "bear" and snap["future_avg_change"] < 0)
            if correct:
                train_correct += 1
                train_pnl += abs(snap["future_avg_change"])
            else:
                train_pnl -= abs(snap["future_avg_change"])

        if train_total == 0:
            continue
        acc = train_correct / train_total
        composite = acc * 100 + min(train_pnl, 20)

        if composite > best["score"]:
            best["score"] = composite
            best["params"] = {s: {k: v} for s, k, v in zip(param_sections, param_keys, values)}
            best["train_metrics"] = {"signals": train_total, "correct": train_correct,
                                     "accuracy": round(acc, 3), "avg_pnl": round(train_pnl/max(train_total,1), 2)}

    if best["params"] is None:
        if verbose:
            print(f"    ⚠ 无有效信号截面")
        return None

    # 测试集验证
    test_correct = 0
    test_total = 0
    test_pnl = 0.0
    for snap in test_snaps:
        res = score_single(snap["tech"], period="120m", override=best["params"])
        if res["grade"] not in ("STRONG", "WATCH", "WEAK"):
            continue
        test_total += 1
        correct = (res["direction"] == "bull" and snap["future_avg_change"] > 0) or \
                  (res["direction"] == "bear" and snap["future_avg_change"] < 0)
        if correct:
            test_correct += 1
            test_pnl += abs(snap["future_avg_change"])
        else:
            test_pnl -= abs(snap["future_avg_change"])

    test_acc = test_correct / max(test_total, 1)

    result = {
        "symbol": symbol,
        "total_snapshots": n,
        "train_metrics": best["train_metrics"],
        "test_metrics": {
            "signals": test_total,
            "correct": test_correct,
            "accuracy": round(test_acc, 3),
            "avg_pnl": round(test_pnl / max(test_total, 1), 2),
        },
        "params": best["params"],
        "composite_score": round(best["score"], 1),
    }
    return result


def run_optimization(symbols, verbose=True):
    """遍历品种执行优化"""
    print(f"\n{'='*60}")
    print(f"  120m Walk-Forward 参数优化")
    print(f"  品种: {len(symbols)} | 训练: 前70% | 测试: 后30%")
    print(f"  参数: {len(PRIMARY_PARAMS)}个维度, 网格搜索")
    print(f"{'='*60}")

    results = []
    for sym, name in symbols:
        print(f"\n  [{sym}] 加载120m数据(60m重采样)...", end="")
        snapshots = prepare_120m_snapshots(sym, name)
        if snapshots is None:
            print(f" ❌ 数据不足")
            continue
        print(f" ✅ {len(snapshots)}截面")

        if verbose:
            result = walk_forward_optimize_120m(sym, snapshots, verbose=True)
        else:
            result = walk_forward_optimize_120m(sym, snapshots, verbose=False)

        if result:
            results.append(result)
            tm = result["train_metrics"]
            tst = result["test_metrics"]
            p = result["params"]
            pstr = "; ".join(f"{s}.{k}={v}" for s, d in p.items() for k, v in d.items())
            print(f"  → 训练准确率={tm['accuracy']:.0%}({tm['signals']}信号) "
                  f"测试准确率={tst['accuracy']:.0%}({tst['signals']}信号) "
                  f"| {pstr}")
        else:
            print(f"  → 优化失败(无有效信号)")

    # 汇总
    print(f"\n{'='*60}")
    print(f"  优化完成: {len(results)}/{len(symbols)}品种")
    print(f"{'='*60}")
    print(f"  {'品种':4s} | {'训练准确率':>8s} | {'训练信号':>6s} | {'测试准确率':>8s} | {'测试信号':>6s} | {'测试盈亏':>6s} | {'综合分':>5s}")
    print(f"  {'-'*4}-+-{'-'*8}-+-{'-'*6}-+-{'-'*8}-+-{'-'*6}-+-{'-'*6}-+-{'-'*5}")
    good = []
    for r in sorted(results, key=lambda x: x.get("test_metrics",{}).get("accuracy",0), reverse=True):
        tm = r["train_metrics"]
        tst = r["test_metrics"]
        is_good = " ✅" if tst["accuracy"] >= 0.55 else ""
        print(f"  {r['symbol']:4s} | {tm['accuracy']:.0%}({tm['signals']:3d}) | {tm['signals']:3d}    | {tst['accuracy']:.0%}({tst['signals']:3d}) | {tst['signals']:3d}    | {tst['avg_pnl']:+5.2f} | {r['composite_score']:5.1f}{is_good}")
        if tst["accuracy"] >= 0.55:
            good.append(r)

    print(f"\n  测试准确率≥55%: {len(good)}/{len(results)}")
    print(f"  品种: {', '.join(r['symbol'] for r in good)}")

    # 适合120m品种
    print(f"\n{'='*60}")
    print(f"  适合120m品种推荐（测试准确率≥55%）")
    print(f"{'='*60}")
    for r in sorted(good, key=lambda x: x.get("test_metrics",{}).get("accuracy",0), reverse=True):
        tm = r["train_metrics"]
        tst = r["test_metrics"]
        print(f"  {r['symbol']:4s} | 训练={tm['accuracy']:.0%} 测试={tst['accuracy']:.0%} | 测试盈亏={tst['avg_pnl']:+5.2f}")

    return results, good


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default="",
                        help="逗号分隔, 默认21个已知子周期品种")
    args = parser.parse_args()

    if args.symbols:
        sym_list = [(s.strip(), "") for s in args.symbols.split(",")]
    else:
        sym_list = [(s, "") for s in HOURLY_SYMBOLS]

    # 补全name
    for i, (s, n) in enumerate(sym_list):
        if not n:
            for s2, n2 in ALL_SYMBOLS:
                if s2 == s:
                    sym_list[i] = (s, n2)
                    break

    results, good = run_optimization(sym_list, verbose=True)
