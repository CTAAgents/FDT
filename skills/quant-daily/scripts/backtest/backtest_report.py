#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货辩论专家团 — 标准回测报告生成器 v2.0
===========================================
生产环境级：单品种/多品种回测 + 3基线对比 + CR/AR/SR/MDD全指标 + HTML报告

用法：
  # 单品种回测
  python backtest_report.py --symbols RB --days 180 --mc-iterations 2000

  # 多品种
  python backtest_report.py --symbols RB,PK --days 250

  # 全量
  python backtest_report.py --days 250

输出：
  - reports/backtest/backtest_report_{symbol}_{YYYYMMDD}.json
  - reports/backtest/backtest_report_{symbol}_{YYYYMMDD}.html
"""

import sys, os, json, math, time, random, warnings
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(SKILL_DIR)
if not os.path.isdir(PARENT_DIR):
    PARENT_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")
    SKILL_DIR = os.path.join(PARENT_DIR, "quant-daily", "scripts")
for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd
import numpy as np
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy

# ================================================================
# 核心指标计算
# ================================================================


def calc_cr(prices: List[float]) -> float:
    """累计收益率 Cumulative Return (%)"""
    return (prices[-1] / prices[0] - 1) * 100 if prices and prices[0] > 0 else 0.0


def calc_ar(prices: List[float], trading_days: int = 252) -> float:
    """年化收益率 Annualized Return (%)"""
    cr = calc_cr(prices)
    n = len(prices)
    if n < 2:
        return 0.0
    years = n / trading_days
    return ((1 + cr / 100) ** (1 / max(years, 0.01)) - 1) * 100


def calc_sr(returns: List[float], rf: float = 0.02) -> float:
    """夏普比率 Sharpe Ratio (年化)"""
    if len(returns) < 2:
        return 0.0
    r = np.array(returns, dtype=float)
    excess = r - rf / 252  # 日化无风险利率
    if np.std(r, ddof=1) < 1e-8:
        return 0.0
    daily_sr = np.mean(excess) / np.std(excess, ddof=1)
    return float(daily_sr * math.sqrt(252))


def calc_mdd(prices: List[float]) -> float:
    """最大回撤 Maximum Drawdown (%)"""
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    mdd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        dd = (peak - p) / peak * 100
        if dd > mdd:
            mdd = dd
    return round(mdd, 2)


def calc_win_rate(returns: List[float], short: bool = False) -> float:
    """胜率 (%)"""
    if not returns:
        return 0.0
    if short:
        wins = sum(1 for r in returns if r < 0)
    else:
        wins = sum(1 for r in returns if r > 0)
    return wins / len(returns) * 100


def calc_profit_factor(returns: List[float], short: bool = False) -> float:
    """盈亏比 Profit Factor"""
    if not returns:
        return 0.0
    if short:
        gross_profit = abs(sum(r for r in returns if r < 0))
        gross_loss = sum(r for r in returns if r >= 0)
    else:
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r <= 0))
    return round(gross_profit / max(gross_loss, 1e-6), 3)


def calc_calmar(cr: float, mdd: float) -> float:
    """卡玛比率 Calmar Ratio"""
    return round(cr / max(mdd, 0.01), 2)


# ================================================================
# 数据采集
# ================================================================


def fetch_kline(symbol: str, days: int = 250) -> Optional[List[dict]]:
    """获取单品种K线数据"""
    adapter = MultiSourceAdapter()
    resp = adapter.get_kline(variety=symbol, days=days)
    if not (isinstance(resp, dict) and resp.get("success")):
        return None
    valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
    if len(valid) < 60:
        return None
    return valid


def compute_tech_at(df: pd.DataFrame, symbol: str) -> dict:
    """计算单个时间截面的技术指标"""
    tech = _compute_indicators_numpy(df, symbol)
    tech["last_price"] = float(df["close"].iloc[-1])
    return tech


# ================================================================
# 策略实现
# ================================================================


def strategy_buy_hold(observations: List[dict], forward: int = 10) -> Dict:
    """策略1: 买入持有 (Buy & Hold) — 在所有截面上都信号。"""
    key = f"ret_{forward}d"
    returns = [ob.get(key) for ob in observations if ob.get(key) is not None]
    return {"returns": returns, "signals": len(returns)}


def strategy_ma_cross(observations: List[dict], forward: int = 10, fast: int = 5, slow: int = 20) -> Dict:
    """策略2: MA金叉 — 在当前截面MA5>MA20时做多。"""
    key = f"ret_{forward}d"
    returns = []
    for ob in observations:
        if ob.get("ma_cross_buy") and ob.get(key) is not None:
            returns.append(ob[key])
    return {"returns": returns, "signals": len(returns)}


def strategy_rsi(observations: List[dict], forward: int = 10, oversold: float = 30, overbought: float = 70) -> Dict:
    """策略3: RSI超买/超卖 — 超卖做多, 超买做空。"""
    key = f"ret_{forward}d"
    returns = []
    for ob in observations:
        r = ob.get(key)
        if r is None:
            continue
        if ob.get("rsi_buy"):
            returns.append(r)  # 超卖做多
        elif ob.get("rsi_sell"):
            returns.append(-r)  # 超买做空（反转）
    return {"returns": returns, "signals": len(returns)}


def strategy_watch_buy(observations: List[dict], forward: int = 10) -> Dict:
    """策略4: WATCH+BUY — 本系统策略"""
    key = f"ret_{forward}d"
    returns = []
    for ob in observations:
        if ob.get("grade") == "WATCH" and ob.get("direction") == "BUY":
            r = ob.get(key)
            if r is not None:
                returns.append(r)
    return {"returns": returns, "signals": len(returns)}


def strategy_weak_sell(observations: List[dict], forward: int = 10) -> Dict:
    """策略5: 技术分析评分 WEAK+SELL — 本系统策略"""
    key = f"ret_{forward}d"
    returns = []
    for ob in observations:
        if ob.get("grade") == "WEAK" and ob.get("direction") == "SELL":
            r = ob.get(key)
            if r is not None:
                returns.append(r)
    return {"returns": returns, "signals": len(returns)}


def _strategy_consensus(observations: List[dict], forward: int, side: str = "sell") -> Dict:
    """策略6: ADX过滤+双策略共识 — 只在ADX>25趋势市出手。"""
    key = f"ret_{forward}d"
    field = "dual_consensus_sell" if side == "sell" else "dual_consensus_buy"
    returns = []
    for ob in observations:
        if ob.get(field) and ob.get(key) is not None:
            r = ob[key]
            if side == "sell":
                returns.append(r)  # 做空，r为原始涨跌幅
            else:
                returns.append(r)  # 做多
    return {"returns": returns, "signals": len(returns)}


def benchmark_monte_carlo(returns: List[float], n_iterations: int = 2000) -> Dict:
    """蒙提卡罗基准：随机抽样的胜率分布 vs 实际胜率"""
    if len(returns) < 5:
        return {
            "avg_win_rate": 0,
            "p95_win_rate": 0,
            "p_value": 1.0,
            "is_significant": False,
            "n_iterations": n_iterations,
        }

    n_signals = len(returns)
    actual_win_rate = calc_win_rate(returns)
    random_win_rates = []

    for _ in range(n_iterations):
        sample = [random.choice(returns) for _ in range(n_signals)]
        wr = sum(1 for r in sample if r > 0) / n_signals * 100
        random_win_rates.append(wr)

    random_win_rates.sort()
    p95 = random_win_rates[int(n_iterations * 0.95)]
    p_value = sum(1 for wr in random_win_rates if wr >= actual_win_rate) / n_iterations

    return {
        "actual_win_rate": round(actual_win_rate, 2),
        "avg_random_win_rate": round(np.mean(random_win_rates), 2),
        "median_random_win_rate": round(np.median(random_win_rates), 2),
        "p95_random_win_rate": round(p95, 2),
        "p_value": round(p_value, 4),
        "is_significant": p_value < 0.05,
        "n_iterations": n_iterations,
    }


# ================================================================
# 主回测流程
# ================================================================


def run_symbol_backtest(
    symbol: str,
    name: str = "",
    days: int = 250,
    step: int = 5,
    min_start: int = 60,
    forward_days: List[int] = None,
    mc_iterations: int = 2000,
) -> Dict:
    """单个品种的完整回测

    Returns:
        包含所有策略在所有持有期下的指标 + 蒙提卡罗 + 基线对比
    """
    if forward_days is None:
        forward_days = [5, 10, 20]

    print(f"  [{symbol}] 采集数据...")
    kline = fetch_kline(symbol, days)
    if not kline:
        return {"symbol": symbol, "name": name, "error": "数据采集失败", "status": "ERROR"}

    closes = [float(r["close"]) for r in kline]
    n = len(kline)

    # ── 多时间截面采样 ──
    observations = []
    for start in range(min_start, n - max(forward_days), step):
        window = kline[: start + 1]
        df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
        df["volume"] = [float(r.get("volume", 0)) for r in window]

        tech = _compute_indicators_numpy(df, symbol)
        price = tech.get("last_price", float(df["close"].iloc[-1]))

        # ── 透明评分引擎（替代calculate_composite_score，避免方向偏差）──
        ma5 = tech.get("MA5", np.mean(closes[start - 4 : start + 1]) if start >= 4 else np.mean(closes[: start + 1]))
        ma10 = tech.get("MA10", np.mean(closes[start - 9 : start + 1]) if start >= 9 else np.mean(closes[: start + 1]))
        ma20 = tech.get(
            "MA20", np.mean(closes[start - 19 : start + 1]) if start >= 19 else np.mean(closes[: start + 1])
        )
        ma60 = tech.get("MA60", np.mean(closes[max(0, start - 59) : start + 1]))
        macd_dif = tech.get("MACD_DIF", 0)
        rsi_val = tech.get("RSI14", 50)
        pdi = tech.get("DMI_PDI", 25)
        mdi = tech.get("DMI_MDI", 25)
        adx_val = tech.get("ADX", tech.get("ADX14", 0))
        st_dir = tech.get("SUPERTREND_DIR", 0)
        vol_ratio = tech.get("VOL_RATIO", tech.get("volume_ratio", 1.0))
        atr_val = tech.get("ATR14", 0)

        # L1: 趋势结构（权重40）
        l1_score = 0
        # 价格 vs MA20/MA60
        if price > ma60:
            l1_score += 20
        elif price < ma60:
            l1_score -= 20
        if price > ma20:
            l1_score += 10
        elif price < ma20:
            l1_score -= 10
        # MA排列
        if ma5 > ma10 > ma20 and min(ma5, ma10, ma20) > 0:
            l1_score += 10
        elif ma5 < ma10 < ma20:
            l1_score -= 10

        # L2: 量价配合（权重30）
        l2_score = 0
        if vol_ratio > 1.5:
            l2_score += 15 if l1_score > 0 else -15
        elif vol_ratio > 1.2:
            l2_score += 5 if l1_score > 0 else -5

        # L3: DMI+ADX强度（权重20）
        l3_score = 0
        if adx_val > 25:
            trend_strength = min(adx_val / 100, 0.5)
            if pdi > mdi:
                l3_score += int(10 * trend_strength * 2)
            else:
                l3_score -= int(10 * trend_strength * 2)

        # L4: MACD + RSI确认（权重10）
        l4_score = 0
        if macd_dif > 0:
            l4_score += 5
        else:
            l4_score -= 5
        if rsi_val > 55:
            l4_score += 3
        elif rsi_val < 45:
            l4_score -= 3

        # 否决分：ADX极低、RSI极端、超买超卖
        veto = 0
        if adx_val < 15:
            veto -= 10  # 无趋势
        if rsi_val > 80 or rsi_val < 20:
            veto -= 8  # 极端RSI

        total = l1_score + l2_score + l3_score + l4_score + veto

        # 方向
        direction = "BUY" if total > 0 else ("SELL" if total < 0 else "HOLD")
        abs_total = abs(total)
        if abs_total >= 60:
            grade = "WATCH"
        elif abs_total >= 40:
            grade = "WEAK"
        elif abs_total >= 20:
            grade = "NOISE"
        else:
            grade = "NOISE"

        # ── 基线策略信号（使用上面已计算的ma5/ma20）──
        ma_cross_buy = ma5 > ma20

        # RSI: <30 超卖做多, >70 超买做空
        rsi_buy = rsi_val < 30
        rsi_sell = rsi_val > 70

        ob = {
            "sym": symbol,
            "name": name or symbol,
            "date_idx": start,
            "price": price,
            "total": total,
            "direction": direction,
            "grade": grade,
            "adx": round(adx_val, 1),
            "rsi": round(rsi_val, 1),
            "ma_cross_buy": ma_cross_buy,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "atr": round(atr_val, 2),
            "volume_ratio": round(vol_ratio, 2),
            "l1": l1_score,
            "l2": l2_score,
            "l3": l3_score,
            "l4": l4_score,
        }
        # 双策略共识：技术分析评分 + 因子择时的共振
        ob["dual_consensus_sell"] = (
            direction == "SELL" and grade in ("WEAK", "WATCH", "STRONG") and ob["adx"] > 25
        )  # 趋势过滤
        ob["dual_consensus_buy"] = direction == "BUY" and grade in ("WEAK", "WATCH", "STRONG") and ob["adx"] > 25
        for fd in forward_days:
            idx = start + fd
            if idx < n:
                ob[f"ret_{fd}d"] = (closes[idx] / closes[start] - 1) * 100
        observations.append(ob)

    if not observations:
        return {"symbol": symbol, "name": name, "error": "无有效观测", "status": "ERROR"}

    # ── 基线策略 ──
    print(f"  [{symbol}] 评估 {len(observations)} 个截面...")

    strategies = {}
    baselines = {}

    for fd in forward_days:
        # 本系统策略
        wb = strategy_watch_buy(observations, fd)
        ws = strategy_weak_sell(observations, fd)
        strategies[f"watch_buy_{fd}d"] = wb
        strategies[f"weak_sell_{fd}d"] = ws

        # 增强策略：ADX过滤+双策略共识
        dc_buy = _strategy_consensus(observations, fd, "buy")
        dc_sell = _strategy_consensus(observations, fd, "sell")
        strategies[f"consensus_buy_{fd}d"] = dc_buy
        strategies[f"consensus_sell_{fd}d"] = dc_sell

        # 基线策略（在截面上评估，与技术分析评分使用同一组数据）
        bh = strategy_buy_hold(observations, fd)
        ma = strategy_ma_cross(observations, fd)
        rsi_s = strategy_rsi(observations, fd)
        baselines[f"buy_hold_{fd}d"] = bh
        baselines[f"ma_cross_{fd}d"] = ma
        baselines[f"rsi_{fd}d"] = rsi_s

    # ── 计算指标 ──
    all_returns = []
    for fd in forward_days:
        for strat_name in ["watch_buy", "weak_sell"]:
            key = f"{strat_name}_{fd}d"
            if key in strategies:
                all_returns.extend(strategies[key].get("returns", []))

    mc_result = benchmark_monte_carlo(all_returns, mc_iterations)

    # ── 聚合指标 ──
    def compute_metrics(strat_result: Dict, name: str, short: bool = False) -> Dict:
        returns = strat_result.get("returns", [])
        if not returns:
            return {"name": name, "signals": 0, "status": "NO_DATA"}

        # 做空策略需反转收益率（价格跌=盈利）
        effective_returns = [-r for r in returns] if short else returns

        # 模拟价格序列（累计收益曲线）
        cum_prices = [100]
        for r in effective_returns:
            cum_prices.append(cum_prices[-1] * (1 + r / 100))

        return {
            "name": name,
            "signals": strat_result.get("signals", 0),
            "win_rate": round(calc_win_rate(returns, short), 2),
            "avg_return": round(np.mean(effective_returns), 3),
            "profit_factor": calc_profit_factor(returns, short),
            "cumulative_return": calc_cr(cum_prices),
            "annualized_return": round(calc_ar(cum_prices), 2),
            "sharpe_ratio": round(calc_sr(effective_returns), 3),
            "max_drawdown": calc_mdd(cum_prices),
            "calmar_ratio": calc_calmar(calc_cr(cum_prices), calc_mdd(cum_prices)),
            "std_return": round(float(np.std(effective_returns, ddof=1)), 3),
            "max_return": round(max(effective_returns), 3) if effective_returns else 0,
            "min_return": round(min(effective_returns), 3) if effective_returns else 0,
            "status": "OK",
        }

    results = {"strategies": {}, "baselines": {}}
    for fd in forward_days:
        for strat_name, data in strategies.items():
            if str(fd) in strat_name:
                short = "sell" in strat_name
                results["strategies"][strat_name] = compute_metrics(data, strat_name, short)

        for base_name, data in baselines.items():
            if str(fd) in base_name:
                short = "rsi" in base_name
                results["baselines"][base_name] = compute_metrics(data, base_name, short)

    return {
        "symbol": symbol,
        "name": name or symbol,
        "status": "OK",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "days": days,
            "step": step,
            "min_start": min_start,
            "forward_days": forward_days,
            "mc_iterations": mc_iterations,
            "kline_bars": n,
            "observations": len(observations),
        },
        "monte_carlo": mc_result,
        "grade_distribution": {
            grade: sum(1 for ob in observations if ob["grade"] == grade)
            for grade in ["STRONG", "WATCH", "WEAK", "NOISE"]
        },
        **results,
    }


# ================================================================
# HTML报告生成
# ================================================================


def generate_html(report: Dict) -> str:
    """从回测结果生成自包含HTML报告"""
    symbol = report.get("symbol", "?")
    name = report.get("name", symbol)
    status = report.get("status", "ERROR")
    ts = report.get("timestamp", "")

    # 颜色映射
    def fmt_dir(d):
        if d > 0:
            return "🟢"
        if d < 0:
            return "🔴"
        return "⚪"

    def fmt_pct(v):
        if v is None:
            return "—"
        return f"{v:+.2f}%"

    def fmt_num(v):
        if v is None:
            return "—"
        return f"{v:.2f}"

    # 策略对照表
    strategy_rows = ""
    best_strat = {"name": "", "cr": -999}
    best_base = {"name": "", "cr": -999}

    for fd in report.get("config", {}).get("forward_days", []):
        fd_label = f"{fd}日"
        # 本系统策略
        for key in ["watch_buy", "weak_sell"]:
            s = report.get("strategies", {}).get(f"{key}_{fd}d", {})
            if s.get("status") != "OK":
                continue
            label = "WATCH+BUY" if "buy" in key else "WEAK+SELL"
            cr = s.get("cumulative_return", 0)
            if cr > best_strat["cr"]:
                best_strat = {"name": f"{label}({fd_label})", "cr": cr}
            strategy_rows += f"""
        <tr>
            <td style="font-weight:600">{symbol}</td>
            <td><span class="tag-{"buy" if "buy" in key else "sell"}">{label}</span></td>
            <td>{fd_label}</td>
            <td>{s.get("signals", 0)}</td>
            <td>{s.get("win_rate", 0):.1f}%</td>
            <td class="num">{fmt_pct(s.get("avg_return", 0))}</td>
            <td class="num">{fmt_pct(cr)}</td>
            <td class="num">{fmt_num(s.get("sharpe_ratio", 0))}</td>
            <td class="num">{fmt_pct(s.get("max_drawdown", 0))}</td>
            <td class="num">{fmt_num(s.get("profit_factor", 0))}</td>
            <td class="num">{fmt_num(s.get("calmar_ratio", 0))}</td>
        </tr>"""

        # 基线策略
        for key in ["buy_hold", "ma_cross", "rsi"]:
            s = report.get("baselines", {}).get(f"{key}_{fd}d", {})
            if s.get("status") != "OK":
                continue
            label_map = {"buy_hold": "买入持有", "ma_cross": "MA金叉/死叉", "rsi": "RSI超买/卖"}
            cr = s.get("cumulative_return", 0)
            if cr > best_base["cr"]:
                best_base = {"name": f"{label_map[key]}({fd_label})", "cr": cr}
            strategy_rows += f"""
        <tr style="color:#94a3b8">
            <td style="font-weight:400">{symbol}</td>
            <td><span class="tag-base">{label_map.get(key, key)}</span></td>
            <td>{fd_label}</td>
            <td>{s.get("signals", 0)}</td>
            <td>{s.get("win_rate", 0):.1f}%</td>
            <td class="num">{fmt_pct(s.get("avg_return", 0))}</td>
            <td class="num">{fmt_pct(cr)}</td>
            <td class="num">{fmt_num(s.get("sharpe_ratio", 0))}</td>
            <td class="num">{fmt_pct(s.get("max_drawdown", 0))}</td>
            <td class="num">{fmt_num(s.get("profit_factor", 0))}</td>
            <td class="num">{fmt_num(s.get("calmar_ratio", 0))}</td>
        </tr>"""

    # 蒙提卡罗
    mc = report.get("monte_carlo", {})
    mc_sig = mc.get("is_significant", False)
    mc_html = (
        f"""
    <div style="background:{"#22c55e10" if mc_sig else "#f59e0b10"};border:1px solid {"#22c55e" if mc_sig else "#f59e0b"};border-radius:8px;padding:14px 18px;margin:12px 0">
        <div style="font-size:13px;font-weight:600;color:{"#22c55e" if mc_sig else "#f59e0b"};margin-bottom:6px">
            {"✅ 策略统计显著" if mc_sig else "⚠️ 策略统计不显著"}
        </div>
        <div style="font-size:12px;color:#94a3b8;line-height:1.6">
            实际胜率 {mc.get("actual_win_rate", "?")}% vs 随机中位 {mc.get("median_random_win_rate", "?")}% (p={mc.get("p_value", "?")})
        </div>
    </div>"""
        if mc
        else ""
    )

    # 最优对比
    comparison = ""
    if best_strat["cr"] > -999 and best_base["cr"] > -999:
        delta = best_strat["cr"] - best_base["cr"]
        comparison = f"""
    <div style="background:#1a1d28;border-radius:8px;padding:12px 16px;margin:12px 0;border-left:3px solid {"#22c55e" if delta > 0 else "#ef4444"}">
        <span style="font-weight:600;color:{"#22c55e" if delta > 0 else "#ef4444"}">
            {"🏆 本系统超越最佳基线" if delta > 0 else "📉 本系统落后最佳基线"}
        </span>
        <span style="color:#94a3b8;font-size:12px;margin-left:8px">
            本系统最佳: {best_strat["name"]}(CR={best_strat["cr"]:+.2f}%) vs 基线最佳: {best_base["name"]}(CR={best_base["cr"]:+.2f}%) — 差值 {delta:+.2f}%
        </span>
    </div>"""

    # 等级分布
    gd = report.get("grade_distribution", {})
    total_obs = sum(gd.values()) or 1

    html = f"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>回测报告 — {symbol} {name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0c10;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px;max-width:1200px;margin:0 auto}}
h1{{font-size:24px;background:linear-gradient(135deg,#f59e0b,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}}
.sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.card{{background:#1a1d28;border:1px solid #2a2d3a;border-radius:12px;padding:20px 24px;margin-bottom:16px}}
.card h2{{font-size:16px;color:#f59e0b;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #2a2d3a}}
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-bottom:16px}}
.s-item{{background:#12141a;border-radius:8px;padding:12px;text-align:center}}
.s-item .v{{font-size:22px;font-weight:700}}
.s-item .l{{font-size:10px;color:#94a3b8;margin-top:2px}}
.s-item.positive .v{{color:#22c55e}}
.s-item.negative .v{{color:#ef4444}}
.s-item.neutral .v{{color:#6366f1}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#252940;padding:8px 10px;text-align:left;font-weight:600;color:#94a3b8;font-size:10px;white-space:nowrap}}
td{{padding:6px 10px;border-top:1px solid #2a2d3a30}}
tr:hover{{background:#f59e0b06}}
.num{{text-align:right;font-family:"Courier New",monospace}}
.tag-buy{{display:inline-block;padding:1px 6px;border-radius:3px;background:#22c55e20;color:#22c55e;font-size:10px;font-weight:600}}
.tag-sell{{display:inline-block;padding:1px 6px;border-radius:3px;background:#ef444420;color:#ef4444;font-size:10px;font-weight:600}}
.tag-base{{display:inline-block;padding:1px 6px;border-radius:3px;background:#6366f120;color:#6366f1;font-size:10px;font-weight:600}}
.footer{{text-align:center;padding:24px;color:#6b7280;font-size:11px;border-top:1px solid #2a2d3a;margin-top:24px}}
</style></head><body>

<h1>📊 回测报告 — {symbol}</h1>
<div class="sub">{name} | {ts} | {report.get("config", {}).get("kline_bars", "?")}根K线 | 截面: {
        report.get("config", {}).get("observations", "?")
    }</div>

<div class="card">
    <h2>📈 核心指标总览</h2>
    <div class="summary-grid">
        <div class="s-item {
        "positive"
        if report.get("strategies", {}).get("watch_buy_10d", {}).get("cumulative_return", 0) > 0
        else "negative"
    }">
            <div class="v">{
        fmt_num(report.get("strategies", {}).get("watch_buy_10d", {}).get("cumulative_return", 0))
    }%</div>
            <div class="l">累计收益 CR</div>
        </div>
        <div class="s-item {
        "positive" if report.get("strategies", {}).get("watch_buy_10d", {}).get("sharpe_ratio", 0) > 1 else "neutral"
    }">
            <div class="v">{fmt_num(report.get("strategies", {}).get("watch_buy_10d", {}).get("sharpe_ratio", 0))}</div>
            <div class="l">夏普 SR</div>
        </div>
        <div class="s-item {
        "positive" if report.get("strategies", {}).get("watch_buy_10d", {}).get("max_drawdown", 0) < 10 else "negative"
    }">
            <div class="v">{fmt_pct(report.get("strategies", {}).get("watch_buy_10d", {}).get("max_drawdown", 0))}</div>
            <div class="l">最大回撤 MDD</div>
        </div>
        <div class="s-item neutral">
            <div class="v">{fmt_num(report.get("strategies", {}).get("watch_buy_10d", {}).get("win_rate", 0))}%</div>
            <div class="l">胜率</div>
        </div>
        <div class="s-item neutral">
            <div class="v">{fmt_num(report.get("strategies", {}).get("watch_buy_10d", {}).get("calmar_ratio", 0))}</div>
            <div class="l">卡玛比</div>
        </div>
        <div class="s-item neutral">
            <div class="v">{
        fmt_num(report.get("strategies", {}).get("watch_buy_10d", {}).get("profit_factor", 0))
    }</div>
            <div class="l">盈亏比</div>
        </div>
    </div>
    {comparison}
    {mc_html}
</div>

<div class="card">
    <h2>📋 策略对比全表</h2>
    <p style="font-size:11px;color:#94a3b8;margin-bottom:10px">颜色: 🟢 本系统策略 | 🔵 基线策略</p>
    <table>
        <thead><tr>
            <th>品种</th><th>策略</th><th>周期</th><th>信号</th><th>胜率</th>
            <th class="num">均收益</th><th class="num">累计收益</th><th class="num">夏普</th>
            <th class="num">回撤</th><th class="num">盈亏比</th><th class="num">卡玛</th>
        </tr></thead>
        <tbody>{strategy_rows}</tbody>
    </table>
</div>

<div class="card">
    <h2>📊 等级分布</h2>
    <p style="font-size:11px;color:#94a3b8;margin-bottom:8px">共 {total_obs} 个观测截面</p>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
        {
        "".join(
            f'''<div style="background:#12141a;border-radius:6px;padding:10px 14px;text-align:center;min-width:80px">
            <div style="font-size:18px;font-weight:700;color:{"#22c55e" if g == "STRONG" else "#f59e0b" if g == "WATCH" else "#ef4444" if g == "WEAK" else "#6b7280"}">{gd.get(g, 0)}</div>
            <div style="font-size:10px;color:#94a3b8">{g}</div>
            <div style="font-size:10px;color:#6b7280">{gd.get(g, 0) / total_obs * 100:.1f}%</div>
        </div>'''
            for g in ["STRONG", "WATCH", "WEAK", "NOISE"]
        )
    }
    </div>
</div>

<div class="card">
    <h2>⚙️ 回测配置</h2>
    <table style="width:auto">
        <tr><td style="font-weight:600">数据天数</td><td>{report.get("config", {}).get("days", "?")}</td></tr>
        <tr><td style="font-weight:600">采样步长</td><td>{report.get("config", {}).get("step", "?")}根K线</td></tr>
        <tr><td style="font-weight:600">持有周期</td><td>{
        ", ".join(f"{fd}日" for fd in report.get("config", {}).get("forward_days", []))
    }</td></tr>
        <tr><td style="font-weight:600">蒙提卡罗</td><td>{
        mc.get("n_iterations", report.get("config", {}).get("mc_iterations", "?"))
    }次</td></tr>
        <tr><td style="font-weight:600">基线对比</td><td>买入持有 / MA交叉 / RSI超买卖</td></tr>
    </table>
</div>

<div class="footer">
    期货辩论专家团 · 回测报告生成器 v2.0 | {ts}
</div>

</body></html>"""
    return html


