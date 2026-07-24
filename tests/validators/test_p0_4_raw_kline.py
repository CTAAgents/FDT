"""
P0-4 原始K线重校验门禁测试（含 G43 类别错误修复验证）
====================================================
G43 根因：P0-4 伪突破校验原对**所有** trend_following 子信号无差别套用
"末根必须突破前20根极值"，把 supertrend/sar/macd/tsmom/chandelier 等非突破
子信号误判为伪突破并降级 total=0。
修复后仅 dc20/dc55 真唐奇安突破进入 P0-4，非突破子信号放行。

测试：
1. _is_v2_breakout 路由正确（dc20/dc55=True；其他 trend 子信号=False）
2. 非突破子信号（supertrend）不被误降
3. 真突破子信号（dc20）末根不破仍被降
"""
from dataclasses import dataclass, field

import pytest


@dataclass
class MockContext:
    kline_data: dict = field(default_factory=dict)
    higher_tf: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def _make_kline(bars: int = 25):
    """前 20 根 high=110/low=90，末根 high=105/low=95（不破极值）。"""
    dlist = []
    for i in range(bars):
        dlist.append({
            "date": f"202607{10 + i:02d}",
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 100.0,
            "volume": 1000.0,
            "oi": 5000.0,
        })
    dlist[-1]["high"] = 105.0
    dlist[-1]["low"] = 95.0
    return "daily", dlist


class TestIsV2Breakout:
    def test_dc20_true(self):
        from signals.validators.p0_4_raw_kline import _is_v2_breakout
        assert _is_v2_breakout("trend_following.dc20") is True

    def test_dc55_true(self):
        from signals.validators.p0_4_raw_kline import _is_v2_breakout
        assert _is_v2_breakout("trend_following.dc55") is True

    @pytest.mark.parametrize("sig", [
        "trend_following.supertrend", "trend_following.sar",
        "trend_following.macd", "trend_following.tsmom",
        "trend_following.chandelier", "trend_following.bb",
        "trend_following.keltner", "trend_following.dual_thrust",
    ])
    def test_non_breakout_false(self, sig):
        from signals.validators.p0_4_raw_kline import _is_v2_breakout
        assert _is_v2_breakout(sig) is False

    def test_non_trend_prefix_false(self):
        from signals.validators.p0_4_raw_kline import _is_v2_breakout
        assert _is_v2_breakout("mean_reversion.rsi") is False


class TestG43NoFalseDemote:
    def _rec(self, signal_type, direction="bull", grade="STRONG", total=80):
        return {
            "symbol": "TEST", "direction": direction, "signal_type": signal_type,
            "grade": grade, "total": total, "price": 100.0,
            "_raw_grade": grade, "_raw_total": total,
        }

    def test_supertrend_not_demoted(self):
        """非突破子信号 supertrend 末根不破极值，不应被 P0-4 误降。"""
        from signals.validators.p0_4_raw_kline import validate_p0_4_raw_kline
        ctx = MockContext(kline_data={"TEST": _make_kline()}, extra={})
        r = self._rec("trend_following.supertrend")
        validate_p0_4_raw_kline(r, ctx)
        assert r["grade"] == "STRONG", "supertrend 非突破信号不应被 P0-4 误降"
        assert r.get("_validator_demoted", False) is False

    def test_dc20_demoted_when_not_broken(self):
        """真突破子信号 dc20 末根不破极值，应被 P0-4 降级。"""
        from signals.validators.p0_4_raw_kline import validate_p0_4_raw_kline
        ctx = MockContext(kline_data={"TEST": _make_kline()}, extra={})
        r = self._rec("trend_following.dc20")
        validate_p0_4_raw_kline(r, ctx)
        assert r["grade"] == "NOISE", "dc20 末根不破极值应被 P0-4 降级"
        assert r.get("_validator_demoted") is True
