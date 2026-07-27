"""
graph.py — 辩论主图构建函数

使用逐品种辩论子图 (per_symbol_subgraph) 替代原来的全部内联节点。

旧版路由/辅助函数已迁移至 _routing.py，此处保留向后兼容的 re-export。

主图节点（7 个）:
  scan → freshness_gate → judge_direction
      → [per_symbol_subgraph (16 个内部节点)]
      → report → signal_output → END

直接辩论模式节点（8 个）:
  load_cache → judge_direction
      → [per_symbol_subgraph (16 个内部节点)]
      → report → signal_output → update_cache → END
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from fdt_langgraph._routing import (
    calculate_divergence,
    route_after_freshness,
    route_after_merge_research,
    route_after_quality_inspect,
    _get_current_symbol,
    _get_p3_node_names,
    _should_skip_p3_source,
)
from fdt_langgraph.nodes import (
    node_aggregate_results,
    node_freshness_gate,
    node_judge_direction,
    node_load_cache,
    node_report,
    node_scan,
    node_signal_output,
    node_update_cache,
)
from fdt_langgraph.per_symbol_graph import build_per_symbol_subgraph
from fdt_langgraph.state import DebateState

logger = logging.getLogger(__name__)

# ── 向后兼容 re-export ──
# 这些函数已迁移到 _routing.py，保持在此处导出供外部代码导入
__all__ = [
    "calculate_divergence",
    "route_after_freshness",
    "route_after_merge_research",
    "route_after_quality_inspect",
    "_get_current_symbol",
    "_get_p3_node_names",
    "_should_skip_p3_source",
]


# ═══════════════════════════════════════════════════════
# Checkpointer
# ═══════════════════════════════════════════════════════


def _get_checkpointer():
    """获取 checkpointer 实例（PG → SQLite 降级）。"""
    use_pg = os.environ.get("FDT_CHECKPOINTER", "").lower() == "pg"

    if use_pg:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            from fdt_pg.connection import PGConnection
            engine = PGConnection.get_engine()
            import psycopg2
            config = PGConnection._config
            conn = psycopg2.connect(
                host=config.host, port=config.port,
                dbname=config.database, user=config.username,
                password=config.password,
            )
            return PostgresSaver(conn)
        except ImportError:
            pass
        except Exception:
            pass

    db_path = Path("memory/langgraph.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    return SqliteSaver(conn)


# ═══════════════════════════════════════════════════════
# 主图构建（含子图）
# ═══════════════════════════════════════════════════════


def _register_debate_graph(graph: StateGraph, mode: str) -> None:
    """注册辩论主图（含逐品种辩论子图）。

    主图节点:
      scan → freshness_gate → judge_direction
          → per_symbol_subgraph (18 个内部节点 + 循环边)
          → report → signal_output → END
    """
    # ── 前置节点 ──
    graph.add_node("scan", node_scan)
    graph.add_node("freshness_gate", node_freshness_gate)
    graph.add_node("judge_direction", node_judge_direction)

    # ── P4 逐品种辩论子图（1 个节点替代原来 16 个节点 + 全部边） ──
    per_symbol_subgraph = build_per_symbol_subgraph(mode)
    graph.add_node("per_symbol_debate", per_symbol_subgraph)

    # ── 后置节点 ──
    graph.add_node("aggregate_results", node_aggregate_results)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    # ── 边 ──
    graph.set_entry_point("scan")
    graph.add_edge("scan", "freshness_gate")
    graph.add_conditional_edges("freshness_gate", route_after_freshness, {
        "judge_direction": "judge_direction",
        "aggregate_results": "aggregate_results",
    })
    graph.add_edge("judge_direction", "per_symbol_debate")
    graph.add_edge("per_symbol_debate", "aggregate_results")
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", END)


def _register_direct_debate_graph(graph: StateGraph, mode: str) -> None:
    """直接辩论模式（跳过 scan，从 load_cache 进入，辩论后更新缓存）。"""
    graph.add_node("load_cache", node_load_cache)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("update_cache", node_update_cache)

    per_symbol_subgraph = build_per_symbol_subgraph(mode)
    graph.add_node("per_symbol_debate", per_symbol_subgraph)

    graph.add_node("aggregate_results", node_aggregate_results)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    graph.set_entry_point("load_cache")
    graph.add_edge("load_cache", "judge_direction")
    graph.add_edge("judge_direction", "per_symbol_debate")
    graph.add_edge("per_symbol_debate", "aggregate_results")
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", "update_cache")
    graph.add_edge("update_cache", END)


# ═══════════════════════════════════════════════════════
# 公开构建函数
# ═══════════════════════════════════════════════════════


def build_debate_graph(mode: str = "fast") -> StateGraph:
    """构建辩论图（含 checkpointer）。"""
    graph = StateGraph(DebateState)
    _register_debate_graph(graph, mode)

    memory = _get_checkpointer()
    graph = graph.compile(checkpointer=memory)
    return graph


def build_debate_graph_with_profile(profile: str = "default") -> StateGraph:
    """从 Profile 名称构建辩论图 (G93: 替代 coordinator.py)"""
    PROFILE_MODES = {
        "default": "default",
        "fast": "fast",
        "deep_research": "deep_research",
        "tournament": "default",
    }
    mode = PROFILE_MODES.get(profile, "fast")
    return build_debate_graph(mode=mode)


def build_debate_graph_no_checkpoint(mode: str = "fast") -> StateGraph:
    """构建辩论图（无 checkpointer）。"""
    graph = StateGraph(DebateState)

    direct_debate = os.environ.get("FDT_DIRECT_DEBATE", "").lower() == "true"

    if direct_debate:
        _register_direct_debate_graph(graph, mode)
    else:
        _register_debate_graph(graph, mode)

    graph = graph.compile()
    return graph
