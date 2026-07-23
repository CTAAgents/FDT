import pytest
from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_judge_direction,
    node_chain, node_technical, node_fundamental,
    node_merge_research,
    node_bullish_v1, node_bearish_v1,
    node_bearish_rebuttal, node_bullish_rebuttal,
    node_bear_final, node_bull_final,
    node_verdict, node_signal_output, node_risk_check, node_report
)
from fdt_langgraph.graph import (
    route_after_merge_research,
)
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock


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
    assert "P2" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_bullish_v1():
    """P3 步1: 多头立论 v1"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["completed_phases"] = ["P1", "P2", "P2"]
    result = await node_bullish_v1(state)
    assert result["bullish_arguments"] is not None
    assert len(result["bullish_arguments"]) == 1
    assert result["bullish_arguments"][0]["phase"] == "v1"
    assert result["bullish_arguments"][0]["role"] == "bullish"
    assert result["debate_round"] == 1
    assert result["current_phase"] == "P3_bullish_v1"


@pytest.mark.asyncio
async def test_node_bearish_v1():
    """P3 步2: 空头立论 — 独立做空论据 v1（不再是对多头质疑）"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["debate_round"] = 1
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1"]
    result = await node_bearish_v1(state)
    assert result["bearish_arguments"] is not None
    assert len(result["bearish_arguments"]) == 1
    assert result["bearish_arguments"][0]["phase"] == "v1"
    assert result["bearish_arguments"][0]["role"] == "bearish"
    assert result["debate_round"] == 2
    assert result["current_phase"] == "P3_bearish_v1"


@pytest.mark.asyncio
async def test_node_bullish_rebuttal():
    """P3 步4: 多头反驳 — 针对空头立论和空头反驳进行再反驳"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    # 注入完整历史：多头v1 + 空头v1（独立做空论据）
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["bearish_arguments"] = [
        {"round": 2, "role": "bearish", "phase": "v1", "symbols": {"RB": {"arguments": ["做空论据1"], "confidence": 0.6}}}
    ]
    state["debate_round"] = 2
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1"]
    result = await node_bullish_rebuttal(state)
    # node_bullish_rebuttal 写入 bullish_rebuttal_arguments（非 bullish_arguments）
    assert result["bullish_rebuttal_arguments"] is not None
    assert len(result["bullish_rebuttal_arguments"]) == 1
    assert result["bullish_rebuttal_arguments"][0]["phase"] == "rebuttal"
    assert result["bullish_rebuttal_arguments"][0]["role"] == "bullish"
    assert result["bullish_rebuttal_arguments"][0]["round"] == 4
    assert result["debate_round"] == 3
    assert result["current_phase"] == "P3_bullish_rebuttal"


@pytest.mark.asyncio
async def test_node_bearish_rebuttal():
    """P3 步3: 空头反驳多头立论 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["debate_round"] = 1
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1"]
    # Mock FdtAgentExecutor to return a dict with JSON output
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["反驳看多论据1"], "confidence": 0.65}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bearish_rebuttal(state)
    assert result["bearish_rebuttal_arguments"] is not None
    assert len(result["bearish_rebuttal_arguments"]) == 1
    assert result["bearish_rebuttal_arguments"][0]["phase"] == "rebuttal_v1"
    assert result["bearish_rebuttal_arguments"][0]["role"] == "bearish"
    assert result["debate_round"] == 2
    assert result["current_phase"] == "P3_bearish_rebuttal"


