"""tests/loop_engine/test_evolution_loop.py — 主循环测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from loop_engine.contracts import EVOLUTION_VERSION
from loop_engine.evolution_loop import EvolutionLoop, EvolutionRunResult
from loop_engine.state import (
    EvolutionStateManager,
    generate_run_id,
    generate_trace_id,
)


# ─── trace_id 生成 ────────────────────────────────────────

def test_generate_trace_id_format():
    tid = generate_trace_id("l2")
    assert tid.startswith("l2_")
    # 格式: l2_<8hex>_<timestamp>
    parts = tid.split("_")
    assert len(parts) == 3


def test_generate_run_id_format():
    rid = generate_run_id()
    assert rid.startswith("run_")


def test_generate_trace_id_uniqueness():
    ids = {generate_trace_id("x") for _ in range(100)}
    assert len(ids) >= 95  # 高概率唯一


# ─── 状态管理 ─────────────────────────────────────────────

def test_state_manager_init(tmp_memory_dir):
    """首次加载应初始化新状态。"""
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    assert state["status"] == "running"
    assert state["version"] == EVOLUTION_VERSION
    assert state["last_generation"] == 0
    assert state["total_factors_evaluated"] == 0


def test_state_manager_save_and_load(tmp_memory_dir):
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    state["last_generation"] = 5
    state["total_factors_evaluated"] = 20
    mgr.save(state)

    # 重新加载
    mgr2 = EvolutionStateManager(tmp_memory_dir)
    state2 = mgr2.load_or_init()
    assert state2["last_generation"] == 5
    assert state2["total_factors_evaluated"] == 20


def test_state_manager_creates_backup(tmp_memory_dir):
    """保存时应自动创建 backup 文件。"""
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    mgr.save(state)
    backup = tmp_memory_dir / "state.json.backup"
    assert backup.exists()


def test_state_manager_recovers_from_backup(tmp_memory_dir):
    """主文件损坏时应从 backup 恢复。"""
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    state["last_generation"] = 7
    mgr.save(state)

    # 损坏主文件
    (tmp_memory_dir / "state.json").write_text("invalid json", encoding="utf-8")

    # 重新加载应从 backup 恢复
    mgr2 = EvolutionStateManager(tmp_memory_dir)
    state2 = mgr2.load_or_init()
    assert state2["last_generation"] == 7


def test_state_manager_version_check(tmp_memory_dir):
    """版本不匹配时应视为损坏。"""
    # 写入错误版本
    (tmp_memory_dir / "state.json").write_text(
        json.dumps({"version": "0.0.0", "status": "running"}),
        encoding="utf-8",
    )
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    # 应重新初始化
    assert state["version"] == EVOLUTION_VERSION
    assert state["last_generation"] == 0


def test_state_manager_mark_running(tmp_memory_dir):
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.mark_running()
    assert state["status"] == "running"
    assert state["run_id"].startswith("run_")


def test_state_manager_mark_completed(tmp_memory_dir):
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    mgr.mark_completed(state)
    state2 = mgr.load_or_init()
    assert state2["status"] == "completed"


def test_state_manager_mark_circuit_broken(tmp_memory_dir):
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    mgr.mark_circuit_broken(state, "Token 熔断")
    state2 = mgr.load_or_init()
    assert state2["status"] == "circuit_broken"
    assert "Token" in state2["last_error"]


def test_state_manager_add_tokens(tmp_memory_dir):
    mgr = EvolutionStateManager(tmp_memory_dir)
    state = mgr.load_or_init()
    initial = state["tokens_consumed"]
    mgr.add_tokens(state, 500)
    state2 = mgr.load_or_init()
    assert state2["tokens_consumed"] == initial + 500


# ─── EvolutionLoop 完整运行 ────────────────────────────────

@pytest.fixture
def mock_llm_client():
    """Mock LLM 客户端 — 返回固定响应。"""
    client = MagicMock()
    client.complete.return_value = (
        json.dumps({
            "mutation_type": "macro_logic",
            "mutation_summary": "Mock: window+5",
            "code_modification": "window_plus_5",
            "economic_logic_modification": {
                "theory": 4, "behavioral": 3, "microstructure": 3, "institutional": 4,
                "narrative": "Mock LLM 经济逻辑"
            },
            "lessons_referenced": ["历史成功"],
        }),
        200,
    )
    return client


def test_evolution_loop_runs_minimal(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """应能完整运行 1 代演化。"""
    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        llm_client=mock_llm_client,
        n_trials_micro=5,  # 减少 trials 加速测试
    )
    result = loop.run(max_generation=1)
    assert result.status in ("completed", "paused", "circuit_broken")
    assert result.generations_completed >= 0
    assert result.tokens_consumed > 0


def test_evolution_loop_creates_state_file(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """运行后应创建 state.json。"""
    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        llm_client=mock_llm_client,
        n_trials_micro=3,
    )
    loop.run(max_generation=1)
    assert (tmp_memory_dir / "state.json").exists()


def test_evolution_loop_creates_elite_dir(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """应自动创建 elite 目录。"""
    assert not tmp_elite_dir.exists()
    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        llm_client=mock_llm_client,
        n_trials_micro=3,
    )
    loop.run(max_generation=1)
    assert tmp_elite_dir.exists()


def test_evolution_loop_record_experience_traces(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """运行后应在 failure/ 或 success/ 目录写入轨迹。"""
    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        llm_client=mock_llm_client,
        n_trials_micro=3,
    )
    loop.run(max_generation=2)

    success_dir = tmp_memory_dir / "success"
    failure_dir = tmp_memory_dir / "failure"
    # 至少有一个目录有轨迹（合成数据下大概率失败）
    total = len(list(success_dir.glob("*.json"))) + len(list(failure_dir.glob("*.json")))
    assert total > 0


def test_evolution_loop_circuit_breaker_on_token(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """token 超过 2x 预算应触发熔断。"""
    from loop_engine.contracts import BudgetConfig

    # 设置极小预算 + 极大 mock token
    mock_llm_client.complete.return_value = (
        json.dumps({
            "mutation_type": "macro_logic",
            "mutation_summary": "Mock",
            "code_modification": "window_plus_5",
            "economic_logic_modification": {
                "theory": 4, "behavioral": 3, "microstructure": 3, "institutional": 4,
                "narrative": "Mock"
            },
            "lessons_referenced": [],
        }),
        500_000,  # 极大 token 数
    )

    budget = BudgetConfig(
        nightly_token_limit=100,  # 极小预算
        monthly_token_limit=1000,
        max_generation=10,
        max_tokens_per_factor=10_000,
        circuit_breaker_token_ratio=2.0,
        circuit_breaker_consecutive_low_ic=3,
        circuit_breaker_low_ic_threshold=0.01,
        circuit_breaker_failure_rate=0.99,
    )

    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        budget=budget,
        llm_client=mock_llm_client,
        n_trials_micro=2,
    )
    result = loop.run(max_generation=5)
    assert result.status == "circuit_broken"
    assert "Token" in (result.circuit_breaker_reason or "")


def test_evolution_loop_to_dict(
    sample_ohlcv, forward_returns, tmp_memory_dir, tmp_elite_dir, mock_llm_client
):
    """EvolutionRunResult.to_dict() 应返回完整字典。"""
    loop = EvolutionLoop(
        data=sample_ohlcv,
        forward_returns=forward_returns,
        elite_dir=tmp_elite_dir,
        memory_dir=tmp_memory_dir,
        llm_client=mock_llm_client,
        n_trials_micro=2,
    )
    result = loop.run(max_generation=1)
    d = result.to_dict()
    assert "run_id" in d
    assert "trace_id" in d
    assert "generations_completed" in d
    assert "status" in d
