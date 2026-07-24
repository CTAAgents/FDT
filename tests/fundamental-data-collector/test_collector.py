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


# ═══════════════════════════════════════════════════════════════
#  数据结构化升级测试（Phase 3.1）
# ═══════════════════════════════════════════════════════════════

from scripts.structured_data import (
    parse_numeric,
    parse_unit,
    detect_direction,
    enrich_with_meta,
    enrich_all_fields,
)


class TestStructuredDataParse(unittest.TestCase):
    """结构化工具函数测试。"""

    def test_parse_numeric_simple(self):
        self.assertEqual(parse_numeric("80元/吨"), 80.0)

    def test_parse_numeric_negative(self):
        self.assertEqual(parse_numeric("-500元/吨"), -500.0)

    def test_parse_numeric_decimal(self):
        self.assertEqual(parse_numeric("36.5%"), 36.5)

    def test_parse_numeric_none(self):
        self.assertIsNone(parse_numeric("亏损加深"))

    def test_parse_unit_yuan_per_ton(self):
        self.assertEqual(parse_unit("80元/吨"), "元/吨")

    def test_parse_unit_percent(self):
        self.assertEqual(parse_unit("36.5%"), "%")

    def test_parse_unit_wan_ton(self):
        self.assertEqual(parse_unit("105万吨"), "万吨")

    def test_parse_unit_empty(self):
        self.assertEqual(parse_unit("亏损"), "")

    def test_detect_direction_up(self):
        self.assertEqual(detect_direction("上升"), "上升")
        self.assertEqual(detect_direction("高位"), "上升")

    def test_detect_direction_down(self):
        self.assertEqual(detect_direction("下降"), "下降")
        self.assertEqual(detect_direction("亏损"), "下降")

    def test_detect_direction_flat(self):
        self.assertEqual(detect_direction("中性"), "持平")

    def test_enrich_with_meta_explicit(self):
        data = enrich_with_meta({"利润": "80元/吨"}, "利润", value=80, unit="元/吨", direction="下降")
        self.assertIn("_meta", data)
        meta = data["_meta"]["利润"]
        self.assertEqual(meta.value, 80)
        self.assertEqual(meta.unit, "元/吨")
        self.assertEqual(meta.direction, "下降")
        self.assertEqual(meta.revision, "v1")

    def test_enrich_with_meta_auto_parse(self):
        data = enrich_with_meta({"开工率": "36.5%"}, "开工率")
        meta = data["_meta"]["开工率"]
        self.assertEqual(meta.value, 36.5)
        self.assertEqual(meta.unit, "%")

    def test_enrich_with_meta_no_numeric(self):
        data = enrich_with_meta({"趋势": "低位"}, "趋势")
        self.assertIn("_meta", data)
        meta = data["_meta"]["趋势"]
        self.assertIsNone(meta.value)

    def test_enrich_all_fields(self):
        raw = {
            "开工率": "78%",
            "库存": "105万吨",
            "_source": "隆众资讯",
            "_updated": "2026-07-04",
        }
        data = enrich_all_fields(raw)
        self.assertIn("_meta", data)
        self.assertIn("开工率", data["_meta"])
        self.assertIn("库存", data["_meta"])
        self.assertEqual(data["_meta"]["开工率"].value, 78.0)
        self.assertEqual(data["_meta"]["库存"].value, 105.0)
        # 原始文本不变
        self.assertEqual(data["开工率"], "78%")


class TestStructuredDataIntegration(unittest.TestCase):
    """集成测试：query_* 函数返回的数据结构。"""

    def test_supply_has_source(self):
        from scripts.supply import query_supply
        result = query_supply("PK")
        self.assertIn("_source", result)

    def test_demand_has_source(self):
        from scripts.demand import query_demand
        result = query_demand("PK")
        self.assertIn("_source", result)

    def test_inventory_has_source(self):
        from scripts.inventory import query_inventory
        result = query_inventory("RB")
        self.assertIn("_source", result)
        self.assertIn("_updated", result)

    def test_margin_has_source(self):
        from scripts.margin import query_margin
        result = query_margin("RB")
        self.assertIn("_source", result)
        self.assertIn("_updated", result)


if __name__ == "__main__":
    unittest.main()
