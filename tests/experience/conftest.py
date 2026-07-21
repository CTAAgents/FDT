"""experience 测试包的共享 fixture"""
import sys
from pathlib import Path

import pytest

# 确保 contracts 模块可导入
_fdt_root = Path(__file__).resolve().parents[2]
if str(_fdt_root) not in sys.path:
    sys.path.insert(0, str(_fdt_root))


@pytest.fixture
def sample_task_conditions():
    return {
        "symbol": "RB2501",
        "adx_range": "low",
        "volatility_regime": "normal",
        "data_sources_available": ["web_fallback", "tdx"],
        "data_freshness_level": "fresh",
        "debate_divergence": 0.35,
    }


@pytest.fixture
def sample_harness_config():
    return {
        "d1_context": {"max_evidence_items": 5},
        "d3_generation": {"debater_temp": 0.4, "judge_temp": 0.2},
        "d4_orchestration": {"debate_rounds": 6},
        "d5_memory": {"history_turns": 3},
    }


@pytest.fixture
def sample_result():
    return {
        "success": True,
        "verdict_direction": "bullish",
        "verdict_confidence": 0.72,
        "signal_quality": "actionable",
        "cost_tokens": 12500,
        "duration_seconds": 180.0,
    }


@pytest.fixture
def sample_execution_record(sample_task_conditions, sample_harness_config, sample_result):
    return {
        "trace_id": "a3f7b1c9e4d2",
        "loop_id": "daily-debate",
        "timestamp": "2026-07-22T15:30:00",
        "task_conditions": sample_task_conditions,
        "harness_config": sample_harness_config,
        "result": sample_result,
    }


@pytest.fixture
def sample_distilled_pattern():
    return {
        "pattern_id": "P001",
        "pattern_type": "success",
        "created_at": "2026-07-22T16:00:00",
        "last_updated": "2026-07-22T16:00:00",
        "conditions": {
            "adx_range": ["low"],
            "volatility_regime": ["normal"],
            "data_freshness_level": ["fresh", "acceptable"],
        },
        "config_delta": {
            "d1_context": {"max_evidence_items": 8},
            "d3_generation": {"debater_temp": 0.5},
        },
        "confidence": 0.75,
        "sample_count": 12,
        "success_rate": 0.83,
        "source_trace_ids": ["a3f7", "b1c9", "e4d2"],
        "status": "confirmed",
    }


@pytest.fixture
def tmp_records_dir(tmp_path):
    """创建临时 records 目录"""
    d = tmp_path / "records"
    d.mkdir()
    return d
