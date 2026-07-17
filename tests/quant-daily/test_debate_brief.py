"""debate_brief.py 核心函数单元测试"""

import json
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from signals import debate_brief as db


class TestComputeDebateScore:
    def test_divergence_high_value(self):
        l = dict(total=76, direction="bull", adx=59.5, rsi=27.7, cons=3, stage="launch", veto=0, z_score=2.3)
        f = dict(total=-45, direction="bear", adx=35, cons=2, stage="quiet", veto=0)
        r = db.compute_debate_score(l, f, chain="黑色链")
        assert 60 <= r["debate_value"] <= 100
        assert "方向分歧" in r["tags"]
        assert "强趋势" in r["tags"]

    def test_consensus_bull(self):
        l = dict(total=40, direction="bull", adx=22, rsi=55, cons=3, stage="quiet", veto=0, z_score=1.0)
        f = dict(total=30, direction="bull", adx=20, cons=2, stage="quiet", veto=0)
        r = db.compute_debate_score(l, f)
        assert r["debate_value"] > 0
        assert "方向分歧" not in r["tags"]

    def test_extreme_rsi(self):
        l = dict(total=80, direction="bull", adx=45, rsi=18, cons=4, stage="launch", veto=0, z_score=3.1)
        f = dict(total=60, direction="bull", adx=40, cons=3, stage="launch", veto=0)
        r = db.compute_debate_score(l, f, chain="贵金属")
        assert "RSI超卖" in r["tags"] or "RSI超买" in r["tags"]

    def test_null_inputs(self):
        r = db.compute_debate_score(None, None)
        assert r["debate_value"] == 13.0  # data=10 + chain=3

    def test_empty_inputs(self):
        r = db.compute_debate_score({}, {})
        assert r["debate_value"] == 13.0

    def test_low_value(self):
        l = dict(total=2, direction="bull", adx=8, rsi=50, cons=0, stage="quiet", veto=2, z_score=0.1)
        f = dict(total=1, direction="bull", adx=7, cons=0, stage="quiet", veto=1)
        r = db.compute_debate_score(l, f)
        assert r["debate_value"] < 50

    def test_veto_penalty(self):
        l = dict(total=50, direction="bull", adx=30, rsi=55, cons=3, stage="trending", veto=3, z_score=1.0)
        f = dict(total=40, direction="bull", adx=25, cons=2, stage="trending", veto=2)
        r = db.compute_debate_score(l, f)
        assert r["breakdown"]["data"] < 5





class TestExtractFunctions:
    def test_l1l4(self, sample_l1l4_entry):
        assert db._extract_l1l4(sample_l1l4_entry)["total"] == 76

    def test_l1l4_empty(self):
        assert db._extract_l1l4({})["total"] == 0

    def test_factor(self, sample_factor_entry):
        assert db._extract_factor(sample_factor_entry)["total"] == -45

    def test_factor_empty(self):
        assert db._extract_factor({})["total"] == 0

    def test_risk_conflict(self, sample_l1l4_entry, sample_factor_entry):
        assert db._extract_risk_input(sample_l1l4_entry, sample_factor_entry)["direction_conflict"] is True

    def test_risk_consensus(self):
        l = dict(total=50, direction="bull", adx=30, cons=4, atr=35)
        f = dict(total=40, direction="bull", vote_confidence=0.8)
        assert db._extract_risk_input(l, f)["direction_conflict"] is False

    def test_atr_fallback(self):
        l = dict(total=100, direction="bull", adx=30, cons=2, atr=0)
        f = dict(total=30, direction="bull", vote_confidence=0.5)
        assert db._extract_risk_input(l, f)["ATR"]["value"] > 0

    def test_detect_pattern(self):
        assert "衰竭阶段" in db._detect_pattern_risk(dict(adx=50, rsi=80, stage="exhaustion", cons=3), {})

    def test_detect_no_risk(self):
        assert db._detect_pattern_risk(dict(adx=25, rsi=50, stage="trending", cons=3), {}) == "无"

    def test_invalid_strong(self):
        assert "跌破25" in db._build_invalid_condition(dict(total=50, adx=45))

    def test_load_json(self, tmp_path):
        p = tmp_path / "t.json"
        p.write_text('{"k":"v"}', encoding="utf-8")
        assert db._load_json(str(p))["k"] == "v"


