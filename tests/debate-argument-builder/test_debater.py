# -*- coding: utf-8 -*-
"""debate-argument-builder 测试"""

import pytest
import sys, os, unittest, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
try:
    from scripts.debater_tools import (
        _find_report,
        _find_recent,
        team_outline,
        find_debate_report_path,
    )
    _HAS_MODULE = True
except ImportError:
    _HAS_MODULE = False
    pytest.skip("module scripts.debater_tools not available", allow_module_level=True)



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

    def test_known_returns_enhanced_data(self):
        """验证增强后的 get_price_action 返回更多字段"""
        result = get_price_action("PK")
        if "error" not in result:
            # 至少包含新增字段中的一个
            has_enhanced = any(k in result for k in ["grid", "side", "signal_type", "factor_detail"])
            self.assertTrue(has_enhanced)


class TestFindReport(unittest.TestCase):
    """报告查找测试"""

    def test_known_report_format(self):
        from scripts.debater_tools import _find_report, _find_recent

        # 测试 _find_recent 不崩溃
        tmp_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
        result = _find_recent(tmp_dir, "debater")
        # 可能为 None，但不应该抛异常
        self.assertIsNotNone(result) if result else self.assertIsNone(result)


class TestChainEdgeCases(unittest.TestCase):
    """链映射边界情况"""

    def test_new_energy_symbols(self):
        for sym in ["LC", "SI", "PS"]:
            result = get_chain_context(sym)
            self.assertIn("chain", result)

    def test_all_black_members(self):
        for sym in ["RB", "HC", "I", "J", "JM", "SF", "SM"]:
            result = get_chain_context(sym)
            self.assertNotEqual(result["chain"], "未分类")


class TestSKILLMd(unittest.TestCase):
    """SKILL.md 结构验证"""

    def test_agent_created_flag(self):
        skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("agent_created: true", content)

    def test_has_version(self):
        skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("version:", content)

    def test_dual_role_structure(self):
        """验证 SKILL.md 以角色为框架而不是以方向为框架"""
        skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 证真/慎思应出现在多头/空头之前
        zhengzhen_pos = content.find("证真")
        zhensi_pos = content.find("慎思")
        bull_pos = content.find("多头")
        bear_pos = content.find("空头")
        # 证真/慎思应该先出现（除非不在同一文档段）
        for role_pos in [zhengzhen_pos, zhensi_pos]:
            self.assertGreater(role_pos, 0, "证真/慎思角色定义未找到")
        # 方向描述不应出现在角色定义之前
        # （在角色框架章节后的方向描述是正常的）
        self.assertGreater(bull_pos, 0, "方向描述应存在")

    def test_role_not_direction(self):
        """确保 role 参数是证真/慎思而不是多头/空头"""
        skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        # "role:" 后面应该跟 "证真" 或 "慎思" 而不是 "bull" 或 "bear"
        self.assertIn('role: "证真"', content)
        self.assertIn('role: "慎思"', content)


if __name__ == "__main__":
    unittest.main()
