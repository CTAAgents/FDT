"""debate_history.py 单元测试"""

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from debate import history as dh


class TestDebateHistory:
    def test_empty_load(self, temp_history_dir):
        assert dh.load_feedback() == {}

    def test_record_and_load(self, temp_history_dir):
        dh.record_feedback("RB", 85.0, 90.0, outcome="win")
        dh.record_feedback("RB", 72.0, 70.0, outcome="loss")
        dh.record_feedback("SC", 65.0, 60.0)
        fb = dh.load_feedback()
        assert fb["RB"]["debate_count"] == 2
        assert fb["RB"]["wins"] == 1
        assert fb["RB"]["losses"] == 1
        assert fb["RB"]["win_rate"] == 0.5
        assert fb["SC"]["win_rate"] is None

    def test_symbol_value_score(self, temp_history_dir):
        dh.record_feedback("RB", 85.0, 90.0, outcome="win")
        dh.record_feedback("RB", 72.0, 70.0, outcome="loss")
        sc = dh.get_symbol_value_score("RB")
        assert -10 <= sc <= 10

    def test_no_history_score(self, temp_history_dir):
        assert dh.get_symbol_value_score("XX") == 0.0

    def test_auto_load_score(self, temp_history_dir):
        dh.record_feedback("RB", 80, 80, "win")
        assert -10 <= dh.get_symbol_value_score("RB") <= 10

    def test_recent_records(self, temp_history_dir):
        for s in ["A", "B", "C"]:
            dh.record_feedback(s, 70, 60)
        assert len(dh.get_recent_records(2)) == 2

    def test_empty_records(self, temp_history_dir):
        assert dh.get_recent_records() == []

    def test_clear(self, temp_history_dir):
        dh.record_feedback("RB", 80, 80)
        assert dh.load_feedback() != {}
        dh.clear_history()
        assert dh.load_feedback() == {}

    def test_case_insensitive(self, temp_history_dir):
        dh.record_feedback("rb", 80, 80, outcome="win")
        assert dh.load_feedback()["RB"]["debate_count"] == 1

    def test_average_calc(self, temp_history_dir):
        for v in [80, 60, 100]:
            dh.record_feedback("RB", v, v)
        fb = dh.load_feedback()
        assert fb["RB"]["avg_debate_value"] == 80.0

    def test_corrupt_json(self, temp_history_dir):
        with open(os.path.join(temp_history_dir, "debate_feedback.json"), "w") as f:
            f.write("{corrupt")
        assert dh.load_feedback() == {}
