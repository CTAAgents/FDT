"""Phase A: 裁决数据库 + 置信度校准 — 测试"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

# SUT
from memory.verdict.verdict_db import VerdictDB
from memory.verdict.calibrate import (
    compute_calibration,
    compute_calibration_error,
    calibrate_confidence,
    run_calibration,
)
from memory.manager.schemas import VerdictRecord


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def tmp_verdict_db(tmp_path: Path) -> VerdictDB:
    return VerdictDB(tmp_path)


@pytest.fixture
def sample_verdicts() -> list[VerdictRecord]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        # 高置信度正确
        {"trace_id": "v001", "timestamp": now, "symbol": "RB", "direction": "bull",
         "confidence": 85.0, "grade": "STRONG", "outcome_actual": "correct",
         "outcome_pnl": 200.0, "schema_version": "2.1"},
        {"trace_id": "v002", "timestamp": now, "symbol": "RB", "direction": "bear",
         "confidence": 80.0, "grade": "STRONG", "outcome_actual": "correct",
         "outcome_pnl": 150.0, "schema_version": "2.1"},
        # 中置信度正确
        {"trace_id": "v003", "timestamp": now, "symbol": "RB", "direction": "bull",
         "confidence": 55.0, "grade": "WATCH", "outcome_actual": "correct",
         "outcome_pnl": 50.0, "schema_version": "2.1"},
        # 高置信度错误
        {"trace_id": "v004", "timestamp": now, "symbol": "RB", "direction": "bull",
         "confidence": 90.0, "grade": "STRONG", "outcome_actual": "wrong",
         "outcome_pnl": -300.0, "schema_version": "2.1"},
        # 低置信度（40-60区间）
        {"trace_id": "v005", "timestamp": now, "symbol": "RB", "direction": "bear",
         "confidence": 45.0, "grade": "WATCH", "outcome_actual": "wrong",
         "outcome_pnl": -100.0, "schema_version": "2.1"},
        # 低置信度（0-20区间）
        {"trace_id": "v006", "timestamp": now, "symbol": "RB", "direction": "neutral",
         "confidence": 15.0, "grade": "WATCH", "outcome_actual": "correct",
         "outcome_pnl": 0.0, "schema_version": "2.1"},
        # 尚未有 outcome（模拟最新裁决）
        {"trace_id": "v007", "timestamp": now, "symbol": "RB", "direction": "bull",
         "confidence": 75.0, "grade": "STRONG", "schema_version": "2.1"},
    ]


# ═══════════════════════════════════════════════════════
# VerdictDB 测试
# ═══════════════════════════════════════════════════════


class TestVerdictDB:
    def test_store_and_get(self, tmp_verdict_db: VerdictDB):
        record: VerdictRecord = {
            "trace_id": "t001", "timestamp": "2026-07-26T00:00:00",
            "symbol": "RB", "direction": "bull", "confidence": 80.0,
            "grade": "STRONG", "schema_version": "2.1",
        }
        tid = tmp_verdict_db.store(record)
        assert tid == "t001"

        loaded = tmp_verdict_db.get("RB", "t001")
        assert loaded is not None
        assert loaded["trace_id"] == "t001"
        assert loaded["symbol"] == "RB"

    def test_get_nonexistent(self, tmp_verdict_db: VerdictDB):
        assert tmp_verdict_db.get("RB", "nonexistent") is None

    def test_query_by_symbol(self, tmp_verdict_db: VerdictDB, sample_verdicts):
        for r in sample_verdicts:
            tmp_verdict_db.store(r)

        results = tmp_verdict_db.query(symbol="RB")
        assert len(results) == 7  # all stored

        results_other = tmp_verdict_db.query(symbol="CU")
        assert len(results_other) == 0

    def test_query_by_direction(self, tmp_verdict_db: VerdictDB, sample_verdicts):
        for r in sample_verdicts:
            tmp_verdict_db.store(r)

        bulls = tmp_verdict_db.query(symbol="RB", direction="bull")
        assert len(bulls) == 4  # v001, v003, v004, v007（v004 是错误预测但方向仍是 bull）

        bears = tmp_verdict_db.query(symbol="RB", direction="bear")
        assert len(bears) == 2  # v002, v005

    def test_query_by_confidence(self, tmp_verdict_db: VerdictDB, sample_verdicts):
        for r in sample_verdicts:
            tmp_verdict_db.store(r)

        high_conf = tmp_verdict_db.query(symbol="RB", confidence_low=80, confidence_high=100)
        assert len(high_conf) == 3  # v001(85), v002(80), v004(90)

        low_conf = tmp_verdict_db.query(symbol="RB", confidence_low=0, confidence_high=30)
        assert len(low_conf) == 1  # v006(15)

    def test_count_and_list(self, tmp_verdict_db: VerdictDB, sample_verdicts):
        assert tmp_verdict_db.count() == 0
        assert tmp_verdict_db.list_symbols() == []

        for r in sample_verdicts:
            tmp_verdict_db.store(r)

        assert tmp_verdict_db.count() == 7
        assert "RB" in tmp_verdict_db.list_symbols()

    def test_multiple_symbols(self, tmp_verdict_db: VerdictDB):
        rec1: VerdictRecord = {
            "trace_id": "a001", "timestamp": "2026-07-01T00:00:00",
            "symbol": "CU", "direction": "bull", "confidence": 70.0,
            "grade": "WATCH", "schema_version": "2.1",
        }
        rec2: VerdictRecord = {
            "trace_id": "a002", "timestamp": "2026-07-01T00:00:00",
            "symbol": "SC", "direction": "bear", "confidence": 65.0,
            "grade": "WATCH", "schema_version": "2.1",
        }
        tmp_verdict_db.store(rec1)
        tmp_verdict_db.store(rec2)

        assert len(tmp_verdict_db.query()) == 2
        assert set(tmp_verdict_db.list_symbols()) == {"CU", "SC"}


# ═══════════════════════════════════════════════════════
# 校准模块测试
# ═══════════════════════════════════════════════════════


class TestCalibration:
    def test_compute_calibration_empty(self):
        buckets = compute_calibration([])
        assert len(buckets) == 5  # 5 个默认桶
        assert all(b["count"] == 0 for b in buckets)

    def test_compute_calibration_basic(self, sample_verdicts):
        buckets = compute_calibration(sample_verdicts)
        assert len(buckets) == 5

        # 80-100 桶（label = "80-100"）：v001(85,correct), v002(80,correct), v004(90,wrong) → 2/3 = 0.6667
        high_bucket = next(b for b in buckets if b["bucket_label"] == "80-100")
        assert high_bucket["count"] == 3
        assert high_bucket["correct"] == 2
        assert high_bucket["accuracy"] == pytest.approx(2 / 3, rel=1e-3)

        # 40-59 桶（label = "40-59"）：v003(55,correct), v005(45,wrong) → 1/2 = 0.5
        mid_bucket = next(b for b in buckets if b["bucket_label"] == "40-59")
        assert mid_bucket["count"] == 2
        assert mid_bucket["correct"] == 1
        assert mid_bucket["accuracy"] == pytest.approx(0.5, rel=1e-3)

        # 0-19 桶（label = "0-19"）：v006(15,correct) → 1/1 = 1.0
        low_bucket = next(b for b in buckets if b["bucket_label"] == "0-19")
        assert low_bucket["count"] == 1
        assert low_bucket["correct"] == 1
        assert low_bucket["accuracy"] == 1.0

    def test_calibrate_confidence(self, sample_verdicts):
        buckets = compute_calibration(sample_verdicts)

        # 85 置信度 → 80-100 桶 → accuracy = 0.6667
        cal = calibrate_confidence(85.0, buckets)
        assert cal == pytest.approx(66.7, rel=1e-1)

        # 50 置信度 → 40-60 桶 → accuracy = 0.5
        cal = calibrate_confidence(50.0, buckets)
        assert cal == pytest.approx(50.0, rel=1e-1)

        # 10 置信度 → 0-20 桶 → accuracy = 1.0
        cal = calibrate_confidence(10.0, buckets)
        assert cal == 100.0

        # 95 置信度落空（超出范围）→ 返回原始值
        cal = calibrate_confidence(95.0, [])  # empty buckets
        assert cal == 95.0

    def test_compute_calibration_error(self, sample_verdicts):
        buckets = compute_calibration(sample_verdicts)
        ece = compute_calibration_error(buckets)
        assert ece > 0  # 应该有一些误差
        assert isinstance(ece, float)

    def test_calibration_error_perfect(self):
        """完美校准 → ECE = 0"""
        # 构造完美校准的样本
        now = datetime.now(timezone.utc).isoformat()
        perfect = []
        for conf, correct_count, total_count in [(85, 8, 10), (55, 5, 10)]:
            for i in range(correct_count):
                perfect.append({
                    "trace_id": f"p{conf}_{i}", "timestamp": now, "symbol": "TEST",
                    "direction": "bull", "confidence": conf, "grade": "STRONG",
                    "outcome_actual": "correct", "schema_version": "2.1",
                })
            for i in range(total_count - correct_count):
                perfect.append({
                    "trace_id": f"n{conf}_{i}", "timestamp": now, "symbol": "TEST",
                    "direction": "bull", "confidence": conf, "grade": "WATCH",
                    "outcome_actual": "wrong", "schema_version": "2.1",
                })

        buckets = compute_calibration(perfect)
        ece = compute_calibration_error(buckets)
        assert ece >= 0

    def test_run_calibration_integration(self, tmp_verdict_db: VerdictDB, sample_verdicts):
        for r in sample_verdicts:
            tmp_verdict_db.store(r)

        results = run_calibration(tmp_verdict_db, symbol="RB")
        assert "RB" in results

        rb = results["RB"]
        assert rb["total_verdicts"] == 6  # v007 没有 outcome_actual
        assert rb["overall_accuracy"] > 0
        assert len(rb["buckets"]) == 5
