"""
TrendFollowingStrategy v2 测试

⚠️ 去融合（v8.1.8 掌柜铁律）：每个子信号独立产出 RawSignal，signal_type 命名空间独立
（trend_following.dc20 / .dc55 / .bb / .keltner / .supertrend / .sar / .chandelier /
.macd / .tsmom / .dual_thrust），禁止投票累加 / signal_type 拼接融合。
本测试据此断言：每个触发的子信号独立存在于结果中，且绝不存在 `trend_following.mixed`
或 `trend_following.dc20+keltner+...` 这类融合 signal_type。
"""
import pytest


class TestTrendFollowingV2:
    """趋势跟踪策略 v2 测试"""

    @staticmethod
    def _find(signals, sub: str):
        return [x for x in signals if x.signal_type == f"trend_following.{sub}"]

    @staticmethod
    def _assert_no_fusion(signals):
        for x in signals:
            assert "+" not in x.signal_type
            assert x.signal_type != "trend_following.mixed"

    def test_strategy_interface(self):
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        assert s.name == "trend_following"
        assert "p0_4_raw_kline" in s.validators
        assert s.weight == 1.0

    def test_bull_signal_dc20_break(self):
        """DC20 上方突破 → 多头（独立 dc20 子信号）。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        signals = s.compute(tech, {})
        self._assert_no_fusion(signals)
        dc20 = self._find(signals, "dc20")
        assert len(dc20) == 1
        assert dc20[0].direction == "bull"

    def test_bear_signal_dc20_break(self):
        """DC20 下方突破 → 空头（独立 dc20 子信号）。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = [{"symbol": "RB", "price": 2800,
                 "dc20_high": 3100, "dc20_low": 2950,
                 "dc55_high": 3150, "dc55_low": 2900,
                 "bb": 0.02, "adx": 30}]
        signals = s.compute(tech, {})
        self._assert_no_fusion(signals)
        dc20 = self._find(signals, "dc20")
        assert len(dc20) == 1
        assert dc20[0].direction == "bear"

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

    def test_via_pipeline_no_fusion(self):
        """通过 StrategyPipeline：去融合后每个子信号独立透传，无融合 signal_type。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        from strategies.pipeline import StrategyPipeline
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        pipe = StrategyPipeline([TrendFollowingStrategy()])
        result = pipe.run(tech, {}, {})
        ranked = result["all_ranked"]
        # dc20 + bb 各独立一条 → 至少 2 条
        assert len(ranked) >= 2
        stypes = {d["signal_type"] for d in ranked}
        assert "trend_following.dc20" in stypes
        # 去融合铁律：禁止拼接 / mixed
        for st in stypes:
            assert "+" not in st
            assert st != "trend_following.mixed"
        assert result["_meta"]["fusion_method"] == "no_fusion (disabled by design v8.1.8)"

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
        """价格突破 Keltner 上轨 → 多头，独立 keltner 子信号存在。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3150, kc_upper=3100, kc_lower=2900, kc_mid=3000)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        kl = self._find(sigs, "keltner")
        assert len(kl) == 1
        assert kl[0].direction == "bull"
        assert kl[0].meta["keltner_score"] > 0

    def test_keltner_bear_breakout(self):
        """价格跌破 Keltner 下轨 → 空头，独立 keltner 子信号存在。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=2850, kc_upper=3100, kc_lower=2900, kc_mid=3000)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        kl = self._find(sigs, "keltner")
        assert len(kl) == 1
        assert kl[0].direction == "bear"

    def test_supertrend_bull_state(self):
        """supertrend 方向=1 → 多头，独立 supertrend 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(supertrend=1)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        st = self._find(sigs, "supertrend")
        assert len(st) == 1
        assert st[0].direction == "bull"
        assert st[0].meta["supertrend_score"] > 0

    def test_sar_bull_state(self):
        """SAR 趋势=1 且收盘在 SAR 上方 → 多头，独立 sar 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3050, sar=3000, sar_trend=1)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        sar = self._find(sigs, "sar")
        assert len(sar) == 1
        assert sar[0].direction == "bull"

    def test_chandelier_bear_exit(self):
        """价格跌破 Chandelier 下轨(long exit) → 空头，独立 chandelier 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 带内（price 在 [ch_long, ch_short]）→ 中性，不发 chandelier 信号
        tech_in = self._base_tech(price=3000, chandelier_long=2950, chandelier_short=3050)
        sigs_in = s.compute(tech_in, {})
        # 带外下方（price < ch_long）→ 空头突破
        tech_out = self._base_tech(price=2900, chandelier_long=2950, chandelier_short=3050)
        sigs_out = s.compute(tech_out, {})
        self._assert_no_fusion(sigs_out)
        ch = self._find(sigs_out, "chandelier")
        assert len(ch) == 1
        assert ch[0].direction == "bear"

    def test_macd_bull_hist(self):
        """MACD DIF>DEA → 多头动量，独立 macd 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3000, macd_dif=20.0, macd_dea=10.0)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        macd = self._find(sigs, "macd")
        assert len(macd) == 1
        assert macd[0].direction == "bull"
        assert macd[0].meta["macd_score"] > 0

    def test_full_confluence_all_subs(self):
        """10 子信号全同向 → 去融合后各自独立产出 10 条信号，signal_type 互不拼接。"""
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
            dt_upper=3050, dt_lower=2950, dt_range=100,
        )
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        # 10 个子信号各独立一条
        subs = ("dc20", "dc55", "bb", "keltner", "supertrend", "sar",
                "chandelier", "macd", "tsmom", "dual_thrust")
        assert len(sigs) == len(subs), f"期望 {len(subs)} 条独立子信号，实际 {len(sigs)}"
        for sub in subs:
            found = self._find(sigs, sub)
            assert len(found) == 1, f"缺失/重复子信号 {sub}"
            assert found[0].direction == "bull"

    def test_tsmom_bull_multi_window(self):
        """TSMOM 四窗口全多头 → 多头，独立 tsmom 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(
            tsmom_1m=0.05, tsmom_3m=0.06, tsmom_6m=0.07, tsmom_12m=0.08,
        )
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        ts = self._find(sigs, "tsmom")
        assert len(ts) == 1
        assert ts[0].direction == "bull"
        assert ts[0].meta["tsmom_score"] > 0

    def test_tsmom_bear_multi_window(self):
        """TSMOM 四窗口全空头 → 空头，独立 tsmom 子信号。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(
            tsmom_1m=-0.05, tsmom_3m=-0.06, tsmom_6m=-0.07, tsmom_12m=-0.08,
        )
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        ts = self._find(sigs, "tsmom")
        assert len(ts) == 1
        assert ts[0].direction == "bear"

    def test_tsmom_partial_windows_vote(self):
        """仅部分窗口可用（其余缺失/0.0）→ 按可用窗口判定，不崩溃。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 仅 1m 正、其余缺失（_base_tech 默认无 tsmom 字段 → 0.0 被剔除）
        tech = self._base_tech(tsmom_1m=0.10)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        ts = self._find(sigs, "tsmom")
        assert len(ts) == 1
        assert ts[0].direction == "bull"
        # 单窗口 avg=0.10 → 满强 1.0
        assert ts[0].meta["tsmom_score"] == 1.0

    # ─────────────────────────────────────────────────────────
    # G33 Dual Thrust 日内突破测试
    # ─────────────────────────────────────────────────────────

    def test_dual_thrust_bull_breakout(self):
        """价格突破 Dual Thrust 上轨 → 多头，独立 dt 子信号存在。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=3100, dt_upper=3050, dt_lower=2950, dt_range=100)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        dt = self._find(sigs, "dual_thrust")
        assert len(dt) == 1
        assert dt[0].direction == "bull"
        assert dt[0].meta["dual_thrust_score"] > 0

    def test_dual_thrust_bear_breakout(self):
        """价格跌破 Dual Thrust 下轨 → 空头，独立 dt 子信号存在。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        tech = self._base_tech(price=2900, dt_upper=3050, dt_lower=2950, dt_range=100)
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        dt = self._find(sigs, "dual_thrust")
        assert len(dt) == 1
        assert dt[0].direction == "bear"
        assert dt[0].meta["dual_thrust_score"] > 0

    def test_dual_thrust_in_range_neutral(self):
        """价格在 Dual Thrust 轨内 → dt 不触发（仅 dt 触发时无信号）。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 轨内 price=3000（介于 [2950, 3050]），其它字段中性 → 无信号
        tech = self._base_tech(price=3000, dt_upper=3050, dt_lower=2950, dt_range=100)
        sigs = s.compute(tech, {})
        assert len(sigs) == 0

    def test_missing_g30_fields_no_crash(self):
        """G30 新字段缺失/为零 → 不崩溃，仅老 DC/BB 子信号独立生效（无 G30 子标签、无融合）。"""
        from strategies.trend_following_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy()
        # 仅提供老字段，新字段全缺
        tech = [{"symbol": "RB", "price": 3200,
                 "dc20_high": 3100, "dc20_low": 2900,
                 "dc55_high": 3150, "dc55_low": 2800,
                 "bb": 0.98, "adx": 30}]
        sigs = s.compute(tech, {})
        self._assert_no_fusion(sigs)
        # 仅 dc20 + bb 两条，不含任何 G30/G31/G33 子信号
        stypes = {x.signal_type for x in sigs}
        assert "trend_following.dc20" in stypes
        assert "trend_following.bb" in stypes
        for sub in ("keltner", "supertrend", "sar", "chandelier", "macd", "tsmom", "dual_thrust"):
            assert all(sub not in st for st in stypes), f"不应出现 {sub}"
