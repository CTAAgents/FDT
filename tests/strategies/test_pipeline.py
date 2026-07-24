"""
StrategyPipeline + StrategyFusion 测试
"""
import pytest


class TestTopoSort:
    """拓扑排序测试"""

    def _make(self, name, weight=1.0, depends=None):
        from strategies.base_v2 import BaseStrategyV2, ScoredSignal
        deps = depends or []
        class Dummy(BaseStrategyV2):
            @property
            def n(self) -> str: return name
            @property
            def name(self): return self.n
            @property
            def depends_on(self): return deps
            def score(self, *a, **kw):
                return [ScoredSignal(symbol="RB", direction="bear", signal_type="t",
                                     strategy_name=name, total=-10, abs_score=10)]
        return Dummy()

    def test_no_deps(self):
        from strategies.pipeline import _topo_sort
        a, b = self._make("a", 1.0), self._make("b", 0.5)
        result = _topo_sort([b, a])
        assert [s.name for s in result] == ["b", "a"]

    def test_with_deps(self):
        from strategies.pipeline import _topo_sort
        a = self._make("a")
        b = self._make("b")
        c = self._make("c", depends=["a"])
        result = _topo_sort([b, c, a])
        names = [s.name for s in result]
        assert names.index("a") < names.index("c")

    def test_circular_detection(self):
        from strategies.base_v2 import BaseStrategyV2
        from strategies.pipeline import _topo_sort
        class CircularA(BaseStrategyV2):
            @property
            def name(self): return "circ_a"
            @property
            def depends_on(self): return ["circ_b"]
            def score(self, *a, **kw): return []
        class CircularB(BaseStrategyV2):
            @property
            def name(self): return "circ_b"
            @property
            def depends_on(self): return ["circ_a"]
            def score(self, *a, **kw): return []
        with pytest.raises(ValueError, match="Circular"):
            _topo_sort([CircularA(), CircularB()])


class TestStrategyFusion:
    """跨策略融合测试"""

    def _sig(self, name, direction="bear", total=-38, abs_score=38, weight=1.0, grade=None):
        from strategies.base_v2 import ScoredSignal
        kwargs = dict(symbol="RB", direction=direction, signal_type="t",
                      strategy_name=name, total=total, abs_score=abs_score,
                      weight=weight)
        if grade:
            kwargs["grade"] = grade
        return ScoredSignal(**kwargs)

    def test_weighted_max(self):
        from strategies.pipeline import StrategyFusion
        fusion = StrategyFusion(StrategyFusion.WEIGHTED_MAX)
        per = {"a": [self._sig("a", weight=1.0)], "b": [self._sig("b", total=-20, abs_score=20, weight=0.5)]}
        result = fusion.fuse(per)
        assert len(result) == 1
        assert result[0].total == -38
        assert "strategy_breakdown" in result[0].extra

    def test_weighted_avg(self):
        from strategies.pipeline import StrategyFusion
        fusion = StrategyFusion(StrategyFusion.WEIGHTED_AVG)
        per = {"a": [self._sig("a", weight=1.0)], "b": [self._sig("b", total=-20, abs_score=20, weight=0.5)]}
        result = fusion.fuse(per)
        expected = (-38 * 1.0 + -20 * 0.5) / 1.5
        assert abs(result[0].total - expected) < 0.1

    def test_signal_stack(self):
        from strategies.pipeline import StrategyFusion
        fusion = StrategyFusion(StrategyFusion.SIGNAL_STACK)
        per = {"a": [self._sig("a")], "b": [self._sig("b", total=-20, abs_score=20)]}
        result = fusion.fuse(per)
        assert result[0].extra["strategy_breakdown"]["a"]["total"] == -38
        assert result[0].extra["strategy_breakdown"]["b"]["total"] == -20

    def test_direction_conflict(self):
        from strategies.pipeline import StrategyFusion
        fusion = StrategyFusion(StrategyFusion.WEIGHTED_MAX)
        per = {"a": [self._sig("a", weight=1.0, grade="STRONG")],
               "b": [self._sig("b", direction="bull", total=20, abs_score=20, weight=0.5, grade="WEAK")]}
        result = fusion.fuse(per)
        assert len(result) == 2
        assert any(r.direction == "bear" and r.extra.get("direction_conflict") for r in result)
        assert any(r.direction == "bull" and r.extra.get("direction_conflict") for r in result)

    def test_unknown_method_raises(self):
        from strategies.pipeline import StrategyFusion
        with pytest.raises(ValueError):
            StrategyFusion("unknown_method")


