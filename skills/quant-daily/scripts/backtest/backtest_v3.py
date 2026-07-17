#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货辩论专家团 — 回测引擎 v3.0
================================
三大改进：
1. 双策略共振：多策略信号同向才出手
2. 非重叠窗口：平仓后再开新仓，权益真实复合增长
3. PnL反馈闭环：trade_journal记录+按策略表现动态调权重

用法：
  python backtest_v3.py --symbols RB --days 365
  python backtest_v3.py --symbols RB,HC,au,PK --days 365
  python backtest_v3.py --symbols RB --days 365 --no-journal  # 不写trade_journal
"""

import sys, os, json, math, time, warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

warnings.filterwarnings("ignore")

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
import warnings
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy

# 可选依赖：trade_journal（用于PnL反馈）
try:
    from feedback.trade_journal import record_trade, close_trade, annotate_prediction, get_performance_summary

    HAVE_JOURNAL = True
except ImportError:
    HAVE_JOURNAL = False


# ================================================================
# 核心指标计算
# ================================================================


def calc_sharpe(returns: List[float], rf: float = 0.02) -> float:
    if len(returns) < 2:
        return 0.0
    r = np.array(returns, dtype=float)
    excess = r - rf / 252
    if np.std(r, ddof=1) < 1e-8:
        return 0.0
    return float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(252))


def calc_mdd(equity_curve: List[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    mdd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd:
            mdd = dd
    return round(mdd, 2)


# ================================================================
# 评分引擎
# ================================================================


def compute_l1l4_score(tech: dict, close_arr: List[float], start: int) -> dict:
    """透明评分。"""
    price = tech.get("last_price", close_arr[start])
    ma5 = tech.get("MA5")
    ma10 = tech.get("MA10")
    ma20 = tech.get("MA20")
    ma60 = tech.get("MA60")
    macd_dif = tech.get("MACD_DIF", 0)
    rsi = tech.get("RSI14", 50)
    pdi = tech.get("DMI_PDI", 25)
    mdi = tech.get("DMI_MDI", 25)
    adx = tech.get("ADX", tech.get("ADX14", 0))
    st_dir = tech.get("SUPERTREND_DIR", 0)
    vol_ratio = tech.get("VOL_RATIO", tech.get("volume_ratio", 1.0))
    atr = tech.get("ATR14", 0)
    roc10 = tech.get("ROC10", 0)
    cci = tech.get("CCI20", 0)
    obv = tech.get("OBV", 0)
    obv_ma = tech.get("OBV_MA20", 0)

    # ══ 评分 ══
    l1_score = 0
    if price > ma60:
        l1_score += 20
    elif price < ma60:
        l1_score -= 20
    if price > ma20:
        l1_score += 10
    elif price < ma20:
        l1_score -= 10
    if all(v is not None for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            l1_score += 10
        elif ma5 < ma10 < ma20:
            l1_score -= 10

    l2_score = 0
    if vol_ratio > 1.5:
        l2_score += 15 if l1_score > 0 else -15
    elif vol_ratio > 1.2:
        l2_score += 5 if l1_score > 0 else -5

    l3_score = 0
    if adx > 25:
        factor = min(adx / 100, 0.5)
        if pdi > mdi:
            l3_score += int(10 * factor * 2)
        else:
            l3_score -= int(10 * factor * 2)

    l4_score = 0
    if macd_dif > 0:
        l4_score += 5
    else:
        l4_score -= 5
    if rsi > 55:
        l4_score += 3
    elif rsi < 45:
        l4_score -= 3

    veto = 0
    if adx < 15:
        veto -= 10
    if rsi > 80 or rsi < 20:
        veto -= 8

    total = l1_score + l2_score + l3_score + l4_score + veto
    direction = "BUY" if total > 0 else ("SELL" if total < 0 else "HOLD")
    abs_total = abs(total)
    grade = "WATCH" if abs_total >= 55 else ("WEAK" if abs_total >= 35 else "NOISE")

    # ══ 因子代理 ══
    # F1: 动量 (momentum) — ROC10 + 价格vsMA
    f1_score = 0
    if roc10 > 0:
        f1_score += 1
    else:
        f1_score -= 1
    if price > ma20 and ma20 < ma60:
        f1_score += 1  # 短期向上且长期未转势
    if price < ma20 and ma20 > ma60:
        f1_score -= 1  # 短期向下且长期已转势

    # F2: 展期/carry (term structure proxy) — 近远月价差
    f2_score = 0
    if st_dir == 1:
        f2_score += 1  # supertrend多头=backwardation傾向
    elif st_dir == -1:
        f2_score -= 1

    # F3: 偏度 (skew) — RSI极端位置
    f3_score = 0
    if rsi > 60:
        f3_score += 1
    elif rsi < 40:
        f3_score -= 1
    if cci > 100:
        f3_score += 1
    elif cci < -100:
        f3_score -= 1

    # F4: 量价相关性 (price-volume)
    f4_score = 0
    if vol_ratio > 1.2 and l1_score > 0:
        f4_score += 1  # 放量上涨
    elif vol_ratio > 1.2 and l1_score < 0:
        f4_score -= 1  # 放量下跌
    if obv and obv_ma and obv > obv_ma:
        f4_score += 1
    elif obv and obv_ma and obv < obv_ma:
        f4_score -= 1

    # F5: 逆情绪 (contrarian) — CCI极端 / ST方向
    f5_score = 0
    if cci > 200:
        f5_score -= 1  # 极度超买→逆空
    elif cci < -200:
        f5_score += 1  # 极度超卖→逆多

    # 5因子投票
    votes = [f1_score, f2_score, f3_score, f4_score, f5_score]
    net_vote = sum(1 for v in votes if v > 0) - sum(1 for v in votes if v < 0)
    f_direction = "bull" if net_vote > 0 else ("bear" if net_vote < 0 else "neutral")
    f_confidence = abs(net_vote) / 5.0

    return {
        "l1l4_total": total,
        "l1l4_dir": direction,
        "l1l4_grade": grade,
        "l1": l1_score,
        "l2": l2_score,
        "l3": l3_score,
        "l4": l4_score,
        "f_direction": f_direction,
        "f_net_vote": net_vote,
        "f_confidence": f_confidence,
        "price": price,
        "adx": round(adx, 1),
        "rsi": round(rsi, 1),
        "atr": round(atr, 2),
        "vol_ratio": round(vol_ratio, 2),
    }


# ================================================================
# 数据采集
# ================================================================


def fetch_all_kline(symbols: List[str], days: int = 365) -> Dict[str, List[dict]]:
    """并行采集多个品种的K线数据。"""
    adapter = MultiSourceAdapter()
    results = {}
    for sym in symbols:
        try:
            resp = adapter.get_kline(variety=sym, days=days)
            if isinstance(resp, dict) and resp.get("success"):
                valid = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
                if len(valid) >= 60:
                    results[sym] = valid
                    print(f"  [{sym}] {len(valid)}根K线")
                    continue
        except Exception:
            pass
        print(f"  [{sym}] ❌ 数据不足")
    return results


# ================================================================
# 非重叠窗口回测
# ================================================================


def run_non_overlap_backtest(
    symbol: str, kline: List[dict], forward: int = 10, min_start: int = 60, fee_rate: float = 0.0
) -> Dict:
    """非重叠窗口模拟：平仓后下一截面才开新仓，权益曲线真实复合增长。

    Args:
        symbol: 品种代码
        kline: K线数据
        forward: 持仓天数
        min_start: 最少K线数（指标计算）
        fee_rate: 交易费率（双边）

    Returns:
        {equity_curve, trades, signals, metrics}
    """
    closes = [float(r["close"]) for r in kline]
    n = len(kline)

    # 初始化
    trades = []  # 已平仓交易记录
    all_signals = []  # 所有截面信号统计

    # 非重叠循环
    pos = min_start
    trade_id_counter = 0

    while pos + forward < n:
        # ── 计算当前截面的信号 ──
        window = kline[: pos + 1]
        df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
        df["volume"] = [float(r.get("volume", 0)) for r in window]
        tech = _compute_indicators_numpy(df, symbol)
        sc = compute_l1l4_score(tech, closes, pos)

        entry_price = sc["price"]
        adx = sc["adx"]
        l_dir = sc["l1l4_dir"]
        l_grade = sc["l1l4_grade"]
        f_dir = sc["f_direction"]
        f_conf = sc["f_confidence"]

        # 策略信号
        l1_signal = l_dir if l_grade in ("WATCH", "WEAK") else "HOLD"

        f_signal = (
            "BUY" if f_dir == "bull" and f_conf >= 0.2 else ("SELL" if f_dir == "bear" and f_conf >= 0.2 else "HOLD")
        )

        # 双策略共识（共振）
        dual_signal = "HOLD"
        if l1_signal == "BUY" and f_signal == "BUY" and adx > 25:
            dual_signal = "BUY"
        elif l1_signal == "SELL" and f_signal == "SELL" and adx > 25:
            dual_signal = "SELL"

        sig = {
            "date_idx": pos,
            "price": entry_price,
            "l1l4_dir": l_dir,
            "l1l4_grade": l_grade,
            "f_dir": f_dir,
            "f_confidence": f_conf,
            "dual_signal": dual_signal,
            "adx": adx,
        }
        all_signals.append(sig)

        # ── 开仓条件 ──
        open_trade = False
        if dual_signal != "HOLD":
            open_trade = True
        elif l1_signal != "HOLD" and f_signal == "HOLD":
            # 只有技术分析评分信号但因子择时无信号 → 可辩论级别
            open_trade = True

        if open_trade:
            trade_side = l1_signal if l1_signal != "HOLD" else dual_signal
            if trade_side == "HOLD":
                trade_side = "BUY" if sc["l1l4_total"] > 0 else "SELL"

            exit_idx = pos + forward
            if exit_idx >= n:
                break

            exit_price = closes[exit_idx]
            raw_ret = (exit_price / entry_price - 1) * 100
            # 做空反转
            ret = -raw_ret if trade_side == "SELL" else raw_ret

            # 交易摩擦
            fee_cost = fee_rate * 2 * 100  # %
            net_ret = ret - abs(ret) * fee_cost / 100

            trade_id = f"{symbol}_{pos}_{trade_id_counter}"
            trade_id_counter += 1

            trade = {
                "trade_id": trade_id,
                "symbol": symbol,
                "side": trade_side,
                "entry_idx": pos,
                "exit_idx": exit_idx,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "raw_return": round(ret, 3),
                "net_return": round(net_ret, 3),
                "adx": adx,
                "dual": dual_signal != "HOLD",
                "l1l4_total": sc["l1l4_total"],
            }
            trades.append(trade)

            # ── PnL日志（可选） ──
            if HAVE_JOURNAL:
                try:
                    tid = record_trade(
                        symbol,
                        "long" if trade_side == "BUY" else "short",
                        entry_price,
                        entry_price * 0.95 if trade_side == "BUY" else entry_price * 1.05,
                        entry_price * 1.05 if trade_side == "BUY" else entry_price * 0.95,
                        1,
                        datetime.now().strftime("%Y-%m-%d"),
                        tech_prediction=l1_signal,
                    )
                    close_trade(tid, exit_price, datetime.now().strftime("%Y-%m-%d"))
                    direction_ok = ret > 0
                    annotate_prediction(
                        tid, l1_signal if l1_signal != "HOLD" else "HOLD", "BUY" if direction_ok else "SELL", ret
                    )
                except Exception:
                    pass

            # 前进到平仓之后
            pos = exit_idx + 1
        else:
            # 无信号，前进一步
            pos += 1

    # ── 计算指标 ──
    if not trades:
        return {"symbol": symbol, "trades": 0, "status": "NO_TRADES"}

    returns = [t["net_return"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    # 权益曲线
    equity = [100]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))

    cr = (equity[-1] / equity[0] - 1) * 100
    mdd = calc_mdd(equity)
    sr = calc_sharpe(returns)
    win_rate = len(wins) / len(returns) * 100
    pf = abs(sum(wins) / max(abs(sum(losses)), 1e-6))
    avg_r = np.mean(returns) if returns else 0
    calmar = cr / max(mdd, 0.01)

    return {
        "symbol": symbol,
        "status": "OK",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "forward_days": forward,
            "min_start": min_start,
            "bars": n,
            "fee_rate": fee_rate,
        },
        "trades": len(trades),
        "equity_curve": equity,
        "metrics": {
            "cumulative_return": round(cr, 2),
            "annualized_return": round((1 + cr / 100) ** (252 / len(returns)) - 1, 2) * 100 if len(returns) else 0,
            "sharpe_ratio": round(sr, 3),
            "max_drawdown": mdd,
            "calmar_ratio": round(calmar, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(pf, 2),
            "avg_return": round(float(avg_r), 3),
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
        },
        "dual_signal_breakdown": {
            "total_dual_signals": sum(1 for t in trades if t.get("dual")),
            "dual_win_rate": round(
                sum(1 for t in trades if t.get("dual") and t["net_return"] > 0)
                / max(sum(1 for t in trades if t.get("dual")), 1)
                * 100,
                1,
            ),
            "l1_only_signals": sum(1 for t in trades if not t.get("dual")),
            "l1_win_rate": round(
                sum(1 for t in trades if not t.get("dual") and t["net_return"] > 0)
                / max(sum(1 for t in trades if not t.get("dual")), 1)
                * 100,
                1,
            ),
        },
    }


# ================================================================
# PnL反馈权重调整
# ================================================================


def adjust_weights(trades: List[Dict], results: List[Dict]) -> Dict:
    """按近期表现动态调整权重。"""
    if len(trades) < 10:
        return {"note": "样本不足(需要10+交易)", "l_weights": [35, 35, 20, 10], "f_threshold": 0.2, "adx_min": 25}

    # 按信号类型分组
    dual_trades = [t for t in trades if t.get("dual")]
    l1_trades = [t for t in trades if not t.get("dual")]

    dual_wr = sum(1 for t in dual_trades if t["net_return"] > 0) / max(len(dual_trades), 1)
    l1_wr = sum(1 for t in l1_trades if t["net_return"] > 0) / max(len(l1_trades), 1)

    # 权重调整
    weights = [35, 35, 20, 10]
    f_threshold = 0.2
    adx_min = 25

    # 如果双策略共振优于单技术分析评分，提升因子择时权重（降低阈值）
    if dual_wr > l1_wr + 0.05:
        f_threshold = max(0.1, f_threshold - 0.02)
    elif l1_wr > dual_wr + 0.05:
        f_threshold = min(0.4, f_threshold + 0.02)

    # ADX阈值自适应
    good_trades = [t for t in trades if t["net_return"] > 0]
    if good_trades:
        avg_adx_win = np.mean([t["adx"] for t in good_trades])
        bad_trades = [t for t in trades if t["net_return"] <= 0]
        if bad_trades:
            avg_adx_loss = np.mean([t["adx"] for t in bad_trades])
            if avg_adx_win > avg_adx_loss + 5:
                adx_min = min(30, adx_min + 2)
            elif avg_adx_loss > avg_adx_win + 5:
                adx_min = max(15, adx_min - 2)

    return {
        "note": "OK" if len(trades) >= 10 else "样本不足",
        "l_weights": weights,
        "f_threshold": round(f_threshold, 2),
        "adx_min": round(adx_min, 1),
        "dual_win_rate": round(dual_wr * 100, 1) if dual_trades else 0,
        "l1_win_rate": round(l1_wr * 100, 1) if l1_trades else 0,
        "total_trades": len(trades),
    }


# ================================================================
# HTML报告
# ================================================================


def generate_html(report: Dict) -> str:
    """生成自包含HTML回测报告。"""
    sym = report.get("symbol", "?")
    m = report.get("metrics", {})
    db = report.get("dual_signal_breakdown", {})
    config = report.get("config", {})
    eq = report.get("equity_curve", [])
    ts = report.get("timestamp", "")

    cr = m.get("cumulative_return", 0)
    sr = m.get("sharpe_ratio", 0)
    wr = m.get("win_rate", 0)

    cr_class = "positive" if cr > 0 else "negative"
    sr_class = "positive" if sr > 1 else "neutral"

    html = f"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>回测报告 v3.0 — {sym}</title>
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
.num{{text-align:right;font-family:"Courier New",monospace}}
.tag-dual{{display:inline-block;padding:1px 6px;border-radius:3px;background:#f59e0b20;color:#f59e0b;font-size:10px;font-weight:600}}
.tag-l1{{display:inline-block;padding:1px 6px;border-radius:3px;background:#6366f120;color:#6366f1;font-size:10px;font-weight:600}}
.footer{{text-align:center;padding:24px;color:#6b7280;font-size:11px;border-top:1px solid #2a2d3a;margin-top:24px}}
</style></head><body>

<h1>📊 回测报告 v3.0 — {sym}</h1>
<div class="sub">非重叠窗口 | 双策略共振 | PnL反馈 | {ts}</div>

<div class="card">
    <h2>📈 核心指标</h2>
    <div class="summary-grid">
        <div class="s-item {cr_class}"><div class="v">{cr:+.2f}%</div><div class="l">累计收益 CR</div></div>
        <div class="s-item {sr_class}"><div class="v">{sr:.2f}</div><div class="l">夏普 SR</div></div>
        <div class="s-item neutral"><div class="v">{wr:.1f}%</div><div class="l">胜率</div></div>
        <div class="s-item neutral"><div class="v">{m.get("max_drawdown", 0):.2f}%</div><div class="l">最大回撤</div></div>
        <div class="s-item neutral"><div class="v">{m.get("profit_factor", 0):.2f}</div><div class="l">盈亏比</div></div>
        <div class="s-item neutral"><div class="v">{m.get("calmar_ratio", 0):.2f}</div><div class="l">卡玛比</div></div>
    </div>
</div>

<div class="card">
    <h2>🔀 双策略共振分析</h2>
    <table style="width:auto">
        <tr><td>双策略信号</td><td><span class="tag-dual">双策略共振</span></td>
            <td>{db.get("total_dual_signals", 0)}次</td>
            <td>胜率 {db.get("dual_win_rate", 0)}%</td></tr>
        <tr><td>单信号</td><td><span class="tag-l1">仅单策略</span></td>
            <td>{db.get("l1_only_signals", 0)}次</td>
            <td>胜率 {db.get("l1_win_rate", 0)}%</td></tr>
    </table>
</div>

<div class="card">
    <h2>📋 交易明细 (最近{min(len(eq) - 1 if eq else 0, 20)}笔)</h2>
    <table><thead><tr>
        <th>#</th><th>方向</th><th class="num">入场</th><th class="num">出场</th>
        <th class="num">收益%</th><th>ADX</th><th>类型</th>
    </tr></thead><tbody>
"""
    # 添加交易明细（从报告传不进来…只显示统计信息）
    html += f"""<tr><td colspan="7" style="text-align:center;color:#94a3b8">
        共 {m.get("total_trades", 0)} 笔交易 · 非重叠窗口 · 含摩擦后净值
    </td></tr>"""
    html += f"""
    </tbody></table>
</div>

<div class="card">
    <h2>⚙️ 配置</h2>
    <table style="width:auto">
        <tr><td>持仓天数</td><td>{config.get("forward_days", 10)}日</td></tr>
        <tr><td>K线根数</td><td>{config.get("bars", 0)}</td></tr>
        <tr><td>交易费率</td><td>{config.get("fee_rate", 0) * 100:.2f}% (双边)</td></tr>
        <tr><td>PnL反馈</td><td>{"✅ 已接入" if HAVE_JOURNAL else "❌ 未启用"}</td></tr>
    </table>
</div>

<div class="footer">期货辩论专家团 · 回测引擎 v3.0 | {ts}</div>
</body></html>"""
    return html


