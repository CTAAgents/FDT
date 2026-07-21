"""
FDT 数据源切换适配层 — FDC ↔ Data-Core 统一接口。

通过环境变量 ``FDT_DATA_SOURCE`` 控制：
  - ``fdc`` (默认)：使用 ``futures_data_core`` 包
  - ``datacore``：使用 ``datacore.fdc_compat`` 包

所有数据消费者（scan_all.py, fdt_langgraph/nodes.py）统一通过本模块获取数据，
无需关心底层使用哪个数据源。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("data_source_adapter")

# ── 当前选中的数据源 ──
_DATA_SOURCE: str | None = None  # "fdc" or "datacore"


def get_data_source() -> str:
    """返回当前数据源名称。"""
    global _DATA_SOURCE
    if _DATA_SOURCE is None:
        _DATA_SOURCE = os.environ.get("FDT_DATA_SOURCE", "fdc").lower().strip()
        if _DATA_SOURCE not in ("fdc", "datacore"):
            logger.warning(
                "[DataAdapter] FDT_DATA_SOURCE=%s 无效，回退到 fdc", _DATA_SOURCE
            )
            _DATA_SOURCE = "fdc"
        logger.info("[DataAdapter] 数据源: %s", _DATA_SOURCE)
    return _DATA_SOURCE


def set_data_source(source: str) -> None:
    """动态切换数据源（主要用于测试）。"""
    global _DATA_SOURCE
    source = source.lower().strip()
    if source not in ("fdc", "datacore"):
        raise ValueError(f"不支持的数据源: {source}，仅支持 fdc / datacore")
    _DATA_SOURCE = source
    logger.info("[DataAdapter] 数据源已切换为: %s", source)


# ════════════════════════════════════════════════════════════
# 懒加载模块获取
# ════════════════════════════════════════════════════════════


def _get_fdc():
    """导入并返回 futures_data_core 模块。"""
    import futures_data_core as _m

    return _m


def _get_datacore():
    """导入并返回 datacore.fdc_compat 模块。"""
    from datacore import fdc_compat as _m

    return _m


def _get_source_module():
    """获取当前数据源对应的顶层模块。"""
    if get_data_source() == "datacore":
        return _get_datacore()
    return _get_fdc()


# ════════════════════════════════════════════════════════════
# K 线 / 行情（核心数据接口）
# ════════════════════════════════════════════════════════════


async def get_kline(
    symbol: str, period: str = "daily", days: int = 120, source: str = "auto"
) -> Any:
    """获取 K 线数据。"""
    mod = _get_source_module()
    return await mod.get_kline(symbol, period=period, days=days, source=source)


async def get_quote(symbol: str, source: str = "auto") -> Any:
    """获取行情快照。"""
    mod = _get_source_module()
    try:
        return await mod.get_quote(symbol, source=source)
    except TypeError:
        return await mod.get_quote(symbol)


async def batch_get_quotes(symbols: list[str]) -> dict[str, dict]:
    """批量获取行情快照。"""
    mod = _get_source_module()
    return await mod.batch_get_quotes(symbols)


# ════════════════════════════════════════════════════════════
# 技术指标
# ════════════════════════════════════════════════════════════


def compute_indicators(data: dict, indicators: str = "all") -> dict:
    """计算技术指标。"""
    mod = _get_source_module()
    return mod.compute_indicators(data, indicators=indicators)


# ════════════════════════════════════════════════════════════
# F10 衍生品数据
# ════════════════════════════════════════════════════════════


async def get_term_structure(symbol: str, **kwargs) -> Any:
    """获取期限结构。"""
    mod = _get_source_module()
    return await mod.get_term_structure(symbol, **kwargs)


async def get_spread(symbol: str, **kwargs) -> Any:
    """获取跨期价差。"""
    mod = _get_source_module()
    return await mod.get_spread(symbol, **kwargs)


async def get_basis(symbol: str, **kwargs) -> Any:
    """获取基差。"""
    mod = _get_source_module()
    return await mod.get_basis(symbol, **kwargs)


async def get_warrant(symbol: str, **kwargs) -> Any:
    """获取仓单数据。"""
    mod = _get_source_module()
    return await mod.get_warrant(symbol, **kwargs)


async def get_fundamental(symbol: str, **kwargs) -> Any:
    """获取基本面数据。"""
    mod = _get_source_module()
    return await mod.get_fundamental(symbol, **kwargs)


async def get_position_ranking(symbol: str) -> Any:
    """获取持仓排名。"""
    mod = _get_source_module()
    return await mod.get_position_ranking(symbol)


async def get_f10(symbol: str, **kwargs) -> Any:
    """获取 F10 综合报告。"""
    mod = _get_source_module()
    return await mod.get_f10(symbol, **kwargs)


# ════════════════════════════════════════════════════════════
# FDC 专有子模块适配（Data-Core 中无对应子路径时降级）
# ════════════════════════════════════════════════════════════


def _import_fdc_sub(path: str, name: str) -> Any:
    """从 futures_data_core.{path} 导入指定符号（FDC fallback）。"""
    import importlib

    mod = importlib.import_module(f"futures_data_core.{path}")
    return getattr(mod, name)


async def get_warrant_fdc(symbol: str, transport=None) -> Any:
    """获取仓单数据（经 FDC f10 子路径）。"""
    if get_data_source() == "datacore":
        try:
            mod = _get_datacore()
            return await mod.get_warrant(symbol)
        except (AttributeError, Exception) as e:
            logger.debug("[DataAdapter] datacore.get_warrant 不可用: %s", e)
            func = _import_fdc_sub("f10.warrant", "get_warrant")
            return await func(symbol, transport=transport)
    func = _import_fdc_sub("f10.warrant", "get_warrant")
    return await func(symbol, transport=transport)


def load_fundamental(symbol: str, **kwargs) -> Any:
    """从基本面缓存加载数据。"""
    if get_data_source() == "datacore":
        try:
            from datacore.fdc_compat import get_fundamental as _gf

            return _gf(symbol, **kwargs)
        except (ImportError, Exception) as e:
            logger.debug("[DataAdapter] datacore load_fundamental 不可用: %s", e)
            func = _import_fdc_sub("cache.f10_cache", "load_fundamental")
            return func(symbol, **kwargs)
    func = _import_fdc_sub("cache.f10_cache", "load_fundamental")
    return func(symbol, **kwargs)


def get_macro_pmi(**kwargs) -> Any:
    """获取 PMI 宏观数据。"""
    if get_data_source() == "datacore":
        try:
            from datacore.fdc_compat import get_pmi as _gp

            return _gp(**kwargs)
        except (ImportError, AttributeError, Exception) as e:
            logger.debug("[DataAdapter] datacore PMI 不可用: %s", e)
            func = _import_fdc_sub("f10.macro", "get_macro_pmi")
            return func(**kwargs)
    func = _import_fdc_sub("f10.macro", "get_macro_pmi")
    return func(**kwargs)


def get_macro_rate(**kwargs) -> Any:
    """获取利率宏观数据。"""
    if get_data_source() == "datacore":
        try:
            from datacore.fdc_compat import get_rate as _gr

            return _gr(**kwargs)
        except (ImportError, AttributeError, Exception) as e:
            logger.debug("[DataAdapter] datacore 利率不可用: %s", e)
            func = _import_fdc_sub("f10.macro", "get_macro_rate")
            return func(**kwargs)
    func = _import_fdc_sub("f10.macro", "get_macro_rate")
    return func(**kwargs)


# ════════════════════════════════════════════════════════════
# 金十 MCP 快讯/资讯/日历（FDC 专有，Data-Core 无对应）
# ════════════════════════════════════════════════════════════


_jin10_fetcher: Any = None


def _get_jin10() -> Any:
    """获取金十 MCP 采集器单例。"""
    global _jin10_fetcher
    if _jin10_fetcher is None:
        cls = _import_fdc_sub("f10.jin10_mcp", "Jin10McpFetcher")
        _jin10_fetcher = cls()
    return _jin10_fetcher


def jin10_available() -> bool:
    """金十 MCP 是否可用（已设置 token）。"""
    try:
        fetcher = _get_jin10()
        return fetcher.available
    except Exception as e:
        logger.debug("[DataAdapter] 金十 MCP 不可用: %s", e)
        return False


async def jin10_list_flash(cursor: str | None = None) -> dict:
    """获取金十最新快讯列表。"""
    fetcher = _get_jin10()
    return await fetcher.list_flash(cursor=cursor)


async def jin10_search_flash(keyword: str, cursor: str | None = None) -> dict:
    """按关键词搜索金十快讯。"""
    fetcher = _get_jin10()
    return await fetcher.search_flash(keyword, cursor=cursor)


async def jin10_list_news(cursor: str | None = None) -> dict:
    """获取金十最新资讯列表。"""
    fetcher = _get_jin10()
    return await fetcher.list_news(cursor=cursor)


async def jin10_search_news(keyword: str, cursor: str | None = None) -> dict:
    """按关键词搜索金十资讯。"""
    fetcher = _get_jin10()
    return await fetcher.search_news(keyword, cursor=cursor)


async def jin10_get_news(news_id: str) -> dict:
    """获取金十单篇资讯详情。"""
    fetcher = _get_jin10()
    return await fetcher.get_news(news_id)


async def jin10_list_calendar() -> dict:
    """获取金十财经日历数据。"""
    fetcher = _get_jin10()
    return await fetcher.list_calendar()


async def jin10_get_quote(code: str) -> dict:
    """获取金十外盘品种实时报价。"""
    fetcher = _get_jin10()
    return await fetcher.get_quote(code)


async def jin10_get_kline(code: str, time: str = "1day", count: int = 100) -> dict:
    """获取金十外盘品种K线数据。"""
    fetcher = _get_jin10()
    return await fetcher.get_kline(code, time=time, count=count)


# ════════════════════════════════════════════════════════════
# 品种 / 新鲜度工具
# ════════════════════════════════════════════════════════════


def list_symbols() -> list:
    """列出所有品种。"""
    mod = _get_source_module()
    return mod.list_symbols()


def is_known(code: str) -> bool:
    """是否已知品种。"""
    mod = _get_source_module()
    return mod.is_known(code)


def get_symbol(code: str) -> str:
    """品种代码标准化。"""
    mod = _get_source_module()
    return mod.get_symbol(code)


# ════════════════════════════════════════════════════════════
# 公开 API
# ════════════════════════════════════════════════════════════

__all__ = [
    "get_data_source",
    "set_data_source",
    # 核心数据接口
    "get_kline",
    "get_quote",
    "batch_get_quotes",
    "compute_indicators",
    # F10 衍生品
    "get_term_structure",
    "get_spread",
    "get_basis",
    "get_warrant",
    "get_fundamental",
    "get_position_ranking",
    "get_f10",
    # 专有子模块适配
    "get_warrant_fdc",
    "load_fundamental",
    "get_macro_pmi",
    "get_macro_rate",
    # 金十 MCP
    "jin10_available",
    "jin10_list_flash",
    "jin10_search_flash",
    "jin10_list_news",
    "jin10_search_news",
    "jin10_get_news",
    "jin10_list_calendar",
    "jin10_get_quote",
    "jin10_get_kline",
    # 工具
    "list_symbols",
    "is_known",
    "get_symbol",
]
