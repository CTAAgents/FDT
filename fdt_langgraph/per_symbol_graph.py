"""P4 逐品种辩论子图 — 从主图提取的独立 LangGraph 子图。

封装一个或多个品种的完整辩论流程（prepare_one_symbol → P3 → debate
→ verdict → risk → quality → aggregate_results），
可独立编译、独立测试、嵌入主图作为单节点。

用法:
    # 独立使用
    subgraph = build_per_symbol_subgraph("default")
    result = subgraph.invoke(initial_state)

    # 嵌入主图
    graph.add_node("per_symbol_debate", build_per_symbol_subgraph(mode))
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langgraph.graph import END, StateGraph

from fdt_langgraph._routing import (
    _get_p3_node_names,
    route_after_merge_research,
    route_after_quality_inspect,
)
from fdt_langgraph.nodes import (
    node_aggregate_results,
    node_bear_final,
    node_bearish_rebuttal,
    node_bearish_v1,
    node_bull_final,
    node_bullish_rebuttal,
    node_bullish_v1,
    node_chain,
    node_fundamental,
    node_merge_research,
    node_prepare_one_symbol,
    node_quality_inspect,
    node_right_side_check,
    node_risk_check,
    node_route_next_symbol,
    node_sentiment,
    node_store_per_symbol_result,
    node_technical,
    node_verdict,
)
from fdt_langgraph.state import DebateState

logger = logging.getLogger(__name__)


def _build_per_symbol_subgraph_inner(mode: str) -> StateGraph:
    """构建逐品种辩论子图（内部函数，不缓存）。

    Args:
        mode: 运行模式（影响 P3 源的选择）

    Returns:
        编译好的 StateGraph，可嵌入主图或独立运行。

    子图内部路由:
        prepare_one_symbol
          → [chain/tech/fund/sent] (fan-out)
          → merge_research
          → [fast] verdict / [debate] 6 辩论节点
          → verdict → right_side_check → risk_check → quality_inspect
          → [FAIL+重试<2] → prepare_one_symbol (重修)
          → [PASS] → store_per_symbol_result
            → [还有品种] → prepare_one_symbol (下一品种)
            → [全部完成] → aggregate_results → 子图出口
    """
    graph = StateGraph(DebateState)

    # ── 注册 16+ 个节点 ──
    graph.add_node("prepare_one_symbol", node_prepare_one_symbol)

    graph.add_node("chain", node_chain)
    graph.add_node("technical", node_technical)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("sentiment", node_sentiment)
    graph.add_node("merge_research", node_merge_research)

    graph.add_node("bullish_v1", node_bullish_v1)
    graph.add_node("bearish_v1", node_bearish_v1)
    graph.add_node("bearish_rebuttal", node_bearish_rebuttal)
    graph.add_node("bullish_rebuttal", node_bullish_rebuttal)
    graph.add_node("bear_final", node_bear_final)
    graph.add_node("bull_final", node_bull_final)

    graph.add_node("verdict", node_verdict)
    graph.add_node("right_side_check", node_right_side_check)
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("quality_inspect", node_quality_inspect)
    graph.add_node("store_per_symbol_result", node_store_per_symbol_result)
    graph.add_node("aggregate_results", node_aggregate_results)

    graph.set_entry_point("prepare_one_symbol")
    graph.set_finish_point("aggregate_results")

    # ── P3 四源并行：扇出到全部 P3 节点 ──
    p3_nodes = _get_p3_node_names(mode)
    for node_name in p3_nodes:
        graph.add_edge("prepare_one_symbol", node_name)
        graph.add_edge(node_name, "merge_research")

    # ── 辩论链条 ──
    graph.add_conditional_edges("merge_research", route_after_merge_research, {
        "bullish_v1": "bullish_v1",
        "verdict": "verdict",  # fast 模式跳过辩论
    })
    graph.add_conditional_edges("bullish_v1", lambda s: "bearish_v1", {"bearish_v1": "bearish_v1"})
    graph.add_conditional_edges("bearish_v1", lambda s: "bearish_rebuttal", {"bearish_rebuttal": "bearish_rebuttal"})
    graph.add_conditional_edges("bearish_rebuttal", lambda s: "bullish_rebuttal", {"bullish_rebuttal": "bullish_rebuttal"})
    graph.add_conditional_edges("bullish_rebuttal", lambda s: "bear_final", {"bear_final": "bear_final"})
    graph.add_conditional_edges("bear_final", lambda s: "bull_final", {"bull_final": "bull_final"})
    graph.add_conditional_edges("bull_final", lambda s: "verdict", {"verdict": "verdict"})

    # ── 裁决 + 风控 + 质检 ──
    graph.add_edge("verdict", "right_side_check")
    graph.add_edge("right_side_check", "risk_check")
    graph.add_edge("risk_check", "quality_inspect")

    # ── 质检路由：重修 / 存储 / 跳过 ──
    graph.add_conditional_edges("quality_inspect", route_after_quality_inspect, {
        "prepare_one_symbol": "prepare_one_symbol",
        "store_per_symbol_result": "store_per_symbol_result",
        "aggregate_results": "aggregate_results",
    })

    # ── 品种循环路由 ──
    graph.add_conditional_edges("store_per_symbol_result", node_route_next_symbol, {
        "prepare_one_symbol": "prepare_one_symbol",
        "aggregate_results": "aggregate_results",
    })

    return graph.compile()


@lru_cache(maxsize=4)
def build_per_symbol_subgraph(mode: str = "default") -> StateGraph:
    """构建逐品种辩论子图（带 LRU 缓存）。

    Args:
        mode: 运行模式（影响 P3 源的选择）

    Returns:
        编译好的 StateGraph，可嵌入主图或独立运行。

    因主图构建时会调用 build_per_symbol_subgraph()，同一 mode 的子图可复用。
    缓存大小为 4（覆盖 default/fast/deep_research/tournament 四种模式）。
    """
    logger.debug("[per_symbol_subgraph] building subgraph for mode=%s", mode)
    return _build_per_symbol_subgraph_inner(mode)
