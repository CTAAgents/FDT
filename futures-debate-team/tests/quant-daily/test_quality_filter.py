"""quality_filter.py 单元测试"""

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from pipeline import quality_filter as qf

GOOD = "螺纹钢：今日开工率78.5%，环比上升2.3%。库存去化加速至350万吨。高炉检修影响5万吨/日。房地产新开工超预期，需求回暖。预计偏强运行，建议做多。"


class TestParseQuality:
    def test_high_value(self):
        r = qf.parse_report_quality(GOOD)
        assert r["is_valuable"] is True and r["score"] >= 50

    def test_low_value(self):
        r = qf.parse_report_quality("今日市场震荡，等待指引。")
        assert r["is_valuable"] is False and r["score"] < 50

    def test_empty(self):
        r = qf.parse_report_quality("")
        assert r["is_valuable"] is False and r["score"] == 0

    def test_none(self):
        r = qf.parse_report_quality(None)
        assert r["is_valuable"] is False and r["score"] == 0

    def test_supply_only(self):
        r = qf.parse_report_quality("OPEC+减产200万桶/日，伊朗出口受限，俄罗斯检修。")
        assert r["checklist"]["has_supply_shock"] is True

    def test_demand_only(self):
        r = qf.parse_report_quality("央行降息，房地产政策宽松，基建提速。")
        assert r["checklist"]["has_demand_change"] is True

    def test_score_bounds(self):
        assert 0 <= qf.parse_report_quality(GOOD)["score"] <= 100


class TestFilterReports:
    def test_basic(self):
        f = qf.filter_reports([{"text": GOOD, "src": "a"}, {"text": "今日震荡", "src": "b"}, {"text": "", "src": "c"}])
        assert len(f) == 1

    def test_content_field(self):
        f = qf.filter_reports([{"content": GOOD, "src": "a"}])
        assert len(f) == 1


class TestAutoLabel:
    def test_positive(self):
        l = qf.auto_label_reports([{"text": GOOD, "score_5layer": 75, "driver_id": 1}])
        assert l[0]["label"] == 1

    def test_negative(self):
        l = qf.auto_label_reports([{"text": "今日震荡", "score_5layer": 10, "driver_id": 0}])
        assert l[0]["label"] == 0

    def test_threshold(self):
        l = qf.auto_label_reports(
            [{"text": GOOD, "score_5layer": 60, "driver_id": 1}, {"text": GOOD, "score_5layer": 59, "driver_id": 1}]
        )
        assert l[0]["label"] == 1 and l[1]["label"] == 0

    def test_fallback(self):
        l = qf.auto_label_reports([{"text": GOOD, "total_score": 70, "main_driver": 1}])
        assert l[0]["label"] == 1
