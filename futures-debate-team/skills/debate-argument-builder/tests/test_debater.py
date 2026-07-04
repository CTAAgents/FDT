# -*- coding: utf-8 -*-
"""debate-argument-builder 测试"""

import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.debater_tools import (
    get_factor_decomp, get_chain_context, get_price_action,
    _FALLBACK_CHAIN_MAP,
)


class TestFactorDecomp(unittest.TestCase):
    """因子分解测试（依赖真实数据文件，可能 fallback）"""

    def test_known_symbol_returns_dict(self):
        result = get_factor_decomp("PK")
        self.assertIsInstance(result, dict)

    def test_unknown_symbol_returns_error(self):
        result = get_factor_decomp("ZZZZZZ")
        self.assertIn("error", result)


class TestChainContext(unittest.TestCase):
    """链上下文测试"""

    def test_rb_black_chain(self):
        result = get_chain_context("RB")
        self.assertIn("chain", result)

    def test_sc_energy_chain(self):
        result = get_chain_context("SC")
        self.assertIn("chain", result)

    def test_au_precious_chain(self):
        result = get_chain_context("AU")
        self.assertIn("chain", result)

    def test_case_insensitive(self):
        r1 = get_chain_context("RB")
        r2 = get_chain_context("rb")
        self.assertEqual(r1["chain"], r2["chain"])

    def test_unknown_symbol(self):
        result = get_chain_context("ZZZZZZ")
        self.assertEqual(result["chain"], "未分类")


class TestFallbackChainMap(unittest.TestCase):
    """备用映射完整性测试"""

    def test_covers_black_chain(self):
        for sym in ["RB", "HC", "I", "J", "JM", "SF", "SM"]:
            self.assertIn(sym, _FALLBACK_CHAIN_MAP, f"{sym} 不在备用映射中")

    def test_covers_energy(self):
        for sym in ["SC", "LU", "FU", "BU", "PG"]:
            self.assertIn(sym, _FALLBACK_CHAIN_MAP)

    def test_fallback_count(self):
        """备用映射至少覆盖60个品种"""
        self.assertGreaterEqual(len(_FALLBACK_CHAIN_MAP), 60)


class TestPriceAction(unittest.TestCase):
    """价格走势测试"""

    def test_returns_dict(self):
        result = get_price_action("PK")
        self.assertIsInstance(result, dict)

    def test_unknown_returns_error(self):
        result = get_price_action("ZZZZZZ")
        self.assertIn("error", result)


class TestSKILLMd(unittest.TestCase):
    """SKILL.md 结构验证"""

    def test_agent_created_flag(self):
        skill_path = os.path.join(os.path.dirname(__file__), '..', 'SKILL.md')
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("agent_created: true", content)

    def test_has_version(self):
        skill_path = os.path.join(os.path.dirname(__file__), '..', 'SKILL.md')
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("version:", content)


if __name__ == '__main__':
    unittest.main()
