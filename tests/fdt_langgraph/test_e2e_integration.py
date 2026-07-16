import pytest
import json
from datetime import datetime
from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_judge_direction,
    node_chain, node_technical, node_fundamental,
    node_merge_research, node_debate, node_verdict,
    node_trading_plan, node_risk_check, node_report
)


class TestEndToEndIntegration:
    """端到端集成测试：验证完整辩论流程的数据流转一致性"""

    @pytest.mark.asyncio
    async def test_full_pipeline_default_mode(self):
        """测试 default 模式完整流程（scan → judge → 三源并行 → merge → debate → verdict → plan → risk → report）"""
        trace_id = "e2e-default-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB", "CU"]

        s1 = await node_scan(state)
        assert s1["trace_id"] == trace_id
        assert s1["scan_results"] is not None
        assert isinstance(s1["scan_results"], dict)
        assert s1["current_phase"] == "P1"
        assert "P1" in s1["completed_phases"]

        s2 = await node_judge_direction(s1)
        assert s2["trace_id"] == trace_id
        assert "judge_direction" in s2
        assert isinstance(s2["judge_direction"], dict)
        assert s2["current_phase"] == "P2"
        assert "P2" in s2["completed_phases"]

        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())
        s_fund = await node_fundamental(s2.copy())

        assert s_chain["trace_id"] == trace_id
        assert s_tech["trace_id"] == trace_id
        assert s_fund["trace_id"] == trace_id
        assert "chain_analysis" in s_chain
        assert "technical_data" in s_tech
        assert "fundamental_data" in s_fund

        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = s_tech.get("technical_data")
        merged["fundamental_data"] = s_fund.get("fundamental_data")
        s3 = await node_merge_research(merged)
        assert s3["trace_id"] == trace_id
        assert "research_data" in s3
        assert isinstance(s3["research_data"], dict)
        assert s3["current_phase"] == "P3"
        assert "P3" in s3["completed_phases"]

        s4 = await node_debate(s3)
        assert s4["trace_id"] == trace_id
        assert "bullish_arguments" in s4
        assert "bearish_arguments" in s4
        assert isinstance(s4["bullish_arguments"], list)
        assert isinstance(s4["bearish_arguments"], list)
        assert s4["current_phase"] == "P4"
        assert "P4" in s4["completed_phases"]

        s5 = await node_verdict(s4)
        assert s5["trace_id"] == trace_id
        assert "verdict" in s5
        assert isinstance(s5["verdict"], dict)
        assert s5["current_phase"] == "P5_verdict"

        s6 = await node_trading_plan(s5)
        assert s6["trace_id"] == trace_id
        assert "trading_plan" in s6
        assert s6["current_phase"] == "P5_plan"

        s7 = await node_risk_check(s6)
        assert s7["trace_id"] == trace_id
        assert "risk_check" in s7
        assert s7["current_phase"] == "P5_risk"

        s8 = await node_report(s7)
        assert s8["trace_id"] == trace_id
        assert "report_path" in s8
        assert s8["current_phase"] == "P6"
        assert "P6" in s8["completed_phases"]

    @pytest.mark.asyncio
    async def test_full_pipeline_fast_mode(self):
        """测试 fast 模式（跳过 debate，直接 verdict）"""
        trace_id = "e2e-fast-001"
        state = create_initial_state(trace_id, mode="fast")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        assert s1["trace_id"] == trace_id

        s2 = await node_judge_direction(s1)
        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())

        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = s_tech.get("technical_data")
        s3 = await node_merge_research(merged)

        s4 = await node_verdict(s3)
        assert s4["trace_id"] == trace_id
        assert "verdict" in s4

    @pytest.mark.asyncio
    async def test_data_contract_consistency(self):
        """测试各阶段输出数据契约一致性"""
        trace_id = "e2e-contract-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["CU"]

        s1 = await node_scan(state)
        assert isinstance(s1.get("scan_results"), dict)

        s2 = await node_judge_direction(s1)
        jd = s2.get("judge_direction", {})
        assert isinstance(jd, dict)
        assert "agent_name" in jd or "result" in jd or len(jd) > 0

        s_chain = await node_chain(s2.copy())
        chain_data = s_chain.get("chain_analysis", {})
        assert isinstance(chain_data, dict)

        s_tech = await node_technical(s2.copy())
        tech_data = s_tech.get("technical_data", {})
        assert isinstance(tech_data, dict)

        s_fund = await node_fundamental(s2.copy())
        fund_data = s_fund.get("fundamental_data", {})
        assert isinstance(fund_data, dict)

    @pytest.mark.asyncio
    async def test_state_serialization_roundtrip(self):
        """测试 DebateState 的 JSON 序列化/反序列化往返"""
        trace_id = "e2e-serialization-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB", "AU"]
        state["scan_results"] = {"RB": {"score": 80}, "AU": {"score": 65}}

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)

        state_dict = dict(s2)
        serialized = json.dumps(state_dict, default=str, ensure_ascii=False)
        assert serialized is not None
        assert len(serialized) > 0

        deserialized = json.loads(serialized)
        assert deserialized["trace_id"] == trace_id
        assert deserialized["mode"] == "default"

    @pytest.mark.asyncio
    async def test_trading_plan_risk_consistency(self):
        """测试交易计划与风控检查的一致性"""
        trace_id = "e2e-risk-consistency-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)
        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())

        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = s_tech.get("technical_data")
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)
        s6 = await node_trading_plan(s5)
        s7 = await node_risk_check(s6)

        assert "risk_check" in s7
        risk = s7["risk_check"]
        assert isinstance(risk, dict)

    @pytest.mark.asyncio
    async def test_report_contains_path(self):
        """测试最终报告生成路径"""
        trace_id = "e2e-report-sections-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["CU"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)
        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())
        s_fund = await node_fundamental(s2.copy())

        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = s_tech.get("technical_data")
        merged["fundamental_data"] = s_fund.get("fundamental_data")
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)
        s6 = await node_trading_plan(s5)
        s7 = await node_risk_check(s6)
        s8 = await node_report(s7)

        assert "report_path" in s8
        assert isinstance(s8["report_path"], str)
        assert len(s8["report_path"]) > 0