class TestBuildSignalSummary:
    def test_basic(self, tmp_path):
        l = tmp_path / "l.json"
        f = tmp_path / "f.json"
        l.write_text(
            json.dumps(
                {
                    "_meta": {},
                    "all_ranked": [
                        {
                            "symbol": "RB",
                            "total": 76,
                            "direction": "bull",
                            "name": "RB",
                            "adx": 60,
                            "rsi": 28,
                            "stage": "launch",
                            "cons": 3,
                            "veto": 0,
                            "atr": 45,
                            "z_score": 2.3,
                            "volume": 100,
                        },
                        {
                            "symbol": "HC",
                            "total": -30,
                            "direction": "bear",
                            "name": "HC",
                            "adx": 35,
                            "rsi": 30,
                            "stage": "trending",
                            "cons": 2,
                            "veto": 0,
                            "atr": 30,
                            "z_score": 1.8,
                            "volume": 50,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        f.write_text(
            json.dumps(
                {
                    "_meta": {},
                    "all_ranked": [
                        {
                            "symbol": "RB",
                            "total": -45,
                            "direction": "bear",
                            "vote_net": -3,
                            "vote_confidence": -0.65,
                            "g_group": "G10",
                        },
                        {
                            "symbol": "HC",
                            "total": -20,
                            "direction": "bear",
                            "vote_net": -2,
                            "vote_confidence": -0.5,
                            "g_group": "G1",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        s = db.build_signal_summary(str(l), str(f))
        assert s["_meta"]["total_symbols"] == 2
        syms = {x["symbol"]: x for x in s["symbols"]}
        assert syms["RB"]["l1l4"]["total"] == 76
        assert syms["HC"]["l1l4"]["total"] == -30

    def test_missing_symbols(self, tmp_path):
        l = tmp_path / "l.json"
        f = tmp_path / "f.json"
        l.write_text(
            json.dumps({"_meta": {}, "all_ranked": [{"symbol": "RB", "total": 50, "direction": "bull", "name": "RB"}]}),
            encoding="utf-8",
        )
        f.write_text(
            json.dumps({"_meta": {}, "all_ranked": [{"symbol": "HC", "total": -30, "direction": "bear"}]}),
            encoding="utf-8",
        )
        assert db.build_signal_summary(str(l), str(f))["_meta"]["total_symbols"] == 2

    def test_empty(self, tmp_path):
        l = tmp_path / "l.json"
        f = tmp_path / "f.json"
        l.write_text(json.dumps({"_meta": {}, "all_ranked": []}), encoding="utf-8")
        f.write_text(json.dumps({"_meta": {}, "all_ranked": []}), encoding="utf-8")
        assert db.build_signal_summary(str(l), str(f))["_meta"]["total_symbols"] == 0


class TestSelectDebateSymbols:
    def _sym(self, sym, lt=0, ld="n", ft=0, fd="n", adx=20, rsi=50, st="quiet", cs=1, vt=0, zs=0):
        return {
            "symbol": sym,
            "name": sym,
            "l1l4": dict(
                total=lt,
                direction=ld,
                adx=adx,
                rsi=rsi,
                stage=st,
                cons=cs,
                veto=vt,
                z_score=zs,
                grade="B",
                price=100,
                volume=100,
                ma_slope=0,
                macd_cross="none",
                dc20_break="none",
                ma_align="mixed",
                l1=0,
                l2=0,
                l3=0,
                l4=0,
            ),
            "risk_input": dict(confidence=50),
        }

    def test_divergence_first(self, sample_chain_map):
        s = [
            self._sym("RB", lt=76, ld="bull", ft=-45, fd="bear", adx=59, cs=3),
            self._sym("HC", lt=40, ld="bull", ft=30, fd="bull"),
        ]
        r = db.select_debate_symbols(dict(_meta={}, symbols=s), chain_map=sample_chain_map, min_count=1)
        assert r["debate_candidates"][0]["symbol"] == "RB"

    def test_judge_fields(self, sample_chain_map):
        s = [self._sym("RB", lt=76, ld="bull", ft=-45, fd="bear", adx=59, cs=3)]
        c = db.select_debate_symbols(dict(_meta={}, symbols=s), chain_map=sample_chain_map, min_count=1)[
            "debate_candidates"
        ][0]
        for k in ("quick_summary", "conflict", "strength", "risk_flags", "breakdown", "tags", "debate_value"):
            assert k in c

    def test_no_chain_map(self):
        s = [self._sym("RB", lt=50, ld="bull", ft=-30, fd="bear")]
        r = db.select_debate_symbols(dict(_meta={}, symbols=s), min_count=1)
        assert r["_meta"]["total_candidates"] >= 1

    def test_history_path(self, sample_chain_map, tmp_path):
        hp = tmp_path / "h.json"
        hp.write_text(
            '{"RB":{"debate_count":5,"high_value_count":4,"avg_judge_confidence":85,"win_rate":0.8,"avg_debate_value":82,"wins":4,"losses":1}}',
            encoding="utf-8",
        )
        s = [self._sym("RB", lt=50, ld="bull", ft=-30, fd="bear")]
        r = db.select_debate_symbols(
            dict(_meta={}, symbols=s), chain_map=sample_chain_map, min_count=1, history_path=str(hp)
        )
        rb = [c for c in r["debate_candidates"] if c["symbol"] == "RB"]
        if rb:
            assert "history_adjustment" in rb[0]
