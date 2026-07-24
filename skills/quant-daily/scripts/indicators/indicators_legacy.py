"""遗留 numpy 指标 — 已迁移至 data_adapter.indicators（FDC 已退役）。

本文件为兼容 shim：``_compute_indicators_numpy`` 经 re-export 转发自
``data_adapter.indicators``。``assess_trend_maturity`` 为本地简化实现。
"""

from data_adapter.indicators import compute_indicators as _compute_indicators_numpy


def assess_trend_maturity(kline_data) -> dict:
    """简化的趋势成熟度评估（FDC 已退役，轻量本地实现）。

    Args:
        kline_data: K 线数据（list[dict] 或类似结构）。

    Returns:
        dict 含 maturity / confidence 字段。
    """
    try:
        tech = _compute_indicators_numpy(kline_data)
        adx = tech.get("ADX", 0) or 0
        ma20_slope = tech.get("MA20_SLOPE", 0) or 0
        if adx > 25 and abs(ma20_slope) > 0.01:
            maturity = "mature"
            confidence = min(adx / 50, 1.0)
        elif adx > 20:
            maturity = "developing"
            confidence = adx / 40
        else:
            maturity = "immature"
            confidence = 0.2
        return {"maturity": maturity, "confidence": confidence, "adx": adx, "ma20_slope": ma20_slope}
    except Exception:
        return {"maturity": "unknown", "confidence": 0.0, "_note": "assess_trend_maturity 本地简化实现"}


__all__ = ["_compute_indicators_numpy", "assess_trend_maturity"]
