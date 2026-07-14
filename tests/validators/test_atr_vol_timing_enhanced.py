"""
V3 atr_vol_timing 基差+低波联合增强测试
========================================
测试 V3 在以下场景的正确降级/撤销降级行为：
1. ATR%<0.5% 且无基差数据 → 降级（原逻辑）
2. ATR%<0.5% 但基差走阔>2% → 撤销降级（undemote）
3. ATR%>4% 且基差收缩<-2% → 降级
"""
import pytest
from dataclasses import dataclass, field


@dataclass
class MockContext:
    kline_data: dict = field(default_factory=dict)
    higher_tf: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


class TestAtrVolTimingEnhanced:
    """V3 基差+低波联合增强测试"""

    def _make_record(self, signal_type="channel_breakout", direction="bear",
                     symbol="TEST", atr=0.3, price=100.0):
        """ATR%=0.3% → 低于 0.5% 阈值，正常会降级"""
        return {
            "symbol": symbol,
            "direction": direction,
            "signal_type": signal_type,
            "grade": "WATCH",
            "total": -30,
            "price": price,
            "atr": atr,
            "_raw_grade": "WATCH",
            "_raw_total": -30,
        }

    def test_low_atr_no_basis_demote(self):
        """ATR%<0.5% 且无基差数据 → 正常降级"""
        from signals.validators.atr_vol_timing import validate_atr_vol_timing

        ctx = MockContext(
            kline_data={},
            extra={"basis_data": {}},
        )
        r = self._make_record(atr=0.3, price=100.0)  # ATR%=0.3%

        validate_atr_vol_timing(r, ctx)
        assert r["grade"] == "NOISE", "ATR%<0.5% 无基差应降级"
        assert "低波动" in r.get("_validator_reason", "")

    def test_v1_basis_widen_override(self):
        """V1 内部：低波但基差走阔>2% → V1 不降级"""
        from signals.validators.p0_4_raw_kline import validate_p0_4_raw_kline

        dlist = ("daily", [
            {"date": f"202607{10+i:02d}", "open": 100.0, "high": 110.0,
             "low": 90.0, "close": 100.0, "volume": 1000, "oi": 5000}
            for i in range(25)
        ])
        # 末根不突破极值
        dlist[1][-1]["high"] = 105.0
        dlist[1][-1]["low"] = 95.0

        ctx = MockContext(
            kline_data={"TEST": dlist},
            extra={
                "basis_data": {
                    "TEST": {
                        "basis": 5.0, "basis_pct": 3.5, "spot": 105,
                        "futures": 100, "unit": "元/吨",
                    }
                }
            },
        )
        r = self._make_record(atr=0.3, price=100.0)
        validate_p0_4_raw_kline(r, ctx)
        assert r["grade"] != "NOISE", "基差走阔>2%应覆写伪突破判定"
        assert r.get("_strangle_compressed"), "应有弹簧压缩标记"

    def test_high_atr_basis_shrink_demote(self):
        """ATR%>4% 且基差收缩<-2% → 降级"""
        from signals.validators.atr_vol_timing import validate_atr_vol_timing

        ctx = MockContext(
            kline_data={},
            extra={
                "basis_data": {
                    "TEST": {
                        "basis": -5.0, "basis_pct": -3.5, "spot": 95,
                        "futures": 100, "unit": "元/吨",
                    }
                }
            },
        )
        r = self._make_record(atr=5.0, price=100.0)  # ATR%=5%

        validate_atr_vol_timing(r, ctx)
        assert r["grade"] == "NOISE", "高波+基差收缩应降级"
        assert "过热" in r.get("_validator_reason", "")
