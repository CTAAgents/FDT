"""
RHI 整合测试 — HarnessSpec + PairwiseEvaluator + HarnessOptimizer + RHI Graph + Global.
"""


from contracts.rhi_harness_spec import HarnessSpec
from scripts.rhi_harness_optimizer import (
    apply_config_delta,
    build_optimizer_prompt,
    parse_optimizer_response,
)
from scripts.rhi_pairwise_eval import (
    _score_quality_pass,
    _score_risk_pass,
    _score_signal_quality,
    compute_improvement_rate,
)

# ── HarnessSpec 基本测试 ──

def test_harness_spec_minimal():
    """最小 HarnessSpec 可构造。"""
    spec: HarnessSpec = {
        "agent_candidates": {},
        "workflow": {"contracts": {}, "hops": [], "orchestrator_instruction": ""},
        "auxiliary_rules": {"acceptance_gates": [], "fallback_rules": [], "communication_rules": [], "recall_triggers": []},
        "iteration": 0,
        "trace_id": "test-001",
        "created_at": "2026-07-23T12:00:00",
    }
    assert spec["iteration"] == 0
    assert spec["trace_id"] == "test-001"


def test_harness_spec_with_agents():
    """带 Agent 的 HarnessSpec。"""
    spec: HarnessSpec = {
        "agent_candidates": {
            "judge": {"role": "judge", "instruction": "做出裁决", "contract_fields": ["direction", "confidence"]}
        },
        "workflow": {
            "contracts": {"judge": {"contract_fields": ["direction", "confidence"]}},
            "hops": [{"name": "裁决", "agents": ["judge"], "input_from": [], "output_to": ["verdict"], "timeout": 120, "fallback": "D06"}],
            "orchestrator_instruction": "",
        },
        "auxiliary_rules": {"acceptance_gates": [], "fallback_rules": [], "communication_rules": [], "recall_triggers": []},
        "iteration": 1,
        "trace_id": "test-002",
        "created_at": "2026-07-23T12:00:00",
    }
    assert "judge" in spec["agent_candidates"]
    assert len(spec["workflow"]["hops"]) == 1


# ── Pairwise Evaluator 测试 ──

def test_score_quality_pass_no_issues():
    """质检无问题 → 1.0。"""
    state = {"quality_report": {"issues": [], "status": "PASS"}}
    assert _score_quality_pass(state) == 1.0


def test_score_quality_pass_with_errors():
    """质检有 error → 扣分。"""
    state = {"quality_report": {"issues": [{"field": "symbol", "message": "missing", "severity": "error"}]}}
    score = _score_quality_pass(state)
    assert score < 1.0
    assert score >= 0.0


def test_score_quality_pass_empty():
    """无质检数据 → 0。"""
    assert _score_quality_pass({}) == 0.0


def test_score_risk_pass_green():
    """风控 green → 1.0。"""
    assert _score_risk_pass({"risk_check": {"risk_level": "green"}}) == 1.0


def test_score_risk_pass_yellow():
    """风控 yellow → 0.5。"""
    assert _score_risk_pass({"risk_check": {"risk_level": "yellow"}}) == 0.5


def test_score_risk_pass_red():
    """风控 red → 0.0。"""
    assert _score_risk_pass({"risk_check": {"risk_level": "red"}}) == 0.0


def test_score_risk_pass_missing():
    """无风控数据 → 0.0。"""
    assert _score_risk_pass({}) == 0.0


def test_score_signal_quality():
    """信号质量评分。"""
    state = {"signal_report": {"signals": [
        {"symbol": "RB", "confidence": 0.8},
        {"symbol": "CU", "confidence": 0.6},
    ]}}
    score = _score_signal_quality(state)
    assert 0 < score <= 1.0


def test_score_signal_quality_empty():
    """无信号 → 0.0。"""
    assert _score_signal_quality({}) == 0.0


def test_compute_improvement_rate_all_improve():
    """全部改进 → 1.0。"""
    prefs = [
        {"iteration": 1, "preference": "improve"},
        {"iteration": 2, "preference": "improve"},
    ]
    assert compute_improvement_rate(prefs) == 1.0


def test_compute_improvement_rate_mixed():
    """混合偏好 → 0.5。"""
    prefs = [
        {"iteration": 1, "preference": "improve"},
        {"iteration": 2, "preference": "regress"},
    ]
    assert compute_improvement_rate(prefs) == 0.5


def test_compute_improvement_rate_empty():
    """空历史 → 0.0。"""
    assert compute_improvement_rate([]) == 0.0


# ── Harness Optimizer 测试 ──

