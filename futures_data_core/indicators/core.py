"""技术指标计算 [INDEPENDENT]。

纯 numpy 实现，无 LLM 依赖、无网络依赖。所有函数接收 ``close`` /
``high`` / ``low`` / ``volume`` 数组（``list`` 或 ``numpy.ndarray``），
返回与输入等长、前导填充 ``NaN`` 的 ``numpy.ndarray``（标准期货软件约定）。

设计原则：
    - 输入过短（不足以计算）时返回全 ``NaN`` 数组，绝不抛错（除显式参数错误）。
    - 纯函数，无副作用，便于单元测试与缓存。
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "sma", "ema", "rsi", "macd", "boll", "kdj", "atr", "cci",
    "williams_r", "obv", "adx", "bias", "roc", "momentum", "stddev",
    "volume_ma", "compute_indicators", "INDICATOR_NAMES",
]

INDICATOR_NAMES = [
    "MA", "EMA", "RSI", "MACD", "BOLL", "KDJ", "ATR", "CCI",
    "WILLIAMS_R", "OBV", "ADX", "BIAS", "ROC", "MOM", "STDDEV", "VOL_MA",
]


def _as_float_array(x) -> np.ndarray:
    """将输入转换为 float64 数组。"""
    return np.asarray(x, dtype=np.float64)


def sma(close, period: int = 20) -> np.ndarray:
    """简单移动平均 (MA)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period or period <= 0:
        return out
    cum = np.cumsum(close)
    out[period - 1:] = (cum[period - 1:] - np.concatenate(([0.0], cum[:-period]))) / period
    return out


