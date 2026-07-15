"""
协整配对均值回归策略 — Pairs Reversion（G35 Phase 1）。

期货特有的「做空均值回归」核心维度：跨品种协整配对，做多便宜腿 + 做空贵腿，
**天然双向做空**，弥补单合约价格反转（MeanReversionStrategy）缺乏期货价差语义的空白。

设计要点：
  - 复用 arbitrage.CROSS_VARIETY_PAIRS 的 7 组产业链配对（RB-HC/I-J/TA-EG/M-RM/Y-OI/SA-FG）
  - 用 kline_data 两品种 120 天历史做 Engle-Granger 协整回归取残差（替代原 arbitrage 的
    简化比率 Z-score，更接近成熟配对交易）
  - 残差滚动 Z-score（窗口 20/60），|Z|>2 出信号
  - **Hurst 前置门禁**：任一腿 Hurst>0.55（趋势型）跳过该配对，避免伪均值回归
  - 产两腿独立 RawSignal（贵腿 bear + 便宜腿 bull），下游 trade_plan 按 symbol 自然处理

数据来源：全部复用现有管线 —— kline_data（120 天日线，scan_all 已采集）+ tech_list（全品种
最新价）。零新数据源。
"""

from __future__ import annotations
from typing import Any

import numpy as np

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal
from .arbitrage_strategy import CROSS_VARIETY_PAIRS


# ── 阈值配置 ──
HURST_MAX = 0.75          # 任一腿 Hurst 超过此值（强趋势型）→ 跳过该配对。
                            # 注：R/S 法在小样本上有 ≈+0.12 上偏（i.i.d. 收益实测≈0.62、
                            # 随机游走 diff≈0.68），故阈值取 0.75 仅跳过强趋势（动量收益≈0.84），
                            # 随机游走腿（≈0.68）正常通过，避免误杀多数期货配对。
Z_ENTRY = 2.0             # 残差 Z-score 绝对值超过 → 出信号
MIN_BARS = 60             # 协整/ Hurst 所需最小历史 bar 数
HALF_LIFE_MAX = 120.0     # OU 半衰期上限（日），超过视为弱回归不放大权重


# ── 统计工具（纯 numpy，策略自包含） ──