def test_parse_optimizer_response_valid():
    """有效 JSON 响应可解析。"""
    response = '{"workflow": {"contracts": {}}, "change_summary": "test change"}'
    delta, summary = parse_optimizer_response(response)
    assert delta is not None
    assert summary == "test change"


def test_parse_optimizer_response_markdown_wrapped():
    """Markdown 包裹的 JSON。"""
    response = '```json\n{"workflow": {"contracts": {}}, "change_summary": "test"}\n```'
    delta, summary = parse_optimizer_response(response)
    assert delta is not None
    assert summary == "test"


def test_parse_optimizer_response_invalid():
    """无效 JSON → None。"""
    delta, summary = parse_optimizer_response("not json")
    assert delta is None
    assert summary is None


def test_parse_optimizer_response_empty():
    """空字符串 → None。"""
    delta, summary = parse_optimizer_response("")
    assert delta is None
    assert summary is None


def test_build_optimizer_prompt():
    """Optimizer prompt 可构造。"""
    spec: HarnessSpec = {
        "agent_candidates": {
            "judge": {"role": "judge", "instruction": "裁决", "contract_fields": ["direction"]}
        },
        "workflow": {
            "contracts": {"judge": {"contract_fields": ["direction"]}},
            "hops": [{"name": "裁决", "agents": ["judge"], "input_from": [], "output_to": ["verdict"], "timeout": 120, "fallback": "D06"}],
            "orchestrator_instruction": "",
        },
        "auxiliary_rules": {"acceptance_gates": ["12项检查"], "fallback_rules": ["D06"], "communication_rules": [], "recall_triggers": []},
        "iteration": 1,
        "trace_id": "t1",
        "created_at": "",
    }
    prefs = [{"iteration": 1, "preference": "improve", "score_current": 0.8, "score_previous": 0.6, "score_breakdown": {"current": {}, "previous": {}}, "rationale": "better", "key_diffs": ["quality_pass: +0.2"]}]
    prompt = build_optimizer_prompt(spec, prefs, task_desc="测试任务")
    assert "Judge" in prompt or "judge" in prompt
    assert "改进" in prompt or "improve" in prompt


def test_apply_config_delta_contracts():
    """Workflow contracts 合并。"""
    base: HarnessSpec = {
        "agent_candidates": {"judge": {"role": "judge", "instruction": "", "contract_fields": ["direction"]}},
        "workflow": {"contracts": {"judge": {"contract_fields": ["direction"]}}, "hops": [{"name": "裁决", "agents": ["judge"], "input_from": [], "output_to": ["verdict"], "timeout": 120, "fallback": "D06"}], "orchestrator_instruction": ""},
        "auxiliary_rules": {"acceptance_gates": [], "fallback_rules": [], "communication_rules": [], "recall_triggers": []},
        "iteration": 0,
        "trace_id": "t1",
        "created_at": "",
    }
    delta = {"workflow": {"contracts": {"judge": {"contract_fields": ["direction", "new_field"]}}}}
    new = apply_config_delta(base, delta)
    assert "new_field" in new["workflow"]["contracts"]["judge"]["contract_fields"]
    assert new["iteration"] == 1


def test_apply_config_delta_aux_rules():
    """Auxiliary Rules 合并。"""
    base: HarnessSpec = {
        "agent_candidates": {},
        "workflow": {"contracts": {}, "hops": [], "orchestrator_instruction": ""},
        "auxiliary_rules": {"acceptance_gates": ["C01"], "fallback_rules": [], "communication_rules": [], "recall_triggers": []},
        "iteration": 0,
        "trace_id": "",
        "created_at": "",
    }
    delta = {"auxiliary_rules": {"recall_triggers": ["ADX<20: 增加基本面权重"]}}
    new = apply_config_delta(base, delta)
    assert "ADX<20" in new["auxiliary_rules"]["recall_triggers"][0]
    assert "C01" in new["auxiliary_rules"]["acceptance_gates"]


# ── Global Harness 测试 ──

def test_global_rhi_scoring():
    """全局 Harness 评分功能。"""
    # 无法直接测试 _read_claude_md，但可以测评分逻辑
    sample_content = r"""
# FDT Project
## Harness 工程规范
docs/harness contains all specs
反模式检测规则: AP01-AP10
12项检查清单: C01-C12
project_memory is available
Knowledge base at D:\Knowledge
    """
    # 注入模拟内容
    import scripts.rhi_global_harness as rhi_global
    original_read = rhi_global._read_claude_md
    rhi_global._read_claude_md = lambda: sample_content

    try:
        score = rhi_global._score_output()
        assert score["score"] > 0.5  # 各项指标都应该被满足
    finally:
        rhi_global._read_claude_md = original_read
