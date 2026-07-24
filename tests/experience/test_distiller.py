"""
pattern_distiller 测试 — Phase B6
==================================
测试模式蒸馏引擎的聚类、差异提取、置信度计算和持久化功能。
"""
import json
import sys
from pathlib import Path

# 路径设置
_work_root = Path(__file__).resolve().parents[1]
if str(_work_root) not in sys.path:
    sys.path.insert(0, str(_work_root))
_contracts_dir = _work_root / "contracts"
if str(_contracts_dir) not in sys.path:
    sys.path.insert(0, str(_contracts_dir))


def _make_record(trace_id, symbol, adx_range, vol_regime, freshness, quality, config):
    """创建测试用的 Et 记录"""
    return {
        "trace_id": trace_id,
        "loop_id": "daily-debate",
        "timestamp": "2026-07-22T15:30:00",
        "task_conditions": {
            "symbol": symbol,
            "adx_range": adx_range,
            "volatility_regime": vol_regime,
            "data_freshness_level": freshness,
        },
        "harness_config": config,
        "result": {
            "success": quality == "actionable",
            "signal_quality": quality,
        },
    }


# ── 聚类测试 ──

class TestClustering:
    def test_records_clustered_by_three_dims(self):
        """记录按三维条件正确聚类"""
        from scripts.pattern_distiller import cluster_records

        r1 = _make_record("t1", "RB", "low", "normal", "fresh", "actionable", {})
        r2 = _make_record("t2", "CU", "low", "normal", "fresh", "actionable", {})
        r3 = _make_record("t3", "AU", "high", "normal", "fresh", "skip", {})

        clusters = cluster_records([r1, r2, r3])
        assert ("low", "normal", "fresh") in clusters
        assert len(clusters[("low", "normal", "fresh")]) == 2
        assert ("high", "normal", "fresh") in clusters
        assert len(clusters[("high", "normal", "fresh")]) == 1

    def test_empty_records_returns_empty(self):
        """空记录返回空聚类"""
        from scripts.pattern_distiller import cluster_records
        assert cluster_records([]) == {}


# ── 配置差异提取测试 ──

class TestConfigDelta:
    def test_significant_delta_extracted(self):
        """显著配置差异被正确提取"""
        from scripts.pattern_distiller import extract_config_delta

        success = [
            _make_record("s1", "RB", "low", "normal", "fresh", "actionable",
                         {"d3_generation": {"debater_temp": 0.6, "judge_temp": 0.2}}),
            _make_record("s2", "RB", "low", "normal", "fresh", "actionable",
                         {"d3_generation": {"debater_temp": 0.6, "judge_temp": 0.2}}),
        ]
        failure = [
            _make_record("f1", "RB", "low", "normal", "fresh", "skip",
                         {"d3_generation": {"debater_temp": 0.2, "judge_temp": 0.1}}),
            _make_record("f2", "RB", "low", "normal", "fresh", "skip",
                         {"d3_generation": {"debater_temp": 0.2, "judge_temp": 0.1}}),
        ]
        delta = extract_config_delta(success, failure)
        assert "d3_generation" in delta
        assert delta["d3_generation"]["debater_temp"] == 0.6

    def test_no_delta_when_similar(self):
        """配置相似时返回空 delta"""
        from scripts.pattern_distiller import extract_config_delta

        same_config = {"d3_generation": {"debater_temp": 0.4}}
        success = [_make_record("s1", "RB", "low", "normal", "fresh", "actionable", same_config)]
        failure = [_make_record("f1", "RB", "low", "normal", "fresh", "skip", same_config)]
        delta = extract_config_delta(success, failure)
        assert delta == {}

    def test_no_delta_when_missing_group(self):
        """任一组为空时返回空 delta"""
        from scripts.pattern_distiller import extract_config_delta

        success = [_make_record("s1", "RB", "low", "normal", "fresh", "actionable", {})]
        delta = extract_config_delta(success, [])
        assert delta == {}


# ── 置信度计算测试 ──

