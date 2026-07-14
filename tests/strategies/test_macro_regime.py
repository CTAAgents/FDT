"""
MacroRegimeStrategy 测试
"""
import pytest


class TestMacroRegime:
    """宏观制度策略测试"""

    def test_strategy_interface(self):
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        s = MacroRegimeStrategy()
        assert s.name == "macro_regime"
        assert s.validators == []

    def test_bull_signal(self):
        """macro_signal=bull 时所有品种产出多头"""
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        s = MacroRegimeStrategy()
        tech = [{"symbol": "RB"}, {"symbol": "CU"}, {"symbol": "SC"}]
        signals = s.compute(tech, {}, {"macro_signal": "bull"})
        assert len(signals) == 3
        assert all(s.direction == "bull" for s in signals)

    def test_bear_signal(self):
        """macro_signal=bear 时所有品种产出空头"""
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        s = MacroRegimeStrategy()
        tech = [{"symbol": "RB"}, {"symbol": "CU"}]
        signals = s.compute(tech, {}, {"macro_signal": "bear"})
        assert all(s.direction == "bear" for s in signals)

    def test_neutral_no_signal(self):
        """macro_signal=neutral 时无信号"""
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        s = MacroRegimeStrategy()
        signals = s.compute([{"symbol": "RB"}], {}, {"macro_signal": "neutral"})
        assert len(signals) == 0

    def test_sector_tagging(self):
        """信号带板块标签"""
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        s = MacroRegimeStrategy()
        tech = [{"symbol": "RB"}, {"symbol": "CU"}]
        signals = s.compute(tech, {}, {"macro_signal": "bull"})
        rb = next(sig for sig in signals if sig.symbol == "RB")
        assert rb.meta["sector"] == "黑色"
        cu = next(sig for sig in signals if sig.symbol == "CU")
        assert cu.meta["sector"] == "有色"

    def test_score_weight_04(self):
        from strategies.macro_regime_strategy import MacroRegimeStrategy
        from strategies.base_v2 import RawSignal
        s = MacroRegimeStrategy()
        raw = RawSignal(symbol="RB", direction="bull", signal_type="macro.black",
                        raw_score=0.3, strategy_name="macro_regime", meta={})
        results = s.score([raw], [])
        assert results[0].weight == 0.4
