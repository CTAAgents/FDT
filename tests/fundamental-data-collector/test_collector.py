# -*- coding: utf-8 -*-
"""fundamental-data-collector 测试 — 覆盖全部6个模块。"""

import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from scripts.supply import list_available_symbols, query_supply
    _HAS_MODULE = True
except ImportError:
    _HAS_MODULE = False
    pytest.skip("module scripts.supply not available", allow_module_level=True)

from scripts.demand import query_demand
from scripts.inventory import query_inventory
from scripts.margin import query_margin
from scripts.term_basis import query_term
from scripts.web_collector import query_web


class TestSupply(unittest.TestCase):
    def test_known_symbol(self):
        result = query_supply("PK")
        self.assertIn("开工率", result)
        self.assertIn("_source", result)
        self.assertIn("_updated", result)

    def test_unknown_symbol(self):
        result = query_supply("XXXXX")
        self.assertIn("info", result)

    def test_case_insensitive(self):
        r1 = query_supply("PK")
        r2 = query_supply("pk")
        self.assertEqual(r1.get("开工率"), r2.get("开工率"))

    def test_list_available(self):
        symbols = list_available_symbols()
        self.assertGreater(len(symbols), 10)
        self.assertIn("PK", symbols)


class TestDemand(unittest.TestCase):
    def test_known_symbol(self):
        result = query_demand("PK")
        self.assertIn("压榨利润", result)
        self.assertIn("_source", result)

    def test_unknown_symbol(self):
        result = query_demand("XXXXX")
        self.assertIn("info", result)

    def test_case_insensitive(self):
        r1 = query_demand("JD")
        r2 = query_demand("jd")
        self.assertEqual(r1.get("养殖利润"), r2.get("养殖利润"))


class TestInventory(unittest.TestCase):
    def test_known_symbol(self):
        result = query_inventory("RB")
        self.assertIn("社库", result)
        self.assertIn("_source", result)

    def test_known_with_seasonal(self):
        result = query_inventory("PK")
        self.assertIn("seasonal", result)
        self.assertIn("分位数", result["seasonal"])

    def test_unknown_symbol(self):
        result = query_inventory("XXXXX")
        self.assertIn("info", result)


class TestMargin(unittest.TestCase):
    def test_known_symbol(self):
        result = query_margin("RB")
        self.assertIn("长流程毛利", result)
        self.assertIn("_source", result)

    def test_unknown_symbol(self):
        result = query_margin("XXXXX")
        self.assertIn("info", result)


class TestTermBasis(unittest.TestCase):
    def test_known_symbol(self):
        result = query_term("RB")
        # 如果从 ranked 数据获取，应含 data_source；如果从缓存获取，应含 structure
        has_structure = "structure" in result
        has_data_source = "data_source" in result
        self.assertTrue(has_structure or has_data_source)
        self.assertIn("_source", result)

    def test_known_term_structure(self):
        result = query_term("AU")
        # AU 可能从 ranked 数据获取（非缓存格式）或从缓存获取
        # 只要返回了非 error 数据即可
        self.assertNotIn("error", str(result))
        self.assertIn("_source", result)

    def test_case_insensitive(self):
        r1 = query_term("RB")
        r2 = query_term("rb")
        self.assertEqual(r1.get("structure"), r2.get("structure"))


class TestWebCollector(unittest.TestCase):
    def test_basic_search(self):
        result = query_web("纯碱 库存")
        self.assertIn("建议搜索", result)
        self.assertIn("WebSearch", result)

    def test_margin_keyword(self):
        result = query_web("螺纹钢 利润")
        self.assertIn("利润", result)
        self.assertIn("成本", result)


class TestSKILLMd(unittest.TestCase):
    """验证 SKILL.md 的 agent_created 标记和核心字段"""

    def test_skill_md_exists(self):
        skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
        self.assertTrue(os.path.exists(skill_path))

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


if __name__ == "__main__":
    unittest.main()
