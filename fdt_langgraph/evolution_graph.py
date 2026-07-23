"""
evolution_graph.py — 自进化闭环 LangGraph 图 (APM-CS 五轴驱动)

以 APM-CS 评分卡 (D1-D5) 为核心评估标准构建外循环 (Outer Loop)，
辩论结束后自动触发。独立于 inner loop 辩论图，可独立运行或作为后处理步骤。

使用方式:
    from fdt_langgraph.evolution_graph import run_evolution

    # 辩论后自动触发
    state = run_evolution(source_trace_id="debate_trace_xxx")

    # 独立运行
    state = run_evolution()

流程图:
    collect_metrics → apm_eval → decide_actions
        → [条件] improve (APM 任一轴 degenerate)
        → [条件] calibrate (验证样本 ≥5)
        → [条件] evolve (总样本 ≥5)
        → [条件] ml_train (总样本 ≥50)
        → complete
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from langgraph.graph import StateGraph, END

from fdt_langgraph.evolution_state import EvolutionState
from fdt_langgraph.evolution_nodes import (
    node_collect_metrics, node_apm_eval, node_decide_actions,
    node_improve, node_calibrate, node_evolve, node_ml_train, node_complete,
    route_after_decide, route_after_improve, route_after_calibrate, route_after_evolve,
)

logger = logging.getLogger(__name__)


def _build_evolution_graph() -> StateGraph:
    """构建自进化 LangGraph。"""
    graph = StateGraph(EvolutionState)

    # ── 注册节点 ──
    graph.add_node("collect_metrics", node_collect_metrics)
    graph.add_node("apm_eval", node_apm_eval)
    graph.add_node("decide_actions", node_decide_actions)
    graph.add_node("improve", node_improve)
    graph.add_node("calibrate", node_calibrate)
    graph.add_node("evolve", node_evolve)
    graph.add_node("ml_train", node_ml_train)
    graph.add_node("complete", node_complete)

    # ── 入口 ──
    graph.set_entry_point("collect_metrics")

    # ── 必经链路 ──
    graph.add_edge("collect_metrics", "apm_eval")
    graph.add_edge("apm_eval", "decide_actions")

    # ── 条件路由 (基于 APM 评分 + 样本量) ──
    graph.add_conditional_edges(
        "decide_actions", route_after_decide, {
            "improve": "improve",
            "calibrate": "calibrate",
            "evolve": "evolve",
            "ml_train": "ml_train",
            "complete": "complete",
        }
    )

    # ── improve 后可流转到 calibrate/evolve/ml/complete ──
    graph.add_conditional_edges(
        "improve", route_after_improve, {
            "calibrate": "calibrate",
            "evolve": "evolve",
            "ml_train": "ml_train",
            "complete": "complete",
        }
    )

    # ── calibrate 后可流转到 evolve/ml/complete ──
    graph.add_conditional_edges(
        "calibrate", route_after_calibrate, {
            "evolve": "evolve",
            "ml_train": "ml_train",
            "complete": "complete",
        }
    )

    # ── evolve 后可流转到 ml/complete ──
    graph.add_conditional_edges(
        "evolve", route_after_evolve, {
            "ml_train": "ml_train",
            "complete": "complete",
        }
    )

    # ── ml_train 后结束 ──
    graph.add_edge("ml_train", "complete")

    # ── complete → END ──
    graph.add_edge("complete", END)

    return graph.compile()


# 全局编译图实例 (惰性加载)
_EVOLUTION_GRAPH = None


def get_evolution_graph():
    """获取编译后的进化图（全局单例）。"""
    global _EVOLUTION_GRAPH
    if _EVOLUTION_GRAPH is None:
        _EVOLUTION_GRAPH = _build_evolution_graph()
    return _EVOLUTION_GRAPH


def run_evolution(trace_id: str = "", source_trace_id: str = "") -> EvolutionState:
    """运行自进化闭环并返回最终状态。

    Args:
        trace_id: 进化流程自身的 trace_id (自动生成 if empty)
        source_trace_id: 触发本次进化的辩论 trace_id

    Returns:
        最终 EvolutionState
    """
    if not trace_id:
        from scripts.core.trace_id import new_trace
        trace_id = new_trace("evolve")

    initial = EvolutionState.create(trace_id=trace_id, source_trace_id=source_trace_id)
    graph = get_evolution_graph()
    result = graph.invoke(initial)
    logger.info(f"[EvolutionGraph] 自进化闭环完成: trace_id={trace_id}, "
                f"phase={result.get('phase')}, errors={len(result.get('errors', []))}")
    return result


def route_after_debate(debate_state: dict) -> EvolutionState | None:
    """辩论图 END 后的钩子：如果 FDT_RUN_EVOLUTION=true，触发进化闭环。

    用法: 在 debate 图的 signal_output 或 END 节点后调用。
    """
    import os
    if os.environ.get("FDT_RUN_EVOLUTION", "").lower() != "true":
        logger.info("[EvolutionGraph] FDT_RUN_EVOLUTION 未启用，跳过自进化")
        return None

    trace_id = debate_state.get("trace_id", "")
    logger.info(f"[EvolutionGraph] 辩论完成，触发自进化: source_trace_id={trace_id}")
    return run_evolution(source_trace_id=trace_id)
