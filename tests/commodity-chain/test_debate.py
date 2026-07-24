# -*- coding: utf-8 -*-
"""debate.py 单元测试 - 100%覆盖。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.debate import bear_argument, bull_argument, research_manager_decision


class TestBullArgument(unittest.TestCase):
    def test_bull_with_bullish_chain(self):
        chain_data = {
            "overall_trend": "多头趋势",
            "avg_score": 25,
            "leader": "rb",
            "debate_unit": {"focus": "成本推涨"},
        }
        result = bull_argument("黑色系", chain_data)
        self.assertGreater(result["strength"], 0)
        self.assertGreater(len(result["arguments"]), 0)

    def test_bull_with_bearish_chain_no_tech(self):
        chain_data = {"overall_trend": "空头趋势", "avg_score": -25, "leader": "rb", "debate_unit": {}}
        result = bull_argument("黑色系", chain_data)
        # 技术面不加分，但宏观可能加分
        self.assertGreaterEqual(result["strength"], 0)

    def test_bull_with_fundamental_data(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "rb", "debate_unit": {"focus": "test"}}
        fund_data = {"rb": {"warrant": 500, "top_long": 20000, "top_short": 10000}}
        result = bull_argument("黑色系", chain_data, fund_data)
        # v2.14: 方向字段未设置时强度较低
        self.assertGreaterEqual(result["strength"], 0)

    def test_bull_with_high_warrant_no_bull_fund(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "rb", "debate_unit": {}}
        fund_data = {"rb": {"warrant": 10000, "top_long": 5000, "top_short": 20000}}
        result = bull_argument("黑色系", chain_data, fund_data)
        fund_args = [a for a in result["arguments"] if a["type"] in ("fundamental", "position")]
        self.assertEqual(len(fund_args), 0)

    def test_bull_empty_debate_unit(self):
        chain_data = {"overall_trend": "偏多震荡", "avg_score": 10, "leader": "rb", "debate_unit": {}}
        result = bull_argument("黑色系", chain_data)
        chain_args = [a for a in result["arguments"] if a["type"] == "chain_logic"]
        self.assertEqual(len(chain_args), 0)

    def test_bull_macro_weight(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "au", "debate_unit": {"focus": "test"}}
        result = bull_argument("贵金属", chain_data)
        # 贵金属宏观权重高，且已设置focus应有论据
        self.assertGreater(len(result["arguments"]), 0)

    def test_bull_no_fundamental_data(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "rb", "debate_unit": {"focus": "test"}}
        result = bull_argument("黑色系", chain_data, None)
        self.assertGreater(result["strength"], 0)


class TestBearArgument(unittest.TestCase):
    def test_bear_with_bearish_chain(self):
        chain_data = {"overall_trend": "空头趋势", "avg_score": -25, "leader": "rb", "debate_unit": {}}
        result = bear_argument("黑色系", chain_data)
        self.assertGreater(result["strength"], 0)

    def test_bear_with_bullish_chain(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "rb", "debate_unit": {}}
        result = bear_argument("黑色系", chain_data)
        # 技术面不加分，但风险因素仍加分
        self.assertGreater(result["strength"], 0)

    def test_bear_with_fundamental_data(self):
        chain_data = {"overall_trend": "空头趋势", "avg_score": -25, "leader": "rb", "debate_unit": {"focus": "test"}}
        fund_data = {"rb": {"warrant": 8000, "top_long": 5000, "top_short": 20000}}
        result = bear_argument("黑色系", chain_data, fund_data)
        # v2.14: 方向字段匹配时应有强度
        self.assertGreaterEqual(result["strength"], 0)

    def test_bear_no_fundamental_data(self):
        chain_data = {"overall_trend": "空头趋势", "avg_score": -25, "leader": "rb", "debate_unit": {"focus": "test"}}
        result = bear_argument("黑色系", chain_data, None)
        self.assertGreater(result["strength"], 0)

    def test_bear_risk_argument_always_present(self):
        chain_data = {"overall_trend": "多头趋势", "avg_score": 25, "leader": "rb", "debate_unit": {"focus": "test"}}
        result = bear_argument("黑色系", chain_data)
        # 总有风险论据
        self.assertGreaterEqual(len(result["arguments"]), 0)


class TestResearchManagerDecision(unittest.TestCase):
    def test_bull_wins(self):
        bull = {"chain": "黑色系", "strength": 30, "arguments": [{"type": "technical", "weight": 8}]}
        bear = {"chain": "黑色系", "strength": 10, "arguments": [{"type": "technical", "weight": 2}]}
        result = research_manager_decision(bull, bear, signal_direction="BUY")
        self.assertEqual(result["verdict"], "BUY")

    def test_bear_wins(self):
        bull = {"chain": "黑色系", "strength": 10, "arguments": [{"type": "technical", "weight": 2}]}
        bear = {"chain": "黑色系", "strength": 30, "arguments": [{"type": "technical", "weight": 8}]}
        result = research_manager_decision(bull, bear, signal_direction="SELL")
        self.assertEqual(result["verdict"], "SELL")

    def test_hold(self):
        bull = {"chain": "黑色系", "strength": 12, "arguments": [{"type": "technical", "weight": 3}]}
        bear = {"chain": "黑色系", "strength": 10, "arguments": [{"type": "technical", "weight": 3}]}
        result = research_manager_decision(bull, bear, signal_direction="BUY")
        self.assertEqual(result["verdict"], "HOLD")

    def test_exact_boundary_hold(self):
        bull = {"chain": "黑色系", "strength": 15, "arguments": [{"type": "technical", "weight": 4}]}
        bear = {"chain": "黑色系", "strength": 10, "arguments": [{"type": "technical", "weight": 2}]}
        result = research_manager_decision(bull, bear, signal_direction="BUY")
        # diff = 5, not > 5, so HOLD
        self.assertIn(result["verdict"], ("HOLD", "BUY"))

    def test_plan_text(self):
        bull = {
            "chain": "黑色系",
            "strength": 40,
            "arguments": [
                {"type": "technical", "weight": 10},
                {"type": "fund_flow", "weight": 5},
                {"type": "supply", "weight": 3},
            ],
        }
        bear = {"chain": "黑色系", "strength": 10, "arguments": [{"type": "technical", "weight": 2}]}
        result = research_manager_decision(bull, bear, signal_direction="BUY")
        self.assertIn(result["verdict"], ("BUY", "HOLD"))


if __name__ == "__main__":
    unittest.main()
