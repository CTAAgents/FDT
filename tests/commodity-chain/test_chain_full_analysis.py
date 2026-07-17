# -*- coding: utf-8 -*-
"""build_symbol_map 回归测试 (2026-07-14 迁移后)。

本测试固化 scan_all 输出的三源合并逻辑，防止回归。
"""

import sys
import os
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
        # 新架构：summary 只有 all_ranked（无 symbols 键），l1l4/ft 独立
        summary = {
            "all_ranked": [
                _mk("RB", direction="bear", adx=20.7, rsi=45.1),
                _mk("CU", direction="bull", adx=12.6, rsi=55.2),
            ]
        }
        l1l4 = {
            "all_ranked": [
                _mk("RB", total=10, direction="bear", grade="B", adx=20.7,
                    rsi=45.1, z_score=0.5, stage="trending", volume=1000),
                _mk("CU", total=-5, direction="bull", grade="C", adx=12.6,
                    rsi=55.2, z_score=-0.3, stage="unknown", volume=800),
                _mk("I", total=8, direction="bull", grade="B", adx=13.8,
                    rsi=54.5, z_score=0.2, stage="trending", volume=900),
            ]
        }
        ft = {
            "all_ranked": [
                _mk("RB", total=3, direction="bear"),
                _mk("CU", total=-2, direction="bull"),
                _mk("MA", total=5, direction="bull"),
            ]
        }
        smap = build_symbol_map(summary, l1l4, ft)
        # 并集 4 品种
        self.assertEqual(set(smap.keys()), {"RB", "CU", "I", "MA"})
        # l1l4 字段来自独立文件
        self.assertEqual(smap["RB"]["l1l4_total"], 10)
        self.assertEqual(smap["RB"]["l1l4_direction"], "bear")
        self.assertEqual(smap["RB"]["l1l4_grade"], "B")
        self.assertEqual(smap["RB"]["ft_total"], 3)
        self.assertEqual(smap["RB"]["ft_direction"], "bear")
        self.assertEqual(smap["RB"]["adx"], 20.7)
        self.assertEqual(smap["RB"]["z_score_l1"], 0.5)
        self.assertEqual(smap["RB"]["stage"], "trending")
        self.assertEqual(smap["RB"]["volume"], 1000)
        # 仅 l1l4 有、summary/ft 无的品种
        self.assertEqual(smap["I"]["l1l4_total"], 8)
        self.assertEqual(smap["I"]["ft_total"], 0)  # ft 无 I
        # 仅 ft 有、l1l4 无的品种
        self.assertEqual(smap["MA"]["ft_total"], 5)
        self.assertEqual(smap["MA"]["l1l4_total"], 0)
        # 名称回退
        self.assertEqual(smap["CU"]["name"], "CU")

    def test_no_longer_depends_on_summary_symbols(self):
        # 确认不再依赖旧的 summary['symbols'] 嵌套结构（旧结构会 KeyError）
        summary = {"all_ranked": [_mk("RB", direction="bear")]}
        l1l4 = {"all_ranked": [_mk("RB", total=10, direction="bear", grade="B",
                                  adx=20, rsi=45, z_score=0.5, stage="t", volume=1)]}
        ft = {"all_ranked": [_mk("RB", total=2, direction="bear")]}
        smap = build_symbol_map(summary, l1l4, ft)
        self.assertIn("RB", smap)
        self.assertEqual(smap["RB"]["l1l4_total"], 10)
        self.assertEqual(smap["RB"]["ft_total"], 2)


if __name__ == "__main__":
    unittest.main()
