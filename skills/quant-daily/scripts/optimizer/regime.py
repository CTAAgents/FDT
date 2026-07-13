"""市场制度感知模块 — v2.0（FDC 直驱，不再依赖 MSA）

功能:
  1. compute_symbol_regime(symbol) → 单品种 regime
  2. compute_market_regime() → 全市场制度（从代表品种加权聚合）

三步判断:
  1. ADX 分位: 当前 ADX 在其 N 日序列中的百分位（高=趋势市）
  2. 波动率 regime: ATR% 相对均值比值（高=高波动）
  3. 方向斜率: 近期斜率符号
"""

import numpy as np

# ── 代表品种（覆盖黑色/能源/有色/贵金属/农产品，反映全市场状态）──
_MARKET_BASKET = ["rb", "sc", "cu", "au", "c", "MA", "TA"]

# ── FDC 内核（同步包装） ──
def _fdc_kline(symbol: str, days: int = 400, period: str = "daily") -> dict:
    """从 FDC 同步获取 K 线数据"""
    import asyncio
    from futures_data_core import get_kline

    try:
        payload = asyncio.run(get_kline(symbol, period=period, days=days))
        if isinstance(payload, dict):
            data = payload.get("data") if payload.get("success") else payload.get("bars", [])
            if data:
                return {"success": True, "data": data}
        return {"success": False, "data": []}
    except Exception:
        return {"success": False, "data": []}


def _adx_and_atr(close, high, low, volume=None):
    """轻量计算 ADX 当前值 + ATR%，不需要完整的指标引擎"""
    n = len(close)
    if n < 20:
        return None, None
    # 简化 ATR: 平均真实波幅 / 收盘价%
    tr = []
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr.append(max(hl, hc, lc))
    atr = sum(tr[-14:]) / min(14, len(tr)) if tr else 0
    atr_pct = (atr / close[-1] * 100) if close[-1] > 0 else 0
    return atr, atr_pct


def compute_symbol_regime(symbol: str, period: str = "daily") -> dict:
    """计算单品种 regime"""
    kd = _fdc_kline(symbol, period=period)
    if not kd.get("success"):
        return {"symbol": symbol, "regime": "unknown", "weight": 1.0}

    dlist = kd["data"]
    if len(dlist) < 30:
        return {"symbol": symbol, "regime": "unknown", "weight": 1.0}

    closes = np.array([float(r.get("close", 0)) for r in dlist])
    highs = np.array([float(r.get("high", 0)) for r in dlist])
    lows = np.array([float(r.get("low", 0)) for r in dlist])
    vols = np.array([float(r.get("volume", 0)) for r in dlist])

    from indicators.calc_core import calculate_tdx_compatible

    # 取最近 60 根计算 ADX 序列
    recent = min(60, len(dlist))
    adx_series, atr_pct_series = [], []
    for i in range(20, recent):
        ind = calculate_tdx_compatible(
            high=highs[:i + 1], low=lows[:i + 1], close=closes[:i + 1],
            open_price=closes[:i + 1], volume=vols[:i + 1],
        )
        if ind.get("adx") is not None:
            adx_series.append(float(ind["adx"]))
        if ind.get("atr") is not None and closes[i] > 0:
            atr_pct_series.append(float(ind["atr"]) / closes[i] * 100)

    if not adx_series:
        return {"symbol": symbol, "regime": "unknown", "weight": 1.0}

    adx_now = adx_series[-1]
    adx_pctl = sum(1 for v in adx_series if v <= adx_now) / len(adx_series)

    if atr_pct_series:
        mean_vol = sum(atr_pct_series) / len(atr_pct_series)
        vol_ratio = (atr_pct_series[-1] / mean_vol) if mean_vol > 0 else 1.0
    else:
        vol_ratio = 1.0

    slope = float(np.polyfit(range(len(closes)), closes, 1)[0]) if len(closes) > 1 else 0.0

    if vol_ratio >= 1.5:
        regime, weight = "volatile", 0.6
    elif adx_pctl >= 0.6 and slope > 0:
        regime, weight = "trend_up", 1.4
    elif adx_pctl >= 0.6 and slope < 0:
        regime, weight = "trend_down", 1.4
    elif adx_pctl < 0.4:
        regime, weight = "range", 0.7
    else:
        regime, weight = "mixed", 1.0

    return {
        "symbol": symbol,
        "regime": regime,
        "weight": weight,
        "adx": round(adx_now, 1),
        "adx_pctl": round(adx_pctl, 2),
        "vol_ratio": round(vol_ratio, 2),
        "slope": round(slope, 4),
        "n_bars": len(dlist),
    }


def compute_market_regime(period: str = "daily") -> dict:
    """从代表品种加权聚合全市场制度

    返回:
      {
        "regime": "trend_up" | "trend_down" | "range" | "volatile" | "mixed" | "unknown",
        "weight": 0.6~1.4 (乘数, 供下游信号评分用),
        "details": [品种级 regime 明细],
        "basket_size": 代表品种数,
        "success_count": 成功计算数,
      }
    """
    details = []
    for sym in _MARKET_BASKET:
        r = compute_symbol_regime(sym, period)
        if r["regime"] != "unknown":
            details.append(r)

    if not details:
        return {"regime": "unknown", "weight": 1.0, "details": [], "basket_size": len(_MARKET_BASKET), "success_count": 0}

    # 投票制: 每种 regime 计数
    counts = {}
    for d in details:
        r = d["regime"]
        counts[r] = counts.get(r, 0) + 1

    # 找出最多票
    max_count = max(counts.values())
    winners = [r for r, c in counts.items() if c == max_count]

    # 平票 → mixed
    if len(winners) > 1:
        # 如果有 trend 在 winner 里，优先 trend
        for w in ("trend_up", "trend_down"):
            if w in winners:
                regime = w
                break
        else:
            regime = "mixed"
    else:
        regime = winners[0]

    # 平均权重
    avg_weight = sum(d["weight"] for d in details) / len(details)

    # volatility 检测优先: 如果有品种 volatile 且数量 >= 1/3
    if counts.get("volatile", 0) >= len(details) // 3:
        regime = "volatile"
        avg_weight = min(avg_weight, 0.8)

    return {
        "regime": regime,
        "weight": round(avg_weight, 2),
        "details": details,
        "basket_size": len(_MARKET_BASKET),
        "success_count": len(details),
    }