def ema(close, period: int = 12) -> np.ndarray:
    """指数移动平均 (EMA)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period or period <= 0:
        return out
    alpha = 2.0 / (period + 1)
    seed = np.mean(close[:period])
    out[period - 1] = seed
    for i in range(period, n):
        out[i] = alpha * close[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close, period: int = 14) -> np.ndarray:
    """相对强弱指标 (RSI, Wilder 平滑)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n <= period:
        return out
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)
    # 初始均值
    avg_gain[period] = np.mean(gain[:period])
    avg_loss[period] = np.mean(loss[:period])
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i - 1]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss[period:] == 0, np.inf, avg_gain[period:] / avg_loss[period:])
    rsi_vals = np.where(rs == np.inf, 100.0, 100.0 - 100.0 / (1.0 + rs))
    out[period:] = rsi_vals
    return out


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 指标，返回 ``(dif, dea, hist)`` 三个等长数组。"""
    close = _as_float_array(close)
    n = close.size
    dif = np.full(n, np.nan)
    dea = np.full(n, np.nan)
    hist = np.full(n, np.nan)
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    valid_from = max(fast, slow) - 1
    if n <= valid_from:
        return dif, dea, hist
    dif[valid_from:] = ema_fast[valid_from:] - ema_slow[valid_from:]
    # DEA = EMA(signal) of DIF over valid region
    valid = dif[valid_from:]
    dea_region = ema(valid, signal)
    dea[valid_from:] = dea_region
    hist[valid_from:] = 2.0 * (dif[valid_from:] - dea[valid_from:])
    return dif, dea, hist


def boll(close, period: int = 20, num_std: float = 2.0):
    """布林带，返回 ``(mid, upper, lower)``。"""
    close = _as_float_array(close)
    mid = sma(close, period)
    n = close.size
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    if n < period:
        return mid, upper, lower
    std = np.full(n, np.nan)
    cum = np.cumsum(close)
    cumsq = np.cumsum(close ** 2)
    for i in range(period - 1, n):
        s = cum[i] - (cum[i - period] if i - period >= 0 else 0.0)
        sq = cumsq[i] - (cumsq[i - period] if i - period >= 0 else 0.0)
        mean = s / period
        var = sq / period - mean ** 2
        std[i] = np.sqrt(max(var, 0.0))
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def kdj(high, low, close, n: int = 9, m1: int = 3, m2: int = 3):
    """随机指标 KDJ，返回 ``(k, d, j)``。"""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    nsize = close.size
    k = np.full(nsize, np.nan)
    d = np.full(nsize, np.nan)
    j = np.full(nsize, np.nan)
    if nsize < n:
        return k, d, j
    rsv = np.full(nsize, np.nan)
    for i in range(n - 1, nsize):
        hh = np.max(high[i - n + 1:i + 1])
        ll = np.min(low[i - n + 1:i + 1])
        if hh == ll:
            rsv[i] = 50.0
        else:
            rsv[i] = (close[i] - ll) / (hh - ll) * 100.0
    k[n - 1] = 50.0
    for i in range(n, nsize):
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv[i]
    d[n - 1] = 50.0
    for i in range(n, nsize):
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i]
    j[n - 1:] = 3 * k[n - 1:] - 2 * d[n - 1:]
    return k, d, j


def atr(high, low, close, period: int = 14) -> np.ndarray:
    """平均真实波幅 (ATR)。"""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < 2:
        return out
    tr = np.full(n, np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    if n < period + 1:
        return out
    out[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def cci(high, low, close, period: int = 14) -> np.ndarray:
    """顺势指标 (CCI)。"""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period:
        return out
    tp = (high + low + close) / 3.0
    ma = sma(tp, period)
    std = np.full(n, np.nan)
    cum = np.cumsum(tp)
    cumsq = np.cumsum(tp ** 2)
    for i in range(period - 1, n):
        s = cum[i] - (cum[i - period] if i - period >= 0 else 0.0)
        sq = cumsq[i] - (cumsq[i - period] if i - period >= 0 else 0.0)
        mean = s / period
        var = sq / period - mean ** 2
        std[i] = np.sqrt(max(var, 0.0))
    denom = 0.015 * std
    valid = denom != 0
    out[valid] = (tp[valid] - ma[valid]) / denom[valid]
    return out


def williams_r(high, low, close, period: int = 14) -> np.ndarray:
    """威廉指标 (%R)。"""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period:
        return out
    for i in range(period - 1, n):
        hh = np.max(high[i - period + 1:i + 1])
        ll = np.min(low[i - period + 1:i + 1])
        if hh == ll:
            out[i] = -50.0
        else:
            out[i] = (hh - close[i]) / (hh - ll) * -100.0
    return out


def obv(close, volume) -> np.ndarray:
    """能量潮 (OBV)。"""
    close = _as_float_array(close)
    volume = _as_float_array(volume)
    n = close.size
    out = np.full(n, np.nan)
    if n == 0:
        return out
    out[0] = 0.0
    for i in range(1, n):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def _trure_range_dir(high, low, close):
    """返回 +DM, -DM, TR 序列（用于 ADX）。"""
    n = close.size
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return plus_dm, minus_dm, tr


def adx(high, low, close, period: int = 14) -> np.ndarray:
    """平均趋向指数 (ADX)。"""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    plus_dm, minus_dm, tr = _trure_range_dir(high, low, close)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    atr_v = np.full(n, np.nan)
    atr_v[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, n):
        atr_v[i] = (atr_v[i - 1] * (period - 1) + tr[i]) / period
    for i in range(period, n):
        if atr_v[i] != 0:
            plus_di[i] = 100.0 * _smooth(plus_dm, atr_v, i, period) / atr_v[i]
            minus_di[i] = 100.0 * _smooth(minus_dm, atr_v, i, period) / atr_v[i]
    dx = np.full(n, np.nan)
    for i in range(period, n):
        denom = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if denom == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / denom
    start = period * 2 - 1
    if n <= start:
        return out
    out[start] = np.mean(dx[period:start + 1])
    for i in range(start + 1, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def _smooth(dm, atr_v, i, period):
    """Wilder 平滑 DM。"""
    if i == period:
        return np.sum(dm[1:period + 1])
    return (atr_v[i - 1] / atr_v[i]) * _smooth(dm, atr_v, i - 1, period) if atr_v[i] != 0 else 0.0


def bias(close, period: int = 20) -> np.ndarray:
    """乖离率 (BIAS)。"""
    close = _as_float_array(close)
    ma = sma(close, period)
    n = close.size
    out = np.full(n, np.nan)
    valid = ~np.isnan(ma) & (ma != 0)
    out[valid] = (close[valid] - ma[valid]) / ma[valid] * 100.0
    return out


def roc(close, period: int = 12) -> np.ndarray:
    """变动率 (ROC)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    for i in range(period, n):
        if close[i - period] != 0:
            out[i] = (close[i] - close[i - period]) / close[i - period] * 100.0
    return out


