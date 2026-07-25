"""跨品种价差因子单元测试"""
from __future__ import annotations

import numpy as np
import pytest

from data_adapter.factors.types import CrossSpreadResult
from data_adapter.factors.cross_spread import compute_cross_spreads, _compute_percentile, _detect_trend


def _make_kline_result(symbol: str, n: int = 100, base_price: float = 5000, seed: int = 42):
    """生成模拟 K 线数据。"""
    np.random.seed(seed)
    prices = base_price + np.cumsum(np.random.randn(n) * 10)
    prices = np.maximum(prices, base_price * 0.5)
    bars = []
    for i in range(n):
        bars.append({
            "date": f"20260101+{i:03d}",
            "open": float(prices[i]),
            "high": float(prices[i] + 5),
            "low": float(prices[i] - 5),
            "close": float(prices[i]),
            "volume": float(1000),
            "open_interest": float(10000),
        })
    return {"symbol": symbol, "bars": bars}


class TestCrossSpread:
    """跨品种价差计算测试。"""

    def test_no_valid_pairs(self):
        """品种不在配置中对时返回空。"""
        result = compute_cross_spreads(
            ["FU"], {}, [("RB", "HC")]
        )
        assert len(result) == 0

    def test_insufficient_data(self):
        """K 线不足 30 根时跳过。"""
        kdata = {
            "RB": _make_kline_result("RB", n=20, seed=1),
            "HC": _make_kline_result("HC", n=20, seed=2),
        }
        result = compute_cross_spreads(
            ["RB", "HC"], kdata, [("RB", "HC")]
        )
        assert len(result) == 0

    def test_normal_calculation(self):
        """正常计算应返回完整结果。"""
        kdata = {
            "RB": _make_kline_result("RB", n=100, seed=1),
            "HC": _make_kline_result("HC", n=100, seed=2),
        }
        result = compute_cross_spreads(
            ["RB", "HC"], kdata, [("RB", "HC")]
        )
        assert len(result) == 1
        cs = result[0]
        assert cs.pair == ("RB", "HC")
        assert cs.data_grade == "PRIMARY"
        assert cs.zscore != 0
        assert 0 <= cs.percentile <= 100

    def test_percentile(self):
        """百分位计算正确性。"""
        arr = np.array([100, 110, 120, 130, 140, 150])
        p = _compute_percentile(arr, 125)
        assert p == 50.0, f"125 应在 50% 位: {p}"

    def test_trend_detection(self):
        """趋势判断。"""
        # 上升趋势
        rising = np.array([100, 105, 110, 115, 120])
        assert _detect_trend(rising, 5) == "widening"
        # 下降趋势
        falling = np.array([120, 115, 110, 105, 100])
        assert _detect_trend(falling, 5) == "narrowing"
        # 稳定
        stable = np.array([110, 111, 110, 109, 110])
        assert _detect_trend(stable, 5) == "stable"
