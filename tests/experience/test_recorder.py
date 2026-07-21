"""
experience_recorder 测试 — Phase A5
=====================================
测试经验记录器的核心功能：Schema 验证、记录写入、索引更新。
"""
import json
import sys
from pathlib import Path

import pytest

# 确保 FDT 项目根目录在 sys.path 中
_fdt_root = Path(__file__).resolve().parents[3]
if str(_fdt_root) not in sys.path:
    sys.path.insert(0, str(_fdt_root))

# 导入被测模块 — 使用工作目录中的副本
_sys_path_backup = sys.path[:]
_work_root = Path(__file__).resolve().parents[1]
_scripts_dir = _work_root / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
_contracts_dir = _work_root / "contracts"
if str(_contracts_dir) not in sys.path:
    sys.path.insert(0, str(_contracts_dir))


# ── 1. Schema 验证测试 ──

class TestExecutionRecordValidation:
    """ExecutionRecord Schema 验证"""

    def test_valid_record_passes(self, sample_execution_record):
        """完整的有效记录通过验证"""
        from contracts.experience_schema import validate_execution_record
        errors = validate_execution_record(sample_execution_record)
        assert errors == []

    def test_missing_trace_id_fails(self, sample_execution_record):
        """缺少 trace_id 应报错"""
        from contracts.experience_schema import validate_execution_record
        record = {**sample_execution_record}
        del record["trace_id"]
        errors = validate_execution_record(record)
        assert any("trace_id" in e for e in errors)

    def test_empty_trace_id_fails(self, sample_execution_record):
        """空 trace_id 应报错"""
        from contracts.experience_schema import validate_execution_record
        record = {**sample_execution_record, "trace_id": ""}
        errors = validate_execution_record(record)
        assert any("trace_id" in e for e in errors)

    def test_missing_loop_id_fails(self, sample_execution_record):
        """缺少 loop_id 应报错"""
        from contracts.experience_schema import validate_execution_record
        record = {**sample_execution_record}
        del record["loop_id"]
        errors = validate_execution_record(record)
        assert any("loop_id" in e for e in errors)

    def test_invalid_signal_quality_fails(self, sample_execution_record):
        """无效的 signal_quality 应报错"""
        from contracts.experience_schema import validate_execution_record
        record = {**sample_execution_record}
        record["result"]["signal_quality"] = "invalid"
        errors = validate_execution_record(record)
        assert any("signal_quality" in e for e in errors)

    def test_valid_signal_qualities(self, sample_execution_record):
        """三种合法 signal_quality 都通过"""
        from contracts.experience_schema import validate_execution_record
        for quality in ("actionable", "borderline", "skip"):
            record = {**sample_execution_record}
            record["result"]["signal_quality"] = quality
            errors = validate_execution_record(record)
            assert errors == [], f"signal_quality={quality} 应通过验证"

    def test_optional_diagnosis_absent_passes(self, sample_execution_record):
        """diagnosis 可选字段缺失不影响验证"""
        from contracts.experience_schema import validate_execution_record
        assert "diagnosis" not in sample_execution_record
        errors = validate_execution_record(sample_execution_record)
        assert errors == []


