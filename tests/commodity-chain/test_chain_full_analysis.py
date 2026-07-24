# -*- coding: utf-8 -*-
"""build_symbol_map 回归测试 (2026-07-14 迁移后)。

本测试固化 scan_all 输出的三源合并逻辑，防止回归。
"""

import os
import sys
import unittest

SKILL_SCRIPTS = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "skills", "commodity-chain-analysis", "scripts",
)
sys.path.insert(0, os.path.abspath(SKILL_SCRIPTS))

from run_full_chain_analysis import build_symbol_map  # noqa: E402


def _mk(symbol, **kw):
    d = {"symbol": symbol, "name": symbol}
    d.update(kw)
    return d


class TestBuildSymbolMapThreeProducer(unittest.TestCase):
    def test_merge_from_three_files(self):
        # 新架构：build_symbol_map 只接受单一 summary 参数
        summary = {
            "all_ranked": [
                _mk("RB", direction="bear", adx=20.7, rsi=45.1, total=10, grade="B", z_score=0.5, stage="trending", volume=1000),
                _mk("CU", direction="bull", adx=12.6, rsi=55.2, total=-5, grade="C", z_score=-0.3, stage="unknown", volume=800),
                _mk("I", direction="bull", adx=13.8, rsi=54.5, total=8, grade="B", z_score=0.2, stage="trending", volume=900),
            ]
        }
        smap = build_symbol_map(summary)
        # 3 品种
        self.assertEqual(set(smap.keys()), {"RB", "CU", "I"})
        self.assertEqual(smap["RB"]["total"], 10)
        self.assertEqual(smap["RB"]["direction"], "bear")
        self.assertEqual(smap["RB"]["grade"], "B")
        self.assertEqual(smap["RB"]["adx"], 20.7)
        self.assertEqual(smap["RB"]["rsi"], 45.1)
        self.assertEqual(smap["RB"]["z_score"], 0.5)
        self.assertEqual(smap["RB"]["stage"], "trending")
        self.assertEqual(smap["RB"]["volume"], 1000)
        self.assertEqual(smap["I"]["total"], 8)
        self.assertEqual(smap["CU"]["total"], -5)
        # 名称回退
        self.assertEqual(smap["CU"]["name"], "CU")

    def test_no_longer_depends_on_summary_symbols(self):
        # 确认不再依赖旧的 summary['symbols'] 嵌套结构
        summary = {"all_ranked": [_mk("RB", direction="bear", total=10, grade="B",
                                      adx=20, rsi=45, z_score=0.5, stage="t", volume=1)]}
        smap = build_symbol_map(summary)
        self.assertIn("RB", smap)
        self.assertEqual(smap["RB"]["total"], 10)


if __name__ == "__main__":
    unittest.main()
