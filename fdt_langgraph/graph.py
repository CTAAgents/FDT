from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import os
from pathlib import Path
from .state import DebateState
from .nodes import (
    node_scan, node_judge_direction,
    node_chain, node_technical, node_fundamental, node_merge_research,
    node_debate, node_verdict, node_trading_plan, node_risk_check, node_report
)


def _get_checkpointer():
    """获取 Checkpointer 实例。

    优先级：
    1. FDT_CHECKPOINTER=pg 且 PG 可连接 → PostgreSQL Checkpointer
    2. 默认 → SQLite Checkpointer（memory/langgraph.db）

    PG Checkpointer 需要安装 langgraph-checkpoint-postgres 包。
    """
    use_pg = os.environ.get("FDT_CHECKPOINTER", "").lower() == "pg"

    if use_pg:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from fdt_pg.connection import PGConnection
            engine = PGConnection.get_engine()
            # PostgresSaver 需要同步连接
            import psycopg2
            config = PGConnection._config
            conn = psycopg2.connect(
                host=config.host, port=config.port,
                dbname=config.database, user=config.username,
                password=config.password,
            )
            return PostgresSaver(conn)
        except ImportError:
            pass  # 降级到 SQLite
        except Exception:
            pass  # 降级到 SQLite

    # 默认 SQLite Checkpointer
    db_path = Path("memory/langgraph.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    return SqliteSaver(conn)


def calculate_divergence(state: DebateState) -> float:
    bull_score = sum(arg.get("confidence", 0) for arg in state["bullish_arguments"])
    bear_score = sum(arg.get("confidence", 0) for arg in state["bearish_arguments"])
    total = bull_score + bear_score
    if total == 0:
        return 0.0
    return abs(bull_score - bear_score) / total


def should_skip_debate(state: DebateState) -> str:
    if state["mode"] == "fast":
        return "verdict"
    return "debate"


def should_deep_debate(state: DebateState) -> str:
    if state["mode"] == "deep_research":
        divergence = calculate_divergence(state)
        if divergence > 0.7:
            return "debate"
    return "verdict"


def build_debate_graph(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)

    graph.add_node("scan", node_scan)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("chain", node_chain)
    graph.add_node("technical", node_technical)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("merge_research", node_merge_research)
    graph.add_node("debate", node_debate)
    graph.add_node("verdict", node_verdict)
    graph.add_node("trading_plan", node_trading_plan)
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("report", node_report)

    graph.set_entry_point("scan")

    graph.add_edge("scan", "judge_direction")

    p3_nodes = []
    if "chain" in mode or mode == "default":
        p3_nodes.append("chain")
    if "technical" in mode or mode == "default":
        p3_nodes.append("technical")
    if "fundamental" in mode or mode == "default":
        p3_nodes.append("fundamental")

    for node_name in p3_nodes:
        graph.add_edge("judge_direction", node_name)
        graph.add_edge(node_name, "merge_research")

    graph.add_conditional_edges("merge_research", should_skip_debate)
    graph.add_conditional_edges("debate", should_deep_debate)
    graph.add_edge("verdict", "trading_plan")
    graph.add_edge("trading_plan", "risk_check")
    graph.add_edge("risk_check", "report")
    graph.add_edge("report", END)

    from pathlib import Path
    memory = _get_checkpointer()
    graph = graph.compile(checkpointer=memory)

    return graph


def build_debate_graph_no_checkpoint(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)

    graph.add_node("scan", node_scan)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("chain", node_chain)
    graph.add_node("technical", node_technical)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("merge_research", node_merge_research)
    graph.add_node("debate", node_debate)
    graph.add_node("verdict", node_verdict)
    graph.add_node("trading_plan", node_trading_plan)
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("report", node_report)

    graph.set_entry_point("scan")

    graph.add_edge("scan", "judge_direction")

    p3_nodes = []
    if "chain" in mode or mode == "default":
        p3_nodes.append("chain")
    if "technical" in mode or mode == "default":
        p3_nodes.append("technical")
    if "fundamental" in mode or mode == "default":
        p3_nodes.append("fundamental")

    for node_name in p3_nodes:
        graph.add_edge("judge_direction", node_name)
        graph.add_edge(node_name, "merge_research")

    graph.add_conditional_edges("merge_research", should_skip_debate)
    graph.add_conditional_edges("debate", should_deep_debate)
    graph.add_edge("verdict", "trading_plan")
    graph.add_edge("trading_plan", "risk_check")
    graph.add_edge("risk_check", "report")
    graph.add_edge("report", END)

    graph = graph.compile()

    return graph