"""
master_graph.py — Master Orchestrator LangGraph

FDT 的统一编排层，替代外部 APScheduler 和 TRAE Schedule。
所有自动化任务在 LangGraph 框架内调度执行，零第三方依赖。

覆盖任务（共 14 个）:
  - 时间触发: daily_debate, update_dominant_mapping, auto_publish,
              apm_scorecard, cluster_failures, discipline_enforce,
              self_optimize_evolve, self_optimize_verify
  - 数据触发: validate_and_evolve, ml_training_check,
              self_optimize_analysis, vibench_baseline
  - 辩论轮次触发: d3_auto_light
  - 遗留兼容: data_collection（与 update_dominant_mapping 共存）

使用方式:
    # 单次检查并运行到期任务
    python -c "from fdt_langgraph.master_graph import run_master_once; run_master_once()"

    # 守护进程模式 (每60秒检查一次)
    python -c "from fdt_langgraph.master_graph import run_master_daemon; run_master_daemon()"
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from langgraph.graph import StateGraph, END

from fdt_langgraph.master_state import create_master_state
from fdt_langgraph.master_nodes import (
    node_check_time,
    node_dispatch,
    route_after_dispatch,
    route_after_task,
    node_run_daily_debate,
    node_run_update_dominant_mapping,
    node_run_auto_publish,
    node_run_apm_scorecard,
    node_run_cluster_failures,
    node_run_discipline_enforce,
    node_run_self_optimize_evolve,
    node_run_self_optimize_verify,
    node_run_validate_and_evolve,
    node_run_ml_training_check,
    node_run_self_optimize_analysis,
    node_run_vibench_baseline,
    node_run_d3_auto_light,
    node_run_data_collection,
)

logger = logging.getLogger(__name__)

# 任务节点注册表: (节点名, 节点函数)
_TASK_NODES: list[tuple[str, Any]] = [
    ("run_debate", node_run_daily_debate),
    ("run_update_dominant_mapping", node_run_update_dominant_mapping),
    ("run_publish", node_run_auto_publish),
    ("run_apm", node_run_apm_scorecard),
    ("run_cluster_failures", node_run_cluster_failures),
    ("run_discipline_enforce", node_run_discipline_enforce),
    ("run_self_optimize_evolve", node_run_self_optimize_evolve),
    ("run_self_optimize_verify", node_run_self_optimize_verify),
    ("run_validate_and_evolve", node_run_validate_and_evolve),
    ("run_ml_training_check", node_run_ml_training_check),
    ("run_self_optimize_analysis", node_run_self_optimize_analysis),
    ("run_vibench_baseline", node_run_vibench_baseline),
    ("run_d3_auto_light", node_run_d3_auto_light),
    ("run_data_collection", node_run_data_collection),
]

_ALL_TASK_NODE_NAMES = [name for name, _ in _TASK_NODES]


def _build_master_graph() -> StateGraph:
    graph = StateGraph(dict)

    graph.add_node("check_time", node_check_time)
    graph.add_node("dispatch", node_dispatch)
    graph.add_node("done", lambda s: s)

    for node_name, node_fn in _TASK_NODES:
        graph.add_node(node_name, node_fn)

    graph.set_entry_point("check_time")
    graph.add_edge("check_time", "dispatch")

    dispatch_targets = {name: name for name in _ALL_TASK_NODE_NAMES}
    dispatch_targets["done"] = "done"
    graph.add_conditional_edges("dispatch", route_after_dispatch, dispatch_targets)

    for node_name in _ALL_TASK_NODE_NAMES:
        graph.add_conditional_edges(node_name, route_after_task, {
            "dispatch": "dispatch",
            "done": "done",
        })

    graph.add_edge("done", END)
    return graph.compile()


_MASTER_GRAPH = None


def get_master_graph():
    global _MASTER_GRAPH
    if _MASTER_GRAPH is None:
        _MASTER_GRAPH = _build_master_graph()
    return _MASTER_GRAPH


def run_master_once(loop_id: str = "") -> dict:
    if not loop_id:
        loop_id = f"master-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    initial = create_master_state(loop_id=loop_id)
    graph = get_master_graph()
    result = graph.invoke(initial)
    n_tasks = len(result.get("task_results", {}))
    n_errors = len(result.get("errors", []))
    logger.info(f"[MasterGraph] 完成: loop_id={loop_id}, "
                f"tasks={n_tasks}, errors={n_errors}")
    return result


def run_master_daemon(interval_seconds: int = 60):
    logger.info(f"[MasterGraph] 守护进程启动, 检查间隔={interval_seconds}s")
    loop_count = 0
    while True:
        loop_count += 1
        loop_id = f"master-loop-{loop_count}-{datetime.now().strftime('%H%M%S')}"
        logger.info(f"[MasterGraph] Loop #{loop_count} 开始")
        try:
            result = run_master_once(loop_id=loop_id)
            tasks = result.get("task_results", {})
            if tasks:
                for name, r in tasks.items():
                    icon = "✅" if r.get("success") else "❌"
                    logger.info(f"[MasterGraph]  {icon} {name}: {r.get('summary', '')[:80]}")
        except Exception as e:
            logger.error(f"[MasterGraph] Loop #{loop_count} 异常: {e}")
        logger.info(f"[MasterGraph] 休眠 {interval_seconds}s...")
        time.sleep(interval_seconds)
