"""日频 Regime 轻量指标 — 用于信号权重, 不参与品种纳入/剔除。

设计意图:
  趋势跟踪策略"当下是否值得跟"应由当前市况(regime)决定, 而非每周重写监测
  宇宙。本模块用低成本指标估算品种所处 regime, 输出权重乘数(0.5~1.5),
  供 scan_monitored 后续乘到信号总分。

指标(均可用本地/已有数据计算, 不触发全量 WF):
  - ADX 长期分位: 当前 ADX 在自身 N 日序列中的百分位(高=趋势市)
  - 波动率 regime: 当前 ATR% 相对 N 日均值的比值(高=高波动市)
  - 价格趋势斜率: 近 M 日回归斜率符号
regime ∈ {trend_up, trend_down, range, volatile, mixed, unknown}
weight: 趋势市给高权重, range/volatile 给低权重
"""

import math

import numpy as np


def _percentile(series, x):
    n = len(series)
    if n == 0:
        return 0.5
    return sum(1 for v in series if v <= x) / n


def compute_regime(adx_series, atr_pct_series, slope):
    """输入序列与斜率, 返回 (regime, weight)。

    adx_series:    近期 ADX 值序列
    atr_pct_series: 近期 ATR/收盘价*100 序列
    slope:          近期收盘价回归斜率(正=上行, 负=下行)
    """
    if not adx_series:
        return "unknown", 1.0
    adx_now = adx_series[-1]
    adx_pctl = _percentile(adx_series, adx_now)
    if atr_pct_series:
        mean_vol = sum(atr_pct_series) / len(atr_pct_series)
        vol_ratio = (atr_pct_series[-1] / mean_vol) if mean_vol > 0 else 1.0
    else:
        vol_ratio = 1.0
    if adx_pctl >= 0.6 and slope > 0:
        return "trend_up", 1.4
    if adx_pctl >= 0.6 and slope < 0:
        return "trend_down", 1.4
    if vol_ratio >= 1.5:
        return "volatile", 0.6
    if adx_pctl < 0.4:
        return "range", 0.7
    return "mixed", 1.0


def build_regime_from_kline(symbol, period="daily", bars=60):
    """从本地/多源拉取最近 bars 根K线, 计算 ADX/ATR% 序列与价格斜率。

    返回 (adx_series, atr_pct_series, slope)。
    """
    from data.multi_source_adapter import MultiSourceAdapter
    from scan_all import collect_kline_for_all
    from indicators.calc_core import calculate_tdx_compatible

    adapter = MultiSourceAdapter()
    kd = collect_kline_for_all(adapter, [(symbol, symbol)], days=400,
                               min_bars=80, period=period)
    _, dlist = kd.get(symbol, (None, []))
    if len(dlist) < 20:
        return [], [], 0.0
    closes = np.array([float(r["close"]) for r in dlist])
    highs = np.array([float(r["high"]) for r in dlist])
    lows = np.array([float(r["low"]) for r in dlist])
    opens = np.array([float(r["open"]) for r in dlist])
    vols = np.array([float(r.get("volume", 0)) for r in dlist])

    adx_series, atr_pct_series = [], []
    for i in range(20, len(closes)):
        ind = calculate_tdx_compatible(
            high=highs[:i + 1], low=lows[:i + 1], close=closes[:i + 1],
            open_price=opens[:i + 1], volume=vols[:i + 1],
        )
        if ind.get("adx") is not None:
            adx_series.append(float(ind["adx"]))
        if ind.get("atr") is not None and closes[i] > 0:
            atr_pct_series.append(float(ind["atr"]) / closes[i] * 100)

    slope = float(np.polyfit(range(len(closes)), closes, 1)[0]) if len(closes) > 1 else 0.0
    return adx_series, atr_pct_series, slope