def calculate_hurst(close: Any, max_lag: int = 20) -> float:
    """Hurst 指数（R/S 重标极差法，Peters 1994）。

    对多个滞后窗口 L，将序列分块计算每块的重标极差 R/S = (max- min 累积偏离)/标准差，
    取 log(R/S) ~ H·log(L) 的斜率即为 H：
        H < 0.5 → 均值回归；H ≈ 0.5 → 随机游走；H > 0.5 → 趋势。
    数据不足返回 0.5（中性，不跳过）。
    """
    x = np.asarray(close, dtype=float)
    n = len(x)
    if n < 20:
        return 0.5
    lags = range(2, min(max_lag, n // 2))
    rs_vals: list[float] = []
    used_lags: list[int] = []
    for L in lags:
        if L >= n:
            continue
        n_seg = n // L
        if n_seg < 1:
            continue
        rs_seg: list[float] = []
        for i in range(n_seg):
            seg = x[i * L:(i + 1) * L]
            if len(seg) < 2:
                continue
            m_seg = np.mean(seg)
            cum = np.cumsum(seg - m_seg)
            r = float(np.max(cum) - np.min(cum))
            s = float(np.std(seg))
            if s > 0:
                rs_seg.append(r / s)
        if rs_seg:
            rs_vals.append(float(np.mean(rs_seg)))
            used_lags.append(L)
    if len(rs_vals) < 2:
        return 0.5
    try:
        poly = np.polyfit(np.log(np.array(used_lags, dtype=float)),
                          np.log(np.array(rs_vals)), 1)
    except Exception:
        return 0.5
    return float(poly[0])


def _engle_granger_residual(y: np.ndarray, x: np.ndarray) -> np.ndarray | None:
    """Engle-Granger 两步法第一步：y 对 x  OLS 回归取残差。

    残差 = y - (alpha + beta*x)，beta = cov(x,y)/var(x)。
    返回残差序列；样本不足返回 None。
    """
    if len(x) < 30 or len(y) < 30:
        return None
    beta = np.cov(x, y)[0, 1] / np.var(x)
    alpha = np.mean(y) - beta * np.mean(x)
    return y - (alpha + beta * x)


def _rolling_z(values: list[float], window: int) -> float:
    """滚动 Z-score（取末值相对窗口均值/标准差的偏离）。"""
    if len(values) < window:
        window = len(values)
    if window < 2:
        return 0.0
    w = np.array(values[-window:], dtype=float)
    mu = float(np.mean(w))
    sd = float(np.std(w))
    if sd <= 1e-9:
        return 0.0
    return float((values[-1] - mu) / sd)


def _half_life(resid: np.ndarray) -> float:
    """OU 过程半衰期：resid[t]-resid[t-1] = a + b*resid[t-1] → hl = -ln(2)/b。

    b >= 0（无均值回复）返回 inf；样本不足返回 inf。
    """
    r = np.asarray(resid, dtype=float)
    if len(r) < 10:
        return float("inf")
    dy = np.diff(r)
    ylag = r[:-1]
    if np.var(ylag) <= 1e-12:
        return float("inf")
    b = np.cov(ylag, dy)[0, 1] / np.var(ylag)
    if b >= 0:
        return float("inf")
    return float(-np.log(2) / b)


# ════════════════════════════════════════════════════════════
# 策略类
# ════════════════════════════════════════════════════════════

class PairsReversionStrategy(BaseStrategyV2):
    """协整配对均值回归：跨品种价差回归做空贵腿 + 做多便宜腿。"""

    @property
    def name(self) -> str:
        return "pairs_reversion"

    @property
    def display_name(self) -> str:
        return "协整配对均值回归(做空回归)"

    @property
    def signal_type(self) -> str:
        return "pairs_reversion"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing", "stability"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        ctx = context or {}

        # 最新价（来自 tech_list，零新数据）
        price_map = {str(t.get("symbol", "")).upper(): float(t.get("price", 0))
                     for t in tech_list}

        # 历史收盘序列（来自 kline_data，120 天日线；scan_all 已采集）
        kline_map: dict[str, np.ndarray] = {}
        for sym, (_name, bars) in (kline_data or {}).items():
            closes = [float(b.get("close", 0)) for b in bars if b.get("close")]
            if len(closes) >= MIN_BARS:
                kline_map[str(sym).upper()] = np.array(closes, dtype=float)

        for pk, pair in CROSS_VARIETY_PAIRS.items():
            pa, pb = str(pair["a"]).upper(), str(pair["b"]).upper()
            if pa not in price_map or pb not in price_map:
                continue
            if pa not in kline_map or pb not in kline_map:
                continue

            ya, yb = kline_map[pa], kline_map[pb]

            # ── Hurst 前置门禁：对价格变化（平稳序列）判定趋势性 ──
            # 随机游走收益 H≈0.5、趋势收益 H>0.5、均值回归收益 H<0.5；
            # 直接对价格水平（I(1)）算会系统性偏高（≈1.0），故用 diff。
            ha = calculate_hurst(np.diff(ya))
            hb = calculate_hurst(np.diff(yb))
            if ha > HURST_MAX or hb > HURST_MAX:
                continue

            # ── Engle-Granger 协整残差 ──
            resid = _engle_granger_residual(ya, yb)
            if resid is None:
                continue

            win = int(pair.get("z_window", 20))
            z = _rolling_z(list(resid), max(win, 20))
            if abs(z) < Z_ENTRY:
                continue

            # ── 方向：残差正 → a 相对 b 偏高（a 贵）→ 做空 a + 做多 b ──
            pa_price, pb_price = price_map[pa], price_map[pb]
            if pb_price <= 0:
                continue
            current_ratio = pa_price / pb_price
            a_dir = "bear" if z > 0 else "bull"
            b_dir = "bull" if a_dir == "bear" else "bear"
            raw = min(1.0, abs(z) / 3.0)

            hl = _half_life(resid)
            meta = {
                "pair_key": pk, "pair_a": pa, "pair_b": pb,
                "current_ratio": round(current_ratio, 4),
                "target_ratio": pair["ratio"],
                "z_score": round(z, 2),
                "hurst_a": round(ha, 2), "hurst_b": round(hb, 2),
                "half_life": round(hl, 1) if hl != float("inf") else None,
                "type": "pair_reversion",
            }

            # 两腿独立信号（天然双向做空）
            signals.append(RawSignal(
                symbol=pa, direction=a_dir,
                signal_type=f"{self.signal_type}.pair.{pa}",
                raw_score=raw, strategy_name=self.name,
                meta={**meta, "leg": "a"},
            ))
            signals.append(RawSignal(
                symbol=pb, direction=b_dir,
                signal_type=f"{self.signal_type}.pair.{pb}",
                raw_score=raw, strategy_name=self.name,
                meta={**meta, "leg": "b"},
            ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100
            grade = "WATCH" if raw > 0.8 else "WEAK" if raw > 0.4 else "NOISE"
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade=grade,
                weight=0.7,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
