"""测试: Master Orchestrator Graph (LangGraph 统一编排层)"""

import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fdt_langgraph.master_state import create_master_state
from fdt_langgraph.master_nodes import (
    node_check_time, node_dispatch,
    route_after_dispatch, route_after_task,
)


class TestMasterState:
    def test_create_default(self):
        state = create_master_state(loop_id="test-001")
        assert state["loop_id"] == "test-001"
        assert state["phase"] == "idle"
        assert len(state["schedules"]) == 4
        assert "daily_debate" in state["schedules"]
        assert "data_collection" in state["schedules"]
        assert "apm_scorecard" in state["schedules"]
        assert "auto_publish" in state["schedules"]
        assert len(state["errors"]) == 0
        assert state["started_at"] != ""

    def test_schedule_config(self):
        state = create_master_state()
        debate = state["schedules"]["daily_debate"]
        assert debate["hour"] == 9
        assert debate["minute"] == 0
        assert 0 in debate["weekdays"]


class TestCheckTime:
    def test_no_tasks_when_no_match(self):
        state = create_master_state()
        for s in state["schedules"].values():
            s["hour"] = 99
        result = node_check_time(state)
        assert result["phase"] == "check_time"
        assert len(result.get("task_queue", [])) == 0

    def test_already_run_skipped(self):
        state = create_master_state()
        state["last_runs"] = {"daily_debate_9999-99-99": datetime.now().isoformat()}
        for s in state["schedules"].values():
            s["hour"] = 99
        result = node_check_time(state)
        assert len(result.get("task_queue", [])) == 0


class TestDispatch:
    def test_first_task(self):
        state = create_master_state()
        state["task_queue"] = ["daily_debate", "apm_scorecard"]
        state["task_index"] = 0
        result = node_dispatch(state)
        assert result["current_task"] == "daily_debate"
        assert result["phase"] == "task_running"

    def test_last_task(self):
        state = create_master_state()
        state["task_queue"] = ["daily_debate", "apm_scorecard"]
        state["task_index"] = 1
        result = node_dispatch(state)
        assert result["current_task"] == "apm_scorecard"

    def test_done_when_empty(self):
        state = create_master_state()
        state["task_queue"] = []
        result = node_dispatch(state)
        assert result["phase"] == "done"

    def test_done_when_all_complete(self):
        state = create_master_state()
        state["task_queue"] = ["daily_debate"]
        state["task_index"] = 1
        result = node_dispatch(state)
        assert result["phase"] == "done"


class TestRouting:
    def test_dispatch_debate(self):
        state = create_master_state()
        state["current_task"] = "daily_debate"
        assert route_after_dispatch(state) == "run_debate"

    def test_dispatch_data(self):
        state = create_master_state()
        state["current_task"] = "data_collection"
        assert route_after_dispatch(state) == "run_data_collection"

    def test_dispatch_apm(self):
        state = create_master_state()
        state["current_task"] = "apm_scorecard"
        assert route_after_dispatch(state) == "run_apm"

    def test_dispatch_publish(self):
        state = create_master_state()
        state["current_task"] = "auto_publish"
        assert route_after_dispatch(state) == "run_publish"

    def test_dispatch_unknown(self):
        state = create_master_state()
        state["current_task"] = "unknown"
        assert route_after_dispatch(state) == "done"

    def test_after_task_more(self):
        state = create_master_state()
        state["task_queue"] = ["daily_debate", "apm_scorecard"]
        state["task_index"] = 1
        assert route_after_task(state) == "dispatch"

    def test_after_task_done(self):
        state = create_master_state()
        state["task_queue"] = ["daily_debate"]
        state["task_index"] = 1
        assert route_after_task(state) == "done"


class TestFullGraph:
    def test_run_with_no_matching_tasks(self):
        from fdt_langgraph.master_graph import get_master_graph
        graph = get_master_graph()
        state = create_master_state(loop_id="test-nomatch")
        for s in state["schedules"].values():
            s["hour"] = 99
        result = graph.invoke(state)
        assert result is not None
        assert len(result.get("task_results", {})) == 0
