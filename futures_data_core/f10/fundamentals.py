"""基本面数据路由 [LLM-ENHANCED]。

三层数据策略（与设计方案一致）：
  1. 静态缓存 [INDEPENDENT]：``cache/fundamental_cache/*.json`` 预采集快照
  2. 确定性爬虫 [INDEPENDENT]：可注入 ``scraper``（如交易所/生意社）
  3. LLM WebSearch [LLM-DRIVEN]：``use_llm=True`` 时调用，失败静默降级

默认 ``use_llm=False``：仅用第 1+2 层，完全独立运行。
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Awaitable, Callable, Optional, Union

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.core._datacore_bridge import (
    dc_result_to_a2apayload,
    try_datacore_first,
)
from futures_data_core._llm_bridge import llm_websearch

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "cache", "fundamental_cache"
)


def _cache_files(data_type: str, cache_dir: str) -> list[str]:
    if data_type == "all":
        return sorted(glob.glob(os.path.join(cache_dir, "*.json")))
    return [os.path.join(cache_dir, f"{data_type}.json")]


def _merge(base: dict, overlay: dict) -> dict:
    """合并两层数据，overlay 优先（纯函数）。"""
    return {**base, **overlay}


def _load_cache(
    symbol: str, data_type: str = "all", cache_dir: str = CACHE_DIR
) -> Optional[dict]:
    """从静态缓存加载品种基本面（纯函数）。

    支持两种文件结构：
      - 按品种聚合：``{"CU": {...}, "RB": {...}}``
      - 直接字段：``{"supply": ..., "cached_at": "..."}``

    Returns:
        合并后的 dict（含 ``cached_at``）；无匹配时 ``None``。
    """
    files = _cache_files(data_type, cache_dir)
    merged: dict[str, Any] = {}
    cached_at: Any = None
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        key_up = symbol.upper()
        key_lo = symbol.lower()
        if key_up in data:
            merged.update(data[key_up])
        elif key_lo in data:
            merged.update(data[key_lo])
        elif any(k in data for k in ("cached_at", "supply", "demand", "inventory", "margin")):
            merged.update(data)
        if "cached_at" in data:
            cached_at = data.get("cached_at")
    if merged:
        merged["cached_at"] = cached_at
        return merged
    return None


async def get_fundamental(
    symbol: str,
    data_type: str = "all",
    use_llm: bool = False,
    *,
    cache_dir: Optional[str] = None,
    scraper: Optional[Callable[[str, str], Union[dict, Awaitable[Optional[dict]]]]] = None,
) -> A2APayload:
    """获取品种基本面数据。

    Args:
        symbol: 品种代码。
        data_type: ``supply`` / ``demand`` / ``inventory`` / ``margin`` / ``all``。
        use_llm: 是否启用 LLM 实时搜索（默认 ``False``，仅独立层）。
        cache_dir: 静态缓存目录（测试可注入）。
        scraper: 可注入确定性爬虫（返回 dict）。

    Returns:
        :class:`A2APayload`，``meta`` 含 ``mode`` / ``llm_used`` / ``sources``。
    """
    # v9.4.0: Data-Core 优先检查
    dc_result, dc_used = await try_datacore_first("get_fundamental", symbol)
    if dc_used:
        return dc_result_to_a2apayload(
            dc_result, symbol, DATA_TYPES["FUNDAMENTAL"],
            f"{symbol} 基本面（Data-Core）",
        )

    cache_dir = cache_dir or CACHE_DIR
    result = _load_cache(symbol, data_type, cache_dir) or {}
    sources: list[dict] = []
    if result:
        sources.append(
            {"name": "static_cache", "type": "cache", "cached_at": result.get("cached_at")}
        )

    # 第 2 层：确定性爬虫
    if scraper is not None:
        scraped = scraper(symbol, data_type)
        if hasattr(scraped, "__await__"):
            scraped = await scraped
        if scraped:
            result = _merge(result, scraped)
            sources.append({"name": "scraper", "type": "collector"})

    # 第 3 层：LLM WebSearch（增强，失败静默降级）
    mode = "independent"
    llm_used = False
    if use_llm:
        try:
            llm_text = await llm_websearch(f"{symbol} 期货基本面 {data_type} 供需 库存 利润 最新")
            if llm_text:
                result["llm_text"] = llm_text[:500]
                mode = "llm_enhanced"
                llm_used = True
        except Exception:
            result.setdefault("llm_note", "LLM 调用失败，已降级为独立模式")

    payload = A2APayload(
        type=DATA_TYPES["FUNDAMENTAL"], runtime_mode=mode, data=result
    )
    payload.set_grade("DAILY" if result else "UNAVAILABLE")
    payload.meta["llm_used"] = llm_used
    payload.meta["sources"] = sources
    if not result:
        payload.add_warning("基本面数据缺失（静态缓存/爬虫/LLM 均无结果）")
    payload.summary = f"{symbol} 基本面（{mode}）"
    return payload
