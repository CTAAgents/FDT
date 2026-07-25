"""波动率因子单元测试"""
from __future__ import annotations

import numpy as np
import pytest

from data_adapter.factors.types import VolatilityResult
from data_adapter.factors.volatility import compute_volatility, _annualized_vol, _compute_atr, _compute_max_drawdown


def _make_kline_result(symbol: str, n: int = 100, base_price: float = 5000):
    """生成模拟 K 线数据（dict 格式）。"""
    np.random.seed(42)
    prices = base_price + np.cumsum(np.random.randn(n) * 20)
    prices = np.maximum(prices, base_price * 0.5)
    bars = []
    for i in range(n):
        bars.append({
            "date": f"20260101+{i:03d}",
            "open": float(prices[i]),
            "high": float(prices[i] + abs(np.random.randn() * 10)),
            "low": float(prices[i] - abs(np.random.randn() * 10)),
            "close": float(prices[i]),
            "volume": float(np.random.randint(1000, 10000)),
            "open_interest": float(np.random.randint(10000, 50000)),
        })
    return {"symbol": symbol, "bars": bars}


class TestVolatilityCalculator:
    """波动率因子计算测试。"""

    def test_compute_volatility_normal(self):
        """正常 K 线数据应返回完整结果。"""
        kline = {"RB": _make_kline_result("RB", n=100)}
        result = compute_volatility(["RB"], kline)
        assert "RB" in result
        r = result["RB"]
        assert r.data_grade == "PRIMARY"
        assert r.hv_20 is not None and r.hv_20 > 0
        assert r.skewness is not None
        assert r.atr is not None and r.atr > 0

    def test_insufficient_data(self):
        """K 线不足 20 根应返回 INSUFFICIENT_DATA。"""
        kline = {"RB": _make_kline_result("RB", n=10)}
        result = compute_volatility(["RB"], kline)
        assert result["RB"].data_grade == "INSUFFICIENT_DATA"

    def test_no_data(self):
        """无 K 线数据应返回 NO_DATA。"""
        result = compute_volatility(["RB"], {})
        assert result["RB"].data_grade == "NO_DATA"

    def test_annualized_vol(self):
        """年化波动率计算正确性。"""
        # 5% 日波动率 ≈ 79% 年化（sqrt(250) ≈ 15.8, 15.8*5 ≈ 79）
        returns = np.random.randn(30) * 0.01  # 1% 日波动
        hv = _annualized_vol(returns, 20, 250)
        # 年化约 1% * sqrt(250) = 15.8%
        assert 10 < hv < 30, f"HV20={hv}"

    def test_max_drawdown(self):
        """最大回撤计算。"""
        prices = np.array([100, 110, 120, 115, 105, 95, 100, 105])
        dd = _compute_max_drawdown(prices)
        # 从 120 到 95 = 20.8%
        assert 18 < dd < 23, f"max_drawdown={dd}%"

    def test_atr_calculation(self):
        """ATR 计算。"""
        highs = np.array([105, 112, 122, 118, 108, 98, 103])
        lows = np.array([95, 108, 116, 112, 102, 92, 97])
        closes = np.array([100, 110, 120, 115, 105, 95, 100])
        atr, atr_pct = _compute_atr(highs, lows, closes, period=5)
        assert atr is not None and atr > 0
        assert atr_pct is not None and atr_pct > 0
