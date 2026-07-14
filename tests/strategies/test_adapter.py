"""
StrategyV1Adapter 测试 — v1 → v2 桥接兼容
"""
import pytest


class TestStrategyV1Adapter:
    """v1 → v2 适配器测试"""

    def _make_v1_mock(self):
        """创建一个模拟 v1 BaseStrategy。"""
        from strategies.base import BaseStrategy
        class MockV1(BaseStrategy):
            @property
            def name(self): return "mock_v1"
            @property
            def display_name(self): return "Mock V1 Strategy"
            def score(self, tech_list, mode="full", **kw):
                return {
                    "all_ranked": [
                        {
                            "symbol": "RB", "name": "螺纹钢",
                            "direction": "bear", "signal_type": "channel_breakout",
                            "total": -38, "abs": 38, "grade": "WEAK",
                            "price": 3100, "adx": 26.2, "rsi": 47.8,
                            "dc20": -30, "bb": -8,
                        },
                        {
                            "symbol": "SA", "name": "纯碱",
                            "direction": "bear", "signal_type": "channel_breakout",
                            "total": -78, "abs": 78, "grade": "STRONG",
                            "price": 1058, "adx": 50.8, "rsi": 28.7,
                            "dc20": -60, "bb": -18,
                        },
                    ],
                    "bull_signals": [],
                    "bear_signals": [
                        {"symbol": "RB", "total": -38, "abs": 38, "direction": "bear"},
                        {"symbol": "SA", "total": -78, "abs": 78, "direction": "bear"},
                    ],
                    "_meta": {"strategy": "channel_breakout"},
                }
        return MockV1()

    def test_adapter_interface(self):
        """适配器实现 BaseStrategyV2 接口"""
        from strategies.base_v2 import StrategyV1Adapter
        mock = self._make_v1_mock()
        adapter = StrategyV1Adapter(mock, validators=["atr_vol_timing"])
        assert adapter.name == "mock_v1"
        assert adapter.signal_type == "mock_v1"
        assert adapter.validators == ["atr_vol_timing"]
        assert adapter.weight == 1.0

    def test_adapter_score_converts_to_scored_signal(self):
        """score() 输出 ScoredSignal 列表"""
        from strategies.base_v2 import StrategyV1Adapter, ScoredSignal
        mock = self._make_v1_mock()
        adapter = StrategyV1Adapter(mock)
        tech_list = [{"symbol": "RB"}, {"symbol": "SA"}]
        signals = adapter.score([], tech_list)
        assert len(signals) == 2
        assert all(isinstance(s, ScoredSignal) for s in signals)
        assert signals[0].symbol == "RB"
        assert signals[0].total == -38
        assert signals[0].grade == "WEAK"
        assert signals[1].symbol == "SA"
        assert signals[1].total == -78
        assert signals[1].grade == "STRONG"

    def test_adapter_signal_type_namespace(self):
        """signal_type 带命名空间前缀"""
        from strategies.base_v2 import StrategyV1Adapter
        mock = self._make_v1_mock()
        adapter = StrategyV1Adapter(mock, signal_type="trend_following")
        signals = adapter.score([], [])
        assert signals[0].signal_type.startswith("trend_following.")

    def test_adapter_via_pipeline(self):
        """适配器可接入 StrategyPipeline"""
        from strategies.base_v2 import StrategyV1Adapter
        from strategies.pipeline import StrategyPipeline
        mock = self._make_v1_mock()
        adapter = StrategyV1Adapter(mock)
        pipeline = StrategyPipeline([adapter])
        result = pipeline.run([], {}, {})
        assert len(result["all_ranked"]) == 2
        assert result["all_ranked"][0]["symbol"] in ("RB", "SA")
