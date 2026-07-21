"""
harness_adapter 测试 — Phase C6
=================================
测试案例适配引擎的检索、合并、边界检查和 Shadow 模式。
"""
import json
import sys
from pathlib import Path

import pytest

_work_root = Path(__file__).resolve().parents[1]
if str(_work_root) not in sys.path:
    sys.path.insert(0, str(_work_root))
_contracts_dir = _work_root / "contracts"
if str(_contracts_dir) not in sys.path:
    sys.path.insert(0, str(_contracts_dir))


# ── 模式匹配测试 ──

class TestPatternMatching:
    def test_exact_condition_match(self):
        """条件完全匹配时返回 True"""
        from scripts.harness_adapter import _matches_conditions

        tc = {"adx_range": "low", "volatility_regime": "normal"}
        pc = {"adx_range": ["low"], "volatility_regime": ["normal"]}
        assert _matches_conditions(tc, pc) is True

    def test_partial_condition_no_match(self):
        """部分条件不匹配时返回 False"""
        from scripts.harness_adapter import _matches_conditions

        tc = {"adx_range": "high", "volatility_regime": "normal"}
        pc = {"adx_range": ["low"], "volatility_regime": ["normal"]}
        assert _matches_conditions(tc, pc) is False

    def test_missing_condition_field(self):
        """任务条件缺少字段时返回 False"""
        from scripts.harness_adapter import _matches_conditions

        tc = {"adx_range": "low"}
        pc = {"adx_range": ["low"], "volatility_regime": ["normal"]}
        assert _matches_conditions(tc, pc) is False


# ── 案例检索测试 ──