@pytest.mark.asyncio
async def test_node_bear_final():
    """P3 步5: 空头最终陈述 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["selected_symbols"] = ["RB"]
    state["bearish_arguments"] = [
        {"round": 2, "role": "bearish", "phase": "v1", "symbols": {"RB": {"arguments": ["做空论据1"], "confidence": 0.6}}}
    ]
    state["bearish_rebuttal_arguments"] = [
        {"round": 3, "role": "bearish", "phase": "rebuttal", "symbols": {"RB": {"arguments": ["反驳看多"], "confidence": 0.65}}}
    ]
    state["debate_round"] = 3
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1", "P3_bearish_rebuttal", "P3_bullish_rebuttal"]
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["空头最终论据"], "confidence": 0.7, "risk_note": "做空风险"}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bear_final(state)
    assert result["bear_final_arguments"] is not None
    assert len(result["bear_final_arguments"]) == 1
    assert result["bear_final_arguments"][0]["phase"] == "final"
    assert result["bear_final_arguments"][0]["role"] == "bearish"
    assert result["current_phase"] == "P3_bear_final"


@pytest.mark.asyncio
async def test_node_bull_final():
    """P3 步6: 多头最终陈述 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["selected_symbols"] = ["RB"]
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["bullish_rebuttal_arguments"] = [
        {"round": 4, "role": "bullish", "phase": "rebuttal", "symbols": {"RB": {"arguments": ["反驳做空"], "confidence": 0.75}}}
    ]
    state["debate_round"] = 5
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1", "P3_bearish_rebuttal", "P3_bullish_rebuttal", "P3_bear_final"]
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["多头最终论据"], "confidence": 0.8, "risk_note": "做多风险"}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bull_final(state)
    assert result["bull_final_arguments"] is not None
    assert len(result["bull_final_arguments"]) == 1
    assert result["bull_final_arguments"][0]["phase"] == "final"
    assert result["bull_final_arguments"][0]["role"] == "bullish"
    assert result["current_phase"] == "P3_bull_final"



def test_route_after_merge_research_fast():
    """fast 模式跳过辩论"""
    state = create_test_state(mode="fast")
    assert route_after_merge_research(state) == "verdict"


def test_route_after_merge_research_default():
    """default 模式进入辩论"""
    state = create_test_state(mode="default")
    assert route_after_merge_research(state) == "bullish_v1"


@pytest.mark.asyncio
async def test_node_verdict():
    state = create_test_state()
    state["bullish_arguments"] = [{"confidence": 0.8}]
    state["bearish_arguments"] = [{"confidence": 0.3}]
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["completed_phases"] = ["P1", "P2", "P2", "P3"]
    result = await node_verdict(state)
    assert result["verdict"] is not None
    assert result["current_phase"] == "P4_verdict"


@pytest.mark.asyncio
async def test_node_signal_output():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    # node_signal_output 从 state["signal_output"] 读取（由 node_risk_check 预置）
    state["signal_output"] = {
        "status": "sent",
        "risk_color": "green",
        "risk_check": {"risk_color": "green", "approved": True},
        "signals": [
            {"symbol": "RB", "direction": "BUY", "entry_price": 3100, "score": 80},
        ],
        "signal": {
            "direction": "BUY",
            "symbol": "RB",
            "entry_price": 3100,
            "stop_loss_price": 3007,
            "target_price": 3255,
            "position_pct": 3,
            "contract": "",
            "risk_reward_ratio": 2.0,
            "confidence": 0.8,
        },
    }
    state["scan_results"] = {
        "all_ranked": [
            {"pid": "RB", "symbol": "RB", "direction": "bull", "total": 80, "price": 3100},
        ]
    }
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_risk"]
    result = await node_signal_output(state)
    assert result["signal_output"] is not None
    assert result["signal_output"]["status"] == "sent"
    assert "signal" in result["signal_output"]
    # v9.0 信号方向使用 "BUY"/"SELL"（大写）
    assert result["signal_output"]["signal"]["direction"] == "BUY"


@pytest.mark.asyncio
async def test_node_risk_check():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict"]
    result = await node_risk_check(state)
    assert result.get("signal_output") is not None
    assert result["signal_output"].get("risk_check") is not None


@pytest.mark.asyncio
async def test_node_report():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    state["risk_check"] = {"risk_level": "low", "risk_color": "green"}
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_risk"]
    result = await node_report(state)
    assert result["report_path"] is not None
    assert result["current_phase"] == "P6"
    assert "P6" in result["completed_phases"]