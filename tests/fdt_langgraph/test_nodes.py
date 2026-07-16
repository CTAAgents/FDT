import pytest
from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_judge_direction,
    node_chain, node_technical, node_fundamental,
    node_merge_research, node_debate,
    node_verdict, node_trading_plan, node_risk_check, node_report
)
from datetime import datetime


def create_test_state(mode="default") -> DebateState:
    return create_initial_state("test-trace", mode)


@pytest.mark.asyncio
async def test_node_scan():
    state = create_test_state()
    result = await node_scan(state)
    assert result["scan_results"] is not None
    assert result["current_phase"] == "P1"
    assert "P1" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_judge_direction():
    state = create_test_state()
    state["scan_results"] = {"RB": {"score": 50}}
    result = await node_judge_direction(state)
    assert result["judge_direction"] is not None
    assert result["selected_symbols"] is not None
    assert result["current_phase"] == "P2"
    assert "P2" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_chain():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_chain(state)
    assert result["chain_analysis"] is not None


@pytest.mark.asyncio
async def test_node_technical():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_technical(state)
    assert result["technical_data"] is not None


@pytest.mark.asyncio
async def test_node_fundamental():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_fundamental(state)
    assert result["fundamental_data"] is not None


@pytest.mark.asyncio
async def test_node_merge_research():
    state = create_test_state()
    state["chain_analysis"] = {"industry": "steel"}
    state["technical_data"] = {"RB": {"adx": 60}}
    state["fundamental_data"] = {"RB": {"inventory": 100}}
    state["completed_phases"] = ["P1", "P2"]
    result = await node_merge_research(state)
    assert result["research_data"] is not None
    assert "P3" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_debate():
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["completed_phases"] = ["P1", "P2", "P3"]
    result = await node_debate(state)
    assert result["bullish_arguments"] is not None
    assert result["bearish_arguments"] is not None
    assert result["current_phase"] == "P4"
    assert "P4" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_verdict():
    state = create_test_state()
    state["bullish_arguments"] = [{"confidence": 0.8}]
    state["bearish_arguments"] = [{"confidence": 0.3}]
    state["completed_phases"] = ["P1", "P2", "P3", "P4"]
    result = await node_verdict(state)
    assert result["verdict"] is not None
    assert result["current_phase"] == "P5_verdict"


@pytest.mark.asyncio
async def test_node_trading_plan():
    state = create_test_state()
    state["verdict"] = {"direction": "bullish"}
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict"]
    result = await node_trading_plan(state)
    assert result["trading_plan"] is not None


@pytest.mark.asyncio
async def test_node_risk_check():
    state = create_test_state()
    state["trading_plan"] = {"position": "long"}
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_plan"]
    result = await node_risk_check(state)
    assert result["risk_check"] is not None


@pytest.mark.asyncio
async def test_node_report():
    state = create_test_state()
    state["verdict"] = {"direction": "bullish"}
    state["trading_plan"] = {"position": "long"}
    state["risk_check"] = {"risk_level": "low"}
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_plan", "P5_risk"]
    result = await node_report(state)
    assert result["report_path"] is not None
    assert result["current_phase"] == "P6"
    assert "P6" in result["completed_phases"]