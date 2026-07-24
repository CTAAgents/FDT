"""Data-Core 采集器适配器 [INDEPENDENT]。
    
将 ``datacore.fdc_compat`` 封装为 :class:`BaseCollector` 子类，使其可接入 FDT 的
多源降级链（MultiSourceAdapter）。Data-Core 内部自动管理 TDX-LC / EastMoney /
TqSDK / QMT 等多数据源的降级路由。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from futures_data_core.collectors.base import BaseCollector, CollectorType
from futures_data_core.core.types import KlineData, KlineBar
from futures_data_core.core.field_normalizer import normalize_kline_row

logger = logging.getLogger("fdt_datacore")


class DataCoreCollector(BaseCollector):
    """Data-Core 采集器适配器。

    优先使用 Data-Core 的统一数据接口。当 Data-Core 不可用时，FDT 降级链
    自动切换到 TDX / Web / QMT / TqSDK 等原有采集器。

    Data-Core 版本: 2.0.0+
    优先级: 0（最高，先于 TDX TQ-Local）
    """

    name: str = "datacore"
    priority: int = 1  # 与 TDX 同优先级（第二数据源）
    collector_type: CollectorType = CollectorType.INDEPENDENT

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    async def check_available(self) -> bool:
        """检查 Data-Core 模块是否可导入。"""
        if self._available is not None:
            return self._available
        try:
            import datacore  # noqa: F401

            self._available = True
        except ImportError:
            self._available = False
            logger.warning("[DataCore] datacore 模块未安装，跳过此采集器")
        return self._available

    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120
    ) -> Optional[KlineData]:
        """通过 Data-Core fdc_compat 获取 K 线。

        Args:
            symbol: 品种代码（如 ``"CU"``）。
            period: 周期（支持 ``"daily"`` / ``"60m"`` / ``"weekly"`` 等）。
            days: 回溯交易日数。

        Returns:
            :class:`KlineData`，失败返回 ``None``。
        """
        try:
            from datacore.fdc_compat import get_kline as _dc_get_kline

            dc_period = _normalize_period(period)
            result = await _dc_get_kline(symbol, period=dc_period, days=days)

            if not result:
                logger.debug("[DataCore] %s K线数据为空 (period=%s)", symbol, period)
                return None

            # v9.3.0: 通过 field_normalizer 标准化 K 线字段
            result = [normalize_kline_row(r) for r in result]

            bars = _dc_kline_to_bars(result)
            if not bars:
                return None

            return KlineData(
                symbol=symbol,
                period=period,
                source=self.name,
                contract="",
                bars=bars,
            )
        except ImportError as exc:
            logger.warning("[DataCore] datacore 模块不可用: %s", exc)
            self._available = False
            return None
        except Exception as exc:
            logger.warning("[DataCore] get_kline(%s) 失败: %s", symbol, exc)
            return None

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """通过 Data-Core 获取实时行情快照。

        Args:
            symbol: 品种代码。

        Returns:
            行情字典，包含 last_price / open / high / low / volume 等字段。
        """
        try:
            from datacore.fdc_compat import get_quote as _dc_get_quote

            return await _dc_get_quote(symbol)
        except ImportError:
            logger.warning("[DataCore] datacore 模块不可用")
            return None
        except Exception as exc:
            logger.warning("[DataCore] get_quote(%s) 失败: %s", symbol, exc)
            return None

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """批量获取行情。

        Args:
            symbols: 品种代码列表。

        Returns:
            ``{symbol: quote_dict}`` 形式的行情字典。
        """
        try:
            from datacore.fdc_compat import batch_get_quotes as _dc_batch

            return await _dc_batch(symbols)
        except ImportError:
            logger.warning("[DataCore] datacore 模块不可用")
            return {}
        except Exception as exc:
            logger.warning("[DataCore] batch_get_quotes 失败: %s", exc)
            return {}

    # ── F10 桥接方法 ──────────────────────────────────────────

    async def get_basis(self, symbol: str) -> dict:
        """获取基差。委托 ``datacore.fdc_compat.get_basis``。"""
        try:
            from datacore.fdc_compat import get_basis as _dc_basis
            return await _dc_basis(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_basis(%s) 失败: %s", symbol, exc)
            return {}

    async def get_term_structure(self, symbol: str) -> dict:
        """获取期限结构。委托 ``datacore.fdc_compat.get_term_structure``。"""
        try:
            from datacore.fdc_compat import get_term_structure as _dc_ts
            return await _dc_ts(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_term_structure(%s) 失败: %s", symbol, exc)
            return {}

    async def get_spread(self, symbol: str) -> dict:
        """获取跨期价差。委托 ``datacore.fdc_compat.get_spread``。"""
        try:
            from datacore.fdc_compat import get_spread as _dc_spread
            return await _dc_spread(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_spread(%s) 失败: %s", symbol, exc)
            return {}

    async def get_warrant(self, symbol: str) -> dict:
        """获取仓单。委托 ``datacore.fdc_compat.get_warrant``。"""
        try:
            from datacore.fdc_compat import get_warrant as _dc_warrant
            return await _dc_warrant(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_warrant(%s) 失败: %s", symbol, exc)
            return {}

    async def get_fundamental(self, symbol: str) -> dict:
        """获取基本面。委托 ``datacore.fdc_compat.get_fundamental``。"""
        try:
            from datacore.fdc_compat import get_fundamental as _dc_fund
            return await _dc_fund(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_fundamental(%s) 失败: %s", symbol, exc)
            return {}

    async def get_f10(self, symbol: str) -> dict:
        """获取 F10 综合报告。委托 ``datacore.fdc_compat.get_f10``。"""
        try:
            from datacore.fdc_compat import get_f10 as _dc_f10
            return await _dc_f10(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_f10(%s) 失败: %s", symbol, exc)
            return {}

    async def get_position_ranking(self, symbol: str) -> dict:
        """获取持仓排名。委托 ``datacore.fdc_compat.get_position_ranking``。"""
        try:
            from datacore.fdc_compat import get_position_ranking as _dc_pr
            return await _dc_pr(symbol)
        except Exception as exc:
            logger.warning("[DataCore] get_position_ranking(%s) 失败: %s", symbol, exc)
            return {}


def _dc_kline_to_bars(dc_data: list[dict]) -> list[KlineBar]:
    """将 Data-Core K 线数据列表转换为 FDT KlineBar 列表。

    Data-Core 返回: [{"open": ..., "high": ..., "close": ..., ...}, ...]
    FDT 需要: [KlineBar(date=..., open=..., ...), ...]
    """
    bars: list[KlineBar] = []
    for item in dc_data:
        if not isinstance(item, dict):
            continue
        date = (
            item.get("date")
            or item.get("datetime")
            or item.get("trade_date")
            or item.get("Date")
            or ""
        )
        # 跳过无日期项（纯空数据）
        if not date:
            continue
        # 统一日期格式：去掉时间部分
        if " " in str(date):
            date = str(date).split(" ")[0]
        elif "T" in str(date):
            date = str(date).split("T")[0]
        else:
            date = str(date)

        try:
            open_v = float(item.get("open", 0) or 0)
            high_v = float(item.get("high", 0) or 0)
            low_v = float(item.get("low", 0) or 0)
            close_v = float(item.get("close", 0) or 0)
            volume_v = float(item.get("volume", 0) or 0)
            amount_v = float(item.get("amount", 0) or 0)
            oi_v = float(item.get("open_interest", 0) or 0)
            settlement_v = float(item.get("settlement", 0) or 0)
            bar = KlineBar(
                date=date,
                open=open_v, high=high_v, low=low_v, close=close_v,
                volume=volume_v, amount=amount_v,
                open_interest=oi_v, settlement=settlement_v,
            )
        except (ValueError, TypeError):
            continue
        bars.append(bar)
    return bars


def _normalize_period(period: str) -> str:
    """统一周期格式。

    FDT 约定：daily / 60m / 120m / 240m / weekly
    Data-Core 接受：daily / 60m / 120m / 240m / weekly
    直接透传。
    """
    # Data-Core fdc_compat.get_kline 直接接受这些周期格式
    return period


__all__ = ["DataCoreCollector"]
