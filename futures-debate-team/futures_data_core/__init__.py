"""futures-data-core — 期货数据采集核心（独立运行）。

运行模式说明:
  [INDEPENDENT]    纯 Python 执行，无需 LLM 上下文
  [LLM-ENHANCED]   基础功能独立运行，增强功能需 LLM
  [LLM-DRIVEN]     必须通过 LLM 执行

本模块 (v0.1.x) 已交付 [INDEPENDENT] 核心:
  - 品种映射 / 数据新鲜度评估
  - 技术指标 (numpy 纯函数)
  - 采集器抽象基类与运行模式声明
  - A2A 兼容数据信封
  - F10 衍生品数据（期限结构 / 价差 / 基差 / 仓单 / 基本面）

公开 API 直接委托给底层模块，调用方无需关心内部降级链与传输细节。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from futures_data_core._version import VERSION, __version__

from futures_data_core._a2a import (
    A2ABatchPayload,
    A2APayload,
    DATA_GRADE_NAME,
    DATA_TYPES,
    RUNTIME_MODES,
)
from futures_data_core._runtime import (
    RuntimeMode,
    current_environment,
    detect_llm_capability,
)
from futures_data_core.core import (
    data_grade_from_age,
    evaluate,
    get_symbol,
    is_known,
    list_exchanges,
    list_symbols,
)
from futures_data_core.core.multi_source_adapter import MultiSourceAdapter
from futures_data_core.f10 import (
    analyze_term_structure,
    compute_basis,
    compute_spread,
    get_basis,
    get_fundamental,
    get_sentiment,
    get_term_structure,
    get_warrant,
    search_fundamental_llm,
)
from futures_data_core.indicators.core import INDICATOR_NAMES, compute_indicators

# 惰性适配器单例：导入本包时不构造，首次调用数据 API 时才创建，
# 避免导入期副作用（如探测采集器可用性）。
_ADAPTER: Optional[MultiSourceAdapter] = None


def get_adapter() -> MultiSourceAdapter:
    """返回进程级 :class:`MultiSourceAdapter` 单例。"""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = MultiSourceAdapter()
    return _ADAPTER


def reset_adapter() -> None:
    """重置适配器单例（主要用于测试隔离）。"""
    global _ADAPTER
    _ADAPTER = None


# ════════════════════════════════════════════════════════════
# [INDEPENDENT] K 线 / 行情（多源降级链）
# ════════════════════════════════════════════════════════════
async def get_kline(
    symbol: str, period: str = "daily", days: int = 120, source: str = "auto"
) -> A2APayload:
    """获取 K 线数据，自动降级。无 LLM 依赖。"""
    return await get_adapter().get_kline(symbol, period, days, source)


async def get_quote(symbol: str, source: str = "auto") -> A2APayload:
    """获取行情快照，自动降级。无 LLM 依赖。"""
    return await get_adapter().get_quote(symbol, source)


# ════════════════════════════════════════════════════════════
# [INDEPENDENT] F10 衍生品数据
# ════════════════════════════════════════════════════════════
async def get_spread(
    symbol: str,
    month_near: Optional[str] = None,
    month_far: Optional[str] = None,
    *,
    fetch_contracts: Optional[Callable[[str], Any]] = None,
) -> A2APayload:
    """跨期价差。无 LLM 依赖。"""
    from futures_data_core.f10.spread import get_spread as _gs

    return await _gs(
        symbol, month_near=month_near, month_far=month_far, fetch_contracts=fetch_contracts
    )


async def get_f10(
    symbol: str,
    enhance_with_llm: bool = False,
    *,
    fetch_contracts: Optional[Callable[[str], Any]] = None,
    fetch_spot: Optional[Callable[[str], Any]] = None,
    fetch_futures: Optional[Callable[[str], Any]] = None,
    transport: Optional[Callable[[str], Any]] = None,
    cache_dir: Optional[str] = None,
    scraper: Optional[Callable[[str, str], Any]] = None,
) -> A2APayload:
    """F10 综合报告。

    运行模式:
      - enhance_with_llm=False (默认): [INDEPENDENT] 纯数据组装
      - enhance_with_llm=True:         [LLM-ENHANCED] 基本面叠加 LLM 实时采集

    返回 :class:`A2APayload`，``data`` 含 ``term_structure`` / ``spread`` /
    ``basis`` / ``warrant`` / ``fundamental`` 五个子块。
    """
    ts = await get_term_structure(symbol, fetch_contracts=fetch_contracts)
    sp = await get_spread(symbol, fetch_contracts=fetch_contracts)
    bs = await get_basis(symbol, fetch_spot=fetch_spot, fetch_futures=fetch_futures)
    wt = await get_warrant(symbol, transport=transport)
    fm = await get_fundamental(
        symbol, use_llm=enhance_with_llm, cache_dir=cache_dir, scraper=scraper
    )

    llm_used = bool(enhance_with_llm and fm.meta.get("llm_used"))
    runtime_mode = "llm_enhanced" if llm_used else "independent"

    data = {
        "symbol": symbol,
        "term_structure": ts.data,
        "spread": sp.data,
        "basis": bs.data,
        "warrant": wt.data,
        "fundamental": fm.data,
    }
    payload = A2APayload(type=DATA_TYPES["F10"], runtime_mode=runtime_mode, data=data)

    # 整体等级取各子项最差（标签数值最大）等级，作为可信度下界
    grades = [
        ts.meta["data_grade_label"],
        sp.meta["data_grade_label"],
        bs.meta["data_grade_label"],
        wt.meta["data_grade_label"],
        fm.meta["data_grade_label"],
    ]
    payload.set_grade(DATA_GRADE_NAME[max(grades)])

    sources = set()
    for sub in (ts, sp, bs, wt, fm):
        for s in sub.meta.get("sources", []):
            # 各子项 sources 类型不统一：期限结构/价差/基差/仓单为字符串，
            # 基本面为富字典（含 name/type/cached_at）。聚合时归一为可哈希键。
            if isinstance(s, str):
                sources.add(s)
            elif isinstance(s, dict):
                sources.add(s.get("name") or s.get("type") or str(s))
            else:
                sources.add(str(s))
    payload.meta["llm_used"] = llm_used
    payload.meta["sources"] = sorted(sources)
    payload.summary = f"{symbol} F10 综合报告（期限结构/价差/基差/仓单/基本面）"
    return payload


__all__ = [
    "__version__",
    "VERSION",
    # A2A
    "A2APayload",
    "A2ABatchPayload",
    "DATA_GRADE_NAME",
    "DATA_TYPES",
    "RUNTIME_MODES",
    # 运行模式
    "RuntimeMode",
    "detect_llm_capability",
    "current_environment",
    # 品种 / 新鲜度
    "get_symbol",
    "is_known",
    "list_exchanges",
    "list_symbols",
    "evaluate",
    "data_grade_from_age",
    # 指标
    "compute_indicators",
    "INDICATOR_NAMES",
    # 适配器
    "get_adapter",
    "reset_adapter",
    "MultiSourceAdapter",
    # 公开数据 API
    "get_kline",
    "get_quote",
    "get_term_structure",
    "analyze_term_structure",
    "get_spread",
    "compute_spread",
    "get_basis",
    "compute_basis",
    "get_warrant",
    "get_fundamental",
    "get_f10",
    "get_sentiment",
    "search_fundamental_llm",
]
