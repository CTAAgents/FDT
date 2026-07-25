"""T3 验证：连续偏差跟踪 + 策略一致性指标

Phase E — 验证增强
在每个辩论轮次后自动运行，追踪裁决偏差和策略一致性。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class BiasTracker:
    """连续偏差跟踪器 — T3 验证层

    功能:
    1. 每轮裁决后自动配对实际走势
    2. 计算滚动偏差率
    3. 计算策略一致性指标
    """

    def __init__(self, memory_dir: Path):
        self._bias_dir = memory_dir / "tracking" / "bias"
        self._bias_dir.mkdir(parents=True, exist_ok=True)

    def record_bias(
        self,
        symbol: str,
        predicted_direction: str,
        actual_direction: str,
        confidence: float,
        regime: Optional[str] = None,
    ) -> dict:
        """记录一轮裁决的偏差

        Args:
            symbol: 品种
            predicted_direction: bull/bear/neutral
            actual_direction: bull/bear/neutral（事后确认）
            confidence: 裁决置信度 (0-1)
            regime: 区制（可选）

        Returns:
            偏差记录
        """
        is_correct = predicted_direction == actual_direction

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol.upper(),
            "predicted": predicted_direction,
            "actual": actual_direction,
            "correct": is_correct,
            "confidence": round(confidence, 4),
            "regime": regime or "unknown",
        }

        # 追加到品种文件
        sym_file = self._bias_dir / f"{symbol.upper()}.json"
        history = []
        if sym_file.exists():
            try:
                with open(sym_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                history = []

        history.append(record)
        # 保留最近 500 条
        history = history[-500:]
        with open(sym_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return record

    def get_rolling_accuracy(self, symbol: str, window: int = 20) -> dict:
        """计算滚动准确率

        Args:
            symbol: 品种
            window: 滚动窗口大小

        Returns:
            {
                "symbol": str,
                "total": int,
                "correct": int,
                "accuracy": float,
                "rolling_accuracy: float (近 window 轮),
                "confidence_gap": float (置信度与准确率之差),
            }
        """
        sym_file = self._bias_dir / f"{symbol.upper()}.json"
        if not sym_file.exists():
            return {"symbol": symbol, "total": 0, "correct": 0,
                    "accuracy": 0.0, "rolling_accuracy": 0.0, "confidence_gap": 0.0}

        with open(sym_file, "r", encoding="utf-8") as f:
            history = json.load(f)

        total = len(history)
        correct = sum(1 for r in history if r.get("correct"))
        accuracy = correct / total if total > 0 else 0.0

        # 滚动准确率
        recent = history[-window:]
        recent_correct = sum(1 for r in recent if r.get("correct"))
        rolling_accuracy = recent_correct / len(recent) if recent else 0.0

        # 置信度偏差（置信度 - 实际准确率）
        avg_confidence = sum(r.get("confidence", 0) for r in recent) / len(recent) if recent else 0.0
        confidence_gap = avg_confidence - rolling_accuracy

        return {
            "symbol": symbol.upper(),
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "rolling_accuracy": round(rolling_accuracy, 4),
            "confidence_gap": round(confidence_gap, 4),
        }

    def get_consistency(self, symbol: str) -> dict:
        """计算策略一致性指标

        检查同一品种在不同波动率区间下的裁决一致性。

        Returns:
            {
                "symbol": str,
                "regime_breakdown": {regime: {total, correct, accuracy}},
                "direction_swing_rate": float (方向变动频率),
            }
        """
        sym_file = self._bias_dir / f"{symbol.upper()}.json"
        if not sym_file.exists():
            return {"symbol": symbol, "regime_breakdown": {}, "direction_swing_rate": 0.0}

        with open(sym_file, "r", encoding="utf-8") as f:
            history = json.load(f)

        if len(history) < 3:
            return {"symbol": symbol, "regime_breakdown": {}, "direction_swing_rate": 0.0}

        # 按区制分解
        regime_stats: dict[str, dict] = {}
        for r in history:
            regime = r.get("regime", "unknown")
            if regime not in regime_stats:
                regime_stats[regime] = {"total": 0, "correct": 0}
            regime_stats[regime]["total"] += 1
            if r.get("correct"):
                regime_stats[regime]["correct"] += 1

        regime_breakdown = {}
        for regime, stats in regime_stats.items():
            regime_breakdown[regime] = {
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy": round(stats["correct"] / stats["total"], 4) if stats["total"] > 0 else 0.0,
            }

        # 方向变动率（方向从 bull→bear 或 bear→bull 的频率）
        direction_swings = 0
        directions = [r.get("predicted", "") for r in history if r.get("predicted") in ("bull", "bear")]
        for i in range(1, len(directions)):
            if directions[i] != directions[i-1]:
                direction_swings += 1
        direction_swing_rate = direction_swings / max(len(directions) - 1, 1)

        return {
            "symbol": symbol.upper(),
            "regime_breakdown": regime_breakdown,
            "direction_swing_rate": round(direction_swing_rate, 4),
        }


def run_bias_check(symbol: str, memory_dir: Path) -> dict:
    """一次性偏差检查（供 evolution_graph 调用）"""
    tracker = BiasTracker(memory_dir)
    acc = tracker.get_rolling_accuracy(symbol)
    consistency = tracker.get_consistency(symbol)
    return {
        "accuracy": acc,
        "consistency": consistency,
        "t3_ready": acc.get("total", 0) >= 10,
    }
