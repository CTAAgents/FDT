"""健康检查模块单元测试。

覆盖目标：
- HealthChecker.check_state_health() 各分支
- HealthChecker.check_graph_health() 各分支
- HealthChecker.get_summary() 聚合结果
- 边界条件（空状态、None值、超时等）
- run_health_check() 便捷函数
"""
import pytest
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fdt_langgraph.state import create_initial_state, DebateState
from fdt_langgraph.health import HealthChecker, get_health_checker, run_health_check


# =============================================================================
# 基础功能测试
# =============================================================================

class TestHealthChecker:
    """健康检查器基础功能"""

    def test_init(self):
        """初始化时所有内部状态为空"""
        checker = HealthChecker()
        assert checker._errors == []
        assert checker._node_durations == {}
        assert checker._node_start_times == {}

    def test_start_end_node(self):
        """start_node / end_node 记录耗时"""
        checker = HealthChecker()
        checker.start_node("scan")
        assert "scan" in checker._node_start_times

        time.sleep(0.01)
        checker.end_node("scan")
        assert "scan" in checker._node_durations
        assert "scan" not in checker._node_start_times
        assert checker._node_durations["scan"] > 0

    def test_end_nonexistent_node_no_error(self):
        """end_node 不存在的节点不应抛异常"""
        checker = HealthChecker()
        checker.end_node("nonexistent")
        assert "nonexistent" not in checker._node_durations

    def test_record_error(self):
        """record_error 正确记录错误信息"""
        checker = HealthChecker()
        try:
            raise ValueError("test error")
        except ValueError as e:
            checker.record_error("scan_node", e)

        assert len(checker._errors) == 1
        assert checker._errors[0]["node"] == "scan_node"
        assert "test error" in checker._errors[0]["error"]
        assert "timestamp" in checker._errors[0]

    def test_record_multiple_errors(self):
        """多次记录错误全部保留"""
        checker = HealthChecker()
        checker.record_error("node_a", ValueError("err1"))
        checker.record_error("node_b", RuntimeError("err2"))
        assert len(checker._errors) == 2


# =============================================================================
# check_state_health 测试
# =============================================================================

class TestCheckStateHealth:
    """状态健康检查 — 覆盖所有分支"""

    def test_healthy_state(self):
        """完整、有效的 DebateState → status=healthy"""
        checker = HealthChecker()
        state = create_initial_state("health-001", mode="default")
        state["selected_symbols"] = ["RB"]

        result = checker.check_state_health(state)
        assert result["status"] == "healthy"
        assert result["n_issues"] == 0
        assert result["trace_id"] == "health-001"
        assert result["current_phase"] == "P0"

    def test_missing_trace_id(self):
        """trace_id 为空 → critical 告警"""
        checker = HealthChecker()
        state = create_initial_state("", mode="default")
        state["trace_id"] = ""

        result = checker.check_state_health(state)
        assert result["status"] == "degraded"
        assert result["n_issues"] >= 1
        assert any(i["rule"] == "missing_trace_id" for i in result["issues"])

    def test_missing_phase(self):
        """current_phase 为空 → warn 告警"""
        checker = HealthChecker()
        state = create_initial_state("health-phase-001", mode="default")
        state["current_phase"] = ""

        result = checker.check_state_health(state)
        assert result["status"] == "degraded"
        issues = [i for i in result["issues"] if i["rule"] == "missing_phase"]
        assert len(issues) == 1

    def test_phase_timeout(self):
        """phase_start_time 超过 300 秒 → phase_timeout 告警"""
        checker = HealthChecker()
        state = create_initial_state("health-timeout-001", mode="default")
        state["phase_start_time"] = time.time() - 600  # 10 分钟前
        state["current_phase"] = "P3"

        result = checker.check_state_health(state)
        issues = [i for i in result["issues"] if i["rule"] == "phase_timeout"]
        assert len(issues) == 1
        assert "P3" in issues[0]["msg"]
        assert "600" in issues[0]["msg"] or "60" in issues[0]["msg"]

    def test_phase_no_timeout_when_recent(self):
        """phase_start_time 小于 300 秒 → 无超时告警"""
        checker = HealthChecker()
        state = create_initial_state("health-ok-001", mode="default")
        state["phase_start_time"] = time.time() - 30  # 30 秒前

        result = checker.check_state_health(state)
        assert not any(i["rule"] == "phase_timeout" for i in result["issues"])

    def test_phase_no_timeout_when_none(self):
        """phase_start_time 为 None → 无超时告警"""
        checker = HealthChecker()
        state = create_initial_state("health-ok-002", mode="default")
        state["phase_start_time"] = None

        result = checker.check_state_health(state)
        assert not any(i["rule"] == "phase_timeout" for i in result["issues"])

    def test_completed_phases_returned(self):
        """completed_phases 正确返回"""
        checker = HealthChecker()
        state = create_initial_state("health-cp-001", mode="default")
        state["completed_phases"].append("P1")
        state["completed_phases"].append("P2")

        result = checker.check_state_health(state)
        assert result["completed_phases"] == ["P1", "P2"]

    def test_degraded_when_errors_recorded(self):
        """checker 中有错误记录 → status=degraded"""
        checker = HealthChecker()
        checker.record_error("scan", ValueError("scan failed"))
        state = create_initial_state("health-err-001", mode="default")

        result = checker.check_state_health(state)
        assert result["status"] == "degraded"
        assert result["n_errors"] == 1

    def test_node_durations_in_result(self):
        """节点耗时信息包含在结果中"""
        checker = HealthChecker()
        checker.start_node("scan")
        checker.end_node("scan")
        state = create_initial_state("health-nd-001", mode="default")

        result = checker.check_state_health(state)
        assert "scan" in result["node_durations"]


