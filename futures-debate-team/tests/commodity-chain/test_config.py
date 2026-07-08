# -*- coding: utf-8 -*-
"""config.py 单元测试（Skill 2: commodity-chain-analysis）。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.config import (
    CONFIG_MANAGER,
    CHAIN_TYPE_MAPPING,
    CHAIN_THRESHOLD_MAPPING,
    get_chain_debate_weight,
)


class TestConfigManager(unittest.TestCase):
    def test_config_has_chain_keys(self):
        for key in ["chain_specific_indicators", "chain_debate_weights"]:
            self.assertIn(key, CONFIG_MANAGER)

    def test_chain_type_mapping_coverage(self):
        all_chains = [
            "黑色系",
            "能源链",
            "聚酯链",
            "油化工",
            "煤化工",
            "有色",
            "贵金属",
            "油脂油料",
            "谷物软商品",
            "建材",
            "橡胶",
            "纸浆造纸",
        ]
        for c in all_chains:
            self.assertIn(c, CHAIN_TYPE_MAPPING)

    def test_chain_threshold_mapping_coverage(self):
        all_chains = [
            "黑色系",
            "能源链",
            "聚酯链",
            "油化工",
            "煤化工",
            "有色",
            "贵金属",
            "油脂油料",
            "谷物软商品",
            "建材",
            "橡胶",
            "纸浆造纸",
        ]
        for c in all_chains:
            self.assertIn(c, CHAIN_THRESHOLD_MAPPING)

    def test_debate_weights_all_chains(self):
        for c in CHAIN_TYPE_MAPPING:
            if c in CONFIG_MANAGER["chain_debate_weights"]:
                w = CONFIG_MANAGER["chain_debate_weights"][c]
                for k in ["technical_weight", "fundamental_weight", "chain_logic_weight", "macro_weight"]:
                    self.assertIn(k, w)
                    self.assertGreater(w[k], 0)


class TestGetChainDebateWeight(unittest.TestCase):
    def test_known_chain(self):
        w = get_chain_debate_weight("黑色系")
        self.assertIn("technical_weight", w)

    def test_unknown_chain_defaults(self):
        w = get_chain_debate_weight("不存在的链")
        self.assertEqual(w["technical_weight"], 1.0)

    def test_precious_macro_heavy(self):
        w = get_chain_debate_weight("贵金属")
        self.assertGreater(w["macro_weight"], w["technical_weight"])


if __name__ == "__main__":
    unittest.main()
