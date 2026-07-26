"""因子归因引擎 — 将裁决结果拆解到因子层面（G23 §3.6）。

用法:
    engine = FactorAttributionEngine()
    report = engine.compute_attribution(verdict, factor_matrix)

    # Outer Loop 消费
    decay = engine.detect_factor_decay(historical_reports)
    if decay["momentum"] > 0.3:
        logger.warning("动量因子持续衰减")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .types import FactorAttributionReport, FactorContribution, FactorMatrixResult

logger = logging.getLogger(__name__)

_DECAY_LOOKBACK = 5  # 检测衰减的回看次数


class FactorAttributionEngine:
    """因子归因引擎 — G23 §3.6。

    核心公式：
      因子权重 = factor_ic × |factor_direction| × 有效性衰减系数
      置信度校准 = min(1.0, Σ|权重| × 分歧度倒数)
    """

    def compute_attribution(
        self,
        verdict: dict[str, Any],
        factor_matrix: FactorMatrixResult | None,
    ) -> FactorAttributionReport:
        """计算单品种的因子归因。

        Args:
            verdict: 裁决结果 dict，含 direction/confidence/grade。
            factor_matrix: 因子信号矩阵（可为 None）。

        Returns:
            FactorAttributionReport。
        """
        symbol = verdict.get("symbol", "?")
        verdict_dir = verdict.get("direction", 0)
        if verdict_dir == "BUY":
            verdict_dir = 2
        elif verdict_dir == "SELL":
            verdict_dir = -2
        elif verdict_dir == "NEUTRAL" or verdict_dir == "neutral":
            verdict_dir = 0
        verdict_dir = int(verdict_dir)
        verdict_conf = float(verdict.get("confidence", 0.5))

        if not factor_matrix or factor_matrix.data_grade == "NO_DATA":
            return FactorAttributionReport(
                symbol=symbol,
                verdict_direction=verdict_dir,
                verdict_confidence=verdict_conf,
                contributions=[],
                calibrated_confidence=verdict_conf,
                divergence_penalty=1.0,
                top_factors=[],
                data_grade="NO_DATA",
            )

        sym_signals = factor_matrix.matrix.get(symbol, {})
        if not sym_signals:
            return FactorAttributionReport(
                symbol=symbol,
                verdict_direction=verdict_dir,
                verdict_confidence=verdict_conf,
                contributions=[],
                calibrated_confidence=verdict_conf * 0.8,
                divergence_penalty=0.8,
                top_factors=[],
                data_grade="NO_DATA",
            )

        # 因子 IC
        ic = factor_matrix.factor_ic or {}

        contributions: list[FactorContribution] = []
        total_weight = 0.0
        total_contrib = 0.0

        for fname, fs in sym_signals.items():
            ic_val = ic.get(fname, 0.0)
            # 有效性衰减系数：IC 为正时有效，为负时反向
            decay = max(0.1, abs(ic_val)) if ic_val != 0 else 0.5
            weight = abs(fs.direction) * decay
            # 贡献度 = 因子方向 × 权重（与裁决方向同向为正）
            contrib = fs.direction * weight if verdict_dir == 0 or fs.direction * verdict_dir >= 0 else -weight

            contributions.append(FactorContribution(
                factor_name=fname,
                weight=round(weight, 3),
                direction=fs.direction,
                contribution=round(contrib, 3),
                ic_value=round(ic_val, 3),
            ))
            total_weight += weight
            total_contrib += contrib

        # 分歧惩罚：因子方向不一致程度
        directions = [c.direction for c in contributions]
        if directions:
            n = len(directions)
            mean_dir = sum(directions) / n
            std = np.std(directions)
            max_std = 2.0
            divergence_penalty = max(0.1, 1.0 - std / max_std)
        else:
            divergence_penalty = 1.0

        # 校准置信度
        calibrated = min(1.0, (total_weight / max(len(contributions), 1)) * (1 / max(divergence_penalty, 0.1)))
        calibrated = round(calibrated, 3)

        # 贡献最大的因子
        sorted_contribs = sorted(contributions, key=lambda c: abs(c.contribution), reverse=True)
        top_factors = [c.factor_name for c in sorted_contribs[:3]]

        return FactorAttributionReport(
            symbol=symbol,
            verdict_direction=verdict_dir,
            verdict_confidence=verdict_conf,
            contributions=contributions,
            calibrated_confidence=min(calibrated, 1.0),
            divergence_penalty=round(divergence_penalty, 3),
            top_factors=top_factors,
            data_grade="PRIMARY",
        )

    def detect_factor_decay(
        self,
        historical_reports: list[FactorAttributionReport],
    ) -> dict[str, float]:
        """检测因子衰减。

        对每个因子检查最近 N 次归因报告：
          - 权重持续下降（负斜率）→ 衰减
          - 方向频繁反转 → 衰减

        Args:
            historical_reports: 历史归因报告列表（从旧到新）。

        Returns:
            {factor_name: decay_score}，0~1，越高越需关注。
        """
        if len(historical_reports) < 3:
            return {}

        # 收集各因子的历史权重序列
        factor_weights: dict[str, list[float]] = {}
        factor_dirs: dict[str, list[int]] = {}

        for report in historical_reports[-_DECAY_LOOKBACK:]:
            for contrib in report.contributions:
                if contrib.factor_name not in factor_weights:
                    factor_weights[contrib.factor_name] = []
                    factor_dirs[contrib.factor_name] = []
                factor_weights[contrib.factor_name].append(contrib.weight)
                factor_dirs[contrib.factor_name].append(contrib.direction)

        decay_scores: dict[str, float] = {}
        for fname, weights in factor_weights.items():
            if len(weights) < 3:
                decay_scores[fname] = 0.0
                continue

            # 权重趋势衰减
            x = np.arange(len(weights))
            slope = np.polyfit(x, weights, 1)[0] if len(weights) >= 2 else 0.0
            # 负斜率 = 下降 → 衰减
            trend_decay = max(0, -slope * 2)

            # 方向反转
            dirs = factor_dirs.get(fname, [])
            reversals = sum(1 for i in range(1, len(dirs)) if dirs[i] * dirs[i - 1] < 0)
            reversal_decay = reversals / max(len(dirs) - 1, 1)

            decay_scores[fname] = round(min(trend_decay + reversal_decay, 1.0), 3)

        return decay_scores