class TestStrategyPipeline:
    """管线完整集成测试"""

    def _make_strategy(self, name, signals=None):
        from strategies.base_v2 import BaseStrategyV2, ScoredSignal
        sigs = signals or [ScoredSignal(symbol="RB", direction="bear", signal_type="t",
                                        strategy_name=name, total=-30, abs_score=30)]
        class Dummy(BaseStrategyV2):
            @property
            def name(self): return name
            def score(self, *a, **kw): return sigs
        return Dummy()

    def _pipeline(self, strategies):
        from strategies.pipeline import StrategyPipeline
        return StrategyPipeline(strategies)

    def test_empty_strategies_raises(self):
        with pytest.raises(ValueError):
            self._pipeline([])

    def test_single_strategy_run(self):
        pipe = self._pipeline([self._make_strategy("a")])
        result = pipe.run([], {})
        assert len(result["all_ranked"]) == 1
        assert result["all_ranked"][0]["symbol"] == "RB"
        assert result["_meta"]["strategies_run"] == ["a"]

    def test_multi_strategy_run(self):
        pipe = self._pipeline([self._make_strategy("a"), self._make_strategy("b")])
        result = pipe.run([], {})
        assert len(result["all_ranked"]) == 2
        assert "per_strategy" in result
        assert "a" in result["per_strategy"]
        assert "b" in result["per_strategy"]

    def test_bull_bear_partition(self):
        from strategies.base_v2 import BaseStrategyV2, ScoredSignal
        class BullStrategy(BaseStrategyV2):
            @property
            def name(self): return "bull"
            def score(self, *a, **kw):
                return [ScoredSignal(symbol="RB", direction="bull", signal_type="t",
                                     strategy_name="bull", total=50, abs_score=50,
                                     grade="WEAK")]
        class BearStrategy(BaseStrategyV2):
            @property
            def name(self): return "bear"
            def score(self, *a, **kw):
                return [ScoredSignal(symbol="SA", direction="bear", signal_type="t",
                                     strategy_name="bear", total=-60, abs_score=60,
                                     grade="WEAK")]
        pipe = self._pipeline([BullStrategy(), BearStrategy()])
        result = pipe.run([], {})
        assert len(result["bull_signals"]) == 1
        assert len(result["bear_signals"]) == 1


class TestSubSignalMerge:
    """Phase 4.8 同品种多子信号合并方向判定测试（修复方向覆盖 bug）。"""

    def _make_multi_sub_strategy(self, symbol, subs):
        from strategies.base_v2 import BaseStrategyV2, ScoredSignal

        class MultiSubStrategy(BaseStrategyV2):
            @property
            def name(self):
                return "trend_following"

            def score(self, *a, **kw):
                return [
                    ScoredSignal(
                        symbol=symbol,
                        direction=d,
                        signal_type=st,
                        strategy_name="trend_following",
                        total=t,
                        abs_score=abs_s,
                        grade=g,
                    )
                    for d, t, abs_s, g, st in subs
                ]

        return MultiSubStrategy()

    def test_sc_direction_majority_bull(self):
        """SC 场景：4 个看多子信号 vs 2 个看空子信号 → 合并后应为看多。"""
        subs = [
            ("bull", 50, 50.0, "STRONG", "trend_following.supertrend"),
            ("bull", 40, 40.0, "STRONG", "trend_following.sar"),
            ("bull", 47, 47.1, "STRONG", "trend_following.chandelier"),
            ("bull", 100, 100.0, "STRONG", "trend_following.macd"),
            ("bear", -95, 94.5, "STRONG", "trend_following.tsmom"),
            ("bear", -100, 100.0, "STRONG", "trend_following.dual_thrust"),
        ]
        import importlib

        import strategies.pipeline as _pipeline_mod
        importlib.reload(_pipeline_mod)
        from strategies.pipeline import StrategyPipeline

        pipe = StrategyPipeline([self._make_multi_sub_strategy("SC", subs)])
        result = pipe.run([], {})
        ranked = result["all_ranked"]
        assert len(ranked) == 1
        merged = ranked[0]
        assert merged["direction"] == "bull", (
            f"Expected bull but got {merged['direction']}. "
            f"total={merged['total']}, sub_signals count={len(merged.get('sub_signals', []))}"
        )
        expected_total = (50 + 40 + 47 + 100 - 95 - 100) / 6
        assert abs(merged["total"] - expected_total) < 1.0

    def test_all_bear_consensus(self):
        """全部看空子信号 → 合并后应为看空。"""
        subs = [
            ("bear", -80, 80.0, "STRONG", "trend_following.tsmom"),
            ("bear", -60, 60.0, "WATCH", "trend_following.dual_thrust"),
        ]
        from strategies.pipeline import StrategyPipeline

        pipe = StrategyPipeline([self._make_multi_sub_strategy("RB", subs)])
        result = pipe.run([], {})
        merged = result["all_ranked"][0]
        assert merged["direction"] == "bear"
        expected_total = (-80 - 60) / 2
        assert abs(merged["total"] - expected_total) < 1.0

    def test_neutral_balance(self):
        """多空完全平衡 → 合并后应为中性。"""
        subs = [
            ("bull", 50, 50.0, "STRONG", "trend_following.macd"),
            ("bear", -50, 50.0, "STRONG", "trend_following.tsmom"),
        ]
        from strategies.pipeline import StrategyPipeline

        pipe = StrategyPipeline([self._make_multi_sub_strategy("CU", subs)])
        result = pipe.run([], {})
        merged = result["all_ranked"][0]
        assert merged["direction"] == "neutral"
        assert abs(merged["total"]) < 1.0

    def test_grade_upgrade(self):
        """grade 应保留最高等级。"""
        subs = [
            ("bull", 30, 30.0, "WEAK", "trend_following.supertrend"),
            ("bull", 80, 80.0, "STRONG", "trend_following.macd"),
        ]
        from strategies.pipeline import StrategyPipeline

        pipe = StrategyPipeline([self._make_multi_sub_strategy("AL", subs)])
        result = pipe.run([], {})
        merged = result["all_ranked"][0]
        assert merged["grade"] == "STRONG"
