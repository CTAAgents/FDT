"""fundamental-data-collector 数据结构化工具测试（Phase 3.1）。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "fundamental-data-collector"))

from scripts.structured_data import (
    parse_numeric,
    parse_unit,
    detect_direction,
    enrich_with_meta,
    enrich_all_fields,
)


class TestParseNumeric(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_numeric("80元/吨"), 80.0)

    def test_negative(self):
        self.assertEqual(parse_numeric("-500元/吨"), -500.0)

    def test_decimal(self):
        self.assertEqual(parse_numeric("36.5%"), 36.5)

    def test_positive_decimal(self):
        self.assertEqual(parse_numeric("+7.3万吨"), 7.3)

    def test_no_numeric(self):
        self.assertIsNone(parse_numeric("亏损加深"))

    def test_empty(self):
        self.assertIsNone(parse_numeric(""))

    def test_zero(self):
        self.assertEqual(parse_numeric("0"), 0.0)


class TestParseUnit(unittest.TestCase):
    def test_yuan_per_ton(self):
        self.assertEqual(parse_unit("80元/吨"), "元/吨")

    def test_percent(self):
        self.assertEqual(parse_unit("36.5%"), "%")

    def test_wan_ton(self):
        self.assertEqual(parse_unit("105万吨"), "万吨")

    def test_yuan_per_jin(self):
        self.assertEqual(parse_unit("1.87元/斤"), "元/斤")

    def test_no_unit(self):
        self.assertEqual(parse_unit("亏损"), "")


class TestDetectDirection(unittest.TestCase):
    def test_up_rise(self):
        self.assertEqual(detect_direction("上升"), "上升")

    def test_up_high(self):
        self.assertEqual(detect_direction("高位"), "上升")

    def test_up_plus(self):
        self.assertEqual(detect_direction("+7.3%"), "上升")

    def test_down_fall(self):
        self.assertEqual(detect_direction("下降"), "下降")

    def test_down_loss(self):
        self.assertEqual(detect_direction("亏损"), "下降")

    def test_down_minus(self):
        self.assertEqual(detect_direction("-0.45万吨"), "下降")

    def test_flat(self):
        self.assertEqual(detect_direction("中性偏弱"), "持平")


class TestEnrichWithMeta(unittest.TestCase):
    def test_explicit_values(self):
        data = enrich_with_meta({"利润": "80元/吨"}, "利润", value=80, unit="元/吨", direction="下降")
        self.assertIn("_meta", data)
        meta = data["_meta"]["利润"]
        self.assertEqual(meta.value, 80)
        self.assertEqual(meta.unit, "元/吨")
        self.assertEqual(meta.direction, "下降")
        self.assertEqual(meta.revision, "v1")

    def test_auto_parse_numeric(self):
        data = enrich_with_meta({"开工率": "36.5%"}, "开工率")
        meta = data["_meta"]["开工率"]
        self.assertEqual(meta.value, 36.5)
        self.assertEqual(meta.unit, "%")

    def test_no_numeric_in_text(self):
        data = enrich_with_meta({"趋势": "低位"}, "趋势")
        self.assertIn("_meta", data)
        meta = data["_meta"]["趋势"]
        self.assertIsNone(meta.value)

    def test_text_preserved(self):
        data = enrich_with_meta({"利润": "80元/吨"}, "利润", value=80)
        self.assertEqual(data["利润"], "80元/吨")

    def test_date_and_source(self):
        data = enrich_with_meta({"利润": "80元/吨"}, "利润", value=80, data_date="2026-07-04", source="Mysteel")
        meta = data["_meta"]["利润"]
        self.assertEqual(meta.data_date, "2026-07-04")
        self.assertEqual(meta.source, "Mysteel")


class TestEnrichAllFields(unittest.TestCase):
    def test_all_fields_enriched(self):
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
        self.assertEqual(data["开工率"], "78%")

    def test_meta_keys_skipped(self):
        raw = {"开工率": "78%", "_source": "test", "_meta": {}, "seasonal": {"分位数": "50%"}}
        data = enrich_all_fields(raw)
        self.assertEqual(len(data["_meta"]), 1)  # only "开工率"
        self.assertNotIn("_source", data["_meta"])
        self.assertNotIn("seasonal", data["_meta"])

    def test_unknown_symbol_no_fields(self):
        raw = {"info": "无数据", "_source": "test"}
        data = enrich_all_fields(raw)
        self.assertEqual(data.get("_meta", {}), {})

    def test_multiple_fields(self):
        raw = {
            "产量": "150万吨",
            "开工率": "85%",
            "利润": "-200元/吨",
            "_source": "Mysteel",
        }
        data = enrich_all_fields(raw)
        self.assertEqual(len(data["_meta"]), 3)
        self.assertEqual(data["_meta"]["产量"].value, 150.0)
        self.assertEqual(data["_meta"]["开工率"].value, 85.0)
        self.assertEqual(data["_meta"]["利润"].value, -200.0)


if __name__ == "__main__":
    unittest.main()
