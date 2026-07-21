"""
DataCoreCollector 适配器测试 — 导入检查 / 格式转换 / 降级链集成。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from futures_data_core.collectors.datacore import (
    DataCoreCollector,
    _dc_kline_to_bars,
    _normalize_period,
)
from futures_data_core.core.types import KlineBar

# ── 辅助：模拟 Data-Core K 线数据 ──────────────────────────

_DC_KLINE_SAMPLE = [
    {"date": "2026-07-01", "open": 5000.0, "high": 5050.0, "low": 4980.0,
     "close": 5030.0, "volume": 100000.0, "amount": 5e8, "open_interest": 200000.0,
     "settlement": 5020.0},
    {"date": "2026-07-02", "open": 5030.0, "high": 5080.0, "low": 5020.0,
     "close": 5070.0, "volume": 120000.0, "amount": 6e8, "open_interest": 210000.0,
     "settlement": 5060.0},
]


# ── 测试用例 ────────────────────────────────────────────────


class TestDcKlineToBars:
    """_dc_kline_to_bars 格式转换测试。"""

    def test_basic_conversion(self):
        bars = _dc_kline_to_bars(_DC_KLINE_SAMPLE)
        assert len(bars) == 2
        assert isinstance(bars[0], KlineBar)
        assert bars[0].date == "2026-07-01"
        assert bars[0].open == 5000.0
        assert bars[0].close == 5030.0
        assert bars[0].volume == 100000.0

    def test_empty_input(self):
        assert _dc_kline_to_bars([]) == []

    def test_handles_invalid_items(self):
        data = [{"bad": "data"}, {"date": "2026-01-01", "open": "invalid", "close": 100}]
        bars = _dc_kline_to_bars(data)
        assert len(bars) == 0

    def test_date_variants(self):
        """处理多种日期格式。"""
        data = [
            {"date": "2026-01-01", "open": 100, "high": 110, "low": 90,
             "close": 105, "volume": 1000},
            {"datetime": "2026-01-02 15:00:00", "open": 105, "high": 115,
             "low": 100, "close": 110, "volume": 2000},
            {"trade_date": "2026-01-03T00:00:00", "open": 110, "high": 120,
             "low": 105, "close": 115, "volume": 3000},
        ]
        bars = _dc_kline_to_bars(data)
        assert len(bars) == 3
        assert bars[0].date == "2026-01-01"
        assert bars[1].date == "2026-01-02"   # 去掉了时间部分
        assert bars[2].date == "2026-01-03"   # 去掉了 T 格式


class TestNormalizePeriod:
    def test_daily_passthrough(self):
        assert _normalize_period("daily") == "daily"

    def test_minute_passthrough(self):
        assert _normalize_period("60m") == "60m"
        assert _normalize_period("120m") == "120m"

    def test_weekly_passthrough(self):
        assert _normalize_period("weekly") == "weekly"


class TestDataCoreCollector:
    """DataCoreCollector 功能测试（mock Data-Core 模块）。"""

    def test_name_and_priority(self):
        collector = DataCoreCollector()
        assert collector.name == "datacore"
        assert collector.priority == 0

    def test_collector_type(self):
        collector = DataCoreCollector()
        assert collector.collector_type.value == "independent"

    @pytest.mark.asyncio
    async def test_get_kline_conversion(self):
        """通过 mock fdc_compat 验证 get_kline 格式转换。"""
        with patch("futures_data_core.collectors.datacore.DataCoreCollector.check_available",
                   return_value=True):
            with patch("datacore.fdc_compat.get_kline",
                       new=AsyncMock(return_value=_DC_KLINE_SAMPLE)):
                collector = DataCoreCollector()
                result = await collector.get_kline("CU", period="daily", days=120)
                assert result is not None
                assert result.symbol == "CU"
                assert result.period == "daily"
                assert result.source == "datacore"
                assert len(result.bars) == 2
                assert result.bars[0].date == "2026-07-01"

    @pytest.mark.asyncio
    async def test_get_kline_empty_result(self):
        """Data-Core 返回空列表时返回 None。"""
        with patch("datacore.fdc_compat.get_kline",
                   new=AsyncMock(return_value=[])):
            collector = DataCoreCollector()
            result = await collector.get_kline("CU")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_kline_no_datacore(self):
        """Data-Core 未安装时 get_kline 返回 None (不抛异常)。"""
        with patch("futures_data_core.collectors.datacore.DataCoreCollector.check_available",
                   return_value=False):
            with patch("datacore.fdc_compat.get_kline",
                       side_effect=ImportError("no module named datacore")):
                collector = DataCoreCollector()
                result = await collector.get_kline("CU")
                assert result is None

    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """成功获取行情快照。"""
        mock_quote = {"last_price": 5000.0, "open": 4980.0, "high": 5050.0,
                      "low": 4970.0, "volume": 100000}
        with patch("datacore.fdc_compat.get_quote",
                   new=AsyncMock(return_value=mock_quote)):
            collector = DataCoreCollector()
            result = await collector.get_quote("CU")
            assert result == mock_quote
            assert result["last_price"] == 5000.0

    @pytest.mark.asyncio
    async def test_batch_get_quotes_success(self):
        """批量获取行情。"""
        mock_batch = {"CU": {"last_price": 5000}, "AL": {"last_price": 15000}}
        with patch("datacore.fdc_compat.batch_get_quotes",
                   new=AsyncMock(return_value=mock_batch)):
            collector = DataCoreCollector()
            result = await collector.batch_get_quotes(["CU", "AL"])
            assert len(result) == 2
            assert result["CU"]["last_price"] == 5000

    # ── F10 桥接方法 ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_basis(self):
        mock_data = {"symbol": "CU", "basis": 120.5}
        with patch("datacore.fdc_compat.get_basis", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_basis("CU")
            assert result.get("basis") == 120.5

    @pytest.mark.asyncio
    async def test_get_term_structure(self):
        mock_data = {"symbol": "CU", "contracts": ["CU2409", "CU2410"]}
        with patch("datacore.fdc_compat.get_term_structure", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_term_structure("CU")
            assert len(result.get("contracts", [])) == 2

    @pytest.mark.asyncio
    async def test_get_spread(self):
        mock_data = {"symbol": "CU", "spread": 200}
        with patch("datacore.fdc_compat.get_spread", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_spread("CU")
            assert result.get("spread") == 200

    @pytest.mark.asyncio
    async def test_get_warrant(self):
        mock_data = {"symbol": "CU", "warrant": 50000}
        with patch("datacore.fdc_compat.get_warrant", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_warrant("CU")
            assert result.get("warrant") == 50000

    @pytest.mark.asyncio
    async def test_get_fundamental(self):
        mock_data = {"symbol": "CU", "supply_demand": "stable"}
        with patch("datacore.fdc_compat.get_fundamental", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_fundamental("CU")
            assert result.get("supply_demand") == "stable"

    @pytest.mark.asyncio
    async def test_get_f10(self):
        mock_data = {"symbol": "CU", "report": "..."}
        with patch("datacore.fdc_compat.get_f10", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_f10("CU")
            assert result.get("report") == "..."

    @pytest.mark.asyncio
    async def test_get_position_ranking(self):
        mock_data = {"symbol": "CU", "rankings": []}
        with patch("datacore.fdc_compat.get_position_ranking", new=AsyncMock(return_value=mock_data)):
            collector = DataCoreCollector()
            result = await collector.get_position_ranking("CU")
            assert "rankings" in result

    # ── F10 失败降级 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_f10_fallback_on_import_error(self):
        """F10 方法在 Data-Core 不可用时返回空 dict。"""
        with patch("datacore.fdc_compat.get_basis", side_effect=ImportError("no datacore")):
            collector = DataCoreCollector()
            result = await collector.get_basis("CU")
            assert result == {}
