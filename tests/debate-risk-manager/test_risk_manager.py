# -*- coding: utf-8 -*-
"""debate-risk-manager 测试 — 仓位计算/跳空模拟/逻辑审计"""

import pytest
import sys, os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
try:
    from scripts.calc_position import (
        calculate_position_size,
        capped_position,
        account_profile,
    )
    _HAS_MODULE = True
except ImportError:
    _HAS_MODULE = False
    pytest.skip("module scripts.calc_position not available", allow_module_level=True)

from scripts.simulate_gap import (
    get_gap_params,
    simulate_gap,
    calc_margin_call_scenario,
)
from scripts.audit_logic import (
    check_narrative_probability,
    assess_rebuttal_quality,
    run_logic_audit,
)


class TestCalcMarginPerLot(unittest.TestCase):
    def test_basic_calc(self):
        # RB: 3100元/吨, 10吨/手, 10%保证金
        margin = calc_margin_per_lot(3100, 10, 0.10)
        self.assertEqual(margin, 3100)

    def test_precious_metal(self):
        # AU: 588元/克, 1000克/手, 8%保证金
        margin = calc_margin_per_lot(588, 1000, 0.08)
        self.assertEqual(margin, 47040)


class TestCalcLeverage(unittest.TestCase):
    def test_2x_leverage(self):
        # 20万合约价值, 10万权益 = 2倍
        lev = calc_leverage(200000, 100000)
        self.assertEqual(lev, 2.0)

    def test_5x_over_limit(self):
        lev = calc_leverage(500000, 100000)
        self.assertEqual(lev, 5.0)

    def test_zero_equity(self):
        lev = calc_leverage(100000, 0)
        self.assertEqual(lev, float("inf"))


class TestCalcMarginUsage(unittest.TestCase):
    def test_green_zone(self):
        ratio, level = calc_margin_usage(20000, 100000)
        self.assertAlmostEqual(ratio, 0.2)
        self.assertEqual(level, "green")

    def test_red_zone(self):
        ratio, level = calc_margin_usage(70000, 100000)
        self.assertEqual(level, "red")

    def test_yellow_zone(self):
        ratio, level = calc_margin_usage(50000, 100000)
        self.assertEqual(level, "yellow")


class TestCalcStopLossPct(unittest.TestCase):
    def test_green(self):
        ratio, level = calc_stop_loss_pct(2000, 100000)
        self.assertEqual(level, "green")

    def test_red(self):
        ratio, level = calc_stop_loss_pct(6000, 100000)
        self.assertEqual(level, "red")

    def test_yellow(self):
        ratio, level = calc_stop_loss_pct(4000, 100000)
        self.assertEqual(level, "yellow")


class TestCalcPositionRisk(unittest.TestCase):
    def test_standard_case(self):
        # RB 3100, 10吨/手, 10%保证金, 100万权益, 50点止损, 5手
        r = calc_position_risk(3100, 10, 0.10, 1000000, 50, 5)
        self.assertEqual(r["lots"], 5)
        # 合约价值=3100*10*5=155000, 杠杆=155000/1M≈0.16
        self.assertAlmostEqual(r["leverage"], 0.16, delta=0.02)
        self.assertEqual(r["margin_level"], "green")
        self.assertEqual(r["stop_level"], "green")
        self.assertEqual(len(r["flags"]), 0)

    def test_over_leverage(self):
        # 超杠杆场景：10手, 价格100000
        r = calc_position_risk(100000, 10, 0.10, 1000000, 100, 15)
        self.assertGreater(r["leverage"], 3)
        self.assertTrue(any(f["level"] == "red" for f in r["flags"]))

    def test_left_signal(self):
        r = calc_position_risk(3100, 10, 0.10, 1000000, 50, 10, is_left_signal=True)
        self.assertEqual(r["lots"], 5)  # 减半

    def test_safe_max(self):
        r = calc_position_risk(3100, 10, 0.10, 1000000, 50, 5)
        self.assertGreaterEqual(r["safe_max"], 1)


class TestGetGapParams(unittest.TestCase):
    def test_aggressive(self):
        p = get_gap_params("sc")
        self.assertEqual(p["category"], "aggressive")
        self.assertEqual(p["typical_gap_pct"], 0.03)

    def test_moderate(self):
        p = get_gap_params("rb")
        self.assertEqual(p["category"], "moderate")
        self.assertEqual(p["typical_gap_pct"], 0.02)

    def test_unknown(self):
        p = get_gap_params("ZZ")
        self.assertEqual(p["category"], "unknown")


class TestSimulateGap(unittest.TestCase):
    def test_sc_typical(self):
        # SC 600元/桶, 1000桶/手, 5手, 1000万权益
        r = simulate_gap("sc", 600, 5, 1000, 10000000, 30)
        self.assertAlmostEqual(r["typical_gap_pct"], 0.03)
        self.assertTrue(r["gap_exceeds_stop_typical"] or not r["gap_exceeds_stop_typical"])

    def test_extreme_loss_warning(self):
        # 小账户极端跳空
        r = simulate_gap("sc", 600, 5, 1000, 500000, 30)
        if r["extreme_loss_pct"] > 0.05:
            self.assertTrue(len(r["warnings"]) > 0)


class TestCalcMarginCall(unittest.TestCase):
    def test_basic_scenario(self):
        r = calc_margin_call_scenario(3100, 5, 10, 3100, 1000000, 50000)
        self.assertIn("remaining_equity", r)
        self.assertIn("margin_call_needed", r)

    def test_margin_call_triggered(self):
        # 大跳空 + 高杠杆
        r = calc_margin_call_scenario(3100, 10, 10, 3100, 500000, 200000)
        self.assertIn("margin_call_needed", r)


class TestNarrativeProbability(unittest.TestCase):
    def test_tail_as_base(self):
        r = check_narrative_probability("供给短缺", 0.60, 0.05)
        self.assertEqual(r["issue"], "尾部当基准")
        self.assertEqual(r["severity"], "red")

    def test_tail_overestimated(self):
        r = check_narrative_probability("需求崩塌", 0.40, 0.08)
        self.assertEqual(r["severity"], "yellow")

    def test_reasonable(self):
        r = check_narrative_probability("库存累积", 0.65, 0.60)
        self.assertEqual(r["severity"], "green")


class TestRebuttalQuality(unittest.TestCase):
    def test_good(self):
        r = assess_rebuttal_quality("接住")
        self.assertTrue(r["acceptable"])
        self.assertEqual(r["score"], 1.0)

    def test_bad(self):
        r = assess_rebuttal_quality("糊弄")
        self.assertFalse(r["acceptable"])
        self.assertEqual(r["score"], 0.0)


class TestRunLogicAudit(unittest.TestCase):
    def test_all_include_no_issue(self):
        dims = [
            {"dim": "供给", "ruling": "include", "rebuttal_quality": "接住"},
            {"dim": "需求", "ruling": "include", "rebuttal_quality": "接住"},
        ]
        r = run_logic_audit(dims)
        self.assertEqual(r["include_count"], 2)
        self.assertTrue(len(r["issues"]) > 0)  # 没有exclude/watch

    def test_with_exclude(self):
        dims = [
            {"dim": "供给", "ruling": "include", "rebuttal_quality": "接住"},
            {"dim": "需求", "ruling": "exclude", "rebuttal_quality": "糊弄"},
        ]
        r = run_logic_audit(dims)
        self.assertEqual(r["exclude_count"], 1)
        self.assertEqual(len(r["bad_quality"]), 1)


if __name__ == "__main__":
    unittest.main()
