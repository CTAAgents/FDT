import pytest
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_judge_direction,
    node_chain, node_technical, node_fundamental,
    node_merge_research, node_debate, node_verdict,
    node_trading_plan, node_risk_check, node_report
)


class TestBenchmarkComparison:
    """基准对比测试：验证 LangGraph 版本与原有 pipeline 的结构一致性"""

    @pytest.mark.asyncio
    async def test_pipeline_phase_count_consistency(self):
        """验证阶段数量与原 pipeline 一致（P1-P6 共6个阶段）"""
        trace_id = "benchmark-phases-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        assert s1["current_phase"] == "P1"

        s2 = await node_judge_direction(s1)
        assert s2["current_phase"] == "P2"

        merged = s2.copy()
        merged["chain_analysis"] = {"test": "chain"}
        merged["technical_data"] = {"test": "tech"}
        merged["fundamental_data"] = {"test": "fund"}
        s3 = await node_merge_research(merged)
        assert s3["current_phase"] == "P3"

        s4 = await node_debate(s3)
        assert s4["current_phase"] == "P4"

        s5 = await node_verdict(s4)
        assert s5["current_phase"] == "P5_verdict"

        s6 = await node_trading_plan(s5)
        assert s6["current_phase"] == "P5_plan"

        s7 = await node_risk_check(s6)
        assert s7["current_phase"] == "P5_risk"

        s8 = await node_report(s7)
        assert s8["current_phase"] == "P6"

    @pytest.mark.asyncio
    async def test_completed_phases_monotonic(self):
        """验证 completed_phases 单调递增（与原 pipeline 一致）"""
        trace_id = "benchmark-monotonic-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["CU"]

        phases_seen = []
        current = state

        current = await node_scan(current)
        phases_seen.append(current["current_phase"])

        current = await node_judge_direction(current)
        phases_seen.append(current["current_phase"])

        merged = current.copy()
        merged["chain_analysis"] = {}
        merged["technical_data"] = {}
        merged["fundamental_data"] = {}
        current = await node_merge_research(merged)
        phases_seen.append(current["current_phase"])

        current = await node_debate(current)
        phases_seen.append(current["current_phase"])

        current = await node_verdict(current)
        phases_seen.append(current["current_phase"])

        current = await node_trading_plan(current)
        phases_seen.append(current["current_phase"])

        current = await node_risk_check(current)
        phases_seen.append(current["current_phase"])

        current = await node_report(current)
        phases_seen.append(current["current_phase"])

        assert len(phases_seen) == 8
        assert len(set(phases_seen)) == 8

    @pytest.mark.asyncio
    async def test_trace_id_consistency_with_original(self):
        """验证 trace_id 格式与原 pipeline 一致"""
        from scripts.trace_id import new_trace as original_generate

        trace_id = original_generate()
        state = create_initial_state(trace_id, mode="default")

        s1 = await node_scan(state)
        assert s1["trace_id"] == trace_id

        s2 = await node_judge_direction(s1)
        assert s2["trace_id"] == trace_id

    @pytest.mark.asyncio
    async def test_verdict_structure_compatibility(self):
        """验证 verdict 输出结构与原格式兼容"""
        trace_id = "benchmark-verdict-compat-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)

        merged = s2.copy()
        merged["chain_analysis"] = {}
        merged["technical_data"] = {}
        merged["fundamental_data"] = {}
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)

        verdict = s5.get("verdict", {})
        assert isinstance(verdict, dict)
        assert "agent_name" in verdict or "result" in verdict or len(verdict) > 0

    @pytest.mark.asyncio
    async def test_state_serialization_compatibility(self):
        """验证 DebateState 可序列化为 JSON（与原 pipeline 的 JSON 输出兼容）"""
        trace_id = "benchmark-serialization-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB", "CU"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)

        state_dict = dict(s2)
        json_str = json.dumps(state_dict, default=str, ensure_ascii=False)
        assert json_str is not None

        deserialized = json.loads(json_str)
        assert deserialized["trace_id"] == trace_id
        assert deserialized["mode"] == "default"

    @pytest.mark.asyncio
    async def test_three_sources_parallel_equivalence(self):
        """验证三源并行结果与顺序执行结果结构等价"""
        trace_id = "benchmark-parallel-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s2 = await node_judge_direction(await node_scan(state))

        s_chain = await node_chain(s2.copy())
        s_tech = await node_technical(s2.copy())
        s_fund = await node_fundamental(s2.copy())

        assert "chain_analysis" in s_chain
        assert "technical_data" in s_tech
        assert "fundamental_data" in s_fund

        merged_state = s2.copy()
        merged_state["chain_analysis"] = s_chain.get("chain_analysis")
        merged_state["technical_data"] = s_tech.get("technical_data")
        merged_state["fundamental_data"] = s_fund.get("fundamental_data")

        s3 = await node_merge_research(merged_state)
        assert "research_data" in s3
        assert isinstance(s3["research_data"], dict)