class TestDistilledPatternValidation:
    """DistilledPattern Schema 验证"""

    def test_valid_pattern_passes(self, sample_distilled_pattern):
        """有效的模式通过验证"""
        from contracts.experience_schema import validate_distilled_pattern
        errors = validate_distilled_pattern(sample_distilled_pattern)
        assert errors == []

    def test_missing_pattern_id_fails(self, sample_distilled_pattern):
        """缺少 pattern_id 应报错"""
        from contracts.experience_schema import validate_distilled_pattern
        pattern = {**sample_distilled_pattern}
        del pattern["pattern_id"]
        errors = validate_distilled_pattern(pattern)
        assert any("pattern_id" in e for e in errors)

    def test_invalid_status_fails(self, sample_distilled_pattern):
        """无效 status 应报错"""
        from contracts.experience_schema import validate_distilled_pattern
        pattern = {**sample_distilled_pattern, "status": "pending"}
        errors = validate_distilled_pattern(pattern)
        assert any("status" in e for e in errors)

    def test_confidence_out_of_range_fails(self, sample_distilled_pattern):
        """confidence 超出 [0,1] 范围应报错"""
        from contracts.experience_schema import validate_distilled_pattern
        for bad_val in (-0.1, 1.1):
            pattern = {**sample_distilled_pattern, "confidence": bad_val}
            errors = validate_distilled_pattern(pattern)
            assert any("confidence" in e for e in errors)

    def test_sample_count_zero_fails(self, sample_distilled_pattern):
        """sample_count 为 0 应报错"""
        from contracts.experience_schema import validate_distilled_pattern
        pattern = {**sample_distilled_pattern, "sample_count": 0}
        errors = validate_distilled_pattern(pattern)
        assert any("sample_count" in e for e in errors)


# ── 2. 记录器功能测试 ──

class TestExperienceRecorder:
    """experience_recorder 核心功能"""

    def test_record_written_to_file(self, sample_execution_record, tmp_path):
        """记录应写入 JSON 文件"""
        from scripts.experience_recorder import write_record
        records_dir = tmp_path / "records"
        records_dir.mkdir()

        path = write_record(sample_execution_record, records_dir)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["trace_id"] == "a3f7b1c9e4d2"
        assert data["result"]["signal_quality"] == "actionable"

    def test_record_filename_format(self, sample_execution_record, tmp_path):
        """文件名应遵循 {symbol}_{date}_{trace_short}.json 格式"""
        from scripts.experience_recorder import write_record
        records_dir = tmp_path / "records"
        records_dir.mkdir()

        path = write_record(sample_execution_record, records_dir)
        assert path.stem.startswith("RB2501_20260722_")
        assert path.suffix == ".json"

    def test_index_updated_after_write(self, sample_execution_record, tmp_path):
        """写入记录后 INDEX.json 应更新"""
        from scripts.experience_recorder import write_record, update_index
        records_dir = tmp_path / "records"
        records_dir.mkdir()
        index_path = tmp_path / "INDEX.json"
        # 初始化索引
        index_path.write_text(
            json.dumps({
                "version": "1.0", "created_at": "2026-07-22",
                "last_updated": "2026-07-22", "records_count": 0,
                "patterns_count": 0, "records": {}, "patterns": {}
            }),
            encoding="utf-8",
        )

        path = write_record(sample_execution_record, records_dir)
        update_index(index_path, sample_execution_record, path.name)

        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert index["records_count"] == 1
        assert "a3f7b1c9e4d2" in index["records"]

    def test_duplicate_trace_id_rejected(self, sample_execution_record, tmp_path):
        """重复 trace_id 应拒绝写入"""
        from scripts.experience_recorder import write_record
        records_dir = tmp_path / "records"
        records_dir.mkdir()
        # 写入第一条
        write_record(sample_execution_record, records_dir)
        # 重复写入应抛异常
        with pytest.raises(FileExistsError, match="重复"):
            write_record(sample_execution_record, records_dir)

    def test_extract_task_conditions_from_scan(self, tmp_path):
        """从扫描数据中提取 task_conditions"""
        from scripts.experience_recorder import extract_task_conditions

        scan_data = {
            "symbol": "CU2501",
            "adx": 15.3,
            "atr_pct": 0.8,
            "sources": ["web_fallback"],
            "freshness_level": "fresh",
            "divergence": 0.42,
        }
        conditions = extract_task_conditions(scan_data)
        assert conditions["symbol"] == "CU2501"
        assert conditions["adx_range"] == "low"        # ADX < 20
        assert conditions["volatility_regime"] == "normal"  # ATR 0.8%
        assert conditions["data_freshness_level"] == "fresh"
        assert conditions["debate_divergence"] == 0.42
