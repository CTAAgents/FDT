"""LLM WebSearch 行业基本面采集 [LLM-DRIVEN]。

必须在支持 WebSearch 的 LLM 上下文（如 WorkBuddy）中执行；独立 Python 环境调用
将抛出 :class:`LlmContextNotAvailableError`。

所有 LLM 调用经由 :mod:`futures_data_core._llm_bridge` 集中管理，业务代码不散落
LLM 逻辑。
"""

from __future__ import annotations

from futures_data_core._llm_bridge import assert_llm_context, llm_websearch


async def search_fundamental_llm(symbol: str, data_type: str = "all") -> dict:
    """通过 LLM WebSearch 搜索品种基本面数据。

    运行模式: ``[LLM-DRIVEN]``。

    Args:
        symbol: 品种代码。
        data_type: 数据类型（supply/demand/inventory/margin/all）。

    Returns:
        ``{"symbol", "data_type", "llm_text"}``。

    Raises:
        LlmContextNotAvailableError: 当前环境无 LLM 能力。
    """
    assert_llm_context("search_fundamental_llm")
    query = f"{symbol} 期货基本面 {data_type} 供需 库存 利润 最新"
    text = await llm_websearch(query)
    return {"symbol": symbol, "data_type": data_type, "llm_text": text}
