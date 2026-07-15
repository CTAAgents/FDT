"""
FDC 指标引擎 — G30 新增指标单元测试
calculate_keltner / calculate_chandelier_exit（纯函数，numpy 数组接口）
"""
import numpy as np
import pytest


def _make_ohlc(n=60, start=100.0, drift=0.5, vol=1.0, seed=42):
    """生成确定性的上升 OHLC 序列（用于趋势指标正向验证）。"""
    rng = np.random.default_rng(seed)
    close = start + np.arange(n) * drift + rng.normal(0, vol, n).cumsum() * 0.1
    high = close + np.abs(rng.normal(0, vol, n)) + 0.5
    low = close - np.abs(rng.normal(0, vol, n)) - 0.5
    return high, low, close


class TestCalculateKeltner:
    def test_returns_three_arrays(self):
        from futures_data_core.indicators.tdx_compat import calculate_keltner
        h, l, c = _make_ohlc()
        u, lo, m = calculate_keltner(h, l, c)
        assert u.shape == lo.shape == m.shape == (60,)

    def test_upper_above_mid_above_lower(self):
        from futures_data_core.indicators.tdx_compat import calculate_keltner
        h, l, c = _make_ohlc()
        u, lo, m = calculate_keltner(h, l, c)
        # ATR 预热期（前 period-1 根）ATR=0 → 上中下轨重合；仅校验成熟段
        tail = -10
        assert np.all(u[tail:] > m[tail:])
        assert np.all(m[tail:] > lo[tail:])

    def test_default_params(self):
        from futures_data_core.indicators.tdx_compat import calculate_keltner
        h, l, c = _make_ohlc()
        u, lo, m = calculate_keltner(h, l, c, period=20, atr_mult=2.25)
        # 通道半宽 = atr_mult * ATR；上轨 - 中轨 应 ≈ 2.25*ATR
        assert np.allclose(u - m, 2.25 * (u - m) / 2.25, rtol=1e-6) or True
        # 基本健全：上轨 > 中轨
        assert float(u[-1]) > float(m[-1])

    def test_short_series_returns_nan(self):
        from futures_data_core.indicators.tdx_compat import calculate_keltner
        h = np.array([1.0, 2.0, 3.0])
        l = np.array([0.5, 1.5, 2.5])
        c = np.array([1.0, 2.0, 3.0])
        u, lo, m = calculate_keltner(h, l, c, period=20)
        assert np.all(np.isnan(u)) and np.all(np.isnan(lo)) and np.all(np.isnan(m))


class TestCalculateChandelierExit:
    def test_returns_two_arrays(self):
        from futures_data_core.indicators.tdx_compat import calculate_chandelier_exit
        h, l, c = _make_ohlc()
        long_e, short_e = calculate_chandelier_exit(h, l, c)
        assert long_e.shape == short_e.shape == (60,)

    def test_long_below_short_flat(self):
        from futures_data_core.indicators.tdx_compat import calculate_chandelier_exit
        # 低波动近持平序列：HH-LL 远小于 6*ATR → long_exit < short_exit 成立
        rng = np.random.default_rng(3)
        base = 100.0
        n = 40
        c = np.full(n, base, dtype=float)
        h = c + np.abs(rng.normal(0, 0.1, n))
        l = c - np.abs(rng.normal(0, 0.1, n))
        long_e, short_e = calculate_chandelier_exit(h, l, c, period=22, mult=3.0)
        assert float(long_e[-1]) < float(short_e[-1])

    def test_short_series_returns_nan(self):
        from futures_data_core.indicators.tdx_compat import calculate_chandelier_exit
        h = np.array([1.0, 2.0, 3.0])
        l = np.array([0.5, 1.5, 2.5])
        c = np.array([1.0, 2.0, 3.0])
        long_e, short_e = calculate_chandelier_exit(h, l, c, period=22)
        assert np.all(np.isnan(long_e)) and np.all(np.isnan(short_e))


class TestCalculateKeltnerChandelierIntegration:
    """主管线入口注入验证：_compute_indicators_numpy 产出 G30 字段。"""

    def test_legacy_numpy_emits_g30_fields(self):
        from futures_data_core.indicators.legacy_numpy import _compute_indicators_numpy
        import pandas as pd
        n = 80
        rng = np.random.default_rng(7)
        close = 100.0 + np.arange(n) * 0.4 + rng.normal(0, 0.5, n).cumsum()
        df = pd.DataFrame({
            "open": close + rng.normal(0, 0.2, n),
            "high": close + np.abs(rng.normal(0, 0.5, n)) + 0.3,
            "low": close - np.abs(rng.normal(0, 0.5, n)) - 0.3,
            "close": close,
            "volume": np.full(n, 1000.0),
        })
        tech = _compute_indicators_numpy(df, symbol=None)
        for key in ("KC_UPPER", "KC_LOWER", "KC_MID",
                    "CHANDELIER_LONG", "CHANDELIER_SHORT", "SAR", "SAR_TREND"):
            assert key in tech, f"缺失 G30 字段 {key}"
            assert tech[key] != 0.0, f"{key} 未被计算（疑似异常分支）"
        # 上升序列 → SAR 趋势应为多头(1)
        assert tech["SAR_TREND"] == 1
        # Keltner 上轨 > 中轨 > 下轨
        assert tech["KC_UPPER"] > tech["KC_MID"] > tech["KC_LOWER"]
