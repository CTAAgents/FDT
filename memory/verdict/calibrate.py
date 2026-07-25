"""置信度校准模块 — 置信度-准确率校准曲线

将历史裁决按置信度分桶，计算每桶实际准确率。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..manager.schemas import CalibrationBucket, CalibrationResult, VerdictRecord
from .verdict_db import VerdictDB

logger = logging.getLogger(__name__)

# 默认分桶区间 [low, high)
DEFAULT_BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]


def compute_calibration(
    records: list[VerdictRecord],
) -> list[CalibrationBucket]:
    """计算置信度-准确率校准桶

    Args:
        records: 已有 outcome_actual 的裁决记录

    Returns:
        按置信度分桶的校准结果
    """
    buckets: list[CalibrationBucket] = []

    for low, high in DEFAULT_BUCKETS:
        subset = [
            r for r in records
            if isinstance(r.get("confidence"), (int, float))
            and low <= r["confidence"] < high
            and r.get("outcome_actual") in ("correct", "wrong")
        ]
        count = len(subset)
        correct = sum(1 for r in subset if r.get("outcome_actual") == "correct")
        accuracy = correct / count if count > 0 else 0.0

        buckets.append({
            "bucket_label": f"{low}-{high-1 if high <= 100 else 100}",
            "low": low,
            "high": high,
            "count": count,
            "correct": correct,
            "accuracy": round(accuracy, 4),
        })

    return buckets


def compute_calibration_error(
    buckets: list[CalibrationBucket],
) -> float:
    """计算校准误差（Expected Calibration Error）

    ECE = Σ(|accuracy - confidence_center| × weight)
    简化版：取各桶校准误差的加权平均
    """
    total_count = sum(b.get("count", 0) for b in buckets)
    if total_count == 0:
        return 0.0

    weighted_error = 0.0
    for b in buckets:
        if b["count"] == 0:
            continue
        center = (b["low"] + b["high"]) / 200  # 归一化到 [0, 1]
        acc = b["accuracy"]
        weight = b["count"] / total_count
        weighted_error += abs(acc - center) * weight

    return round(weighted_error, 4)


def calibrate_confidence(
    raw_confidence: float,
    buckets: list[CalibrationBucket],
) -> float:
    """将原始置信度校准为校准后置信度

    Args:
        raw_confidence: Agent 原始置信度 (0-100)
        buckets: 校准桶（来自 compute_calibration）

    Returns:
        校准后置信度 (0-100)
    """
    for b in buckets:
        if b["count"] == 0:
            continue
        if b["low"] <= raw_confidence < b["high"]:
            return round(b["accuracy"] * 100, 1)

    # 落空时返回原始值
    return raw_confidence


def run_calibration(
    verdict_db: VerdictDB,
    symbol: Optional[str] = None,
) -> dict[str, CalibrationResult]:
    """对全部或指定品种运行校准

    Returns:
        {symbol: CalibrationResult}
    """
    results: dict[str, CalibrationResult] = {}
    now = datetime.now(timezone.utc).isoformat()

    symbols = [symbol] if symbol else verdict_db.list_symbols()

    for sym in symbols:
        records = verdict_db.query(symbol=sym, limit=5000)
        if not records:
            continue

        buckets = compute_calibration(records)
        total = sum(b["count"] for b in buckets)
        overall_acc = sum(b["accuracy"] * b["count"] for b in buckets) / total if total > 0 else 0.0
        ece = compute_calibration_error(buckets)

        results[sym] = {
            "timestamp": now,
            "symbol": sym,
            "buckets": buckets,
            "total_verdicts": total,
            "overall_accuracy": round(overall_acc, 4),
            "calibration_error": ece,
        }

    return results
