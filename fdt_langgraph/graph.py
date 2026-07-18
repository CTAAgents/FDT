from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import os
from pathlib import Path
from .state import DebateState
from .nodes import (
    node_scan, node_judge_direction, node_prepare_data,
    node_chain, node_technical, node_fundamental, node_merge_research,
    node_bullish_v1, node_bearish_v1,
    node_bearish_rebuttal, node_bullish_rebuttal,
    node_bear_final, node_bull_final,
    node_verdict, node_risk_check, node_report, node_signal_output,
)


def _get_checkpointer():
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


def calculate_divergence(state: DebateState) -> float:
    """计算多空分歧度 — 支持 v9.0 六阶段辩论"""
    bull_score = 0.0
    bear_score = 0.0
    for entry in state.get("bullish_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bearish_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    # 反驳阶段
    for entry in state.get("bullish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bearish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    # 最终陈述阶段
    for entry in state.get("bull_final_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bear_final_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    total = bull_score + bear_score
    if total == 0:
        return 0.0
    return abs(bull_score - bear_score) / total


# ==================== 辩论路由函数 (v9.0) ====================

def route_after_merge_research(state: DebateState) -> str:
    """P3 合并研究数据后：判断是否进入辩论"""
    if state.get("mode", "default") == "fast":
        return "verdict"       # fast 模式跳过辩论
    return "bullish_v1"        # 进入多空头攻防六节点


# ==================== 图构建函数 ====================

def _register_p3_nodes(graph: StateGraph, mode: str) -> list[str]:
    p3_nodes = []
    # 全量模式：default / deep_research / tournament 包含所有 P3 节点
    _full_p3_modes = {"default", "deep_research", "tournament"}
    if mode in _full_p3_modes or "chain" in mode:
        p3_nodes.append("chain")
    if mode in _full_p3_modes or "technical" in mode:
        p3_nodes.append("technical")
    if mode in _full_p3_modes or "fundamental" in mode:
        p3_nodes.append("fundamental")
    for node_name in p3_nodes:
        graph.add_edge("prepare_data", node_name)
        graph.add_edge(node_name, "merge_research")
    return p3_nodes


def _register_debate_nodes(graph: StateGraph) -> None:
    """注册 P4 多空头攻防六节点 (v9.0)"""
    graph.add_node("bullish_v1", node_bullish_v1)
    graph.add_node("bearish_v1", node_bearish_v1)
    graph.add_node("bearish_rebuttal", node_bearish_rebuttal)
    graph.add_node("bullish_rebuttal", node_bullish_rebuttal)
    graph.add_node("bear_final", node_bear_final)
    graph.add_node("bull_final", node_bull_final)

    # 辩论流向：merge_research -> bullish_v1 -> bearish_v1
    #           -> bearish_rebuttal -> bullish_rebuttal
    #           -> bear_final -> bull_final -> verdict
    graph.add_conditional_edges("merge_research", route_after_merge_research, {
        "bullish_v1": "bullish_v1", "verdict": "verdict",
    })
    graph.add_conditional_edges("bullish_v1", lambda s: "bearish_v1", {"bearish_v1": "bearish_v1"})
    graph.add_conditional_edges("bearish_v1", lambda s: "bearish_rebuttal", {"bearish_rebuttal": "bearish_rebuttal"})
    graph.add_conditional_edges("bearish_rebuttal", lambda s: "bullish_rebuttal", {"bullish_rebuttal": "bullish_rebuttal"})
    graph.add_conditional_edges("bullish_rebuttal", lambda s: "bear_final", {"bear_final": "bear_final"})
    graph.add_conditional_edges("bear_final", lambda s: "bull_final", {"bull_final": "bull_final"})
    graph.add_conditional_edges("bull_final", lambda s: "verdict", {"verdict": "verdict"})


def _register_common_nodes(graph: StateGraph) -> None:
    """注册 P1/P2/P5/P6 公共节点"""
    graph.add_node("scan", node_scan)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("prepare_data", node_prepare_data)
    graph.add_node("chain", node_chain)
    graph.add_node("technical", node_technical)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("merge_research", node_merge_research)
    graph.add_node("verdict", node_verdict)
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    graph.set_entry_point("scan")
    graph.add_edge("scan", "judge_direction")
    graph.add_edge("judge_direction", "prepare_data")
    graph.add_edge("verdict", "risk_check")
    graph.add_edge("risk_check", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", END)


def build_debate_graph(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)
    _register_common_nodes(graph)
    _register_p3_nodes(graph, mode)
    _register_debate_nodes(graph)

    memory = _get_checkpointer()
    graph = graph.compile(checkpointer=memory)
    return graph


def build_debate_graph_no_checkpoint(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)
    _register_common_nodes(graph)
    _register_p3_nodes(graph, mode)
    _register_debate_nodes(graph)

    graph = graph.compile()
    return graph