# ================================================================
# CLI
# ================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="期货辩论专家团 — 标准回测报告生成器 v2.0")
    parser.add_argument("--symbols", "-s", default="RB,PK", help="品种列表(逗号分隔，默认RB,PK)")
    parser.add_argument("--days", "-d", type=int, default=180, help="历史数据天数(默认180)")
    parser.add_argument("--step", type=int, default=5, help="时间截面采样间隔(默认5)")
    parser.add_argument("--forward", type=str, default="5,10,20", help="持有周期(逗号分隔，默认5,10,20)")
    parser.add_argument("--mc-iterations", type=int, default=2000, help="蒙提卡罗迭代次数(默认2000)")
    parser.add_argument("--output", "-o", default="", help="输出目录(默认自动)")
    parser.add_argument("--no-html", action="store_true", help="不生成HTML")
    parser.add_argument("--fee-rate", type=float, default=0.0, help="交易摩擦费率(如0.001=千1)，默认0不折减")
    parser.add_argument("--rolling-window", type=int, default=0, help="滚动验证窗口天数(默认0=不滚动，建议120)")
    parser.add_argument("--rolling-step", type=int, default=30, help="滚动验证步长(默认30天)")
    parser.add_argument("--min-days", type=int, default=600, help="最低回测天数(默认600，覆盖完整牛熊周期)")
    parser.add_argument("--stress-test", action="store_true", help="运行压力测试")
    parser.add_argument("--permutation-test", action="store_true", help="运行置换检验")
    parser.add_argument("--lookahead-check", action="store_true", help="运行前视偏差检测")
    args = parser.parse_args()

    symbols_raw = [s.strip().upper() for s in args.symbols.split(",")]
    forward_days = [int(f.strip()) for f in args.forward.split(",")]

    # 品种名称映射
    from config.symbols import ALL_SYMBOLS

    sym_map = {s.upper(): n for s, n in ALL_SYMBOLS}

    # 输出目录
    today = datetime.now().strftime("%Y%m%d")
    if args.output:
        out_dir = args.output
    else:
        base = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results")
        out_dir = os.path.join(base, today)
    os.makedirs(out_dir, exist_ok=True)

    print(f"{'=' * 60}")
    print(f"  标准回测报告 v2.0 — {today}")
    print(f"  品种: {', '.join(symbols_raw)}")
    print(f"  数据天数: {args.days} | 持有周期: {', '.join(str(f) for f in forward_days)}日")
    print(f"{'=' * 60}")

    all_reports = []
    for sym in symbols_raw:
        name = sym_map.get(sym, sym)
        print(f"\n[{sym}] 开始回测...")
        t0 = time.time()
        report = run_symbol_backtest(
            sym,
            name=name,
            days=args.days,
            step=args.step,
            forward_days=forward_days,
            mc_iterations=args.mc_iterations,
        )
        elapsed = time.time() - t0

        if report.get("status") == "ERROR":
            print(f"  [{sym}] ❌ 失败: {report.get('error', '未知错误')} ({elapsed:.0f}s)")
            all_reports.append(report)
            continue

        # ── 交易摩擦折减（如有） ──
        fee_rate = args.fee_rate
        report["config"]["fee_rate"] = fee_rate
        if fee_rate > 0:
            for cat in ["strategies", "baselines"]:
                for name, data in report.get(cat, {}).items():
                    if data.get("status") != "OK":
                        continue
                    cr = data.get("cumulative_return", 0)
                    sr = data.get("sharpe_ratio", 0)
                    # 摩擦后：每笔交易扣除 fee_rate × 2 的成本（双边）
                    fee_discount = fee_rate * 2 * 100  # %
                    adjusted_cr = cr - abs(cr) * fee_discount / 100
                    data["cr_before_fee"] = round(cr, 2)
                    data["cumulative_return"] = round(adjusted_cr, 2)
                    # Sharpe ratio 也做同比例折减
                    data["sr_before_fee"] = round(sr, 2)
                    data["sharpe_ratio"] = round(sr * (1 - fee_discount / 100), 3)

        # 保存JSON
        json_path = os.path.join(out_dir, f"backtest_report_{sym}_{today}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  [{sym}] ✅ JSON: {json_path}")

        # 保存HTML
        if not args.no_html:
            html = generate_html(report)
            html_path = os.path.join(out_dir, f"backtest_report_{sym}_{today}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  [{sym}] ✅ HTML: {html_path}")

        # 打印摘要
        wb = report.get("strategies", {}).get("watch_buy_10d", {})
        ws = report.get("strategies", {}).get("weak_sell_10d", {})
        mc = report.get("monte_carlo", {})
        print(f"  [{sym}] 摘要 (10日持有){' [含摩擦折减]' if fee_rate > 0 else ''}:")
        fee_tag = f" (摩擦前{ws.get('cr_before_fee', wb.get('cr_before_fee', '?')):+.2f}%)" if fee_rate > 0 else ""
        print(
            f"     WATCH+BUY: {wb.get('signals', 0)}次 胜率{wb.get('win_rate', 0):.1f}% CR{wb.get('cumulative_return', 0):+.2f}% SR{wb.get('sharpe_ratio', 0):.2f}"
        )
        print(
            f"     WEAK+SELL: {ws.get('signals', 0)}次 胜率{ws.get('win_rate', 0):.1f}% CR{ws.get('cumulative_return', 0):+.2f}% SR{ws.get('sharpe_ratio', 0):.2f}{fee_tag}"
        )
        print(f"     蒙提卡罗: p={mc.get('p_value', '?')} {'[显著]' if mc.get('is_significant') else '[不显著]'}")
        print(f"     耗时: {elapsed:.0f}s")

        all_reports.append(report)

    # ── P0-2: 回测体系加固 — 额外检验模块 ──
    if any([args.stress_test, args.permutation_test, args.lookahead_check]):
        print(f"\n{'=' * 60}")
        print(f"  额外检验模块")
        print(f"{'=' * 60}")

    # 压力测试
    if args.stress_test:
        try:
            from stress_test import run_stress_test

            stress_result = run_stress_test(symbols_raw, scenario_key="all")
            stress_path = os.path.join(out_dir, f"stress_test_{today}.json")
            with open(stress_path, "w", encoding="utf-8") as f:
                json.dump(stress_result, f, ensure_ascii=False, indent=2)
            print(f"  [StressTest] 结果: {stress_result['summary']['pass_rate'] * 100:.1f}%通过 | {stress_path}")
        except Exception as e:
            print(f"  [StressTest] 跳过: {e}")

    # 置换检验
    if args.permutation_test:
        try:
            from permutation_test import permutation_test

            for report in all_reports:
                if report.get("status") != "OK":
                    continue
                sym = report.get("symbol", "unknown")
                returns = report.get("daily_returns", [])
                sharpe = report.get("strategies", {}).get("watch_buy_10d", {}).get("sharpe_ratio", 0)
                if returns:
                    perm_result = permutation_test(returns, sharpe, iterations=1000)
                    report["permutation_test"] = perm_result
                    print(
                        f"  [Permutation] {sym}: p={perm_result['p_value']:.4f} {'✅显著' if perm_result['is_significant'] else '❌不显著'}"
                    )
        except Exception as e:
            print(f"  [Permutation] 跳过: {e}")

    # 前视偏差检测
    if args.lookahead_check:
        try:
            from lookahead_check import detect_lookahead_in_signals

            for report in all_reports:
                if report.get("status") != "OK":
                    continue
                sym = report.get("symbol", "unknown")
                violations = detect_lookahead_in_signals(report)
                report["lookahead_check"] = {"violations": violations, "pass": len(violations) == 0}
                status = "✅通过" if len(violations) == 0 else f"❌{len(violations)}项违规"
                print(f"  [Lookahead] {sym}: {status}")
        except Exception as e:
            print(f"  [Lookahead] 跳过: {e}")

    # 汇总
    success = sum(1 for r in all_reports if r.get("status") == "OK")
    failed = sum(1 for r in all_reports if r.get("status") == "ERROR")
    print(f"\n{'=' * 60}")
    print(f"  ✅ 完成: {success}/{len(all_reports)} 品种 | ❌ 失败: {failed}")
    print(f"  📁 输出: {out_dir}")
    print(f"{'=' * 60}")

    return all_reports


if __name__ == "__main__":
    main()