# =============================================================================
# check_graph_health 测试
# =============================================================================

class TestCheckGraphHealth:
    """图健康检查 — 覆盖所有分支"""

    def test_healthy_graph(self):
        """完整配置 → healthy"""
        checker = HealthChecker()
        graph_config = {
            "nodes": {"scan": {}, "verdict": {}, "report": {}},
            "entry_point": "scan",
        }
        result = checker.check_graph_health(graph_config)
        assert result["status"] == "healthy"
        assert result["n_nodes"] == 3
        assert result["n_issues"] == 0

    def test_no_nodes(self):
        """nodes 为空 → critical 告警"""
        checker = HealthChecker()
        graph_config = {"nodes": {}, "entry_point": "scan"}
        result = checker.check_graph_health(graph_config)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_nodes" for i in result["issues"])

    def test_no_entry_point(self):
        """缺少 entry_point → critical 告警"""
        checker = HealthChecker()
        graph_config = {"nodes": {"scan": {}}}
        result = checker.check_graph_health(graph_config)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_entry" for i in result["issues"])

    def test_none_config(self):
        """config 为 None → warn 告警"""
        checker = HealthChecker()
        result = checker.check_graph_health(None)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_graph_config" for i in result["issues"])

    def test_empty_dict_config(self):
        """空字典配置 → 同时触发 no_nodes + no_entry"""
        checker = HealthChecker()
        result = checker.check_graph_health({})
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_nodes" for i in result["issues"])
        assert any(i["rule"] == "no_entry" for i in result["issues"])

    def test_partial_config_missing_nodes_key(self):
        """config 有 entry_point 但无 nodes 键 → no_nodes"""
        checker = HealthChecker()
        result = checker.check_graph_health({"entry_point": "scan"})
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_nodes" for i in result["issues"])
        assert not any(i["rule"] == "no_entry" for i in result["issues"])

    def test_slow_nodes_detected(self):
        """节点耗时 > 60s → slow_nodes 告警"""
        checker = HealthChecker()
        checker._node_durations["scan"] = 0.1
        checker._node_durations["debate"] = 120.0

        graph_config = {"nodes": {"scan": {}, "debate": {}}, "entry_point": "scan"}
        result = checker.check_graph_health(graph_config)
        assert "debate" in result["slow_nodes"]
        assert "scan" not in result["slow_nodes"]
        assert any(i["rule"] == "slow_nodes" for i in result["issues"])

    def test_no_slow_nodes_with_short_durations(self):
        """所有节点耗时 ≤ 60s → 无 slow_nodes 告警"""
        checker = HealthChecker()
        checker._node_durations["scan"] = 0.1
        checker._node_durations["debate"] = 59.9

        graph_config = {"nodes": {"scan": {}, "debate": {}}, "entry_point": "scan"}
        result = checker.check_graph_health(graph_config)
        assert result["slow_nodes"] == []
        assert not any(i["rule"] == "slow_nodes" for i in result["issues"])

    def test_multiple_issues_aggregated(self):
        """多个问题同时聚合"""
        checker = HealthChecker()
        result = checker.check_graph_health({"nodes": {}})
        assert result["n_issues"] == 2  # no_nodes + no_entry


