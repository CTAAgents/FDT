"""
RHI Pairwise 评估用例 — 包装 rhi_pairwise_eval.evaluate_pairwise()。

两轮辩论产出的四维对比评估 (G21 §3.4):
  - 质检通过率 (0.35)
  - 风控通过率 (0.25)
  - 信号质量   (0.25)
  - 报告完整性 (0.15)

preference → score 映射:
  improve = 1.0
  tie     = 0.7
  regress = 0.3

对应 ARCHITECTURE.md Phase 3 (3.3): rhi_pairwise → cases/evolution/rhi_pairwise.py
"""

from __future__ import annotations

import time
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction, EvalStage
from fdt_eval.core.registry import eval_registry
from scripts.harness.rhi_pairwise_eval import evaluate_pairwise

# preference → score 映射
_PREFERENCE_SCORE = {
    "improve": 1.0,
    "tie": 0.7,
    "regress": 0.3,
}


@eval_registry.register
class RHIPairwiseEval(EvalCase):
    """RHI Pairwise 评估 — 调用 rhi_pairwise_eval.evaluate_pairwise() 进行四维对比。

    EvalContext.overrides 需要包含:
        current_output (str):  本轮 (Hⁱ) 的产出文件路径
        previous_output (str): 上轮 (Hⁱ⁻¹) 的产出文件路径
    """

    case_id = "evolution.rhi_pairwise"
    stage: EvalStage = "evolution"
    description = "RHI两轮产出四维对比评估：质检/风控/信号/报告完整性"
    weight = 0.15
    threshold = 0.70
    action = EvalAction(severity="warn", on_fail="notify")
    data_cost = "medium"

    def run(self, context: EvalContext) -> EvalResult:
        start = time.time()
        trace_id = context.trace_id
        overrides = context.overrides or {}

        current_output: str | None = overrides.get("current_output")
        previous_output: str | None = overrides.get("previous_output")

        # ── 参数校验 ──
        if not current_output or not previous_output:
            missing = []
            if not current_output:
                missing.append("current_output")
            if not previous_output:
                missing.append("previous_output")
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"缺少必需参数: {', '.join(missing)}; "
                       f"EvalContext.overrides 必须包含 current_output 和 previous_output",
                action=self.action,
            )

        cur_path = Path(current_output)
        prev_path = Path(previous_output)

        if not cur_path.exists():
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"当前产出文件不存在: {current_output}",
                action=self.action,
            )
        if not prev_path.exists():
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"上轮产出文件不存在: {previous_output}",
                action=self.action,
            )

        # ── 执行 pairwise 评估 ──
        try:
            preference = evaluate_pairwise(
                output_path_current=current_output,
                output_path_previous=previous_output,
                iteration=0,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"evaluate_pairwise 执行异常: {e}",
                action=self.action,
                duration_ms=round(duration, 1),
            )

        # ── 映射 preference → score ──
        pref = preference.get("preference", "tie")
        score = _PREFERENCE_SCORE.get(pref, 0.5)

        # ── 构建指标 ──
        score_breakdown = preference.get("score_breakdown", {})
        metrics: list[EvalMetric] = [
            EvalMetric(name="preference_score", value=score, threshold=self.threshold),
            EvalMetric(name="score_current", value=preference.get("score_current", 0.0)),
            EvalMetric(name="score_previous", value=preference.get("score_previous", 0.0)),
        ]
        for dim_name, dim_val in score_breakdown.get("current", {}).items():
            metrics.append(
                EvalMetric(name=f"dim_current.{dim_name}", value=dim_val)
            )

        duration = (time.time() - start) * 1000

        detail = (
            f"preference={pref} (score={score:.2f}); "
            f"cur={preference.get('score_current', 0):.3f} "
            f"prev={preference.get('score_previous', 0):.3f}; "
            f"{preference.get('rationale', '')}"
        )

        status = "PASS" if score >= self.threshold else "FAIL"

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=round(score, 4),
            metrics=metrics,
            detail=detail[:500],  # 截断过长的 detail
            raw=preference,
            action=self.action,
            duration_ms=round(duration, 1),
        )
