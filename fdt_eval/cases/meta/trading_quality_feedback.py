"""
交易质量反馈 EvalCase — 跑完 verdict_backtest 后，自动触发参数调整。

这是 Eval 系统从"只报不修"变成"自动改进"的关键节点:
  verdict_backtest (测量)
      → position_tuner (仓位调整)
      → parameter_tuner (置信度+止损/目标校准)
      → config_store 持久化
      → signal_output 消费
"""
from __future__ import annotations

import logging

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry
from fdt_eval.feedback.position_tuner import PositionTuner
from fdt_eval.feedback.parameter_tuner import ParameterTuner
from fdt_eval.feedback.config_store import ConfigStore

logger = logging.getLogger(__name__)


@eval_registry.register
class TradingQualityFeedbackEval(EvalCase):
    """交易质量反馈闭环 — 测量 → 调整 → 持久化。"""

    case_id = "meta.trading_quality_feedback"
    stage = "meta"
    description = "读取裁决回溯统计 → 自动调整仓位/止损/目标参数"
    weight = 0.0        # 元评估，不计入聚合
    threshold = 0.0     # 不阻断（即使调整未执行也不报错）
    action = None       # 不触发闭环动作（自身就是闭环）

    def run(self, context: EvalContext) -> EvalResult:
        """执行反馈闭环。

        从 context.overrides 加载:
            stats_path: validation_stats.json 路径
            followup_path: execution_followup.json 路径
            未指定则使用默认路径。
        """
        store = ConfigStore()
        if not store.global_config.enabled:
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="SKIP", score=0.0,
                metrics=[], detail="反馈闭环已禁用 (global.enabled=False)",
            )

        stats_path = context.overrides.get("stats_path")
        followup_path = context.overrides.get("followup_path")

        parts: list[str] = []
        total_adjustments = 0
        total_calibrations = 0
        changes = 0

        # 1. 仓位调整
        pos_tuner = PositionTuner(store)
        adjustments = pos_tuner.tune(stats_path=stats_path)
        total_adjustments = len(adjustments)
        changes += sum(1 for a in adjustments if a.direction != "unchanged")
        if adjustments:
            directions = {a.direction for a in adjustments}
            parts.append(f"仓位: {len(adjustments)}品种 ({', '.join(sorted(directions))})")

        # 2. 参数校准
        param_tuner = ParameterTuner(store)
        calibrations = param_tuner.tune(followup_path=followup_path)
        total_calibrations = len(calibrations)
        changes += sum(1 for c in calibrations if c.changes_applied)
        if calibrations:
            n_changed = sum(1 for c in calibrations if c.changes_applied)
            parts.append(f"参数: {n_changed}/{len(calibrations)}品种有变更")

        # 3. 构造结果
        detail = "; ".join(parts) if parts else "无变更（数据不足或已最优）"
        score = min(1.0, changes / max(total_adjustments + total_calibrations, 1))

        metrics = [
            EvalMetric(name="adjusted_symbols", value=float(total_adjustments), unit="symbols"),
            EvalMetric(name="calibrated_symbols", value=float(total_calibrations), unit="symbols"),
            EvalMetric(name="changes_applied", value=float(changes), unit="changes"),
        ]

        status = "PASS" if changes > 0 else ("SKIP" if (total_adjustments + total_calibrations) == 0 else "PASS")

        # 记日志
        logger.info(
            f"[FEEDBACK] {detail} | "
            f"adjustments={total_adjustments} calibrations={total_calibrations} changes={changes}"
        )

        return EvalResult(
            case_id=self.case_id, trace_id=context.trace_id,
            stage=self.stage, status=status, score=round(score, 4),
            metrics=metrics, detail=detail,
        )
