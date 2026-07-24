#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎 v3.1 — ML方向预测器替换人工因子代理
=============================================
核心改进：
- 使用 DirectionClassifier(lightGBM) 替代5因子人工打分
- EnsemblePredictor 融合规则层 + ML层(lightGBM)
- 首次运行自动采集训练数据+训练模型
- 后续运行加载已训练模型进行推理

用法：
  python backtest_v3_ml.py --symbols RB --days 365  # 首次训练+回测
  python backtest_v3_ml.py --symbols RB,HC --days 365  # 复用模型
  python backtest_v3_ml.py --symbols RB --days 365 --force-train  # 重新训练
"""

import json
import math
import os
import sys
import time
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(SKILL_DIR)
if not os.path.isdir(PARENT_DIR):
    PARENT_DIR = os.path.join(os.path.expanduser("~"), ".skills", "skills")
    SKILL_DIR = os.path.join(PARENT_DIR, "quant-daily", "scripts")
for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy

# ── ML 依赖（可选）──
try:
    from ml_models.direction_classifier import DirectionClassifier, EnsemblePredictor

    HAVE_ML = True
except ImportError:
    HAVE_ML = False

try:
    from feature_pipeline.feature_engineering import engineer_features

    HAVE_FEATURE = True
except ImportError:
    HAVE_FEATURE = False

# ── 模型存储路径 ──
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "backtest_lgb_model.txt")
FEATURE_NAMES_PATH = os.path.join(MODEL_DIR, "feature_names.json")


# ================================================================
# 指标计算
# ================================================================


def calc_sharpe(returns: List[float], rf: float = 0.02) -> float:
    if len(returns) < 2:
        return 0.0
    r = np.array(returns, dtype=float)
    excess = r - rf / 252
    if np.std(r, ddof=1) < 1e-8:
        return 0.0
    return float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(252))


def calc_mdd(equity: List[float]) -> float:
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd:
            mdd = dd
    return round(mdd, 2)


# ================================================================
# 评分（规则层）
# ================================================================


def score_l1l4(tech: dict, price: float) -> dict:
    """透明评分 → 输出 EnsemblePredictor 兼容格式。"""
    ma5 = tech.get("MA5")
    ma10 = tech.get("MA10")
    ma20 = tech.get("MA20")
    ma60 = tech.get("MA60")
    macd = tech.get("MACD_DIF", 0)
    rsi = tech.get("RSI14", 50)
    pdi = tech.get("DMI_PDI", 25)
    mdi = tech.get("DMI_MDI", 25)
    adx = tech.get("ADX", tech.get("ADX14", 0))
    vol_ratio = tech.get("VOL_RATIO", tech.get("volume_ratio", 1.0))

    l1 = (20 if price > ma60 else -20 if price < ma60 else 0) + (10 if price > ma20 else -10 if price < ma20 else 0)
    if all(v for v in [ma5, ma10, ma20]):
        l1 += 10 if ma5 > ma10 > ma20 else (-10 if ma5 < ma10 < ma20 else 0)

    l2 = 0
    if vol_ratio > 1.5:
        l2 = 15 if l1 > 0 else -15
    elif vol_ratio > 1.2:
        l2 = 5 if l1 > 0 else -5

    l3 = 0
    if adx > 25:
        f = min(adx / 100, 0.5)
        if pdi > mdi:
            l3 = int(10 * f * 2)
        else:
            l3 = -int(10 * f * 2)

    l4 = (5 if macd > 0 else -5) + (3 if rsi > 55 else -3 if rsi < 45 else 0)
    veto = (-10 if adx < 15 else 0) + (-8 if rsi > 80 or rsi < 20 else 0)

    total = l1 + l2 + l3 + l4 + veto
    is_bull = total > 0
    prob = 0.5 + abs(total) / 200.0 * (1 if is_bull else -1)
    direction = 1 if is_bull else (-1 if total < 0 else 0)
    confidence = min(100, abs(total) * 1.2)

    return {
        "prob": max(0.01, min(0.99, prob)),
        "direction": direction,
        "confidence": int(confidence),
        "l1l4_total": total,
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "l4": l4,
        "veto": veto,
    }


# ================================================================
# 特征提取
# ================================================================


def extract_features(tech: dict, price: float, closes: List[float], start: int) -> Dict[str, float]:
    """从tech字典提取ML模型所需的特征向量。

    与 feature_engineering.engineer_features() 接口对齐，
    但只使用可以从_compute_indicators_numpy 获取的数据。
    """
    feat = {}
    ma20 = tech.get("MA20", price)
    ma60 = tech.get("MA60", price)

    # 价格动量
    for d in [1, 5, 10, 20]:
        if start >= d and closes[start - d] > 0:
            feat[f"roc_{d}"] = (price / closes[start - d] - 1) * 100
        else:
            feat[f"roc_{d}"] = 0.0

    # 波动率
    if start >= 5:
        r5 = [closes[start - i] / closes[start - i - 1] - 1 for i in range(5)]
        feat["volatility_5"] = float(np.std(r5)) * 100
    else:
        feat["volatility_5"] = 0.0
    if start >= 20:
        r20 = [closes[start - i] / closes[start - i - 1] - 1 for i in range(20)]
        feat["volatility_20"] = float(np.std(r20)) * 100
    else:
        feat["volatility_20"] = 0.0

    # 高低振幅
    feat["high_low_range_5"] = tech.get("ATR14", 0) / max(price, 1) * 100

    # 收盘价位置
    if start >= 20:
        lo20 = min(closes[start - 19 : start + 1])
        hi20 = max(closes[start - 19 : start + 1])
        feat["close_position_20"] = (price - lo20) / max(hi20 - lo20, 0.01)
    else:
        feat["close_position_20"] = 0.5

    # 技术指标
    feat["adx"] = tech.get("ADX", tech.get("ADX14", 0))
    feat["rsi_14"] = tech.get("RSI14", 50)
    feat["macd_hist"] = tech.get("MACD_DEA", 0)
    feat["bb_position"] = tech.get("BB_PCTB", 0.5)
    feat["ma_short_long"] = ma20 / max(ma60, 1)
    feat["atr_pct"] = tech.get("ATR14", 0) / max(price, 1) * 100
    feat["volume_ratio"] = tech.get("VOL_RATIO", tech.get("volume_ratio", 1.0))

    # 价格 + OI
    vol = tech.get("volume", 0) or sum(closes[max(0, start - 5) : start + 1]) / max(start - max(0, start - 5), 1)
    feat["price"] = price
    feat["dmi_delta"] = tech.get("DMI_PDI", 25) - tech.get("DMI_MDI", 25)

    return feat


def extract_label(closes: List[float], start: int, forward: int = 10) -> int:
    """提取方向标签：1=涨, -1=跌, 0=平"""
    if start + forward >= len(closes):
        return 0
    ret = (closes[start + forward] / closes[start] - 1) * 100
    if ret > 1.0:
        return 1
    if ret < -1.0:
        return -1
    return 0


# ================================================================
# 训练数据采集
# ================================================================


def collect_training_data(
    kline: List[dict], symbol: str, forward: int = 10, min_start: int = 60
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """从K线数据中提取训练特征和标签。"""
    closes = [float(r["close"]) for r in kline]
    n = len(kline)
    all_features = []
    all_labels = []
    sample_feature_names = []

    for start in range(min_start, n - forward, 5):  # step=5
        window = kline[: start + 1]
        df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
        df["volume"] = [float(r.get("volume", 0)) for r in window]
        tech = _compute_indicators_numpy(df, symbol)
        price = tech.get("last_price", closes[start])

        feat = extract_features(tech, price, closes, start)
        label = extract_label(closes, start, forward)

        if not sample_feature_names:
            sample_feature_names = sorted(feat.keys())

        all_features.append([feat.get(k, 0.0) for k in sample_feature_names])
        all_labels.append(label)

    if not all_features:
        return np.array([]), np.array([]), []

    X = np.array(all_features, dtype=np.float32)
    y = np.array(all_labels, dtype=np.int32)

    # 剔除 NaN/Inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    print(f"  [训练数据] {len(X)} 样本, {len(sample_feature_names)} 维特征")
    print(f"  标签分布: 涨{np.sum(y == 1)} 跌{np.sum(y == -1)} 平{np.sum(y == 0)}")

    return X, y, sample_feature_names


# ================================================================
# 模型管理
# ================================================================


def load_model() -> Optional[DirectionClassifier]:
    """加载已训练的模型。"""
    if not os.path.exists(MODEL_PATH) or not os.path.exists(FEATURE_NAMES_PATH):
        return None
    try:
        model = DirectionClassifier()
        model.load(MODEL_PATH)
        with open(FEATURE_NAMES_PATH, encoding="utf-8") as f:
            model.feature_names = json.load(f)
        return model
    except Exception as e:
        print(f"  [WARN] 模型加载失败: {e}")
        return None


# ================================================================
# 非重叠回测（ML版）
# ================================================================


def run_ml_backtest(
    symbol: str,
    kline: List[dict],
    model: DirectionClassifier,
    ensemble: EnsemblePredictor,
    forward: int = 10,
    min_start: int = 60,
    fee_rate: float = 0.0,
) -> Dict:
    """非重叠窗口回测，使用ML方向预测器替代人工因子代理。"""
    closes = [float(r["close"]) for r in kline]
    n = len(kline)
    trades = []
    all_signals = []

    pos = min_start
    trade_id_counter = 0
    equity = [100]

    while pos + forward < n:
        # ── 计算当前截面 ──
        window = kline[: pos + 1]
        df = pd.DataFrame({k: [float(r[k]) for r in window] for k in ["open", "high", "low", "close"]})
        df["volume"] = [float(r.get("volume", 0)) for r in window]
        tech = _compute_indicators_numpy(df, symbol)
        price = tech.get("last_price", closes[pos])

        # 规则层
        rule_out = score_l1l4(tech, price)

        # ML层
        feat = extract_features(tech, price, closes, pos)
        try:
            ml_prob, ml_dir_int, ml_conf = model.predict(feat)
        except Exception:
            ml_prob, ml_dir_int, ml_conf = 0.5, 0, 30

        ml_out = {"prob": ml_prob, "direction": ml_dir_int, "confidence": ml_conf}

        # 集成
        ensemble_out = ensemble.predict(rule_out, ml_out)
        ens_dir = ensemble_out.get("direction", 0)
        ens_conf = ensemble_out.get("confidence", 0)
        adx = tech.get("ADX", tech.get("ADX14", 0))

        # 方向映射
        signal = "HOLD"
        if ens_dir > 0 and adx > 25:
            signal = "BUY"
        elif ens_dir < 0 and adx > 25:
            signal = "SELL"

        # 仅规则层信号（用于对比）
        rule_dir = rule_out.get("direction", 0)
        rule_signal = "HOLD"
        if rule_dir > 0:
            rule_signal = "BUY"
        elif rule_dir < 0:
            rule_signal = "SELL"

        sig = {
            "date_idx": pos,
            "price": price,
            "ensemble": ensemble_out,
            "rule": rule_out,
            "ml": ml_out,
            "signal": signal,
            "rule_signal": rule_signal,
            "adx": round(adx, 1),
        }
        all_signals.append(sig)

        # ── 开仓 ──
        if signal != "HOLD":
            exit_idx = pos + forward
            if exit_idx >= n:
                break

            exit_price = closes[exit_idx]
            raw_ret = (exit_price / price - 1) * 100
            ret = -raw_ret if signal == "SELL" else raw_ret
            fee_cost = fee_rate * 2 * 100
            net_ret = ret - abs(ret) * fee_cost / 100

            trades.append(
                {
                    "trade_id": f"{symbol}_{pos}_{trade_id_counter}",
                    "side": signal,
                    "entry_price": round(price, 2),
                    "exit_price": round(exit_price, 2),
                    "raw_return": round(ret, 3),
                    "net_return": round(net_ret, 3),
                    "ensemble_conf": ens_conf,
                    "ml_prob": round(ml_prob, 3),
                    "adx": round(adx, 1),
                    "dual": True,
                }
            )
            trade_id_counter += 1
            equity.append(equity[-1] * (1 + net_ret / 100))
            pos = exit_idx + 1
        else:
            pos += 1

    # ── 计算指标 ──
    if not trades:
        return {"symbol": symbol, "trades": 0, "status": "NO_TRADES"}

    returns = [t["net_return"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    cr = (equity[-1] / equity[0] - 1) * 100
    mdd = calc_mdd(equity)
    sr = calc_sharpe(returns)
    win_rate = len(wins) / len(returns) * 100
    pf = abs(sum(wins) / max(abs(sum(losses)), 1e-6))
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
            "model": "ML+规则集成",
        },
        "trades": len(trades),
        "equity_end": round(equity[-1], 2),
        "metrics": {
            "cumulative_return": round(cr, 2),
            "sharpe_ratio": round(sr, 3),
            "max_drawdown": mdd,
            "calmar_ratio": round(calmar, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(pf, 2),
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
        },
        "ml_stats": {
            "signal_agreement": round(
                sum(1 for s in all_signals if s["signal"] != "HOLD") / max(len(all_signals), 1) * 100, 1
            ),
            "avg_ml_prob": round(np.mean([s["ml"]["prob"] for s in all_signals]), 3),
        },
    }


# ================================================================
# HTML报告
# ================================================================


def generate_html(report: Dict) -> str:
    sym = report.get("symbol", "?")
    m = report.get("metrics", {})
    ms = report.get("ml_stats", {})
    config = report.get("config", {})
    cr = m.get("cumulative_return", 0)
    sr = m.get("sharpe_ratio", 0)

    return f"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>回测报告 v3.1 ML — {sym}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0c10;color:#e2e8f0;font-family:-apple-system,sans-serif;padding:24px;max-width:1200px;margin:0 auto}}
h1{{font-size:24px;background:linear-gradient(135deg,#6366f1,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.card{{background:#1a1d28;border:1px solid #2a2d3a;border-radius:12px;padding:20px 24px;margin-bottom:16px}}
.card h2{{font-size:16px;color:#6366f1;margin-bottom:12px;border-bottom:1px solid #2a2d3a;padding-bottom:8px}}
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}}
.s-item{{background:#12141a;border-radius:8px;padding:12px;text-align:center}}
.s-item .v{{font-size:22px;font-weight:700}}
.s-item .l{{font-size:10px;color:#94a3b8}}
.s-item.positive .v{{color:#22c55e}} .s-item.negative .v{{color:#ef4444}} .s-item.neutral .v{{color:#6366f1}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#252940;padding:8px;text-align:left;font-weight:600;color:#94a3b8;font-size:10px}}
td{{padding:6px 8px;border-top:1px solid #2a2d3a30}}
.tag-ml{{display:inline-block;padding:1px 6px;border-radius:3px;background:#6366f120;color:#6366f1;font-size:10px;font-weight:600}}
.footer{{text-align:center;padding:24px;color:#6b7280;font-size:11px;border-top:1px solid #2a2d3a;margin-top:24px}}
</style></head><body>

<h1>🤖 回测报告 v3.1 ML — {sym}</h1>
<div class="sub">ML方向预测器替换人工因子 | 规则层+ML层集成 | 非重叠窗口 | {report.get("timestamp", "")}</div>

<div class="card">
    <h2>📈 核心指标</h2>
    <div class="summary-grid">
        <div class="s-item {"positive" if cr > 0 else "negative"}"><div class="v">{cr:+.2f}%</div><div class="l">累计收益 CR</div></div>
        <div class="s-item {"positive" if sr > 1 else "neutral"}"><div class="v">{sr:.2f}</div><div class="l">夏普 SR</div></div>
        <div class="s-item neutral"><div class="v">{m.get("win_rate", 0):.1f}%</div><div class="l">胜率</div></div>
        <div class="s-item neutral"><div class="v">{m.get("max_drawdown", 0):.2f}%</div><div class="l">最大回撤</div></div>
        <div class="s-item neutral"><div class="v">{m.get("profit_factor", 0):.2f}</div><div class="l">盈亏比</div></div>
        <div class="s-item neutral"><div class="v">{m.get("calmar_ratio", 0):.2f}</div><div class="l">卡玛比</div></div>
    </div>
</div>

<div class="card">
    <h2>🧠 ML 模型统计</h2>
    <table style="width:auto">
        <tr><td>集成方式</td><td><span class="tag-ml">规则层+ML(LightGBM)</span></td></tr>
        <tr><td>ML层出手比例</td><td>{ms.get("signal_agreement", 0)}%</td></tr>
        <tr><td>ML平均概率</td><td>{ms.get("avg_ml_prob", 0):.3f}</td></tr>
        <tr><td>交易笔数</td><td>{m.get("total_trades", 0)}</td></tr>
    </table>
</div>

<div class="card">
    <h2>⚙️ 配置</h2>
    <table style="width:auto">
        <tr><td>模型</td><td>{config.get("model", "?")}</td></tr>
        <tr><td>持仓天数</td><td>{config.get("forward_days", 10)}日</td></tr>
        <tr><td>交易费率</td><td>{config.get("fee_rate", 0) * 100:.2f}%</td></tr>
    </table>
</div>

<div class="footer">期货辩论专家团 · 回测引擎 v3.1 ML | {report.get("timestamp", "")}</div>
</body></html>"""