class TestPipelineComparison:
    """与原有 pipeline 的结果对比测试"""

    @pytest.mark.asyncio
    async def test_scan_result_structure_compatible(self):
        """验证 LangGraph 的 scan 输出结构与原有 pipeline 兼容"""
        trace_id = "compat-scan-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB", "CU", "AU"]

        result = await node_scan(state)
        scan_results = result.get("scan_results", {})

        assert isinstance(scan_results, dict)
        for symbol, data in scan_results.items():
            assert isinstance(symbol, str)

    @pytest.mark.asyncio
    async def test_verdict_structure_compatible(self):
        """验证 verdict 输出结构与原有格式兼容"""
        trace_id = "compat-verdict-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)
        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())

        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = s_tech.get("technical_data")
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)

        verdict = s5.get("verdict", {})
        assert isinstance(verdict, dict)

    @pytest.mark.asyncio
    async def test_trace_id_full_chain(self):
        """验证 trace_id 在完整链路中始终一致"""
        trace_id = "trace-full-chain-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        steps = [
            ("scan", node_scan),
            ("judge_direction", node_judge_direction),
        ]

        current = state
        for name, func in steps:
            current = await func(current)
            assert current["trace_id"] == trace_id, f"trace_id 在 {name} 后不匹配"

        for name, func in [("chain", node_chain), ("technical", node_technical), ("fundamental", node_fundamental)]:
            result = await func(current.copy())
            assert result["trace_id"] == trace_id, f"trace_id 在并行节点 {name} 中不匹配"

    @pytest.mark.asyncio
    async def test_timestamp_preserved(self):
        """验证时间戳在状态流转中保持不变"""
        trace_id = "timestamp-preserve-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]
        original_ts = state["timestamp"]

        s1 = await node_scan(state)
        assert s1["timestamp"] == original_ts

        s2 = await node_judge_direction(s1)
        assert s2["timestamp"] == original_ts

    @pytest.mark.asyncio
    async def test_phase_tracking_consistency(self):
        """验证阶段追踪的一致性：completed_phases 单调递增"""
        trace_id = "phase-tracking-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        assert len(s1["completed_phases"]) >= 1
        phases_1 = set(s1["completed_phases"])

        s2 = await node_judge_direction(s1)
        phases_2 = set(s2["completed_phases"])
        assert phases_1.issubset(phases_2)

        s_chain = await node_chain(s2.copy())
        merged = s2.copy()
        merged["chain_analysis"] = s_chain.get("chain_analysis")
        merged["technical_data"] = {}
        merged["fundamental_data"] = {}
        s3 = await node_merge_research(merged)
        phases_3 = set(s3["completed_phases"])
        assert phases_2.issubset(phases_3)