# ================================================================
# CLI
# ================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="回测引擎 v3.0 — 双策略共振+非重叠+反馈")
    parser.add_argument("--symbols", "-s", default="RB,HC,PK", help="品种列表(逗号分隔)")
    parser.add_argument("--days", "-d", type=int, default=365, help="历史数据天数")
    parser.add_argument("--forward", type=int, default=10, help="持仓天数")
    parser.add_argument("--fee-rate", type=float, default=0.0005, help="交易费率(默认万5)")
    parser.add_argument("--no-journal", action="store_true", help="不写trade_journal")
    parser.add_argument("--output", "-o", default="", help="输出目录")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    today = datetime.now().strftime("%Y%m%d")

    if args.output:
        out_dir = args.output
    else:
        out_dir = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results", today)
    os.makedirs(out_dir, exist_ok=True)

    if not HAVE_JOURNAL and not args.no_journal:
        print("[Warning] trade_journal不可用，跳过PnL日志")

    print(f"{'=' * 60}")
    print(f"  回测引擎 v3.0 — {today}")
    print(f"  {' '.join(symbols)} | {args.days}天 | 持仓{args.forward}日 | 费率{args.fee_rate * 100:.2f}%")
    print(f"{'=' * 60}")

    # 采集数据
    print("\n[数据采集]...")
    kline_map = fetch_all_kline(symbols, args.days)

    all_reports = []
    all_trades = []

    for sym in symbols:
        if sym not in kline_map:
            print(f"\n[{sym}] ❌ 跳过（无数据）")
            continue

        print(f"\n[{sym}] 非重叠回测...")
        t0 = time.time()
        report = run_non_overlap_backtest(
            sym,
            kline_map[sym],
            forward=args.forward,
            fee_rate=args.fee_rate,
        )
        elapsed = time.time() - t0

        if report.get("status") != "OK":
            print(f"  [{sym}] ⚠️ {report.get('status', '未知')}")
            all_reports.append(report)
            continue

        m = report.get("metrics", {})
        db = report.get("dual_signal_breakdown", {})
        print(
            f"  {m.get('total_trades', 0)}笔 | 双策略{db.get('total_dual_signals', 0)}笔(胜率{db.get('dual_win_rate', 0)}%)"
            f" | 技术分析评分{db.get('l1_only_signals', 0)}笔(胜率{db.get('l1_win_rate', 0)}%)"
        )
        print(
            f"  CR={m.get('cumulative_return', 0):+.2f}% SR={m.get('sharpe_ratio', 0):.2f} 胜率={m.get('win_rate', 0):.1f}%"
            f" MDD={m.get('max_drawdown', 0):.2f}% PF={m.get('profit_factor', 0):.2f}"
        )

        # PnL反馈权重调整
        if len(all_trades) > 0 or report.get("trades", 0) > 0:
            adj = adjust_weights(
                [
                    {"net_return": t["net_return"], "adx": t["adx"], "dual": t.get("dual", False)}
                    for t in (report.get("_trades", []) if "_trades" in report else [])
                ],
                all_reports,
            )
            report["weight_adjustment"] = adj
            if adj.get("note") == "OK":
                print(f"  ⚙️ 权重调整: f_threshold={adj.get('f_threshold', 0.2)} adx_min={adj.get('adx_min', 25)}")

        # 保存
        json_path = os.path.join(out_dir, f"backtest_v3_{sym}_{today}.json")
        # 不保存大数组
        report_copy = {k: v for k, v in report.items() if k not in ("equity_curve", "_trades")}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_copy, f, ensure_ascii=False, indent=2)

        html = generate_html(report)
        html_path = os.path.join(out_dir, f"backtest_v3_{sym}_{today}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  ✅ {json_path}")
        all_reports.append(report)

    # 总体汇总
    ok = [r for r in all_reports if r.get("status") == "OK"]
    total_trades = sum(r.get("trades", 0) for r in ok)
    total_wins = sum(r.get("metrics", {}).get("wins", 0) for r in ok)
    total_losses = sum(r.get("metrics", {}).get("losses", 0) for r in ok)
    avg_cr = np.mean([r.get("metrics", {}).get("cumulative_return", 0) for r in ok]) if ok else 0
    avg_sr = np.mean([r.get("metrics", {}).get("sharpe_ratio", 0) for r in ok]) if ok else 0

    print(f"\n{'=' * 60}")
    print(f"  {'✅' if ok else '❌'} 完成: {len(ok)}/{len(symbols)}品种")
    print(f"  总交易: {total_trades}笔 | 胜率 {total_wins / max(total_trades, 1) * 100:.1f}%")
    print(f"  平均CR: {avg_cr:+.2f}% | 平均SR: {avg_sr:.2f}")
    print(f"  📁 {out_dir}")
    print(f"{'=' * 60}")

    return all_reports


if __name__ == "__main__":
    main()
