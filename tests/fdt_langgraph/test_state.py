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
    # v9.0.0 六阶段辩论新增字段
    assert state["bearish_rebuttal_arguments"] == []
    assert state["bullish_rebuttal_arguments"] == []
    assert state["bear_final_arguments"] == []
    assert state["bull_final_arguments"] == []
    assert state["data_sources"] == []
    assert state["debate_round"] == 0
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
        bullish_arguments=[{"round": 1, "role": "bullish", "phase": "v1", "symbols": {}}],
        bearish_arguments=[{"round": 2, "role": "bearish", "phase": "v1", "symbols": {}}],
        # v9.0.0 六阶段辩论新增字段
        bearish_rebuttal_arguments=[{"round": 3, "role": "bearish", "phase": "rebuttal", "symbols": {}}],
        bullish_rebuttal_arguments=[{"round": 4, "role": "bullish", "phase": "rebuttal", "symbols": {}}],
        bear_final_arguments=[{"round": 5, "role": "bearish", "phase": "final", "symbols": {}}],
        bull_final_arguments=[{"round": 6, "role": "bullish", "phase": "final", "symbols": {}}],
        data_sources=[{"source": "TDX", "type": "kline"}],
        debate_round=6,
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
    # v9.0.0 六阶段辩论字段
    assert len(state["bearish_rebuttal_arguments"]) == 1
    assert state["bearish_rebuttal_arguments"][0]["round"] == 3
    assert len(state["bullish_rebuttal_arguments"]) == 1
    assert state["bullish_rebuttal_arguments"][0]["round"] == 4
    assert len(state["bear_final_arguments"]) == 1
    assert state["bear_final_arguments"][0]["round"] == 5
    assert len(state["bull_final_arguments"]) == 1
    assert state["bull_final_arguments"][0]["round"] == 6
    assert len(state["data_sources"]) == 1
    assert state["data_sources"][0]["source"] == "TDX"
    assert state["debate_round"] == 6


def test_debate_round_increments():
    """验证 debate_round 随辩论阶段递增"""
    state = create_initial_state("test-rounds", mode="default")
    assert state["debate_round"] == 0
    # 模拟三轮交叉质询
    state["debate_round"] = 1
    assert state["debate_round"] == 1
    state["debate_round"] = 2
    assert state["debate_round"] == 2
    state["debate_round"] = 3
    assert state["debate_round"] == 3


def test_annotated_debate_arguments_accept_lists():
    """验证 bullish/bearish_arguments 可接受 list 赋值（reducer 在 graph 运行时生效）"""
    state = create_initial_state("test-reducer", mode="default")
    assert state["bullish_arguments"] == []
    assert state["bearish_arguments"] == []

    # 验证字段可接受 dict 列表（符合 reducer 追加的预期输入格式）
    round1 = {"round": 1, "role": "bullish", "phase": "v1", "symbols": {}}
    state["bullish_arguments"] = [round1]
    assert len(state["bullish_arguments"]) == 1
    assert state["bullish_arguments"][0]["round"] == 1


def test_debate_state_debate_round_is_int():
    """验证 debate_round 字段类型为 int"""
    state = create_initial_state("test-hints", mode="default")
    assert isinstance(state["debate_round"], int)
    assert isinstance(state.get("bullish_arguments"), list)
    assert isinstance(state.get("bearish_arguments"), list)