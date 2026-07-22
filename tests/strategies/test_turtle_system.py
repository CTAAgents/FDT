"""
G34 Turtle 完整系统 overlay 单元测试 + Pipeline 接线 + trade_plan 消费验证。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 scripts/ 在 sys.path（与项目 pytest 配置一致）
_SCRIPTS = str(Path(__file__).resolve().parents[2] / "skills" / "quant-daily" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
# 确保 skills config 优先于根目录 config（根目录不是包，无 __init__.py）
if "config" in sys.modules:
    del sys.modules["config"]

from futures_data_core.indicators.tdx_compat import calculate_turtle_n
from strategies.base_v2 import BaseStrategyV2, RawSignal, ScoredSignal
from strategies.turtle_system import TurtleSystemOverlay
from strategies.pipeline import StrategyPipeline, StrategyFusion


# ───────────────────────────────────────────────────
# 指标单元：calculate_turtle_n
# ───────────────────────────────────────────────────
class TestCalculateTurtleN:
    def test_constant_tr_converges(self):
        # 构造 TR 恒为 2 → N 应收敛到 2.0
        c = np.arange(1.0, 41.0)  # 40 根
        h = c + 1.0
        l = c - 1.0
        out = calculate_turtle_n(h, l, c, window=20)
        assert np.isfinite(out[-1])
        assert abs(out[-1] - 2.0) < 1e-6

    def test_insufficient_length_nan(self):
        c = np.array([1.0, 2.0, 3.0])
        out = calculate_turtle_n(c, c, c, window=20)
        assert len(out) == 3
        assert np.all(np.isnan(out))

    def test_finite_positive_random(self):
        rng = np.random.default_rng(0)
        c = np.cumsum(rng.normal(0, 1, 60)) + 100
        h = c + np.abs(rng.normal(0, 0.5, 60))
        l = c - np.abs(rng.normal(0, 0.5, 60))
        out = calculate_turtle_n(h, l, c, window=20)
        assert np.isfinite(out[-1]) and out[-1] > 0


# ───────────────────────────────────────────────────
# Overlay 单元
# ───────────────────────────────────────────────────
class TestTurtleSystemOverlayUnit:
    def _sig(self, direction="bull", abs_score=80.0):
        return ScoredSignal(
            symbol="rb", direction=direction, signal_type="trend_following.dc20",
            strategy_name="trend_following", total=abs_score, abs_score=abs_score, grade="STRONG",
        )

    def _tech(self, n=2.0, close=3500.0, dc20_h=3480.0, dc20_l=3450.0):
        return {
            "turtle_n": n, "last_price": close,
            "dc20_high": dc20_h, "dc20_low": dc20_l,
            "dc55_high": 3600.0, "dc55_low": 3400.0,
        }

    def test_bull_s1_units_by_score(self):
        o = TurtleSystemOverlay()
        sig = o.apply(self._sig("bull", 80.0), self._tech())
        assert sig.extra["turtle_system"] == "S1"
        assert sig.extra["turtle_units"] == 2
        # 加仓阶 = close + 0.5*N*1 = 3500 + 1.0 = 3501
        assert sig.extra["turtle_add_steps"] == [3501.0]
        assert sig.extra["turtle_stop_2n"] == round(3500.0 - 2.0 * 2.0, 2)  # 3496

    def test_bear_s2(self):
        o = TurtleSystemOverlay()
        tech = {"turtle_n": 3.0, "last_price": 3500.0,
                 "dc20_high": 3600.0, "dc20_low": 3400.0,
                 "dc55_high": 3520.0, "dc55_low": 3550.0}
        # close=3500 < dc55_low=3550 → S2 bear；dc20 都未突破 → s1 none
        sig = o.apply(self._sig("bear", 90.0), tech)
        assert sig.extra["turtle_system"] == "S2"
        assert sig.extra["turtle_units"] == 3  # 90>=85

    def test_neutral_direction(self):
        o = TurtleSystemOverlay()
        sig = o.apply(self._sig("neutral"), self._tech())
        assert sig.extra["turtle_system"] == "none"
        assert sig.extra["turtle_units"] == 1
        assert sig.extra["turtle_add_steps"] == []

    def test_missing_tech_no_crash(self):
        o = TurtleSystemOverlay()
        sig = o.apply(self._sig(), {})
        assert sig.extra["turtle_n"] == 0.0
        assert sig.extra["turtle_units"] == 1
        assert "未触发" in sig.extra["turtle_note"]

    def test_extreme_score_4_units(self):
        o = TurtleSystemOverlay()
        sig = o.apply(self._sig("bull", 95.0), self._tech())
        assert sig.extra["turtle_units"] == 4
        # 4 单位 → 加仓阶 k=1,2,3
        assert len(sig.extra["turtle_add_steps"]) == 3


# ───────────────────────────────────────────────────
# Pipeline Phase 4.6 接线（NO_FUSION 默认）
# ───────────────────────────────────────────────────
class _DummyTrend(BaseStrategyV2):
    @property
    def name(self):
        return "trend_following"

    @property
    def signal_type(self):
        return "trend_following"

    def compute(self, tech_list, kline_data, context=None):
        syms = [t.get("symbol") for t in tech_list if isinstance(t, dict)]
        return [
            RawSignal(symbol=s, direction="bull",
                      signal_type="trend_following.dc20", raw_score=80.0,
                      strategy_name="trend_following", meta={})
            for s in syms
        ]

    def score(self, filtered, tech_list, context=None):
        return [
            ScoredSignal(symbol=r.symbol, direction="bull",
                         signal_type=r.signal_type, strategy_name="trend_following",
                         total=80.0, abs_score=80.0, grade="STRONG")
            for r in filtered
        ]


class TestTurtlePipelineWiring:
    def test_overlay_injected_into_fused_signals(self):
        pipe = StrategyPipeline([_DummyTrend()], fusion=StrategyFusion())
        tech_list = [
            {"symbol": "rb", "turtle_n": 2.0, "last_price": 3500.0,
             "dc20_high": 3480.0, "dc20_low": 3450.0,
             "dc55_high": 3600.0, "dc55_low": 3400.0},
        ]
        out = pipe.run(tech_list, {}, {})
        d = out["all_ranked"][0]
        # to_dict() 将 extra 平铺到顶层
        assert d["turtle_system"] == "S1"
        assert d["turtle_units"] == 2
        assert d["turtle_n"] == 2.0
        assert "加仓" in d["turtle_note"]


# ───────────────────────────────────────────────────
# trade_plan 消费（G34 单位预算缩放仓位）
# ───────────────────────────────────────────────────
class TestTradePlanTurtleConsumption:
    def _symbol_data(self):
        return {"price": 3000.0, "score": 85, "atr": 30.0, "pid": "rb", "volatility": 0.02}

    def _composite(self):
        return {"direction": "BUY", "total": 85}

    def _tech(self, units=1):
        return {
            "vol_target_scale": 1.0,
            "turtle_units": units,
            "RSI14": 60, "MACD_DIF": 5.0, "DMI_PDI": 30.0, "DMI_MDI": 20.0, "ADX": 40,
        }

    def test_more_units_increases_position(self):
        from signals.trade_plan import generate_trade_plan
        base = self._symbol_data()
        comp = self._composite()
        tp1 = generate_trade_plan(base, "bull", self._tech(1), {}, comp)
        tp4 = generate_trade_plan(base, "bull", self._tech(4), {}, comp)
        assert tp1.get("decision") == "BUY" and tp4.get("decision") == "BUY"
        pos1 = float(tp1["position_size"].strip("%"))
        pos4 = float(tp4["position_size"].strip("%"))
        assert pos4 > pos1

    def test_absent_units_no_change(self):
        from signals.trade_plan import generate_trade_plan
        base = self._symbol_data()
        comp = self._composite()
        tp_a = generate_trade_plan(base, "bull", self._tech(1), {}, comp)
        tech_no = {k: v for k, v in self._tech(1).items() if k != "turtle_units"}
        tp_b = generate_trade_plan(base, "bull", tech_no, {}, comp)
        assert tp_a.get("decision") == "BUY" and tp_b.get("decision") == "BUY"
        assert tp_a["position_size"] == tp_b["position_size"]
