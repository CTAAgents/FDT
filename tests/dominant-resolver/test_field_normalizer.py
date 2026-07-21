"""
FieldNormalizer 字段标准化器测试 — 8 类不一致点的覆盖验证。
"""

from __future__ import annotations

import pytest

from futures_data_core.core.field_normalizer import (
    CanonicalField,
    normalize_kline_row,
    normalize_kline_list,
    normalize_signal_row,
    normalize_signal_list,
    normalize_verdict,
    normalize_risk_check,
    normalize_direction_raw,
    normalize_direction_to_signal,
    normalize_confidence_raw,
    normalize_grade_raw,
)


class TestCanonicalField:
    """规范字段名常量正确性。"""

    def test_direction_normalization(self):
        assert normalize_direction_raw("bull") == "bull"
        assert normalize_direction_raw("Bullish") == "bull"
        assert normalize_direction_raw("BUY") == "bull"
        assert normalize_direction_raw("bear") == "bear"
        assert normalize_direction_raw("bearish") == "bear"
        assert normalize_direction_raw("SELL") == "bear"
        assert normalize_direction_raw("neutral") == "neutral"
        assert normalize_direction_raw("HOLD") == "neutral"
        assert normalize_direction_raw("hold") == "neutral"
        assert normalize_direction_raw("") == "neutral"
        assert normalize_direction_raw("unknown") == "neutral"

    def test_direction_to_signal(self):
        assert normalize_direction_to_signal("bull") == "BUY"
        assert normalize_direction_to_signal("bear") == "SELL"
        assert normalize_direction_to_signal("neutral") == "HOLD"

    def test_confidence_normalization(self):
        # float 0-1
        assert normalize_confidence_raw(0.85) == 0.85
        # float 0-100
        assert normalize_confidence_raw(85.0) == 0.85
        # int 0-100
        assert normalize_confidence_raw(85) == 0.85
        # 中文映射
        assert normalize_confidence_raw("高") == 0.85
        assert normalize_confidence_raw("中") == 0.55
        assert normalize_confidence_raw("低") == 0.25
        # 英文映射
        assert normalize_confidence_raw("HIGH") == 0.85
        assert normalize_confidence_raw("MEDIUM") == 0.55
        assert normalize_confidence_raw("LOW") == 0.25
        # None → fallback
        assert normalize_confidence_raw(None, 60) == 0.6
        assert normalize_confidence_raw(None, 0) == 0.0
        # clamp
        assert normalize_confidence_raw(200) == 1.0
        assert normalize_confidence_raw(-1) == 0.0

    def test_grade_normalization(self):
        assert normalize_grade_raw("STRONG") == "STRONG"
        assert normalize_grade_raw("strong") == "STRONG"
        assert normalize_grade_raw("S") == "STRONG"
        assert normalize_grade_raw("WATCH") == "WATCH"
        assert normalize_grade_raw("W") == "WATCH"
        assert normalize_grade_raw("WEAK") == "WEAK"
        assert normalize_grade_raw("NOISE") == "NOISE"
        assert normalize_grade_raw("") == "NOISE"
        assert normalize_grade_raw("unknown") == "NOISE"


class TestNormalizeKline:
    """K 线行标准化。"""

    def test_standard_kline(self):
        """标准 K 线行。"""
        raw = {
            "date": "2026-07-01",
            "open": 5000, "high": 5050, "low": 4980,
            "close": 5030, "volume": 100000, "amount": 5e8,
            "open_interest": 200000, "settlement": 5020,
        }
        n = normalize_kline_row(raw)
        assert n["date"] == "2026-07-01"
        assert n["open"] == 5000.0
        assert n["oi"] == 200000  # open_interest → oi
        assert n["volume"] == 100000.0

    def test_oi_variants(self):
        """oi / open_interest / OI 三种输入都统一到 oi。"""
        assert normalize_kline_row({"date": "a", "open": 1, "high": 2,
                                    "low": 1, "close": 1, "oi": 100})["oi"] == 100
        assert normalize_kline_row({"date": "a", "open": 1, "high": 2,
                                    "low": 1, "close": 1, "open_interest": 200})["oi"] == 200
        assert normalize_kline_row({"date": "a", "open": 1, "high": 2,
                                    "low": 1, "close": 1, "OI": 300})["oi"] == 300

    def test_date_variants(self):
        """多种日期格式。"""
        assert normalize_kline_row({"date": "2026-01-01", "open": 1, "high": 2,
                                    "low": 1, "close": 1})["date"] == "2026-01-01"
        assert normalize_kline_row({"datetime": "2026-01-02 15:00", "open": 1,
                                    "high": 2, "low": 1, "close": 1})["date"] == "2026-01-02"
        assert normalize_kline_row({"trade_date": "2026-01-03", "open": 1,
                                    "high": 2, "low": 1, "close": 1})["date"] == "2026-01-03"
        assert normalize_kline_row({"Date": "2026-01-04", "open": 1, "high": 2,
                                    "low": 1, "close": 1})["date"] == "2026-01-04"

    def test_float_coercion(self):
        """字段值强制转换。"""
        raw = {
            "date": "2026-01-01", "open": "5000", "high": "5050",
            "low": "4980", "close": "5030", "volume": "100000",
        }
        n = normalize_kline_row(raw)
        assert n["open"] == 5000.0
        assert n["close"] == 5030.0
        assert n["volume"] == 100000.0

    def test_missing_fields(self):
        """缺失字段补 0。"""
        raw = {"date": "2026-01-01", "open": 1, "high": 2, "low": 1, "close": 1}
        n = normalize_kline_row(raw)
        assert n["volume"] == 0.0
        assert n["oi"] == 0

    def test_kline_list(self):
        bars = [{"date": "2026-01-01", "open": 1, "high": 2, "low": 1, "close": 1},
                {"date": "2026-01-02", "open": 2, "high": 3, "low": 1, "close": 2}]
        result = normalize_kline_list(bars)
        assert len(result) == 2
        assert result[0]["close"] == 1.0
        assert result[1]["close"] == 2.0


