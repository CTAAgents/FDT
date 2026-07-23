import pytest
from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.graph import build_debate_graph
from datetime import datetime


def create_test_state(mode="default") -> DebateState:
    return create_initial_state(f"test-trace-{mode}", mode)


def test_graph_default_mode():
    graph = build_debate_graph(mode="default")
    assert graph is not None


def test_graph_fast_mode():
    graph = build_debate_graph(mode="fast")
    assert graph is not None


def test_graph_deep_research_mode():
    graph = build_debate_graph(mode="deep_research")
    assert graph is not None


def test_graph_tournament_mode():
    graph = build_debate_graph(mode="tournament")
    assert graph is not None


@pytest.mark.asyncio
async def test_trace_id_propagation():
    from fdt_langgraph.nodes import node_scan, node_chain

    trace_id = "test-trace-propagation"
    state = create_initial_state(trace_id)

    result1 = await node_scan(state)
    assert result1["trace_id"] == trace_id

    # node_chain 只返回 {"chain_analysis": ...}（部分状态更新，不传播 trace_id）
    result3 = await node_chain(state)
    assert result3["chain_analysis"] is not None


@pytest.mark.asyncio
async def test_parallel_sources_all():
    state = create_test_state()
    state["dispatch_sources"] = ["chain", "technical", "fundamental"]
    state["selected_symbols"] = ["RB"]

    from fdt_langgraph.nodes import node_chain, node_technical, node_fundamental

    chain_result = await node_chain(state.copy())
    tech_result = await node_technical(state.copy())
    fund_result = await node_fundamental(state.copy())

    assert chain_result["chain_analysis"] is not None
    assert tech_result["technical_data"] is not None
    assert fund_result["fundamental_data"] is not None


@pytest.mark.asyncio
async def test_parallel_sources_two():
    state = create_test_state()
    state["dispatch_sources"] = ["chain", "technical"]
    state["selected_symbols"] = ["RB"]

    from fdt_langgraph.nodes import node_chain, node_technical

    chain_result = await node_chain(state.copy())
    tech_result = await node_technical(state.copy())

    assert chain_result["chain_analysis"] is not None
    assert tech_result["technical_data"] is not None


@pytest.mark.asyncio
async def test_parallel_sources_single():
    state = create_test_state()
    state["dispatch_sources"] = ["chain"]
    state["selected_symbols"] = ["RB"]

    from fdt_langgraph.nodes import node_chain

    chain_result = await node_chain(state)
    assert chain_result["chain_analysis"] is not None