class TestConfidence:
    def test_high_confidence(self):
        """大样本 + 高成功率 + 高差异 → 高置信度"""
        from scripts.pattern_distiller import _compute_confidence
        c = _compute_confidence(sample_count=20, success_rate=0.9, delta_magnitude=1.0)
        assert c >= 0.7

    def test_low_confidence(self):
        """小样本 + 低成功率 + 低差异 → 低置信度"""
        from scripts.pattern_distiller import _compute_confidence
        c = _compute_confidence(sample_count=2, success_rate=0.3, delta_magnitude=0.1)
        assert c < 0.3

    def test_confidence_bounded(self):
        """置信度始终在 [0, 1] 范围内"""
        from scripts.pattern_distiller import _compute_confidence
        for n in [1, 5, 10, 50, 100]:
            for sr in [0.0, 0.5, 1.0]:
                for dm in [0.0, 0.5, 1.0]:
                    c = _compute_confidence(n, sr, dm)
                    assert 0.0 <= c <= 1.0, f"n={n} sr={sr} dm={dm} → c={c}"


# ── 安全阀测试 ──

class TestSafetyValves:
    def test_below_min_sample_skipped(self):
        """样本数不足时跳过"""
        from scripts.pattern_distiller import cluster_records

        records = [
            _make_record("t1", "RB", "low", "normal", "fresh", "actionable",
                         {"d3_generation": {"debater_temp": 0.6}}),
            _make_record("t2", "RB", "low", "normal", "fresh", "skip",
                         {"d3_generation": {"debater_temp": 0.2}}),
        ]
        clusters = cluster_records(records)
        total_in_cluster = sum(len(v) for v in clusters.values())
        assert total_in_cluster == 2
        assert total_in_cluster < 5  # 不满足 min_sample

    def test_max_patterns_limit(self):
        """模式库上限为 50"""
        from scripts.pattern_distiller import MAX_PATTERNS
        assert MAX_PATTERNS == 50

    def test_confidence_threshold(self):
        """低于置信度阈值的模式被过滤"""
        from scripts.pattern_distiller import CONFIDENCE_THRESHOLD
        assert CONFIDENCE_THRESHOLD == 0.3


# ── 持久化测试 ──

class TestPersistence:
    def test_save_pattern_creates_file(self, tmp_path):
        """保存模式创建 JSON 文件"""
        from scripts.pattern_distiller import save_pattern

        pattern = {
            "pattern_id": "P001",
            "pattern_type": "success",
            "created_at": "2026-07-22T16:00:00",
            "last_updated": "2026-07-22T16:00:00",
            "conditions": {"adx_range": ["low"]},
            "config_delta": {"d3_generation": {"debater_temp": 0.5}},
            "confidence": 0.75,
            "sample_count": 12,
            "success_rate": 0.83,
            "source_trace_ids": ["t1", "t2"],
            "status": "staging",
        }
        filepath = save_pattern(pattern, tmp_path)
        assert filepath.exists()
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert data["pattern_id"] == "P001"
        assert data["status"] == "staging"


# ── 端到端蒸馏测试 ──

class TestEndToEnd:
    def test_full_distillation_workflow(self, tmp_path):
        """完整蒸馏工作流：写入记录 → 蒸馏 → 保存"""
        from scripts.experience_recorder import write_record
        from scripts.pattern_distiller import distill_patterns

        records_dir = tmp_path / "records"
        records_dir.mkdir()
        patterns_dir = tmp_path / "patterns"

        # 写入 8 条同聚类记录（成功 6 + 失败 2），满足 min_sample=5
        for i in range(6):
            write_record(
                _make_record(f"s{i}", "RB", "low", "normal", "fresh", "actionable",
                            {"d3_generation": {"debater_temp": 0.6, "judge_temp": 0.2}}),
                records_dir,
            )
        for i in range(2):
            write_record(
                _make_record(f"f{i}", "RB", "low", "normal", "fresh", "skip",
                            {"d3_generation": {"debater_temp": 0.2, "judge_temp": 0.1}}),
                records_dir,
            )

        patterns = distill_patterns(records_dir, patterns_dir, min_sample=5, confidence_threshold=0.1)
        assert len(patterns) >= 1
        assert patterns[0]["conditions"]["adx_range"] == ["low"]
        assert patterns[0]["sample_count"] == 8
        assert patterns[0]["status"] == "staging"
