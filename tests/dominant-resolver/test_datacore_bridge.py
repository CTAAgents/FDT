"""Data-Core F10 桥接器测试 [INDEPENDENT]。

覆盖 ``_datacore_bridge.py`` 核心逻辑：
  - Data-Core 未安装时的降级
  - 结果有效性判定
  - A2APayload 包装
  - 同步/异步函数兼容
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from futures_data_core._a2a import A2APayload
from futures_data_core.core._datacore_bridge import (
    _DC_FUNC_MAP,
    _infer_grade,
    _is_valid_dc_result,
    dc_result_to_a2apayload,
    try_datacore_first,
)

_DC_PREFIX = "datacore"


def _make_dc_mock(dc_module: Any) -> None:
    """将 ``dc_module`` 注册为 sys.modules 中的 ``datacore.fdc_compat``。"""
    datacore_mod = MagicMock()
    datacore_mod.fdc_compat = dc_module
    sys.modules["datacore"] = datacore_mod
    sys.modules["datacore.fdc_compat"] = dc_module


class TestTryDatacoreFirst:
    """测试 ``try_datacore_first`` 的降级逻辑。"""

    @pytest.mark.asyncio
    async def test_datacore_not_installed(self):
        """Data-Core 未安装时应返回 (None, False)。"""
        with patch("builtins.__import__", side_effect=ImportError("no datacore")):
            result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_unknown_func_name(self):
        """未知函数名应返回 (None, False)。"""
        result, used = await try_datacore_first("nonexistent_func", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_sync_function_returns_valid(self):
        """Data-Core 同步函数返回有效 dict。"""
        mock_dc = MagicMock()
        mock_dc.get_basis = MagicMock(
            return_value={"basis": 150.0, "basis_pct": 2.5, "spot_price": 7500.0}
        )
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert used is True
        assert result is not None
        assert result["basis"] == 150.0

    @pytest.mark.asyncio
    async def test_async_function_returns_valid(self):
        """Data-Core 异步函数返回有效 dict。"""
        mock_dc = MagicMock()
        mock_dc.get_term_structure = AsyncMock(
            return_value={"structure": "BACK", "slope_pct": -2.5, "contracts": []}
        )
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_term_structure", "CU")
        assert used is True
        assert result is not None
        assert result["structure"] == "BACK"

    @pytest.mark.asyncio
    async def test_returns_empty_dict(self):
        """Data-Core 返回空 dict 时应降级。"""
        mock_dc = MagicMock()
        mock_dc.get_basis = MagicMock(return_value={})
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_returns_none(self):
        """Data-Core 返回 None 时应降级。"""
        mock_dc = MagicMock()
        mock_dc.get_basis = MagicMock(return_value=None)
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_returns_only_meta_fields(self):
        """只有元数据字段应视为无效。"""
        mock_dc = MagicMock()
        mock_dc.get_basis = MagicMock(
            return_value={"symbol": "CU", "data_grade": "FRESH"}
        )
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_raises_exception(self):
        """Data-Core 抛异常时应降级。"""
        mock_dc = MagicMock()
        mock_dc.get_basis = MagicMock(side_effect=TimeoutError("timeout"))
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    @pytest.mark.asyncio
    async def test_missing_function_in_compat(self):
        """fdc_compat 中缺少对应函数时降级。"""
        mock_dc = MagicMock()
        # 不设置 get_basis 属性
        _make_dc_mock(mock_dc)
        result, used = await try_datacore_first("get_basis", "CU")
        assert result is None
        assert used is False

    def test_map_covers_all_f10_funcs(self):
        """函数映射表覆盖所有 F10 桥接函数。"""
        expected = {
            "get_term_structure", "get_spread", "get_basis",
            "get_warrant", "get_fundamental", "get_f10",
            "get_position_ranking", "compute_indicators",
        }
        assert set(_DC_FUNC_MAP.keys()) == expected


class TestDcResultToA2aPayload:
    """测试 ``dc_result_to_a2apayload`` 的 A2APayload 包装。"""

    def test_valid_result(self):
        """有效结果应正确包装为 A2APayload。"""
        dc_result = {"basis": 150.0, "basis_pct": 2.5, "spot_price": 7500.0}
        payload = dc_result_to_a2apayload(
            dc_result, "CU", "fdc.basis", "CU 基差（Data-Core）"
        )
        assert isinstance(payload, A2APayload)
        assert payload.data == dc_result
        assert payload.meta.get("source") == "datacore"
        assert "datacore" in payload.meta.get("sources", [])
        assert payload.type == "fdc.basis"
        assert payload.summary == "CU 基差（Data-Core）"

    def test_empty_result(self):
        """空结果应标记为 UNAVAILABLE。"""
        dc_result = {"symbol": "CU"}
        payload = dc_result_to_a2apayload(dc_result, "CU", "fdc.basis")
        assert payload.meta.get("data_grade") == "UNAVAILABLE"

    def test_runtime_mode_independent(self):
        """运行模式应为 independent。"""
        dc_result = {"basis": 150.0}
        payload = dc_result_to_a2apayload(dc_result, "CU", "fdc.basis")
        assert payload.runtime_mode == "independent"

    def test_preserves_data_grade(self):
        """Data-Core 返回中包含 data_grade 时应保留。"""
        dc_result = {"basis": 150.0, "data_grade": "FRESH"}
        payload = dc_result_to_a2apayload(dc_result, "CU", "fdc.basis")
        assert payload.meta.get("data_grade") == "FRESH"


class TestIsValidDcResult:
    """测试内部 ``_is_valid_dc_result`` 判定函数。"""

    def test_empty_dict(self):
        assert _is_valid_dc_result({}) is False

    def test_none(self):
        assert _is_valid_dc_result(None) is False

    def test_only_meta_fields(self):
        assert _is_valid_dc_result({"symbol": "CU", "source": "datacore"}) is False

    def test_with_content(self):
        assert _is_valid_dc_result({"basis": 150.0, "symbol": "CU"}) is True

    def test_content_is_none(self):
        assert _is_valid_dc_result({"basis": None, "symbol": "CU"}) is False

    def test_content_is_empty_list(self):
        assert _is_valid_dc_result({"contracts": [], "symbol": "CU"}) is False

    def test_content_is_empty_dict(self):
        assert _is_valid_dc_result({"data": {}, "symbol": "CU"}) is False


class TestInferGrade:
    """测试 ``_infer_grade`` 等级推断。"""

    def test_valid_content(self):
        assert _infer_grade({"basis": 150.0}) == "STALE"

    def test_invalid_content(self):
        assert _infer_grade({}) == "UNAVAILABLE"

    def test_only_meta(self):
        assert _infer_grade({"symbol": "CU"}) == "UNAVAILABLE"
