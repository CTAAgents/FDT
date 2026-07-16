"""LangGraph 健康检查与监控模块。

提供 LangGraph 辩论流水线的健康检查能力，包括：
- 节点健康状态检查
- 阶段超时检测
- 异常状态检测
- 健康状态聚合输出
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .state import DebateState


class HealthChecker:
    """LangGraph 健康检查器"""

    def __init__(self):
        self._node_start_times: dict[str, float] = {}
        self._node_durations: dict[str, float] = {}
        self._errors: list[dict] = []

    def start_node(self, node_name: str):
        """记录节点开始时间"""
        self._node_start_times[node_name] = time.time()

    def end_node(self, node_name: str):
        """记录节点结束时间，计算耗时"""
        if node_name in self._node_start_times:
            duration = time.time() - self._node_start_times[node_name]
            self._node_durations[node_name] = duration
            del self._node_start_times[node_name]

    def record_error(self, node_name: str, error: Exception):
        """记录节点错误"""
        self._errors.append({
            "node": node_name,
            "error": str(error),
            "timestamp": datetime.now().isoformat(),
        })

    def check_state_health(self, state: DebateState) -> dict:
        """检查当前状态的健康度"""
        issues = []
        trace_id = state.get("trace_id", "unknown")

        if not state.get("trace_id"):
            issues.append({"level": "critical", "rule": "missing_trace_id",
                           "msg": "状态缺少 trace_id"})

        if not state.get("current_phase"):
            issues.append({"level": "warn", "rule": "missing_phase",
                           "msg": "状态缺少 current_phase"})

        if state.get("phase_start_time"):
            phase_duration = time.time() - state["phase_start_time"]
            if phase_duration > 300:
                issues.append({"level": "warn", "rule": "phase_timeout",
                               "msg": f"阶段 {state['current_phase']} 执行超时 ({phase_duration:.0f}s)"})

        return {
            "trace_id": trace_id,
            "current_phase": state.get("current_phase"),
            "completed_phases": list(state.get("completed_phases", [])),
            "n_issues": len(issues),
            "issues": issues,
            "node_durations": dict(self._node_durations),
            "n_errors": len(self._errors),
            "errors": self._errors,
            "status": "healthy" if len(issues) == 0 and len(self._errors) == 0 else "degraded",
            "check_time": datetime.now().isoformat(),
        }

    def check_graph_health(self, graph_config: dict | None = None) -> dict:
        """检查图配置的健康度"""
        issues = []

        if graph_config is None:
            issues.append({"level": "warn", "rule": "no_graph_config",
                           "msg": "未提供图配置"})
            return {
                "status": "degraded",
                "n_issues": len(issues),
                "issues": issues,
                "check_time": datetime.now().isoformat(),
            }

        if not graph_config.get("nodes"):
            issues.append({"level": "critical", "rule": "no_nodes",
                           "msg": "图中未定义任何节点"})

        if not graph_config.get("entry_point"):
            issues.append({"level": "critical", "rule": "no_entry",
                           "msg": "图未定义入口点"})

        nodes = graph_config.get("nodes", {})
        slow_nodes = {k: v for k, v in self._node_durations.items() if v > 60}
        if slow_nodes:
            issues.append({"level": "warn", "rule": "slow_nodes",
                           "msg": f"慢节点: {list(slow_nodes.keys())}"})

        return {
            "status": "healthy" if len(issues) == 0 else "degraded",
            "n_nodes": len(nodes),
            "n_issues": len(issues),
            "issues": issues,
            "node_durations": dict(self._node_durations),
            "slow_nodes": list(slow_nodes.keys()) if slow_nodes else [],
            "check_time": datetime.now().isoformat(),
        }

    def get_summary(self) -> dict:
        """获取健康检查摘要"""
        total_duration = sum(self._node_durations.values())
        return {
            "total_nodes_tracked": len(self._node_durations) + len(self._node_start_times),
            "completed_nodes": len(self._node_durations),
            "in_progress_nodes": list(self._node_start_times.keys()),
            "total_duration_sec": round(total_duration, 2),
            "n_errors": len(self._errors),
            "errors": self._errors,
            "status": "healthy" if len(self._errors) == 0 else "degraded",
        }


_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """获取全局健康检查器单例"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


def run_health_check(state: DebateState | None = None,
                     graph_config: dict | None = None) -> dict:
    """运行健康检查（便捷函数）"""
    checker = get_health_checker()
    result: dict[str, Any] = {"check_time": datetime.now().isoformat()}

    if state is not None:
        result["state_health"] = checker.check_state_health(state)

    if graph_config is not None:
        result["graph_health"] = checker.check_graph_health(graph_config)

    result["summary"] = checker.get_summary()
    result["overall_status"] = "healthy" if all(
        v.get("status") == "healthy"
        for k, v in result.items()
        if isinstance(v, dict) and "status" in v
    ) else "degraded"

    return result
