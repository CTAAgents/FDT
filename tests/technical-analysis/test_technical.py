# -*- coding: utf-8 -*-
"""technical-analysis 测试"""

import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from scripts.trend_analysis import analyze_trend, check_momentum
    _HAS_MODULE = True
except ImportError:
    _HAS_MODULE = False
    pytest.skip("module scripts.trend_analysis not available", allow_module_level=True)

from scripts.divergence import check_divergence
from scripts.flow_analysis import analyze_seat_flow, estimate_long_short_ratio
from scripts.volume_price import analyze_volume_price, check_fake_breakout


class TestTrendAnalysis(unittest.TestCase):
    def test_bull_alignment(self):
        r = analyze_trend("RB", {"ma20": 3500, "ma60": 3400, "ma250": 3300, "adx": 45})
        self.assertEqual(r["ma_alignment"], "多头排列")
        self.assertEqual(r["adx_strength"], "强趋势")

    def test_bear_alignment(self):
        r = analyze_trend("RB", {"ma20": 3000, "ma60": 3200, "ma250": 3300, "adx": 50})
        self.assertEqual(r["ma_alignment"], "空头排列")

    def test_no_data(self):
        r = analyze_trend("RB")
        self.assertIn("待读取", r["ma_alignment"])


class TestMomentum(unittest.TestCase):
    def test_overbought(self):
        r = check_momentum("RB", rsi=75, cci=250)
        self.assertEqual(r["rsi_status"], "超买区")
        self.assertEqual(r["cci_status"], "极度偏高")

    def test_oversold(self):
        r = check_momentum("RB", rsi=25, cci=-250)
        self.assertEqual(r["rsi_status"], "超卖区")
        self.assertEqual(r["cci_status"], "极度偏低")

    def test_neutral(self):
        r = check_momentum("RB", rsi=50, cci=50)
        self.assertEqual(r["rsi_status"], "中性区")
        self.assertEqual(r["cci_status"], "中性")


class TestVolumePrice(unittest.TestCase):
    def test_bullish_oi_price(self):
        r = analyze_volume_price(oi_change_pct=5, price_change_pct=3)
        self.assertIn("多头主动加仓", r["oi_price_interpretation"])

    def test_bearish_oi_price(self):
        r = analyze_volume_price(oi_change_pct=5, price_change_pct=-3)
        self.assertIn("空头主动加仓", r["oi_price_interpretation"])

    def test_high_volume(self):
        r = analyze_volume_price(volume_ratio=2.5)
        self.assertEqual(r["volume_status"], "显著放量")


class TestFakeBreakout(unittest.TestCase):
    def test_true_breakout(self):
        r = check_fake_breakout("up", 2.5, True)
        self.assertFalse(r["is_fake"])

    def test_fake_breakout_low_volume(self):
        r = check_fake_breakout("up", 1.2, False)
        self.assertTrue(r["is_fake"])
        self.assertIn("缩量", r["reason"])

    def test_down_breakout_real(self):
        r = check_fake_breakout("down", 2.5, True)
        self.assertFalse(r["is_fake"])


class TestDivergence(unittest.TestCase):
    def test_no_divergence(self):
        r = check_divergence(price_trend="up", volume_trend="up", macd_trend="up")
        self.assertEqual(r["severity"], "无")

    def test_volume_price_divergence(self):
        r = check_divergence(price_trend="up", volume_trend="down")
        self.assertGreater(len(r["divergences"]), 0)
        self.assertIn("价量背离", str(r["divergences"]))

    def test_macd_divergence(self):
        r = check_divergence(price_trend="up", macd_trend="down")
        self.assertIn("MACD顶背离", str(r["divergences"]))


class TestFlowAnalysis(unittest.TestCase):
    def test_net_long(self):
        r = analyze_seat_flow(10000, 2000, "up")
        self.assertEqual(r["net_position"], "净多")

    def test_net_short(self):
        r = analyze_seat_flow(-8000, -1500, "down")
        self.assertEqual(r["net_position"], "净空")

    def test_bellwether(self):
        r = analyze_seat_flow(5000, 1000, "up", {"中信": 2000, "永安": -1000})
        self.assertIn("bellwether_summary", r)

    def test_lr_ratio(self):
        r = estimate_long_short_ratio(15000, 10000)
        self.assertGreater(r["ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
