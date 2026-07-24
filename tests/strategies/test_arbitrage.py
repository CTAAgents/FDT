"""
ArbitrageStrategy 测试 — 跨期/跨品种/基差
"""


class TestArbitrageStrategy:
    """套利策略测试"""

    def test_strategy_interface(self):
        """实现 BaseStrategyV2 接口"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        s = ArbitrageStrategy()
        assert s.name == "arbitrage"
        assert s.signal_type == "arbitrage"
        assert "atr_vol_timing" in s.validators

    def test_compute_basis_signals(self):
        """基差>3% 时产出信号"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        s = ArbitrageStrategy()
        tech_list = [{"symbol": "RB", "price": 3100}]
        ctx = {"extra": {"basis_data": {"RB": {"basis_pct": 5.0}}}}
        signals = s.compute(tech_list, {}, ctx)
        rb_sigs = [sig for sig in signals if sig.symbol == "RB"]
        assert len(rb_sigs) == 1
        assert rb_sigs[0].direction == "bull"  # 基差正=现货强=偏多
        assert rb_sigs[0].meta["type"] == "basis"

    def test_compute_no_basis_no_signal(self):
        """基差<3% 时无信号"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        s = ArbitrageStrategy()
        tech_list = [{"symbol": "RB", "price": 3100}]
        ctx = {"extra": {"basis_data": {"RB": {"basis_pct": 1.0}}}}
        signals = s.compute(tech_list, {}, ctx)
        assert len(signals) == 0

    def test_compute_pair_signals(self):
        """跨品种配对偏差>2sigma 时产出信号"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        s = ArbitrageStrategy()
        tech_list = [
            {"symbol": "RB", "price": 3500},  # RB/HC ratio=1.4 > target 1.05
            {"symbol": "HC", "price": 2500},
        ]
        signals = s.compute(tech_list, {}, {})
        pair_sigs = [sig for sig in signals if sig.meta.get("type") == "pair"]
        assert len(pair_sigs) >= 1
        # RB-HC ratio 偏高(=1.1)，方向 bear（做空强势品种）
        assert pair_sigs[0].direction == "bear"

    def test_score_returns_scored_signals(self):
        """score() 产出 ScoredSignal 列表"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        from strategies.base_v2 import RawSignal
        s = ArbitrageStrategy()
        raw = [RawSignal(symbol="RB", direction="bull", signal_type="arbitrage.basis",
                         raw_score=5.0, strategy_name="arbitrage",
                         meta={"type": "basis", "basis_pct": 5.0})]
        results = s.score(raw, [])
        assert len(results) == 1
        assert results[0].total == 5.0
        assert results[0].direction == "bull"
        assert results[0].grade == "WATCH"

    def test_via_pipeline(self):
        """直接接入 StrategyPipeline"""
        from strategies.arbitrage_strategy import ArbitrageStrategy
        from strategies.pipeline import StrategyPipeline
        pipe = StrategyPipeline([ArbitrageStrategy()])
        ctx = {"extra": {"basis_data": {"RB": {"basis_pct": 5.0}}}}
        result = pipe.run([{"symbol": "RB", "price": 3100}], {}, ctx)
        assert len(result["all_ranked"]) >= 1
