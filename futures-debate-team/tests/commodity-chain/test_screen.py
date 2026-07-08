# -*- coding: utf-8 -*-
"""产业链验证模块测试（Skill 2: commodity-chain-analysis）。"""

import unittest
from scripts.chain_verifier import get_chain_for_symbol, chain_verification


class TestGetChainForSymbol(unittest.TestCase):
    """测试品种到产业链映射。"""

    def test_black_chain(self):
        """测试黑色系品种映射。"""
        self.assertEqual(get_chain_for_symbol("rb"), "黑色系")
        self.assertEqual(get_chain_for_symbol("hc"), "黑色系")
        self.assertEqual(get_chain_for_symbol("i"), "黑色系")

    def test_energy_chain(self):
        """测试能源链品种映射。"""
        self.assertEqual(get_chain_for_symbol("sc"), "能源链")
        self.assertEqual(get_chain_for_symbol("ec"), "能源链")

    def test_new_symbols(self):
        """测试新增品种映射。"""
        self.assertEqual(get_chain_for_symbol("lc"), "新能源")
        self.assertEqual(get_chain_for_symbol("si"), "新能源")
        self.assertEqual(get_chain_for_symbol("pt"), "贵金属")


class TestChainVerification(unittest.TestCase):
    """测试产业链验证。"""

    def test_aligned_signal(self):
        """测试信号与产业链趋势一致。"""
        candidate = {
            "product_id": "rb",
            "symbol": "rb",
            "score": -80,
            "stage": "trending",
            "resonance": 0.8,
            "signal_quality": 0.7,
            "direction": "SELL",
        }
        chain_results = {
            "黑色系": {
                "overall_trend": "空头趋势",
                "avg_score": -70,
                "count": 3,
                "members": [
                    {"symbol": "rb", "score": -80},
                    {"symbol": "hc", "score": -75},
                    {"symbol": "i", "score": -60},
                ],
            }
        }
        result = chain_verification(candidate, chain_results)
        self.assertTrue(result["aligned"])
        self.assertGreater(result["confidence_adjustment"], 0)

    def test_divergent_signal(self):
        """测试信号与产业链趋势背离。"""
        candidate = {
            "product_id": "rb",
            "symbol": "rb",
            "score": 60,
            "stage": "launch",
            "resonance": 0.7,
            "signal_quality": 0.6,
            "direction": "BUY",
        }
        chain_results = {
            "黑色系": {
                "overall_trend": "空头趋势",
                "avg_score": -70,
                "count": 3,
                "members": [
                    {"symbol": "rb", "score": 60},
                    {"symbol": "hc", "score": -75},
                    {"symbol": "i", "score": -60},
                ],
            }
        }
        result = chain_verification(candidate, chain_results)
        self.assertFalse(result["aligned"])
        self.assertLess(result["confidence_adjustment"], 0)


if __name__ == "__main__":
    unittest.main()
