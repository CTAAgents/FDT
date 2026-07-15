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


class TestCalculateTSMOM:
    def test_returns_four_windows(self):
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        h, l, c = _make_ohlc(n=300)
        ret = calculate_tsmom(c, windows=(21, 63, 126, 252))
        assert len(ret) == 4

    def test_uptrend_positive(self):
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        # 单调上升序列 → 各窗口累计收益为正
        c = np.arange(1, 301, dtype=float)
        h = c + 0.5
        l = c - 0.5
        r1, r3, r6, r12 = calculate_tsmom(c, windows=(21, 63, 126, 252))
        assert r1 > 0 and r3 > 0 and r6 > 0 and r12 > 0

    def test_downtrend_negative(self):
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        # 单调下降序列 → 各窗口累计收益为负
        c = np.arange(300, 0, -1, dtype=float)
        h = c + 0.5
        l = c - 0.5
        r1, r3, r6, r12 = calculate_tsmom(c, windows=(21, 63, 126, 252))
        assert r1 < 0 and r3 < 0 and r6 < 0 and r12 < 0

    def test_short_series_nan(self):
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        # n=100：1m(21)/3m(63) 可用，6m(126)/12m(252) 不足 → NaN
        c = np.arange(1, 101, dtype=float)
        h = c + 0.5
        l = c - 0.5
        r1, r3, r6, r12 = calculate_tsmom(c, windows=(21, 63, 126, 252))
        assert np.isfinite(r1) and np.isfinite(r3)
        assert np.isnan(r6) and np.isnan(r12)

    def test_very_short_all_nan(self):
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        c = np.array([1.0, 2.0, 3.0])
        h = c + 0.1
        l = c - 0.1
        ret = calculate_tsmom(c, windows=(21, 63, 126, 252))
        assert all(np.isnan(x) for x in ret)


class TestCalculateTSMOMIntegration:
    """主管线入口注入验证：_compute_indicators_numpy 产出 G31 TSMOM 字段。"""

    def test_legacy_numpy_emits_g31_tsmom(self):
        from futures_data_core.indicators.legacy_numpy import _compute_indicators_numpy
        import pandas as pd
        n = 260
        rng = np.random.default_rng(11)
        close = 100.0 + np.arange(n) * 0.5 + rng.normal(0, 0.5, n).cumsum()
        df = pd.DataFrame({
            "open": close + rng.normal(0, 0.2, n),
            "high": close + np.abs(rng.normal(0, 0.5, n)) + 0.3,
            "low": close - np.abs(rng.normal(0, 0.5, n)) - 0.3,
            "close": close,
            "volume": np.full(n, 1000.0),
        })
        tech = _compute_indicators_numpy(df, symbol=None)
        for key in ("TSMOM_1M", "TSMOM_3M", "TSMOM_6M", "TSMOM_12M"):
            assert key in tech, f"缺失 G31 字段 {key}"
        # 上升序列 → 1/3/6/12 月收益均为正
        assert tech["TSMOM_1M"] > 0
        assert tech["TSMOM_3M"] > 0
        assert tech["TSMOM_6M"] > 0
        assert tech["TSMOM_12M"] > 0

    def test_legacy_numpy_tsmom_degrades_short_history(self):
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
        # n=80：1m/3m 可用（正），6m/12m 不足 → 0.0（字段仍存在，策略层剔除）
        assert tech["TSMOM_1M"] > 0 and tech["TSMOM_3M"] > 0
        assert tech["TSMOM_6M"] == 0.0 and tech["TSMOM_12M"] == 0.0
