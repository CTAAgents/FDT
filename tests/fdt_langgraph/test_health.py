import pytest
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fdt_langgraph.state import create_initial_state
from fdt_langgraph.health import HealthChecker, get_health_checker, run_health_check


class TestHealthChecker:
    """健康检查器单元测试"""

    def test_health_checker_init(self):
        """测试健康检查器初始化"""
        checker = HealthChecker()
        assert checker._errors == []
        assert checker._node_durations == {}
        assert checker._node_start_times == {}

    def test_start_end_node(self):
        """测试节点开始/结束计时"""
        checker = HealthChecker()
        checker.start_node("scan")
        assert "scan" in checker._node_start_times

        time.sleep(0.01)
        checker.end_node("scan")
        assert "scan" in checker._node_durations
        assert "scan" not in checker._node_start_times
        assert checker._node_durations["scan"] > 0

    def test_end_nonexistent_node_no_error(self):
        """结束不存在的节点不应报错"""
        checker = HealthChecker()
        checker.end_node("nonexistent")
        assert "nonexistent" not in checker._node_durations

    def test_record_error(self):
        """测试错误记录"""
        checker = HealthChecker()
        try:
            raise ValueError("test error")
        except ValueError as e:
            checker.record_error("scan_node", e)

        assert len(checker._errors) == 1
        assert checker._errors[0]["node"] == "scan_node"
        assert "test error" in checker._errors[0]["error"]
        assert "timestamp" in checker._errors[0]


class TestStateHealthCheck:
    """状态健康检查测试"""

    def test_healthy_state(self):
        """测试健康状态"""
        checker = HealthChecker()
        state = create_initial_state("health-test-001", mode="default")
        state["selected_symbols"] = ["RB"]

        result = checker.check_state_health(state)
        assert result["status"] == "healthy"
        assert result["n_issues"] == 0
        assert result["trace_id"] == "health-test-001"
        assert result["current_phase"] == "P0"

    def test_missing_trace_id(self):
        """测试缺少 trace_id 的状态"""
        checker = HealthChecker()
        state = create_initial_state("", mode="default")
        state["trace_id"] = ""

        result = checker.check_state_health(state)
        assert result["status"] == "degraded"
        assert result["n_issues"] >= 1
        assert any(i["rule"] == "missing_trace_id" for i in result["issues"])

    def test_completed_phases_returned(self):
        """测试返回已完成阶段列表"""
        checker = HealthChecker()
        state = create_initial_state("health-test-002", mode="default")
        state["completed_phases"].append("P1")
        state["completed_phases"].append("P2")

        result = checker.check_state_health(state)
        assert "P1" in result["completed_phases"]
        assert "P2" in result["completed_phases"]


class TestGraphHealthCheck:
    """图健康检查测试"""

    def test_healthy_graph(self):
        """测试健康图配置"""
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
        """测试无节点的图"""
        checker = HealthChecker()
        graph_config = {"nodes": {}, "entry_point": "scan"}

        result = checker.check_graph_health(graph_config)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_nodes" for i in result["issues"])

    def test_no_entry_point(self):
        """测试无入口点的图"""
        checker = HealthChecker()
        graph_config = {"nodes": {"scan": {}}}

        result = checker.check_graph_health(graph_config)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_entry" for i in result["issues"])

    def test_none_config(self):
        """测试 None 配置"""
        checker = HealthChecker()
        result = checker.check_graph_health(None)
        assert result["status"] == "degraded"
        assert any(i["rule"] == "no_graph_config" for i in result["issues"])

    def test_slow_nodes_detected(self):
        """测试慢节点检测"""
        checker = HealthChecker()
        checker._node_durations["scan"] = 0.1
        checker._node_durations["debate"] = 120.0

        graph_config = {
            "nodes": {"scan": {}, "debate": {}},
            "entry_point": "scan",
        }

        result = checker.check_graph_health(graph_config)
        assert "debate" in result["slow_nodes"]
        assert "scan" not in result["slow_nodes"]


class TestHealthSummary:
    """健康摘要测试"""

    def test_summary_no_errors(self):
        """测试无错误摘要"""
        checker = HealthChecker()
        checker.start_node("scan")
        checker.end_node("scan")

        summary = checker.get_summary()
        assert summary["status"] == "healthy"
        assert summary["completed_nodes"] == 1
        assert summary["n_errors"] == 0
        assert summary["total_duration_sec"] >= 0

    def test_summary_with_errors(self):
        """测试有错误摘要"""
        checker = HealthChecker()
        checker.record_error("scan", ValueError("oops"))

        summary = checker.get_summary()
        assert summary["status"] == "degraded"
        assert summary["n_errors"] == 1


class TestHealthCheckConvenience:
    """便捷函数测试"""

    def test_run_health_check_with_state(self):
        """测试带状态的健康检查"""
        state = create_initial_state("convenience-test-001", mode="default")
        result = run_health_check(state=state)

        assert "state_health" in result
        assert "summary" in result
        assert "overall_status" in result
        assert "check_time" in result

    def test_run_health_check_with_graph(self):
        """测试带图配置的健康检查"""
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(graph_config=graph_config)

        assert "graph_health" in result
        assert "summary" in result

    def test_run_health_check_both(self):
        """测试同时检查状态和图"""
        state = create_initial_state("both-test-001", mode="default")
        graph_config = {"nodes": {"scan": {}}, "entry_point": "scan"}
        result = run_health_check(state=state, graph_config=graph_config)

        assert "state_health" in result
        assert "graph_health" in result
        assert "summary" in result
        assert "overall_status" in result

    def test_get_health_checker_singleton(self):
        """测试单例模式"""
        h1 = get_health_checker()
        h2 = get_health_checker()
        assert h1 is h2
