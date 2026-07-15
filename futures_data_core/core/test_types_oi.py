"""OI 字段回归测试 — KlineBar 含 open_interest 且 to_dict/as_dataframe 正确输出。"""

import pytest
from futures_data_core.core.types import KlineBar, KlineData


class TestKlineBarOI:
    """KlineBar.open_interest 字段存在且正确"""

    def test_default_zero(self):
        """默认值应为 0.0"""
        kb = KlineBar(
            date="2026-07-15", open=100.0, high=105.0,
            low=99.0, close=102.0, volume=10000, amount=5e8,
        )
        assert kb.open_interest == 0.0

    def test_explicit_value(self):
        """显式传入可覆盖默认"""
        kb = KlineBar(
            date="2026-07-15", open=100.0, high=105.0,
            low=99.0, close=102.0, volume=10000, amount=5e8,
            open_interest=125000.0,
        )
        assert kb.open_interest == 125000.0

    def test_fractional_oi(self):
        """OI 支持浮点数"""
        kb = KlineBar(
            date="2026-07-15", open=100.0, high=105.0,
            low=99.0, close=102.0, volume=10000, amount=5e8,
            open_interest=123456.78,
        )
        assert kb.open_interest == pytest.approx(123456.78)


class TestKlineDataOIDict:
    """KlineData.to_dict() 输出 open_interest"""

    @pytest.fixture
    def sample_data(self):
        bars = [
            KlineBar("2026-07-14", 99.0, 101.0, 98.0, 100.0, 8000, 4e8, 120000.0),
            KlineBar("2026-07-15", 100.0, 105.0, 99.0, 102.0, 10000, 5e8, 125000.0),
        ]
        return KlineData(symbol="CU", period="daily", source="test", bars=bars)

    def test_dict_contains_oi(self, sample_data):
        d = sample_data.to_dict()
        assert "open_interest" in d["bars"][0]
        assert d["bars"][0]["open_interest"] == 120000.0
        assert d["bars"][1]["open_interest"] == 125000.0

    def test_as_dataframe_contains_oi(self, sample_data):
        df = sample_data.as_dataframe()
        assert "open_interest" in df.columns
        assert df.iloc[0]["open_interest"] == 120000.0
        assert df.iloc[1]["open_interest"] == 125000.0


class TestOICompatibilityShim:
    """scan_all.py 式向后兼容映射"""

    def test_oi_key(self):
        d = {"oi": 125000}
        val = int(d.get("oi") or d.get("open_interest", 0))
        assert val == 125000

    def test_open_interest_key(self):
        d = {"open_interest": 125000}
        val = int(d.get("oi") or d.get("open_interest", 0))
        assert val == 125000

    def test_both_keys(self):
        d = {"oi": 99999, "open_interest": 125000}
        val = int(d.get("oi") or d.get("open_interest", 0))
        assert val == 99999  # oi 优先

    def test_no_oi(self):
        d = {"close": 102.0}
        val = int(d.get("oi") or d.get("open_interest", 0))
        assert val == 0

    def test_oi_zero(self):
        d = {"oi": 0}
        val = int(d.get("oi") or d.get("open_interest", 0))
        assert val == 0
