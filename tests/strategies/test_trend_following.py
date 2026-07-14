"""
TrendFollowingStrategy v2 测试
"""
import pytest


class TestTrendFollowingV2:
    """趋势跟踪策略 v2 测试"""

    def test_strategy_interface(self):
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        assert s.name == "trend_following"
        assert "p0_4_raw_kline" in s.validators
        assert s.weight == 1.0

    def test_bull_signal_dc20_break(self):
        """DC20 上方突破 → 多头"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        signals = s.compute(tech, {})
        assert len(signals) == 1
        assert signals[0].direction == "bull"
        assert "dc20" in signals[0].signal_type

    def test_bear_signal_dc20_break(self):
        """DC20 下方突破 → 空头"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = [{"symbol": "RB", "price": 2800,
                 "dc20_high": 3100, "dc20_low": 2950,
                 "dc55_high": 3150, "dc55_low": 2900,
                 "bb": 0.02, "adx": 30}]
        signals = s.compute(tech, {})
        assert len(signals) == 1
        assert signals[0].direction == "bear"

    def test_no_signal_in_range(self):
        """价格在通道内 → 无信号"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = [{"symbol": "RB", "price": 3000,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2850,
                 "bb": 0.5, "adx": 20}]
        signals = s.compute(tech, {})
        assert len(signals) == 0

    def test_grade_mapping(self):
        """score() 根据强度映射 grade"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        from strategies.base_v2 import RawSignal
        s = TrendFollowingStrategy()
        raw = RawSignal(symbol="RB", direction="bull", signal_type="tf.dc20",
                        raw_score=0.9, strategy_name="trend_following", meta={})
        results = s.score([raw], [])
        assert results[0].grade == "STRONG"
        assert results[0].weight == 1.0

    def test_via_pipeline_with_fusion(self):
        """通过 StrategyPipeline 与其它策略融合"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        from strategies.pipeline import StrategyPipeline
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        pipe = StrategyPipeline([TrendFollowingStrategy()])
        result = pipe.run(tech, {}, {})
        assert len(result["all_ranked"]) == 1
        assert result["all_ranked"][0]["direction"] == "bull"
