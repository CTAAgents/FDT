"""
仓位调优器 — 根据历史裁决验证结果，调整每品种的仓位权重。

核心逻辑:
    - 读取 validation_stats.json (由 validate_verdicts.py 产出)
    - 按品种分组计算准确率
    - 准确率 < 40% → 仓位权重减半 (0.5)
    - 准确率 < 25% → 仓位权重降至最低 (0.3)
    - 准确率 > 70% → 仓位权重提升至 1.5
    - 准确率 > 85% → 仓位权重提升至 2.0
    - 样本不足 (< 3 条) → 不动 (保持 1.0)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdt_eval.feedback.config_store import ConfigStore, SymbolConfig

logger = logging.getLogger(__name__)

# 默认验证统计路径
DEFAULT_STATS_PATH = Path(__file__).resolve().parent.parent.parent / "memory" / "validations" / "validation_stats.json"


@dataclass
class PositionAdjustment:
    """单品仓位调整建议。"""
    symbol: str
    accuracy: float              # 准确率
    n_samples: int               # 样本数
    old_weight: float            # 调整前权重
    new_weight: float            # 调整后权重
    old_base_pct: float          # 调整前基础仓位
    new_base_pct: float          # 调整后基础仓位
    direction: str               # "up" / "down" / "unchanged"


class PositionTuner:
    """仓位调优器。"""

    def __init__(self, config_store: ConfigStore | None = None):
        self.store = config_store or ConfigStore()

    def tune(
        self,
        stats_path: str | Path | None = None,
    ) -> list[PositionAdjustment]:
        """读取验证统计，计算每品种的权重调整。

        Args:
            stats_path: validation_stats.json 路径

        Returns:
            list[PositionAdjustment]
        """
        path = Path(stats_path or DEFAULT_STATS_PATH)
        if not path.exists():
            logger.warning(f"[POSITION_TUNER] 验证统计文件不存在: {path}")
            return []

        try:
            stats = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[POSITION_TUNER] 读取失败: {e}")
            return []

        by_symbol = stats.get("by_symbol", stats.get("symbols", {}))
        if not by_symbol:
            # 尝试从 round_results 中提取
            rounds = stats.get("rounds", stats.get("round_results", []))
            by_symbol = self._aggregate_by_symbol(rounds)

        adjustments: list[PositionAdjustment] = []
        for symbol, data in by_symbol.items():
            adj = self._adjust_symbol(symbol, data)
            if adj:
                adjustments.append(adj)

        if adjustments:
            logger.info(f"[POSITION_TUNER] 调整了 {len(adjustments)} 个品种的仓位参数")
            self.store.save()

        return adjustments

    def _aggregate_by_symbol(self, rounds: list[dict]) -> dict[str, dict]:
        """如果 stats 是按轮次组织的，聚合成按品种。"""
        by_sym: dict[str, dict] = {}
        for r in rounds:
            sym = r.get("symbol", "")
            if not sym:
                continue
            if sym not in by_sym:
                by_sym[sym] = {"total": 0, "correct": 0, "wrong": 0}
            by_sym[sym]["total"] += r.get("total", len(r.get("results", [])))
            by_sym[sym]["correct"] += r.get("correct", 0)
            by_sym[sym]["wrong"] += r.get("wrong", 0)
        return by_sym

    def _adjust_symbol(self, symbol: str, data: dict) -> PositionAdjustment | None:
        """计算单个品种的仓位调整。"""
        total = data.get("total", 0)
        correct = data.get("correct", 0)
        wrong = data.get("wrong", 0)
        valid = correct + wrong

        if valid < self.store.global_config.min_samples_per_symbol:
            return None  # 样本不足，不动

        accuracy = correct / valid if valid > 0 else 0.0
        cfg = self.store.get(symbol)
        old_weight = cfg.position_weight
        old_base_pct = cfg.position_base_pct

        # 权重计算
        if accuracy < 0.25:
            new_weight = 0.3
        elif accuracy < 0.40:
            new_weight = 0.5
        elif accuracy > 0.85:
            new_weight = 2.0
        elif accuracy > 0.70:
            new_weight = 1.5
        else:
            new_weight = 1.0

        # 基础仓位调整: 低准确率减仓
        if accuracy < 0.40:
            new_base_pct = max(1.0, old_base_pct * 0.7)
        elif accuracy > 0.70:
            new_base_pct = min(10.0, old_base_pct * 1.2)
        else:
            new_base_pct = old_base_pct

        # 约束
        new_weight = max(
            self.store.global_config.weight_min,
            min(self.store.global_config.weight_max, new_weight),
        )
        new_base_pct = max(
            self.store.global_config.position_min_pct,
            min(self.store.global_config.position_max_pct, new_base_pct),
        )

        # 记录
        direction = "up" if new_weight > old_weight else ("down" if new_weight < old_weight else "unchanged")

        self.store.update(
            symbol,
            position_weight=round(new_weight, 3),
            position_base_pct=round(new_base_pct, 1),
            recent_accuracy=round(accuracy, 4),
            n_validations=total,
        )

        return PositionAdjustment(
            symbol=symbol,
            accuracy=round(accuracy, 4),
            n_samples=total,
            old_weight=old_weight,
            new_weight=new_weight,
            old_base_pct=old_base_pct,
            new_base_pct=new_base_pct,
            direction=direction,
        )
