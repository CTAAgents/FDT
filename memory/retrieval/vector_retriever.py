"""VectorMemory 封装 — 修复检索断层 + 历史准确率查询"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VectorRetriever:
    """封装 VectorMemory 的历史相似案例检索 + 裁决准确率查询"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
        self._vector_memory = None
        self._initialized = False
        # VerdictDB 延迟初始化以避免循环导入
        self._verdict_db = None

    # ── 内部：延迟初始化 VerdictDB ─────────────────────

    def _get_verdict_db(self):
        if self._verdict_db is None:
            from ..verdict.verdict_db import VerdictDB
            self._verdict_db = VerdictDB(self._memory_dir)
        return self._verdict_db

    # ── 原有接口 ────────────────────────────────────

    def query(self, symbol: str, top_k: int = 3,
              regime: str | None = None) -> list[dict]:
        """基于 VectorMemory 查询历史相似案例"""
        vm = self._get_vector_memory()
        if vm is None:
            return []
        try:
            return vm.query(symbol, regime=regime, top_k=top_k)
        except Exception as e:
            logger.debug(f"VectorMemory query failed (non-fatal): {e}")
            return []

    # ── Phase A: 裁决准确率查询 ──────────────────────

    def query_accuracy(
        self,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> dict:
        """查询历史裁决准确率

        Args:
            symbol: 品种代码，None 时返回全局统计
            direction: 方向过滤

        Returns:
            {
                "symbol": str | None,
                "total_verdicts": int,
                "with_outcome": int,
                "correct": int,
                "accuracy": float,
                "direction": str | None,
                "calibration": CalibrationResult | None,
            }
        """
        vdb = self._get_verdict_db()
        records = vdb.query(
            symbol=symbol,
            direction=direction,
            limit=5000,
        )

        with_outcome = [r for r in records if r.get("outcome_actual") in ("correct", "wrong")]
        correct = sum(1 for r in with_outcome if r.get("outcome_actual") == "correct")

        result = {
            "symbol": symbol.upper() if symbol else None,
            "total_verdicts": len(records),
            "with_outcome": len(with_outcome),
            "correct": correct,
            "accuracy": round(correct / len(with_outcome), 4) if with_outcome else 0.0,
            "direction": direction,
        }

        # 标注校准就绪状态
        if len(records) >= 10:
            from ..verdict.calibrate import run_calibration
            calib = run_calibration(vdb, symbol=symbol)
            target_sym = symbol.upper() if symbol else None
            if target_sym and target_sym in calib:
                result["calibration"] = calib[target_sym]
            elif not symbol and calib:
                # 全局校准 = 全部品种的合并
                result["calibration_ready"] = True

        return result

    def query_accuracy_by_confidence(
        self,
        symbol: Optional[str] = None,
    ) -> dict:
        """按置信度区间查询准确率分布（校准曲线）"""
        from ..verdict.calibrate import run_calibration

        vdb = self._get_verdict_db()
        calib = run_calibration(vdb, symbol=symbol)
        target_sym = symbol.upper() if symbol else None

        if target_sym and target_sym in calib:
            return calib[target_sym]
        elif not symbol and calib:
            # 返回第一个品种或合并结果
            first = next(iter(calib.values()))
            return first

        return {
            "timestamp": "",
            "symbol": symbol or "",
            "buckets": [],
            "total_verdicts": 0,
            "overall_accuracy": 0.0,
            "calibration_error": 0.0,
        }

    def store_verdict(self, record: dict) -> str:
        """存储一条裁决记录到 VerdictDB"""
        return self._get_verdict_db().store(record)

    # ── 内部方法 ────────────────────────────────────

    def _get_vector_memory(self):
        """懒初始化 VectorMemory"""
        if self._initialized:
            return self._vector_memory
        self._initialized = True
        try:
            from scripts.vector_memory import VectorMemory
            self._vector_memory = VectorMemory()
        except Exception as e:
            logger.debug(f"VectorMemory init failed (non-fatal): {e}")
            self._vector_memory = None
        return self._vector_memory