class TestCaseSearch:
    def test_finds_similar_cases(self, tmp_path):
        """检索相似度 >= 阈值的案例"""
        from scripts.harness_adapter import search_similar_cases

        records_dir = tmp_path / "records"
        records_dir.mkdir()

        record = {
            "trace_id": "t1", "loop_id": "daily-debate",
            "timestamp": "2026-07-22T15:30:00",
            "task_conditions": {
                "symbol": "RB2501", "adx_range": "low",
                "volatility_regime": "normal", "data_freshness_level": "fresh",
            },
            "harness_config": {},
            "result": {"signal_quality": "actionable"},
        }
        (records_dir / "RB2501_20260722_t1.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

        tc = {"adx_range": "low", "volatility_regime": "normal", "data_freshness_level": "fresh"}
        results = search_similar_cases(tc, records_dir)
        assert len(results) == 1
        assert results[0][1] == 1.0  # 完全匹配

    def test_filters_below_threshold(self, tmp_path):
        """相似度低于阈值的不返回"""
        from scripts.harness_adapter import search_similar_cases

        records_dir = tmp_path / "records"
        records_dir.mkdir()

        record = {
            "trace_id": "t1", "loop_id": "daily-debate",
            "timestamp": "2026-07-22T15:30:00",
            "task_conditions": {
                "symbol": "AU2506", "adx_range": "high",
                "volatility_regime": "high", "data_freshness_level": "stale",
            },
            "harness_config": {},
            "result": {"signal_quality": "skip"},
        }
        (records_dir / "AU2506_20260722_t1.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

        tc = {"adx_range": "low", "volatility_regime": "normal", "data_freshness_level": "fresh"}
        results = search_similar_cases(tc, records_dir, threshold=0.5)
        assert len(results) == 0


# ── 配置合并测试 ──

class TestConfigMerge:
    def test_delta_applied_correctly(self):
        """config_delta 正确应用到基准配置"""
        from scripts.harness_adapter import apply_config_delta, DEFAULT_CONFIG

        delta = {"d3_generation": {"debater_temp": 0.6}}
        result = apply_config_delta(DEFAULT_CONFIG, delta)
        assert result["d3_generation"]["debater_temp"] == 0.6
        assert DEFAULT_CONFIG["d3_generation"]["debater_temp"] == 0.4  # 原对象不变

    def test_multiple_deltas(self):
        """多维度 delta 同时应用"""
        from scripts.harness_adapter import apply_config_delta, DEFAULT_CONFIG

        delta = {
            "d3_generation": {"debater_temp": 0.5},
            "d1_context": {"max_evidence_items": 8},
        }
        result = apply_config_delta(DEFAULT_CONFIG, delta)
        assert result["d3_generation"]["debater_temp"] == 0.5
        assert result["d1_context"]["max_evidence_items"] == 8

    def test_empty_delta_returns_copy(self):
        """空 delta 返回基准配置的深拷贝"""
        from scripts.harness_adapter import apply_config_delta, DEFAULT_CONFIG

        result = apply_config_delta(DEFAULT_CONFIG, {})
        assert result == DEFAULT_CONFIG
        result["d3_generation"]["debater_temp"] = 0.9
        assert DEFAULT_CONFIG["d3_generation"]["debater_temp"] == 0.4


# ── 边界检查测试 ──

class TestClamping:
    def test_temperature_clamped_high(self):
        """temperature 超过上限被修正"""
        from scripts.harness_adapter import clamp_config

        config = {"d3_generation": {"debater_temp": 1.0}}
        clamped = clamp_config(config)
        assert len(clamped) == 1
        assert clamped[0]["path"] == "d3_generation.debater_temp"
        assert config["d3_generation"]["debater_temp"] == 0.8

    def test_temperature_clamped_low(self):
        """temperature 低于下限被修正"""
        from scripts.harness_adapter import clamp_config

        config = {"d3_generation": {"debater_temp": 0.0}}
        clamped = clamp_config(config)
        assert config["d3_generation"]["debater_temp"] == 0.1

    def test_normal_value_not_clamped(self):
        """正常范围内的值不被修正"""
        from scripts.harness_adapter import clamp_config

        config = {"d3_generation": {"debater_temp": 0.5}}
        clamped = clamp_config(config)
        assert clamped == []


# ── Shadow 模式测试 ──

class TestShadowMode:
    def test_shadow_returns_base_config(self):
        """影子模式返回原始基准配置"""
        from scripts.harness_adapter import adapt_harness, DEFAULT_CONFIG

        tc = {"adx_range": "low", "volatility_regime": "normal", "data_freshness_level": "fresh"}
        tmp_path = Path("nonexistent")
        result = adapt_harness(tc, tmp_path / "patterns", tmp_path / "records",
                              shadow_mode=True)
        assert result["adapted_config"] == DEFAULT_CONFIG
        assert result["applied"] is False

    def test_normal_mode_applies_adaptation(self):
        """普通模式应用适配"""
        from scripts.harness_adapter import adapt_harness, DEFAULT_CONFIG

        tc = {"adx_range": "low", "volatility_regime": "normal", "data_freshness_level": "fresh"}
        tmp_path = Path("nonexistent")
        result = adapt_harness(tc, tmp_path / "patterns", tmp_path / "records",
                              shadow_mode=False)
        assert result["applied"] is True


# ── 适配日志测试 ──

class TestAdaptationLog:
    def test_log_written_to_file(self, tmp_path):
        """适配日志写入文件"""
        from scripts.harness_adapter import log_adaptation

        result = {
            "matched_patterns": ["P001"],
            "matched_cases": 12,
            "adaptations": [{"dimension": "d1", "field": "max_evidence_items", "value": 8}],
            "clamped": [],
            "applied": True,
        }
        filepath = log_adaptation(result, "trace123", "RB2501", tmp_path / "logs")
        assert filepath.exists()
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert data["symbol"] == "RB2501"
        assert data["matched_patterns"] == ["P001"]


# ── 端到端适配测试 ──

class TestEndToEndAdaptation:
    def test_full_adaptation_workflow(self, tmp_path):
        """完整适配工作流：写入模式 → 写入案例 → 适配"""
        from scripts.harness_adapter import adapt_harness
        from scripts.pattern_distiller import save_pattern
        from scripts.experience_recorder import write_record

        patterns_dir = tmp_path / "patterns"
        patterns_dir.mkdir()
        records_dir = tmp_path / "records"
        records_dir.mkdir()

        # 写入 confirmed 模式
        pattern = {
            "pattern_id": "P001", "pattern_type": "success",
            "created_at": "2026-07-22T16:00:00",
            "last_updated": "2026-07-22T16:00:00",
            "conditions": {"adx_range": ["low"], "volatility_regime": ["normal"], "data_freshness_level": ["fresh"]},
            "config_delta": {"d3_generation": {"debater_temp": 0.55}},
            "confidence": 0.8, "sample_count": 10, "success_rate": 0.8,
            "source_trace_ids": ["t1", "t2"], "status": "confirmed",
        }
        save_pattern(pattern, patterns_dir)

        # 写入相似案例
        similar_record = {
            "trace_id": "s1", "loop_id": "daily-debate",
            "timestamp": "2026-07-22T15:30:00",
            "task_conditions": {
                "symbol": "RB2501", "adx_range": "low",
                "volatility_regime": "normal", "data_freshness_level": "fresh",
            },
            "harness_config": {"d3_generation": {"debater_temp": 0.55, "judge_temp": 0.25}},
            "result": {"success": True, "signal_quality": "actionable"},
        }
        write_record(similar_record, records_dir)

        # 执行适配
        tc = {"adx_range": "low", "volatility_regime": "normal", "data_freshness_level": "fresh"}
        result = adapt_harness(tc, patterns_dir, records_dir)

        assert "P001" in result["matched_patterns"]
        assert result["matched_cases"] >= 1
        assert result["applied"] is True
        assert result["adapted_config"]["d3_generation"]["debater_temp"] == 0.55
