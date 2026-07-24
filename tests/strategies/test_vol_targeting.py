"""
G32 Vol Targeting overlay 单元测试 + Pipeline 接线 + trade_plan 消费验证。
"""
import sys
from pathlib import Path

# 确保 scripts/ 在 sys.path（与项目 pytest 配置一致）
_SCRIPTS = str(Path(__file__).resolve().parents[2] / "skills" / "quant-daily" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
# 确保 skills config 优先于根目录 config（根目录不是包，无 __init__.py）
if "config" in sys.modules:
    del sys.modules["config"]


from strategies.base_v2 import BaseStrategyV2, RawSignal, ScoredSignal
from strategies.pipeline import StrategyFusion, StrategyPipeline
from strategies.vol_targeting import VolTargetingOverlay


# ───────────────────────────────────────────────────────────
# Overlay 单元
# ───────────────────────────────────────────────────────────
class TestVolTargetingOverlayUnit:
    def _sig(self, symbol="rb"):
        return ScoredSignal(
            symbol=symbol, direction="bull", signal_type="trend_following.dc20",
            strategy_name="trend_following", total=80.0, abs_score=80.0, grade="STRONG",
        )

    def test_apply_high_vol_downscales(self):
        o = VolTargetingOverlay()
        sig = o.apply(self._sig(), {"vol_target_scale": 0.5, "realized_vol": 0.30})
        assert sig.extra["vol_target_scale"] == 0.5
        assert "降仓" in sig.extra["vol_target_note"]

    def test_apply_low_vol_upsales(self):
        o = VolTargetingOverlay()
        sig = o.apply(self._sig(), {"vol_target_scale": 2.0, "realized_vol": 0.04})
        assert sig.extra["vol_target_scale"] == 2.0
        assert "加仓" in sig.extra["vol_target_note"]

    def test_apply_missing_tech_no_crash(self):
        o = VolTargetingOverlay()
        sig = o.apply(self._sig(), {})
        assert sig.extra["vol_target_scale"] == 1.0
        assert sig.extra["realized_vol"] == 0.0

    def test_apply_uppercase_fields(self):
        o = VolTargetingOverlay()
        sig = o.apply(self._sig(), {"VOL_SCALE": 0.3, "REALIZED_VOL": 0.40})
        assert sig.extra["vol_target_scale"] == 0.3

    def test_apply_non_dict_tech(self):
        o = VolTargetingOverlay()
        sig = o.apply(self._sig(), None)
        assert sig.extra["vol_target_scale"] == 1.0

    def test_compute_scale_pure(self):
        assert VolTargetingOverlay.compute_scale(0.50, 0.10, 0.2, 3.0) == 0.2
        assert VolTargetingOverlay.compute_scale(0.02, 0.10, 0.2, 3.0) == 3.0
        assert VolTargetingOverlay.compute_scale(0.0) == 1.0
        assert VolTargetingOverlay.compute_scale(0.20, 0.10, 0.2, 3.0) == 0.5


# ───────────────────────────────────────────────────────────
# Pipeline Phase 4.5 接线（NO_FUSION 默认）
# ───────────────────────────────────────────────────────────
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


class TestVolTargetingPipelineWiring:
    def test_overlay_injected_into_fused_signals(self):
        pipe = StrategyPipeline([_DummyTrend()], fusion=StrategyFusion())
        tech_list = [
            {"symbol": "rb", "vol_target_scale": 0.5, "realized_vol": 0.30},
        ]
        out = pipe.run(tech_list, {}, {})
        ranked = out["all_ranked"]
        assert len(ranked) == 1
        d = ranked[0]
        # to_dict() 将 extra 平铺到顶层
        assert d["vol_target_scale"] == 0.5
        assert d["realized_vol"] == 0.30
        assert "降仓" in d["vol_target_note"]

    def test_overlay_default_when_absent(self):
        pipe = StrategyPipeline([_DummyTrend()], fusion=StrategyFusion())
        tech_list = [{"symbol": "rb"}]
        out = pipe.run(tech_list, {}, {})
        d = out["all_ranked"][0]
        assert d["vol_target_scale"] == 1.0


# ───────────────────────────────────────────────────────────
# trade_plan 消费（G32 缩放仓位）
# ───────────────────────────────────────────────────────────
class TestTradePlanVolConsumption:
    def _symbol_data(self):
        return {"price": 3000.0, "score": 80, "atr": 30.0, "pid": "rb", "volatility": 0.02}

    def _composite(self):
        return {"direction": "BUY", "total": 85}

    def _tech(self, scale=1.0):
        # 含真实指标字段，使 calc_confidence 走 v2.11 共振确认路径、置信度过 0.4
        return {
            "vol_target_scale": scale,
            "RSI14": 60, "MACD_DIF": 5.0, "DMI_PDI": 30.0, "DMI_MDI": 20.0, "ADX": 40,
        }

    def test_high_vol_reduces_position(self):
        from signals.trade_plan import generate_trade_plan
        base = self._symbol_data()
        comp = self._composite()
        tp_full = generate_trade_plan(base, "bull", self._tech(1.0), {}, comp)
        tp_half = generate_trade_plan(base, "bull", self._tech(0.5), {}, comp)
        assert tp_full.get("decision") == "BUY" and tp_half.get("decision") == "BUY"
        pos_full = float(tp_full["position_size"].rstrip("%"))
        pos_half = float(tp_half["position_size"].rstrip("%"))
        # 高波动（0.5x）→ 仓位应明显更低（截断 [2,10] 内）
        assert pos_half < pos_full
        if pos_full > 2.0:
            assert abs(pos_half - pos_full * 0.5) < 1e-6

    def test_low_vol_increases_position(self):
        from signals.trade_plan import generate_trade_plan
        base = self._symbol_data()
        comp = self._composite()
        tp_full = generate_trade_plan(base, "bull", self._tech(1.0), {}, comp)
        tp_up = generate_trade_plan(base, "bull", self._tech(2.0), {}, comp)
        assert tp_full.get("decision") == "BUY" and tp_up.get("decision") == "BUY"
        pos_full = float(tp_full["position_size"].rstrip("%"))
        pos_up = float(tp_up["position_size"].rstrip("%"))
        assert pos_up > pos_full

    def test_neutral_scale_no_change(self):
        from signals.trade_plan import generate_trade_plan
        base = self._symbol_data()
        comp = self._composite()
        tp_a = generate_trade_plan(base, "bull", self._tech(1.0), {}, comp)
        # 缺 vol_target_scale 字段 → 默认 1.0，应与显式 1.0 一致
        tech_no_scale = {k: v for k, v in self._tech(1.0).items() if k != "vol_target_scale"}
        tp_b = generate_trade_plan(base, "bull", tech_no_scale, {}, comp)
        assert tp_a.get("decision") == "BUY" and tp_b.get("decision") == "BUY"
        assert tp_a["position_size"] == tp_b["position_size"]
