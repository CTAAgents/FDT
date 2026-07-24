"""数据适配层 — 数据源插座路由入口。

环境变量 FDT_DATA_SOURCE 控制当前使用的数据源：
  - "akshare" (默认): AKShareSource

所有接口均为 async 函数，直接调用即可，不关心底层数据源实现。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from data_adapter.base import DataSource
from data_adapter.sources.akshare_source import AKShareSource
from data_adapter.types import KlineResult, QuoteResult

logger = logging.getLogger(__name__)

# ── 全局数据源单例 ──
_SOURCE_NAME = os.environ.get("FDT_DATA_SOURCE", "akshare").lower()

_DATA_SOURCE: Optional[DataSource] = None


def _get_source() -> DataSource:
    """获取当前数据源实例（懒加载单例）。"""
    global _DATA_SOURCE
    if _DATA_SOURCE is not None:
        return _DATA_SOURCE

    logger.info("[DataAdapter] 初始化数据源: %s", _SOURCE_NAME)

    if _SOURCE_NAME == "akshare":
        _DATA_SOURCE = AKShareSource()
    else:
        logger.warning("[DataAdapter] 未知数据源 %s，降级到 akshare", _SOURCE_NAME)
        _DATA_SOURCE = AKShareSource()

    return _DATA_SOURCE


# ── 12 个统一接口 ──


async def get_kline(symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
    """获取 K 线数据。"""
    return await _get_source().get_kline(symbol, period, days)


async def get_quote(symbol: str) -> QuoteResult:
    """获取行情快照。"""
    return await _get_source().get_quote(symbol)


async def batch_get_quotes(symbols: list[str]) -> dict[str, QuoteResult]:
    """批量获取行情快照。"""
    return await _get_source().batch_get_quotes(symbols)


async def get_contract_info(symbol: str) -> dict:
    """获取合约信息。"""
    return await _get_source().get_contract_info(symbol)


async def get_warrant(symbol: str, exchange: str = "SHFE") -> dict:
    """获取仓单日报。"""
    return await _get_source().get_warrant(symbol, exchange)


async def get_inventory(symbol: str) -> dict:
    """获取库存数据。"""
    return await _get_source().get_inventory(symbol)


async def get_position_ranking(symbol: str) -> dict:
    """获取持仓排名。"""
    return await _get_source().get_position_ranking(symbol)


async def get_fund_flow(symbol: str) -> dict:
    """获取资金流向。"""
    return await _get_source().get_fund_flow(symbol)


async def get_foreign_hist(symbol: str) -> dict:
    """获取外盘历史数据。"""
    return await _get_source().get_foreign_hist(symbol)


async def get_basis(symbol: str) -> dict:
    """获取基差数据。"""
    return await _get_source().get_basis(symbol)


async def get_macro_pmi() -> dict:
    """获取 PMI 宏观数据。"""
    return await _get_source().get_macro_pmi()


async def get_macro_rate() -> dict:
    """获取利率宏观数据。"""
    return await _get_source().get_macro_rate()
