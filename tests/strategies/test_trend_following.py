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

    # ─────────────────────────────────────────────────────────
    # G30 指标衍生子策略测试
    # ─────────────────────────────────────────────────────────

    def _base_tech(self, **overrides):
        """构造带全部 G30 字段的基准 tech dict（中性默认值）。"""
        tech = {
            "symbol": "RB", "price": 3000,
            "dc20_high": 3100, "dc20_low": 2900,
            "dc55_high": 3150, "dc55_low": 2850,
            "bb": 0.5, "adx": 20,
            # Keltner（中轨3000，半宽100）
            "kc_upper": 3100, "kc_lower": 2900, "kc_mid": 3000,
            # Supertrend 方向
            "supertrend": 0,
            # SAR
            "sar": 3000, "sar_trend": 0,
            # Chandelier（long 线 2950 / short 线 3050）
            "chandelier_long": 2950, "chandelier_short": 3050,
            # MACD
            "macd_dif": 0.0, "macd_dea": 0.0,
        }
        tech.update(overrides)
        return [tech]

    def test_keltner_bull_breakout(self):
        """价格突破 Keltner 上轨 → 多头，命中 keltner 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3150, kc_upper=3100, kc_lower=2900, kc_mid=3000)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "keltner" in sigs[0].signal_type
        assert sigs[0].meta["keltner_score"] > 0

    def test_keltner_bear_breakout(self):
        """价格跌破 Keltner 下轨 → 空头。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=2850, kc_upper=3100, kc_lower=2900, kc_mid=3000)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bear"
        assert "keltner" in sigs[0].signal_type

    def test_supertrend_bull_state(self):
        """supertrend 方向=1 → 多头，命中 supertrend 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(supertrend=1)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "supertrend" in sigs[0].signal_type
        assert sigs[0].meta["supertrend_score"] > 0

    def test_sar_bull_state(self):
        """SAR 趋势=1 且收盘在 SAR 上方 → 多头，命中 sar 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3050, sar=3000, sar_trend=1)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "sar" in sigs[0].signal_type

    def test_chandelier_bear_exit(self):
        """价格跌破 Chandelier 下轨(long exit) → 空头，命中 chandelier 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 带内（price 在 [ch_long, ch_short]）→ 中性，不发 chandelier 信号
        tech_in = self._base_tech(price=3000, chandelier_long=2950, chandelier_short=3050)
        sigs_in = s.compute(tech_in, {})
        # 带外下方（price < ch_long）→ 空头突破
        tech_out = self._base_tech(price=2900, chandelier_long=2950, chandelier_short=3050)
        sigs_out = s.compute(tech_out, {})
        assert len(sigs_out) == 1
        assert sigs_out[0].direction == "bear"
        assert "chandelier" in sigs_out[0].signal_type

    def test_macd_bull_hist(self):
        """MACD DIF>DEA → 多头动量，命中 macd 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3000, macd_dif=20.0, macd_dea=10.0)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "macd" in sigs[0].signal_type
        assert sigs[0].meta["macd_score"] > 0

    def test_full_confluence_all_subs(self):
        """9 子信号全同向 → 子类型标签携全清单，raw 显著高于单信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(
            price=3200, dc20_high=3100, dc20_low=2900, dc55_high=3150, dc55_low=2800,
            bb=0.98, adx=35,
            kc_upper=3100, kc_lower=2900, kc_mid=3000,
            supertrend=1, sar=3000, sar_trend=1,
            chandelier_long=2950, chandelier_short=3050,
            macd_dif=20.0, macd_dea=10.0,
            tsmom_1m=0.05, tsmom_3m=0.06, tsmom_6m=0.07, tsmom_12m=0.08,
        )
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        st = sigs[0].signal_type
        for sub in ("dc20", "dc55", "bb", "keltner", "supertrend", "sar", "chandelier", "macd", "tsmom"):
            assert sub in st, f"缺失子信号 {sub}"
        # 全共振 raw 应高于仅 DC20 突破的 raw
        single = self._base_tech(price=3200, dc20_high=3100, dc20_low=2900,
                                 bb=0.98, dc55_high=3150, dc55_low=2800)
        s_single = s.compute(single, {})
        assert sigs[0].raw_score > s_single[0].raw_score

    def test_tsmom_bull_multi_window(self):
        """TSMOM 四窗口全多头 → 多头，命中 tsmom 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(
            tsmom_1m=0.05, tsmom_3m=0.06, tsmom_6m=0.07, tsmom_12m=0.08,
        )
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "tsmom" in sigs[0].signal_type
        assert sigs[0].meta["tsmom_score"] > 0

    def test_tsmom_bear_multi_window(self):
        """TSMOM 四窗口全空头 → 空头，命中 tsmom 子标签。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(
            tsmom_1m=-0.05, tsmom_3m=-0.06, tsmom_6m=-0.07, tsmom_12m=-0.08,
        )
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bear"
        assert "tsmom" in sigs[0].signal_type

    def test_tsmom_partial_windows_vote(self):
        """仅部分窗口可用（其余缺失/0.0）→ 按可用窗口投票，不崩溃。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 仅 1m 正、其余缺失（_base_tech 默认无 tsmom 字段 → 0.0 被剔除）
        tech = self._base_tech(tsmom_1m=0.10)
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        assert "tsmom" in sigs[0].signal_type
        # 单窗口 avg=0.10 → 满强 1.0
        assert sigs[0].meta["tsmom_score"] == 1.0

    def test_missing_g30_fields_no_crash(self):
        """G30 新字段缺失/为零 → 不崩溃，仅老 DC/BB 信号生效。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 仅提供老字段，新字段全缺
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        sigs = s.compute(tech, {})
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"
        # 不应含任何 G30 子标签
        for sub in ("keltner", "supertrend", "sar", "chandelier", "macd"):
            assert sub not in sigs[0].signal_type
