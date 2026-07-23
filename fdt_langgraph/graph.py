from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import os
from pathlib import Path
from .state import DebateState
from .nodes import (
    node_scan, node_judge_direction, node_prepare_data,
    node_prepare_one_symbol, node_store_per_symbol_result,
    node_route_next_symbol, node_aggregate_results,
    node_chain, node_technical, node_fundamental, node_sentiment, node_merge_research,
    node_bullish_v1, node_bearish_v1,
    node_bearish_rebuttal, node_bullish_rebuttal,
    node_bear_final, node_bull_final,
    node_verdict, node_risk_check, node_quality_inspect, node_report, node_signal_output,
    node_load_cache, node_update_cache,
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
    for entry in state.get("bullish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bearish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
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


def route_after_quality_inspect(state: DebateState) -> str:
    """质检后路由（Phase 3 Data Governance）。

    逻辑:
      - 当前品种质检 FAIL + 重试 < 2 次 → 退回重修（prepare_one_symbol）
      - 否则 → 存入结果（store_per_symbol_result）
    """
    current_sym = _get_current_symbol(state)
    report = state.get("quality_report")
    counters = state.get("rework_counters", {})
    retries = counters.get(current_sym, 0)

    if report and report.get("status") == "FAIL" and retries < 2:
        return "prepare_one_symbol"
    return "store_per_symbol_result"


def _get_current_symbol(state: DebateState) -> str:
    """获取当前处理的品种代码。"""
    symbols = state.get("selected_symbols", [])
    idx = state.get("symbol_index", -1)
    if 0 <= idx < len(symbols):
        return symbols[idx]
    return ""


# ==================== 逐品种循环图构建 (v9.13.0) ====================

def _get_p3_node_names(mode: str) -> list[str]:
    """根据 mode 返回需要激活的四源节点列表"""
    p3 = []
    _full = {"default", "deep_research", "tournament"}
    if mode in _full or "chain" in mode:
        p3.append("chain")
    if mode in _full or "technical" in mode:
        p3.append("technical")
    if mode in _full or "fundamental" in mode:
        p3.append("fundamental")
    if mode in _full or "sentiment" in mode:
        p3.append("sentiment")
    return p3


def _register_per_symbol_loop(graph: StateGraph, mode: str) -> None:
    """注册逐品种循环流水线（v9.13.0）

    流程:
      scan → judge_direction
        → [loop begins] prepare_one_symbol
          → chain/tech/fund/sent (并行，均只处理当前品种)
          → merge_research
          → debate chain (bullish_v1 → ... → bull_final)
          → verdict → risk_check → store_per_symbol_result
          → route_next_symbol:
            - 还有品种 → 回到 prepare_one_symbol
            - 全部完成 → aggregate_results
          → report → signal_output → END
    """
    # ── 注册所有节点 ──
    graph.add_node("scan", node_scan)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("prepare_one_symbol", node_prepare_one_symbol)
    graph.add_node("store_per_symbol_result", node_store_per_symbol_result)
    graph.add_node("aggregate_results", node_aggregate_results)

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
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("quality_inspect", node_quality_inspect)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    # ── 入口边 ──
    graph.set_entry_point("scan")
    graph.add_edge("scan", "judge_direction")
    graph.add_edge("judge_direction", "prepare_one_symbol")

    # ── 四源并行（从 prepare_one_symbol 出发，均只处理单品种） ──
    p3_nodes = _get_p3_node_names(mode)
    for node_name in p3_nodes:
        graph.add_edge("prepare_one_symbol", node_name)
        graph.add_edge(node_name, "merge_research")

    # ── 辩论链条 ──
    graph.add_conditional_edges("merge_research", route_after_merge_research, {
        "bullish_v1": "bullish_v1", "verdict": "verdict",
    })
    graph.add_conditional_edges("bullish_v1", lambda s: "bearish_v1", {"bearish_v1": "bearish_v1"})
    graph.add_conditional_edges("bearish_v1", lambda s: "bearish_rebuttal", {"bearish_rebuttal": "bearish_rebuttal"})
    graph.add_conditional_edges("bearish_rebuttal", lambda s: "bullish_rebuttal", {"bullish_rebuttal": "bullish_rebuttal"})
    graph.add_conditional_edges("bullish_rebuttal", lambda s: "bear_final", {"bear_final": "bear_final"})
    graph.add_conditional_edges("bear_final", lambda s: "bull_final", {"bull_final": "bull_final"})
    graph.add_conditional_edges("bull_final", lambda s: "verdict", {"verdict": "verdict"})

    # ── 单品种收尾 + 质检 + 循环路由 ──
    # Phase 3: verdict → risk_check → quality_inspect → (PASS → store / FAIL+重试<2 → 重修)
    graph.add_edge("verdict", "risk_check")
    graph.add_edge("risk_check", "quality_inspect")
    graph.add_conditional_edges("quality_inspect", route_after_quality_inspect, {
        "prepare_one_symbol": "prepare_one_symbol",
        "store_per_symbol_result": "store_per_symbol_result",
    })
    graph.add_conditional_edges("store_per_symbol_result", node_route_next_symbol, {
        "prepare_one_symbol": "prepare_one_symbol",
        "aggregate_results": "aggregate_results",
    })

    # ── 汇聚 → 报告 ──
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", END)


def _register_direct_debate_loop(graph: StateGraph, mode: str) -> None:
    """逐品种循环 + 直接辩论（跳过 scan，从 load_cache 进入）"""
    graph.add_node("load_cache", node_load_cache)
    graph.add_node("update_cache", node_update_cache)

    # 复用逐品种循环的全部节点
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("prepare_one_symbol", node_prepare_one_symbol)
    graph.add_node("store_per_symbol_result", node_store_per_symbol_result)
    graph.add_node("aggregate_results", node_aggregate_results)

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
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("quality_inspect", node_quality_inspect)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    # ── 入口边 (load_cache → judge → per-symbol loop) ──
    graph.set_entry_point("load_cache")
    graph.add_edge("load_cache", "judge_direction")
    graph.add_edge("judge_direction", "prepare_one_symbol")

    # ── 四源并行 ──
    p3_nodes = _get_p3_node_names(mode)
    for node_name in p3_nodes:
        graph.add_edge("prepare_one_symbol", node_name)
        graph.add_edge(node_name, "merge_research")

    # ── 辩论链条 ──
    graph.add_conditional_edges("merge_research", route_after_merge_research, {
        "bullish_v1": "bullish_v1", "verdict": "verdict",
    })
    graph.add_conditional_edges("bullish_v1", lambda s: "bearish_v1", {"bearish_v1": "bearish_v1"})
    graph.add_conditional_edges("bearish_v1", lambda s: "bearish_rebuttal", {"bearish_rebuttal": "bearish_rebuttal"})
    graph.add_conditional_edges("bearish_rebuttal", lambda s: "bullish_rebuttal", {"bullish_rebuttal": "bullish_rebuttal"})
    graph.add_conditional_edges("bullish_rebuttal", lambda s: "bear_final", {"bear_final": "bear_final"})
    graph.add_conditional_edges("bear_final", lambda s: "bull_final", {"bull_final": "bull_final"})
    graph.add_conditional_edges("bull_final", lambda s: "verdict", {"verdict": "verdict"})

    # ── 单品种收尾 + 质检 + 循环路由 ──
    # Phase 3: verdict → risk_check → quality_inspect → (PASS → store / FAIL+重试<2 → 重修)
    graph.add_edge("verdict", "risk_check")
    graph.add_edge("risk_check", "quality_inspect")
    graph.add_conditional_edges("quality_inspect", route_after_quality_inspect, {
        "prepare_one_symbol": "prepare_one_symbol",
        "store_per_symbol_result": "store_per_symbol_result",
    })
    graph.add_conditional_edges("store_per_symbol_result", node_route_next_symbol, {
        "prepare_one_symbol": "prepare_one_symbol",
        "aggregate_results": "aggregate_results",
    })

    # ── 汇聚 → 报告 → 缓存写入 ──
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", "update_cache")
    graph.add_edge("update_cache", END)


# ==================== 公开构建函数 ====================

def build_debate_graph(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)
    _register_per_symbol_loop(graph, mode)

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
    mode = PROFILE_MODES.get(profile, "default")
    return build_debate_graph(mode=mode)


def build_debate_graph_no_checkpoint(mode: str = "default") -> StateGraph:
    graph = StateGraph(DebateState)

    direct_debate = os.environ.get("FDT_DIRECT_DEBATE", "").lower() == "true"

    if direct_debate:
        _register_direct_debate_loop(graph, mode)
    else:
        _register_per_symbol_loop(graph, mode)

    graph = graph.compile()
    return graph