def momentum(close, period: int = 10) -> np.ndarray:
    """动量指标 (MOM)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    for i in range(period, n):
        out[i] = close[i] - close[i - period]
    return out


def stddev(close, period: int = 20) -> np.ndarray:
    """标准差 (STDDEV)。"""
    close = _as_float_array(close)
    n = close.size
    out = np.full(n, np.nan)
    if n < period:
        return out
    cum = np.cumsum(close)
    cumsq = np.cumsum(close ** 2)
    for i in range(period - 1, n):
        s = cum[i] - (cum[i - period] if i - period >= 0 else 0.0)
        sq = cumsq[i] - (cumsq[i - period] if i - period >= 0 else 0.0)
        mean = s / period
        var = sq / period - mean ** 2
        out[i] = np.sqrt(max(var, 0.0))
    return out


def volume_ma(volume, period: int = 5) -> np.ndarray:
    """成交量移动平均 (VOL_MA)。"""
    return sma(volume, period)


def compute_indicators(df, indicators: list[str] | str = "all") -> dict:
    """批量计算技术指标。

    Args:
        df: 含 ``open/high/low/close/volume`` 键的类 dict 结构
            （支持 pandas.DataFrame 或 dict of arrays）。
        indicators: 指标名称列表；``"all"`` 计算 :data:`INDICATOR_NAMES` 全部。

    Returns:
        映射 ``指标名 -> 计算结果``。
    """
    if indicators == "all":
        indicators = INDICATOR_NAMES
    if isinstance(indicators, str):
        indicators = [indicators]

    def col(name: str):
        if hasattr(df, "get"):
            return _as_float_array(df.get(name))
        # pandas DataFrame
        return _as_float_array(getattr(df, name))

    close = col("close")
    high = col("high")
    low = col("low")
    volume = col("volume")

    results: dict = {}
    for name in indicators:
        nm = name.upper()
        if nm == "MA":
            results["MA"] = sma(close)
        elif nm == "EMA":
            results["EMA"] = ema(close)
        elif nm == "RSI":
            results["RSI"] = rsi(close)
        elif nm == "MACD":
            results["MACD"] = macd(close)
        elif nm == "BOLL":
            results["BOLL"] = boll(close)
        elif nm == "KDJ":
            results["KDJ"] = kdj(high, low, close)
        elif nm == "ATR":
            results["ATR"] = atr(high, low, close)
        elif nm == "CCI":
            results["CCI"] = cci(high, low, close)
        elif nm == "WILLIAMS_R":
            results["WILLIAMS_R"] = williams_r(high, low, close)
        elif nm == "OBV":
            results["OBV"] = obv(close, volume)
        elif nm == "ADX":
            results["ADX"] = adx(high, low, close)
        elif nm == "BIAS":
            results["BIAS"] = bias(close)
        elif nm == "ROC":
            results["ROC"] = roc(close)
        elif nm == "MOM":
            results["MOM"] = momentum(close)
        elif nm == "STDDEV":
            results["STDDEV"] = stddev(close)
        elif nm == "VOL_MA":
            results["VOL_MA"] = volume_ma(volume)
        else:
            raise ValueError(f"未知指标: {name!r}")
    return results