class TestNormalizeSignal:
    """信号行标准化。"""

    def test_symbol_variants(self):
        assert normalize_signal_row({"symbol": "CU", "total": 50})["symbol"] == "CU"
        assert normalize_signal_row({"pid": "RB", "total": 50})["symbol"] == "RB"
        assert normalize_signal_row({"sym": "SC", "total": 50})["symbol"] == "SC"
        assert normalize_signal_row({"total": 50})["symbol"] == ""

    def test_direction_variants(self):
        assert normalize_signal_row({"direction": "bull", "total": 50})["direction"] == "bull"
        assert normalize_signal_row({"direction": "BUY", "total": 50})["direction"] == "bull"
        assert normalize_signal_row({"dir": "bear", "total": 50})["direction"] == "bear"
        assert normalize_signal_row({"dir": "SELL", "total": 50})["direction"] == "bear"

    def test_total_from_score(self):
        """total 可从 score 回退。"""
        n = normalize_signal_row({"score": 80})
        assert n["total"] == 80.0

    def test_grade_from_level(self):
        """grade 可从 level 回退。"""
        n = normalize_signal_row({"level": "S", "total": 10})
        assert n["grade"] == "STRONG"

    def test_signal_list(self):
        rows = [{"symbol": "CU", "total": 50}, {"symbol": "RB", "total": -30}]
        result = normalize_signal_list(rows)
        assert len(result) == 2
        assert result[0]["symbol"] == "CU"
        assert result[1]["total"] == -30.0


class TestNormalizeVerdict:
    """裁决标准化。"""

    def test_verdict_variants(self):
        """direction / verdict / winner 都统一。"""
        n = normalize_verdict({"direction": "bullish"})
        assert n["direction"] == "bull"
        n2 = normalize_verdict({"verdict": "bearish"})
        assert n2["direction"] == "bear"
        n3 = normalize_verdict({"winner": "bull_win"})
        assert n3["direction"] == "bull"

    def test_entry_price_variants(self):
        """entry / entry_price / price 都统一到 entry_price。"""
        n = normalize_verdict({"entry_price": 5000})
        assert n["entry_price"] == 5000.0
        n2 = normalize_verdict({"entry": 5100})
        assert n2["entry_price"] == 5100.0
        n3 = normalize_verdict({"price": 5200})
        assert n3["entry_price"] == 5200.0

    def test_stop_loss_variants(self):
        n = normalize_verdict({"stop_loss_price": 4900})
        assert n["stop_loss_price"] == 4900.0
        n2 = normalize_verdict({"stop_loss": 4800})
        assert n2["stop_loss_price"] == 4800.0

    def test_target_price_variants(self):
        n = normalize_verdict({"target_price": 6000})
        assert n["target_price"] == 6000.0
        n2 = normalize_verdict({"target": 6100})
        assert n2["target_price"] == 6100.0
        n3 = normalize_verdict({"target1": 6200})
        assert n3["target_price"] == 6200.0

    def test_position_size_to_pct(self):
        n = normalize_verdict({"position_pct": 30})
        assert n["position_pct"] == 30.0
        n2 = normalize_verdict({"position_size": 25})
        assert n2["position_pct"] == 25.0

    def test_risk_reward_variants(self):
        n = normalize_verdict({"risk_reward_ratio": 3.0})
        assert n["risk_reward_ratio"] == 3.0
        n2 = normalize_verdict({"risk_reward": 2.5})
        assert n2["risk_reward_ratio"] == 2.5

    def test_preserve_extra_fields(self):
        n = normalize_verdict({
            "direction": "bull", "overturn_scan": True, "divergence": 0.5,
        })
        assert n.get("overturn_scan") is True
        assert n.get("divergence") == 0.5


class TestNormalizeRiskCheck:
    """风控标准化。"""

    def test_risk_color_variants(self):
        n = normalize_risk_check({"risk_color": "red"})
        assert n["risk_color"] == "red"
        n2 = normalize_risk_check({"risk_level": "YELLOW"})
        assert n2["risk_color"] == "yellow"
        n3 = normalize_risk_check({"risk_color": "GREEN"})
        assert n3["risk_color"] == "green"

    def test_confidence(self):
        n = normalize_risk_check({"confidence": 80})
        assert n["confidence"] == 0.8

    def test_defaults(self):
        n = normalize_risk_check({})
        assert n["risk_color"] == "yellow"
        assert n["approved"] is True
        assert n["warnings"] == []
