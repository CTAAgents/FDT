"""
参数调优器 — 置信度校准 + 止损/目标 ATR 乘数优化。

核心逻辑:
    1. 置信度校准: 对比 LLM 给出的置信度与实际准确率
       - 如果置信度系统性偏高 (conf=70% 但准确率只有 50%)
       - 则 confidence_offset 设为负值
    2. ATR 乘数优化: 基于历史情况下止损/目标是否被触发
       - 如果止损频繁被触发 → 增大 ATR 乘数
       - 如果目标从不达标 → 减小 ATR 乘数
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdt_eval.feedback.config_store import ConfigStore

logger = logging.getLogger(__name__)


@dataclass
class ParameterCalibration:
    """校准结果。"""
    symbol: str
    n_samples: int
    confidence_bias: float            # 正 = LLM 偏乐观, 负 = LLM 偏悲观
    confidence_offset: float          # 应用后的偏移
    old_stop_mult: float
    new_stop_mult: float
    old_target_mult: float
    new_target_mult: float
    changes_applied: bool


class ParameterTuner:
    """参数调优器。"""

    def __init__(self, config_store: ConfigStore | None = None):
        self.store = config_store or ConfigStore()

    def tune(
        self,
        followup_path: str | Path | None = None,
    ) -> list[ParameterCalibration]:
        """加载裁决回溯结果，校准参数。

        Args:
            followup_path: execution_followup.json 路径

        Returns:
            list[ParameterCalibration]
        """
        path = Path(followup_path or self._default_followup_path())
        if not path.exists():
            logger.warning(f"[PARAM_TUNER] followup 文件不存在: {path}")
            return []

        try:
            followup = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[PARAM_TUNER] 读取失败: {e}")
            return []

        rounds = followup if isinstance(followup, list) else followup.get("rounds", followup.get("round_results", []))
        if not rounds:
            return []

        # 按品种聚合验证结果
        by_symbol: dict[str, dict] = {}
        for r in rounds:
            results = r.get("results", [])
            for vr in results:
                sym = vr.get("symbol", "")
                if not sym:
                    continue
                if sym not in by_symbol:
                    by_symbol[sym] = {
                        "n": 0, "confidences": [], "corrects": [],
                        "hit_stop_count": 0, "hit_target_count": 0,
                    }
                d = by_symbol[sym]
                d["n"] += 1
                d["confidences"].append(vr.get("confidence", 0.5))
                d["corrects"].append(1 if vr.get("correct") else 0)
                if vr.get("hit_stop"):
                    d["hit_stop_count"] += 1
                if vr.get("hit_target1") or vr.get("hit_target2"):
                    d["hit_target_count"] += 1

        calibrations: list[ParameterCalibration] = []
        for symbol, data in by_symbol.items():
            cal = self._calibrate_symbol(symbol, data)
            if cal:
                calibrations.append(cal)

        if calibrations:
            self.store.save()
            logger.info(f"[PARAM_TUNER] 校准了 {len(calibrations)} 个品种的参数")

        return calibrations

    def _default_followup_path(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "memory" / "validations" / "execution_followup.json"

    def _calibrate_symbol(self, symbol: str, data: dict) -> ParameterCalibration | None:
        """校准单个品种的参数。"""
        n = data["n"]
        if n < self.store.global_config.min_samples_per_symbol:
            return None

        cfg = self.store.get(symbol)
        old_stop_mult = cfg.atr_stop_multiplier
        old_target_mult = cfg.atr_target_multiplier

        # 1. 置信度校准
        avg_conf = sum(data["confidences"]) / n
        accuracy = sum(data["corrects"]) / n
        bias = avg_conf - accuracy  # 正 = LLM 过度自信
        offset = -min(0.3, max(-0.3, bias))  # 反向修正

        # 2. ATR 止损乘数校准
        stop_hit_rate = data["hit_stop_count"] / n
        if stop_hit_rate > 0.4:
            # 止损被频繁触发 → 加大乘数
            new_stop_mult = min(4.0, old_stop_mult * 1.2)
        elif stop_hit_rate < 0.1 and n >= 5:
            # 止损几乎不触发 → 减小乘数 (提高资金效率)
            new_stop_mult = max(1.0, old_stop_mult * 0.9)
        else:
            new_stop_mult = old_stop_mult

        # 3. ATR 目标乘数校准
        target_hit_rate = data["hit_target_count"] / n
        if target_hit_rate > 0.5:
            # 目标太容易达到 → 加大乘数 (目标设得更远)
            new_target_mult = min(5.0, old_target_mult * 1.15)
        elif target_hit_rate < 0.2 and n >= 5:
            # 目标几乎达不到 → 减小乘数
            new_target_mult = max(1.5, old_target_mult * 0.9)
        else:
            new_target_mult = old_target_mult

        changes = (
            abs(offset - cfg.confidence_offset) > 0.01
            or abs(new_stop_mult - old_stop_mult) > 0.01
            or abs(new_target_mult - old_target_mult) > 0.01
        )

        if changes:
            self.store.update(
                symbol,
                confidence_offset=round(offset, 3),
                atr_stop_multiplier=round(new_stop_mult, 2),
                atr_target_multiplier=round(new_target_mult, 2),
                recent_accuracy=round(accuracy, 4),
                n_validations=n,
            )

        return ParameterCalibration(
            symbol=symbol,
            n_samples=n,
            confidence_bias=round(bias, 4),
            confidence_offset=round(offset, 3),
            old_stop_mult=old_stop_mult,
            new_stop_mult=new_stop_mult,
            old_target_mult=old_target_mult,
            new_target_mult=new_target_mult,
            changes_applied=changes,
        )
