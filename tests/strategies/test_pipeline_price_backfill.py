"""
Pipeline 价格回填测试（G44 修复验证）
====================================
G44 根因：各策略 score() 未必透传 price，导致 ranking 中 price 恒为 0.0、
技术位距离测算缺基准。修复：pipeline Phase 4.7 从 tech_list 按 symbol 取
price/last_price 统一注入 ScoredSignal.price。
"""
import pytest
from strategies.base_v2 import BaseStrategyV2, ScoredSignal
from strategies.pipeline import StrategyPipeline


class _DummyNoPrice(BaseStrategyV2):
    """故意不传 price，模拟策略未透传（复现 G44）。"""
    @property
    def name(self): return "dummy"
    def score(self, *a, **kw):
        return [ScoredSignal(symbol="RB", direction="bear", signal_type="t",
                             strategy_name="dummy", total=-30, abs_score=30)]


class TestPriceBackfill:
    def test_price_injected_from_tech_price(self):
        tech = [{"symbol": "RB", "price": 3500.0, "adx": 30.0}]
        pipe = StrategyPipeline([_DummyNoPrice()])
        result = pipe.run(tech, {})
        assert result["all_ranked"][0]["price"] == 3500.0

    def test_price_injected_from_last_price_fallback(self):
        tech = [{"symbol": "RB", "last_price": 4200.5, "adx": 30.0}]
        pipe = StrategyPipeline([_DummyNoPrice()])
        result = pipe.run(tech, {})
        assert result["all_ranked"][0]["price"] == 4200.5

    def test_price_untouched_if_already_set(self):
        class _DummyWithPrice(BaseStrategyV2):
            @property
            def name(self): return "dp"
            def score(self, *a, **kw):
                return [ScoredSignal(symbol="RB", direction="bear", signal_type="t",
                                     strategy_name="dp", total=-30, abs_score=30,
                                     price=9999.0)]
        tech = [{"symbol": "RB", "price": 3500.0}]
        pipe = StrategyPipeline([_DummyWithPrice()])
        result = pipe.run(tech, {})
        # 策略已赋值（!=0）则不被覆盖
        assert result["all_ranked"][0]["price"] == 9999.0
