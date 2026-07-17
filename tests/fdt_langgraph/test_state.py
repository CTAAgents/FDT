import pytest
from fdt_langgraph.state import DebateState, create_initial_state
from datetime import datetime


def test_debate_state_defaults():
    state = create_initial_state("test-trace-001", mode="default")
    assert state["trace_id"] == "test-trace-001"
    assert state["mode"] == "default"
    assert state["scan_results"] == {}
    assert state["scan_summary"] is None
    assert state["judge_direction"] is None
    assert state["selected_symbols"] == []
    assert state["dispatch_sources"] == []
    assert state["chain_analysis"] is None
    assert state["technical_data"] == {}
    assert state["fundamental_data"] == {}
    assert state["research_data"] is None
    assert state["bullish_arguments"] == []
    assert state["bearish_arguments"] == []
    assert state["verdict"] is None
    assert state["risk_check"] is None
    assert state["report_path"] is None
    # v8.8.0 阶段报告字段
    assert state["scan_report_path"] is None
    assert state["research_report_path"] is None
    assert state["verdict_report_path"] is None
    assert state["signal_report_path"] is None
    assert state["current_phase"] == "P0"
    assert state["error"] is None
    assert state["completed_phases"] == []


def test_debate_state_with_values():
    now = datetime.now()
    state = DebateState(
        trace_id="test-trace-002",
        timestamp=now,
        mode="deep_research",
        scan_results={"RB": {"score": 50}},
        scan_summary="Test summary",
        judge_direction="bullish",
        selected_symbols=["RB", "CU"],
        dispatch_sources=["chain", "technical"],
        chain_analysis={"industry": "steel"},
        technical_data={"RB": {"adx": 60}},
        fundamental_data={"RB": {"inventory": 100}},
        research_data={"sources": ["chain", "technical"]},
        bullish_arguments=[{"confidence": 0.8}],
        bearish_arguments=[{"confidence": 0.3}],
        verdict={"direction": "bullish"},
        risk_check={"risk_level": "low"},
        report_path="/tmp/report.html",
        scan_report_path="/tmp/scan.html",
        research_report_path="/tmp/research.html",
        verdict_report_path="/tmp/verdict.html",
        signal_report_path=None,
        current_phase="P5",
        error=None,
        completed_phases=["P1", "P2", "P3", "P4"],
    )
    assert state["trace_id"] == "test-trace-002"
    assert state["mode"] == "deep_research"
    assert state["scan_results"] == {"RB": {"score": 50}}
    assert state["dispatch_sources"] == ["chain", "technical"]
    assert state["current_phase"] == "P5"
    assert state["completed_phases"] == ["P1", "P2", "P3", "P4"]
    # v8.8.0 阶段报告字段
    assert state["scan_report_path"] == "/tmp/scan.html"
    assert state["research_report_path"] == "/tmp/research.html"