"""FDC 降级兼容性测试 [INDEPENDENT]。

验证当 Data-Core 不可用 / 返回空 / 抛异常时，F10 模块和 compute_indicators
能正确降级到原有 FDC 实现。

这些测试 mock Data-Core 为不可用状态，验证降级路径的完整性。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from futures_data_core.f10.basis import get_basis as fdc_get_basis
from futures_data_core.f10.fundamentals import get_fundamental as fdc_get_fundamental
from futures_data_core.f10.position import get_position_ranking as fdc_get_position
from futures_data_core.f10.spread import get_spread as fdc_get_spread
from futures_data_core.f10.term_structure import get_term_structure as fdc_get_term_structure
from futures_data_core.f10.warrant import get_warrant as fdc_get_warrant


@pytest.fixture(autouse=True)
def _mock_datacore_unavailable():
    """让 ``import datacore.fdc_compat`` 抛 ImportError，触发 F10 模块降级。

    将 ``sys.modules["datacore"]`` 置为 ``None`` 是 Python 标准约定的"模块
    不可导入"信号——``import datacore`` 会直接抛 ``ImportError``，不会触发
    真实的 ``datacore/__init__.py`` 执行（避免 Prometheus Counter 重复注册
    等副作用）。
    """
    saved_dc = sys.modules.get("datacore")
    saved_dcc = sys.modules.get("datacore.fdc_compat")
    sys.modules["datacore"] = None  # type: ignore[assignment]
    sys.modules["datacore.fdc_compat"] = None  # type: ignore[assignment]
    yield
    # 恢复
    if saved_dc is None:
        sys.modules.pop("datacore", None)
    else:
        sys.modules["datacore"] = saved_dc
    if saved_dcc is None:
        sys.modules.pop("datacore.fdc_compat", None)
    else:
        sys.modules["datacore.fdc_compat"] = saved_dcc


class TestTermStructureFallback:
    """期限结构模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        """Data-Core 不可用时返回 A2APayload 实例。"""
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_term_structure("CU")
        assert isinstance(result, A2APayload)

    @pytest.mark.asyncio
    async def test_fallback_has_data_field(self):
        """降级路径返回的数据包含必要字段。"""
        result = await fdc_get_term_structure("CU")
        assert "symbol" in result.data or "structure" in result.data

    @pytest.mark.asyncio
    async def test_fallback_does_not_include_datacore_source(self):
        """降级路径的 sources 不包含 datacore。"""
        result = await fdc_get_term_structure("CU")
        sources = result.meta.get("sources", [])
        assert "datacore" not in sources


class TestSpreadFallback:
    """跨期价差模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_spread("CU")
        assert isinstance(result, A2APayload)

    @pytest.mark.asyncio
    async def test_fallback_has_data(self):
        result = await fdc_get_spread("CU")
        assert result.data is not None


class TestBasisFallback:
    """基差模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_basis("CU")
        assert isinstance(result, A2APayload)


class TestWarrantFallback:
    """仓单模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_warrant("CU", exchange="SHFE")
        assert isinstance(result, A2APayload)


class TestFundamentalFallback:
    """基本面模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_fundamental("CU")
        assert isinstance(result, A2APayload)


class TestPositionRankingFallback:
    """持仓排名模块降级测试。"""

    @pytest.mark.asyncio
    async def test_fallback_returns_a2apayload(self):
        from futures_data_core._a2a import A2APayload
        result = await fdc_get_position("CU", trade_date="20260701")
        assert isinstance(result, A2APayload)