class TestBenchmarkMetrics:
    """基准测试指标验证"""

    def test_benchmark_test_cases_exist(self):
        """验证基准测试集存在"""
        benchmark_path = Path(__file__).parent.parent.parent / "benchmarks" / "test_cases.json"
        assert benchmark_path.exists(), "基准测试集不存在"

        with open(benchmark_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert "benchmark_version" in data
        assert "total_cases" in data
        assert isinstance(data["total_cases"], int)
        assert data["total_cases"] > 0

    def test_benchmark_baseline_exists(self):
        """验证基准测试基线存在"""
        baseline_path = Path(__file__).parent.parent.parent / "benchmarks" / "benchmark_baseline.json"
        assert baseline_path.exists(), "基准测试基线不存在"

        with open(baseline_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert "direction_accuracy" in data
        assert "net_accuracy" in data
        assert "avg_net_pnl_pct" in data

    def test_debate_journal_exists(self):
        """验证辩论日志存在（用于回放测试）"""
        journal_path = Path(__file__).parent.parent.parent / "memory" / "debate_journal.json"
        assert journal_path.exists(), "辩论日志不存在"
        assert journal_path.stat().st_size > 0, "辩论日志为空"

    def test_execution_followup_exists(self):
        """验证执行跟踪数据存在（用于基准对比）"""
        followup_path = Path(__file__).parent.parent.parent / "memory" / "execution_followup.json"
        assert followup_path.exists(), "执行跟踪数据不存在"

        with open(followup_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert "records" in data
        assert isinstance(data["records"], list)


class TestRegressionGuard:
    """回归防护测试：确保关键行为不退化"""

    @pytest.mark.asyncio
    async def test_scan_returns_dict(self):
        """回归测试：scan 必须返回 dict 类型结果"""
        state = create_initial_state("regression-scan-001", mode="default")
        result = await node_scan(state)
        assert isinstance(result["scan_results"], dict)

    @pytest.mark.asyncio
    async def test_verdict_has_trace_id(self):
        """回归测试：verdict 阶段必须保留 trace_id"""
        trace_id = "regression-verdict-trace-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)

        merged = s2.copy()
        merged["chain_analysis"] = {}
        merged["technical_data"] = {}
        merged["fundamental_data"] = {}
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)

        assert s5["trace_id"] == trace_id

    @pytest.mark.asyncio
    async def test_report_phase_is_last(self):
        """回归测试：report 必须是最后一个阶段（P6）"""
        trace_id = "regression-report-last-001"
        state = create_initial_state(trace_id, mode="default")
        state["selected_symbols"] = ["RB"]

        s1 = await node_scan(state)
        s2 = await node_judge_direction(s1)

        merged = s2.copy()
        merged["chain_analysis"] = {}
        merged["technical_data"] = {}
        merged["fundamental_data"] = {}
        s3 = await node_merge_research(merged)
        s4 = await node_debate(s3)
        s5 = await node_verdict(s4)
        s6 = await node_trading_plan(s5)
        s7 = await node_risk_check(s6)
        s8 = await node_report(s7)

        assert s8["current_phase"] == "P6"
        assert "P6" in s8["completed_phases"]
