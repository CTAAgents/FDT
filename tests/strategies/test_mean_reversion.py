"""
MeanReversionStrategy 测试 — RSI/CCI/布林带极端反转
"""
import pytest


class TestMeanReversion:
    """均值回归策略测试"""

    def test_strategy_interface(self):
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        assert s.name == "mean_reversion"
        assert "atr_vol_timing" in s.validators

    def test_rsi_oversold_bull_signal(self):
        """RSI<25 且 ADX<25 → 多头信号"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        signals = s.compute([{"symbol": "RB", "rsi": 15, "adx": 20, "cci": 0, "bb": 0.5, "price": 3000}], {})
        assert len(signals) == 1
        assert signals[0].direction == "bull"
        assert "rsi" in signals[0].meta["sub_types"]

    def test_rsi_overbought_bear_signal(self):
        """RSI>75 且 ADX<25 → 空头信号"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        signals = s.compute([{"symbol": "RB", "rsi": 85, "adx": 20, "cci": 0, "bb": 0.5, "price": 3000}], {})
        assert len(signals) == 1
        assert signals[0].direction == "bear"

    def test_cci_extreme_signal(self):
        """CCI<-200 → 多头信号"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        signals = s.compute([{"symbol": "RB", "rsi": 50, "adx": 20, "cci": -300, "bb": 0.5, "price": 3000}], {})
        assert len(signals) == 1
        assert signals[0].direction == "bull"
        assert "cci" in signals[0].meta["sub_types"]

    def test_bb_lower_reversal(self):
        """布林带 %b<0.1 → 多头信号"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        signals = s.compute([{"symbol": "RB", "rsi": 50, "adx": 20, "cci": 0, "bb": 0.05, "price": 3000}], {})
        assert len(signals) == 1
        assert signals[0].direction == "bull"

    def test_no_signal_in_strong_trend(self):
        """ADX>25 加趋势方向一致时不产生反转信号"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        signals = s.compute([{"symbol": "RB", "rsi": 15, "adx": 40, "cci": 0, "bb": 0.5, "price": 3000}], {})
        assert len(signals) == 0  # 趋势市中反转信号被抑制

    def test_score_maps_grade(self):
        """score() 根据强度映射 grade"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        from strategies.base_v2 import RawSignal
        s = MeanReversionStrategy()
        raw = RawSignal(symbol="RB", direction="bull", signal_type="mr.reversal",
                        raw_score=0.6, strategy_name="mean_reversion", meta={"rsi": 15})
        results = s.score([raw], [])
        assert results[0].grade == "WATCH"
        assert results[0].total > 0

    def test_via_pipeline(self):
        """接入 StrategyPipeline"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        from strategies.pipeline import StrategyPipeline
        pipe = StrategyPipeline([MeanReversionStrategy()])
        result = pipe.run([{"symbol": "RB", "rsi": 15, "adx": 20, "cci": 0, "bb": 0.05, "price": 3000}], {}, {})
        assert len(result["all_ranked"]) >= 1

    def test_kf_meta_fields_present(self):
        """KF 制度过滤器 meta 字段正确注入（无 kline_data → 缺省值）"""
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        s = MeanReversionStrategy()
        # 不传 kline_data → KF 跳过 → kf_regime_ok=True → 信号正常发出
        tech = {"symbol": "RB", "rsi": 15, "adx": 20, "cci": 0, "bb": 0.05, "price": 3000}
        signals = s.compute([tech], {})
        assert len(signals) == 1
        meta = signals[0].meta
        assert "kf_z_score" in meta
        assert "kf_suppressed" in meta
        assert meta["kf_z_score"] == 0.0  # 无 closes → 缺省值
        assert meta["kf_suppressed"] is False
