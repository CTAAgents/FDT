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

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal, format_reason
from .arbitrage_strategy import CROSS_VARIETY_PAIRS
from .spread_reversion_strategy import kalman_filter_ou


# ── 阈值配置 ──
HURST_MAX = 0.75          # 任一腿 Hurst 超过此值（强趋势型）→ 跳过该配对。
                            # 注：R/S 法在小样本上有 ≈+0.12 上偏（i.i.d. 收益实测≈0.62、
                            # 随机游走 diff≈0.68），故阈值取 0.75 仅跳过强趋势（动量收益≈0.84），
                            # 随机游走腿（≈0.68）正常通过，避免误杀多数期货配对。
Z_ENTRY = 2.0             # 残差 Z-score 绝对值超过 → 出信号
MIN_BARS = 60             # 协整/ Hurst 所需最小历史 bar 数
HALF_LIFE_MAX = 120.0     # OU 半衰期上限（日），超过视为弱回归不放大权重
VR_Q = 2                  # 方差比聚合步长（q=2 最灵敏短周期均值回归）
VR_Z_MAX = 1.96           # 方差比 z 统计量 |z| > 1.96 → 拒绝随机游走（95% 置信）
                          # z < -1.96 → 显著均值回归（VR<1）；z > 1.96 → 显著趋势（VR>1）


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


def variance_ratio_test(close: Any, q: int = 2) -> tuple[float, float]:
    """Lo-MacKinlay (1988) 方差比检验（异方差稳健）。

    对价格对数收益 r_t = ln(P_t/P_{t-1})，计算：
      VR(q) = 1/q · Var(r_t(q)) / Var(r_t)，其中 r_t(q) = sum_{i=0}^{q-1} r_{t-i}
    H0(随机游走): VR=1 → z≈0
    H1(均值回归): VR<1 → z<0
    H1(趋势): VR>1 → z>0

    Args:
        close: 收盘价序列。
        q: 聚合步长（default=2，对短周期均值回归最灵敏）。

    Returns:
        (vr_ratio, z_stat)：VR 比值和异方差稳健 z 统计量。
        数据不足 2q+2 返回 (1.0, 0.0)。
    """
    x = np.asarray(close, dtype=float)
    if len(x) < 2 * q + 2:
        return 1.0, 0.0
    log_r = np.diff(np.log(x))
    n = len(log_r)

    # 单期收益方差
    var1 = float(np.var(log_r, ddof=1))
    if var1 <= 0:
        return 1.0, 0.0

    # q期聚合收益（非重叠）
    nq = n // q
    rq = np.array([np.sum(log_r[i * q:(i + 1) * q]) for i in range(nq)])
    varq = float(np.var(rq, ddof=1))
    vr = varq / (q * var1)

    # 异方差稳健方差 (Lo-MacKinlay 1988 eq.16)
    theta = 0.0
    for j in range(1, q):
        delta = q - j
        num = 0.0
        denom = 0.0
        for t in range(j, n):
            num += (log_r[t] * log_r[t - j]) ** 2
            denom += (log_r[t] ** 2) ** 2
        if denom > 0:
            theta_j = (num / denom) * (delta / q) ** 2
            theta += theta_j
    phi = 2 * theta / q
    if phi <= 0:
        return vr, 0.0
    zstat = (vr - 1.0) / float(np.sqrt(phi))
    return round(vr, 4), round(zstat, 4)


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

            # ── 方差比前置门禁（G38）：两腿均拒绝随机游走且偏向趋势→跳过 ──
            # 若任一条腿 VR z<-1.96（单腿即显著均值回归），反而增强配对信号，放行
            _, vr_za = variance_ratio_test(ya, q=VR_Q)
            _, vr_zb = variance_ratio_test(yb, q=VR_Q)
            if vr_za > VR_Z_MAX and vr_zb > VR_Z_MAX:
                continue  # 两腿皆趋势型随机游走（VR>1），不适合配对回归

            # ── Engle-Granger 协整残差 ──
            resid = _engle_granger_residual(ya, yb)
            if resid is None:
                continue

            # ── Kalman 自适应 z 偏离（G37 Phase 2）──
            kf = kalman_filter_ou(resid)
            z = kf["z_score"]
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
                "kf_state_sigma": round(float(kf["state_sigma"][-1]), 4),
                "kf_innov_var": round(kf["last_innovation_var"], 4),
                "vr_z_a": round(vr_za, 3), "vr_z_b": round(vr_zb, 3),
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
            # reason：子信号身份 + 关键条件，供辩论环节识别"为什么选这个信号"
            _m = s.meta
            _metrics = {"z": round(_m.get("z_score", 0), 2)}
            if _m.get("pair_a"):
                _metrics["pair"] = f"{_m['pair_a']}-{_m['pair_b']}"
            if _m.get("leg"):
                _metrics["leg"] = _m["leg"]
            ss.reason = format_reason(
                s.signal_type, s.direction, grade,
                metrics=_metrics, strength=round(raw, 2))
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
