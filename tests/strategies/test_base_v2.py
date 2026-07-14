"""
BaseStrategyV2 / RawSignal / ScoredSignal 接口测试
"""
import pytest


class TestRawSignal:
    """RawSignal 数据契约测试"""

    def _signal(self, raw_score=-30, **kw):
        import sys, os; p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "skills", "quant-daily", "scripts"); sys.path.insert(0, p)
        from strategies.base_v2 import RawSignal
        base = dict(symbol="RB", direction="bear", signal_type="test.a",
                     raw_score=raw_score, strategy_name="test")
        base.update(kw)
        return RawSignal(**base)

    def test_minimal_fields(self):
        s = self._signal()
        assert s.symbol == "RB"
        assert s.direction == "bear"
        assert s.signal_type == "test.a"
        assert s.raw_score == -30

    def test_default_meta_empty(self):
        s = self._signal(raw_score=0)
        assert s.meta == {}


class TestScoredSignal:
    """ScoredSignal 数据契约 + to_dict 测试"""

    def _signal(self, **kw):
        from strategies.base_v2 import ScoredSignal
        return ScoredSignal(symbol="RB", direction="bear", signal_type="t.a",
                            strategy_name="test", **kw)

    def test_minimal_fields(self):
        s = self._signal()
        assert s.grade == "NOISE"
        assert s.weight == 1.0

    def test_to_dict_contains_key_fields(self):
        s = self._signal(total=-38, abs_score=38, grade="WEAK", price=3100, adx=26.2)
        d = s.to_dict()
        assert d["symbol"] == "RB"
        assert d["direction"] == "bear"
        assert d["strategy"] == "test"
        assert d["total"] == -38
        assert d["grade"] == "WEAK"

    def test_to_dict_sub_scores_merged(self):
        s = self._signal(sub_scores={"dc20": -30, "bb": -8})
        d = s.to_dict()
        assert d["dc20"] == -30
        assert d["bb"] == -8

    def test_to_dict_extra_merged(self):
        s = self._signal(extra={"strategy_breakdown": {"test": {"total": -38}}})
        d = s.to_dict()
        assert "strategy_breakdown" in d

    def test_to_dict_raw_fields(self):
        s = self._signal(_raw_total=-38, _raw_grade="WEAK")
        d = s.to_dict()
        assert d["_raw_total"] == -38
        assert d["_raw_grade"] == "WEAK"


class TestBaseStrategyV2:
    """BaseStrategyV2 接口约定测试"""

    def _make(self, **overrides):
        from strategies.base_v2 import BaseStrategyV2
        class MyStrategy(BaseStrategyV2):
            @property
            def name(self) -> str: return overrides.get("name", "my_test")
            @property
            def signal_type(self) -> str: return overrides.get("signal_type", self.name)
            @property
            def validators(self) -> list: return overrides.get("validators", [])
            @property
            def weight(self) -> float: return overrides.get("weight", 1.0)
            @property
            def depends_on(self) -> list: return overrides.get("depends_on", [])
            def score(self, *a, **kw): return []
        return MyStrategy()

    def test_cannot_instantiate_abstract(self):
        from strategies.base_v2 import BaseStrategyV2
        with pytest.raises(TypeError):
            BaseStrategyV2()

    def test_concrete_strategy_works(self):
        s = self._make()
        assert s.name == "my_test"
        assert s.signal_type == "my_test"
        assert s.validators == []
        assert s.weight == 1.0
        assert s.depends_on == []
        assert s.compute([], {}) == []
        assert s.filter([], {}) == []

    def test_signal_type_override(self):
        s = self._make(signal_type="custom_ns")
        assert s.signal_type == "custom_ns"

    def test_validators_override(self):
        s = self._make(validators=["atr_vol_timing", "volume_confirm"])
        assert "atr_vol_timing" in s.validators
        assert len(s.validators) == 2
