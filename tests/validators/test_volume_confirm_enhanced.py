"""
V2 volume_confirm OI+量比联合增强测试
======================================
测试 V2 在以下场景的正确降级/撤销降级行为：
1. 量比<0.8 且无 OI 数据 → 降级（原逻辑）
2. 量比<0.8 但 OI 暴增>15% → 撤销降级（undemote）
3. 量比>1.5 且 OI 萎缩<-10% → 降级
"""
from dataclasses import dataclass, field


@dataclass
class MockContext:
    kline_data: dict = field(default_factory=dict)
    higher_tf: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def _make_kline(close=100.0, volume=1000, oi=5000, bars=25):
    """生成模拟 K 线数据。"""
    dlist = []
    for i in range(bars):
        dlist.append({
            "date": f"202607{10+i:02d}",
            "open": float(close),
            "high": float(close * 1.01),
            "low": float(close * 0.99),
            "close": float(close * (1 + (i - bars + 1) * 0.001)),
            "volume": float(volume),
            "oi": float(oi),
        })
    return "daily", dlist


class TestVolumeConfirmEnhanced:
    """V2 OI+量比联合增强测试"""

    def _make_record(self, signal_type="channel_breakout", direction="bear", symbol="TEST"):
        return {
            "symbol": symbol,
            "direction": direction,
            "signal_type": signal_type,
            "grade": "WATCH",
            "total": -30,
            "price": 100.0,
            "atr": 2.0,
            "_raw_grade": "WATCH",
            "_raw_total": -30,
        }

    def test_low_volume_no_oi_demote(self):
        """量比<0.8 且无 OI 数据 → 正常降级"""
        from signals.validators.volume_confirm import validate_volume_confirm

        dlist = _make_kline(volume=1000, bars=25)
        ctx = MockContext(
            kline_data={"TEST": dlist},
            extra={"oi_data": {}},  # 无 OI 数据
        )
        r = self._make_record()
        # 修改前20根量很大，使量比<0.8
        for bar in dlist[1][-21:-1]:
            bar["volume"] = 50000
        dlist[1][-1]["volume"] = 1000  # 末根量小

        validate_volume_confirm(r, ctx)
        assert r["grade"] == "NOISE", "量比<0.8 无OI应降级"
        assert "突破无量" in r.get("_validator_reason", "")

    def test_v1_oi_surge_override(self):
        """V1 内部：量小但 OI 暴增>15% → V1 不降级（覆写非突破判定）"""
        from signals.validators.p0_4_raw_kline import validate_p0_4_raw_kline

        dlist = _make_kline(close=100.0, volume=1000, oi=5000, bars=25)
        # 使末根不突破前20根极值（触发 V1 伪突破判定）
        for bar in dlist[1][:-1]:
            bar["high"] = 110.0
            bar["low"] = 90.0
        dlist[1][-1]["high"] = 105.0  # 不突破前高110
        dlist[1][-1]["low"] = 95.0    # 不突破前低90

        ctx = MockContext(
            kline_data={"TEST": dlist},
            extra={
                "oi_data": {
                    "TEST": {"oi": 8000, "oi_avg": 4000, "oi_change_pct": 100.0}
                }
            },
        )
        r = self._make_record()
        validate_p0_4_raw_kline(r, ctx)
        assert r["grade"] != "NOISE", "OI暴增>15%即使V1判定突破不成立也不应降级"
        assert r.get("_oi_surge_reversal"), "应有 OI surge 标记"

    def test_high_volume_oi_shrink_demote(self):
        """量比>1.5 且 OI 萎缩<-10% → 降级"""
        from signals.validators.volume_confirm import validate_volume_confirm

        dlist = _make_kline(volume=1000, oi=5000, bars=25)
        ctx = MockContext(
            kline_data={"TEST": dlist},
            extra={
                "oi_data": {
                    "TEST": {"oi": 3000, "oi_avg": 6000, "oi_change_pct": -50.0}
                }
            },
        )
        r = self._make_record()
        for bar in dlist[1][-21:-1]:
            bar["volume"] = 1000
        dlist[1][-1]["volume"] = 50000  # 末根放量

        validate_volume_confirm(r, ctx)
        assert r["grade"] == "NOISE", "量比>1.5且OI萎缩应降级"
        assert "出货" in r.get("_validator_reason", "")
