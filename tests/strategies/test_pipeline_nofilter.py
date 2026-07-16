"""
Pipeline no-filter 语义测试（G43 no-filter 透传验证）
==================================================
验证 StrategyPipeline 在 ctx["filter_disabled"]=True 时：
- 验证器仍运行并附注 _validator_reason
- 但**不**把 grade/total 压成 NOISE/0（原始分保留）
而在 filter_disabled=False（默认）时正常降级。
"""
import pytest
from strategies.base_v2 import BaseStrategyV2, ScoredSignal
from strategies.pipeline import StrategyPipeline


def _make_kline(bars: int = 25):
    """前 20 根 high=110/low=90，末根 high=105/low=95（dc20 不破极值）。"""
    dlist = []
    for i in range(bars):
        dlist.append({
            "date": f"202607{10 + i:02d}", "open": 100.0, "high": 110.0,
            "low": 90.0, "close": 100.0, "volume": 1000.0, "oi": 5000.0,
        })
    dlist[-1]["high"] = 105.0
    dlist[-1]["low"] = 95.0
    return "daily", dlist


class _BreakoutStrategy(BaseStrategyV2):
    """声明 p0_4 验证器，产出会被 demote 的 dc20 信号。"""
    @property
    def name(self): return "tf"
    @property
    def validators(self): return ["p0_4_raw_kline"]
    def score(self, *a, **kw):
        return [ScoredSignal(symbol="TEST", direction="bull",
                             signal_type="trend_following.dc20",
                             strategy_name="tf", total=80, abs_score=80,
                             grade="STRONG")]


class TestNoFilterMode:
    def _ctx(self, disabled: bool):
        kline = {"TEST": _make_kline()}
        return {"filter_disabled": disabled, "kline_data": kline, "extra": {}}, kline

    def test_demote_applied_when_filter_enabled(self):
        ctx, kline = self._ctx(False)
        pipe = StrategyPipeline([_BreakoutStrategy()])
        result = pipe.run([{"symbol": "TEST", "price": 100.0}], kline, context=ctx)
        assert result["all_ranked"][0]["grade"] == "NOISE", "filter 启用时 dc20 不破应降级"

    def test_not_demoted_when_filter_disabled(self):
        ctx, kline = self._ctx(True)
        pipe = StrategyPipeline([_BreakoutStrategy()])
        result = pipe.run([{"symbol": "TEST", "price": 100.0}], kline, context=ctx)
        rank = result["all_ranked"][0]
        assert rank["grade"] == "STRONG", "no-filter 时原始 grade 应保留"
        assert rank.get("_validator_demoted") is False, "no-filter 时不应标记 demoted"
        assert rank["total"] == 80, "no-filter 时原始 total 应保留"