# ================================================================
# CLI
# ================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="回测引擎 v3.1 — ML方向预测器")
    parser.add_argument("--symbols", "-s", default="RB", help="品种")
    parser.add_argument("--days", "-d", type=int, default=365, help="天数")
    parser.add_argument("--forward", type=int, default=10, help="持仓日")
    parser.add_argument("--fee-rate", type=float, default=0.0005, help="费率")
    parser.add_argument("--force-train", action="store_true", help="强制重训练")
    parser.add_argument("--output", "-o", default="", help="输出目录")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    today = datetime.now().strftime("%Y%m%d")
    out_dir = args.output or os.path.join(os.path.dirname(SKILL_DIR), "backtest", "results", today)
    os.makedirs(out_dir, exist_ok=True)

    if not HAVE_ML:
        print("❌ 需要 lightgbm: pip install lightgbm")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"  回测引擎 v3.1 ML — {today}")
    print(f"  {args.symbols} | {args.days}天 | 持仓{args.forward}日 | ML方向预测")
    print(f"{'=' * 60}")

    # ── 加载或训练模型 ──
    model = None if args.force_train else load_model()
    if model is None:
        print("\n[训练阶段] 采集数据 + 训练LightGBM...")
        all_X, all_y, feat_names = [], [], []

        for sym in symbols:
            adapter = MultiSourceAdapter()
            resp = adapter.get_kline(variety=sym, days=args.days)
            if not (isinstance(resp, dict) and resp.get("success")):
                continue
            kline = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
            if len(kline) < 60:
                continue

            print(f"  [{sym}] {len(kline)}根K线")
            X, y, fn = collect_training_data(kline, sym, args.forward)
            if len(X) > 0:
                if not feat_names:
                    feat_names = fn
                all_X.append(X)
                all_y.append(y)

        if all_X:
            X_all = np.vstack(all_X).astype(np.float32)
            y_all = np.concatenate(all_y).astype(np.int32)
            # 时序分割: 前70%训练, 后30%验证（避免前视偏差）
            split = int(len(X_all) * 0.7)
            X_train, X_val = X_all[:split], X_all[split:]
            y_train, y_val = y_all[:split], y_all[split:]
            y_binary = np.where(y_train == 1, 1, 0)
            print(f"\n  总样本{len(X_all)}: 训练{split} / 验证{len(X_all) - split}")
            print(f"  训练集分布: 涨{np.sum(y_binary == 1)}/{len(y_binary) - np.sum(y_binary == 1)}跌平")
            os.makedirs(MODEL_DIR, exist_ok=True)
            model = DirectionClassifier()
            model.train(X_train, y_train, X_val, y_val, feature_names=feat_names)
            model.save(MODEL_PATH)
            with open(FEATURE_NAMES_PATH, "w", encoding="utf-8") as f:
                json.dump(feat_names, f)
            print(f"  ✅ 模型已保存: {MODEL_PATH}")
        else:
            print("❌ 无训练数据")
            return

    # ── 回测阶段 ──
    print("\n[回测阶段]...")
    ensemble = EnsemblePredictor(rule_weight=0.6, ml_weight=0.4, adapt_online=True)
    all_reports = []

    for sym in symbols:
        adapter = MultiSourceAdapter()
        resp = adapter.get_kline(variety=sym, days=args.days)
        if not (isinstance(resp, dict) and resp.get("success")):
            continue
        kline = [r for r in resp["data"] if r.get("volume", 0) > 0 and r.get("close", 0) > 0]
        if len(kline) < 60:
            continue

        print(f"\n[{sym}] ML回测...")
        t0 = time.time()
        report = run_ml_backtest(sym, kline, model, ensemble, forward=args.forward, fee_rate=args.fee_rate)
        elapsed = time.time() - t0

        if report.get("status") != "OK":
            print(f"  [{sym}] ⚠️ {report.get('status')}")
            continue

        m = report["metrics"]
        ms = report["ml_stats"]
        print(
            f"  {m['total_trades']}笔 | 胜率{m['win_rate']}% | CR={m['cumulative_return']:+.2f}% | SR={m['sharpe_ratio']:.2f}"
        )

        json_path = os.path.join(out_dir, f"backtest_ml_{sym}_{today}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        html_path = os.path.join(out_dir, f"backtest_ml_{sym}_{today}.html")
        with open(html_path, "w") as f:
            f.write(generate_html(report))
        print(f"  ✅ {json_path}")
        all_reports.append(report)

    ok = [r for r in all_reports if r.get("status") == "OK"]
    if ok:
        avg_cr = np.mean([r["metrics"]["cumulative_return"] for r in ok])
        avg_sr = np.mean([r["metrics"]["sharpe_ratio"] for r in ok])
        print(f"\n{'=' * 60}")
        print(f"  ✅ {len(ok)}品种 | 平均CR={avg_cr:+.2f}% | 平均SR={avg_sr:.2f}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