# =============================================================================
# get_summary 测试
# =============================================================================

class TestGetSummary:
    """健康摘要测试"""

    def test_empty_checker(self):
        """空检查器 → 0 节点, healthy"""
        checker = HealthChecker()
        summary = checker.get_summary()
        assert summary["total_nodes_tracked"] == 0
        assert summary["completed_nodes"] == 0
        assert summary["in_progress_nodes"] == []
        assert summary["total_duration_sec"] == 0.0
        assert summary["n_errors"] == 0
        assert summary["status"] == "healthy"

    def test_no_errors(self):
        """无错误 → healthy"""
        checker = HealthChecker()
        checker.start_node("scan")
        checker.end_node("scan")

        summary = checker.get_summary()
        assert summary["status"] == "healthy"
        assert summary["completed_nodes"] == 1
        assert summary["n_errors"] == 0
        assert summary["total_duration_sec"] >= 0

    def test_with_errors(self):
        """有错误 → degraded"""
        checker = HealthChecker()
        checker.record_error("scan", ValueError("oops"))

        summary = checker.get_summary()
        assert summary["status"] == "degraded"
        assert summary["n_errors"] == 1

    def test_with_in_progress_nodes(self):
        """有进行中的节点"""
        checker = HealthChecker()
        checker.start_node("scan")
        checker.start_node("report")
        checker.end_node("scan")
        # report 尚未 end

        summary = checker.get_summary()
        assert summary["completed_nodes"] == 1
        assert "report" in summary["in_progress_nodes"]
        assert summary["total_nodes_tracked"] == 2

    def test_total_duration_accumulated(self):
        """多个节点耗时累加"""
        checker = HealthChecker()
        checker.start_node("a")
        checker.end_node("a")
        t1 = checker._node_durations["a"]
        checker.start_node("b")
        checker.end_node("b")
        t2 = checker._node_durations["b"]

        summary = checker.get_summary()
        assert summary["total_duration_sec"] == pytest.approx(t1 + t2, rel=0.1)

    def test_multiple_errors_listed(self):
        """多个错误全部列出"""
        checker = HealthChecker()
        checker.record_error("a", ValueError("e1"))
        checker.record_error("b", RuntimeError("e2"))

        summary = checker.get_summary()
        assert summary["n_errors"] == 2
        assert len(summary["errors"]) == 2


# =============================================================================
# 边界条件测试
# =============================================================================

class TestEdgeCases:
    """边界条件 — 空状态 / None 值 / 极端输入"""

    def test_empty_dict_state(self):
        """传入空字典 → trace_id=unknown, 多告警"""
        checker = HealthChecker()
        result = checker.check_state_health({})  # type: ignore[arg-type]
        assert result["trace_id"] == "unknown"
        assert result["n_issues"] >= 2  # missing_trace_id + missing_phase
        assert result["status"] == "degraded"

    def test_state_with_none_values(self):
        """state 中包含 None 值 → 不抛异常"""
        checker = HealthChecker()
        state: DebateState = {
            "trace_id": "edge-none-001",
            "timestamp": datetime.now(),
            "mode": "default",
            "scan_results": {},
            "selected_symbols": [],
            "dispatch_sources": [],
            "fdc_data": {},
            "technical_data": {},
            "fundamental_data": {},
            "bullish_arguments": [],
            "bearish_arguments": [],
            "debate_round": 0,
            "completed_phases": [],
            "current_phase": "P0",
            "phase_start_time": None,
            "error": None,
        }
        result = checker.check_state_health(state)
        # None 字段应当被 safe get 处理，不应抛异常
        assert result["status"] == "healthy"
        assert result["trace_id"] == "edge-none-001"

    def test_state_with_error_field(self):
        """state.error 有内容（当前代码不直接检查此项，但确保不干扰）"""
        checker = HealthChecker()
        state = create_initial_state("edge-err-001", mode="default")
        state["error"] = "something went wrong"
        result = checker.check_state_health(state)
        # 当前版本 check_state_health 不直接消费 state["error"]，但不应抛异常
        assert "trace_id" in result
        assert result["trace_id"] == "edge-err-001"

    def test_start_node_after_end_no_crash(self):
        """重复 start/end 操作不崩溃"""
        checker = HealthChecker()
        checker.start_node("x")
        checker.end_node("x")
        # 再次 end 已完成的节点
        checker.end_node("x")
        # 再次 start 同名节点
        checker.start_node("x")
        assert "x" in checker._node_start_times

    def test_negative_duration_does_not_break(self):
        """理论上不可能但防止极端值"""
        checker = HealthChecker()
        checker._node_durations["stuck"] = -1.0
        summary = checker.get_summary()
        assert summary["total_duration_sec"] == pytest.approx(-1.0)


# =============================================================================
# run_health_check 便捷函数测试
# =============================================================================

class TestRunHealthCheck:
    """run_health_check 便捷函数"""

    def test_with_state_only(self):
        """仅带 state"""
        state = create_initial_state("run-001", mode="default")
        result = run_health_check(state=state)
        assert "state_health" in result
        assert "summary" in result
        assert "overall_status" in result
        assert "check_time" in result

    def test_with_graph_only(self):
        """仅带 graph_config"""
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(graph_config=graph_config)
        assert "graph_health" in result
        assert "summary" in result

    def test_with_both(self):
        """同时带 state 和 graph_config"""
        state = create_initial_state("run-002", mode="default")
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(state=state, graph_config=graph_config)
        assert "state_health" in result
        assert "graph_health" in result
        assert "summary" in result
        assert "overall_status" in result

    def test_with_neither(self):
        """state 和 graph_config 均为 None"""
        result = run_health_check(state=None, graph_config=None)
        assert "state_health" not in result
        assert "graph_health" not in result
        assert "summary" in result
        assert "overall_status" in result

    def test_overall_status_healthy(self):
        """所有子检查均 healthy → overall_status=healthy"""
        state = create_initial_state("run-003", mode="default")
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(state=state, graph_config=graph_config)
        assert result["overall_status"] == "healthy"

    def test_overall_status_degraded_when_one_fails(self):
        """任一子检查 degraded → overall_status=degraded"""
        state = create_initial_state("run-004", mode="default")
        state["trace_id"] = ""
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(state=state, graph_config=graph_config)
        assert result["overall_status"] == "degraded"

    def test_overall_status_degraded_when_state_none_and_graph_bad(self):
        """state=None, graph 有缺陷 → overall_status=degraded"""
        result = run_health_check(graph_config={})
        assert result["overall_status"] == "degraded"


# =============================================================================
# 单例模式测试
# =============================================================================

class TestSingleton:
    """get_health_checker 单例"""  # noqa: D400

    def test_singleton(self):
        """多次调用返回同一实例"""
        h1 = get_health_checker()
        h2 = get_health_checker()
        assert h1 is h2
