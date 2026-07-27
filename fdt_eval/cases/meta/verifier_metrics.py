"""
验证器质量度量 (Meta-Eval) — 从 EvalStore 读取历史结果，计算每个验证器的漏放率/误杀率。

当 false_pass_rate > 1% 时触发 trigger_retrain 动作。

对应 ARCHITECTURE.md §8.2:
  - false_pass_rate:  漏放率 — PASS 结果中本应为 FAIL 的比例
  - false_block_rate: 误杀率 — FAIL 结果中本应为 PASS 的比例
  - true_positive_rate:  真阳性率 (sensitivity)
  - true_negative_rate:  真阴性率 (specificity)
"""

from __future__ import annotations

import time
from typing import Any

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction, EvalStage
from fdt_eval.core.registry import eval_registry
from fdt_eval.core.store import EvalStore

# 无 ground truth 标签时的启发式阈值:
#   如果 PASS 结果的 score 低于此值，视为"可疑通过"（可能漏放）
_SUSPICIOUS_PASS_SCORE = 0.5
#   如果 FAIL 结果的 score 高于此值，视为"可疑误杀"（可能误杀）
_SUSPICIOUS_FAIL_SCORE = 0.9


@eval_registry.register
class VerifierMetricsEval(EvalCase):
    """计算各验证器的质量指标（漏放率/误杀率/TPR/TNR）。

    从 EvalStore (SQLite) 读取最近 N 条 eval_results，对每个 registered verifier
    计算质量指标。若任何验证器的 false_pass_rate > 1%，结果置 FAIL 并触发 trigger_retrain。
    """

    case_id = "meta.verifier_metrics"
    stage: EvalStage = "meta"
    description = "验证器质量度量：计算各验证器的 false_pass_rate / false_block_rate / TPR / TNR"
    weight = 0.0   # 元评估不计入总体评分
    threshold = 0.95
    action = EvalAction(severity="block", on_fail="trigger_retrain")
    data_cost = "low"

    # 每次分析的最近结果数
    _RECENT_N = 200

    def run(self, context: EvalContext) -> EvalResult:
        start = time.time()
        trace_id = context.trace_id
        store = EvalStore()

        # ── 收集所有非 meta 的验证器 ──
        verifier_ids = [
            cid for cid in eval_registry.all_case_ids
            if eval_registry.get(cid).stage != "meta"
        ]

        per_verifier: dict[str, dict[str, Any]] = {}
        any_suspicious = False
        highest_fpr = 0.0
        highest_fpr_case = ""

        for case_id in sorted(verifier_ids):
            rows = store.trend(case_id, last=self._RECENT_N)
            if not rows:
                continue

            total = len(rows)
            passes = [r for r in rows if r["status"] == "PASS"]
            fails = [r for r in rows if r["status"] == "FAIL"]

            n_pass = len(passes)
            n_fail = len(fails)

            # 启发式: 低分的 PASS (score < threshold) → 可疑漏放
            suspicious_passes = sum(
                1 for r in passes if r["score"] < _SUSPICIOUS_PASS_SCORE
            )
            # 启发式: 高分的 FAIL (score >= threshold) → 可疑误杀
            suspicious_fails = sum(
                1 for r in fails if r["score"] >= _SUSPICIOUS_FAIL_SCORE
            )

            false_pass_rate = suspicious_passes / n_pass if n_pass > 0 else 0.0
            false_block_rate = suspicious_fails / n_fail if n_fail > 0 else 0.0

            # TPR = 正确发现的失败 / 所有实际失败 (启发式)
            true_fails = n_fail - suspicious_fails
            true_positive_rate = true_fails / n_fail if n_fail > 0 else 1.0

            # TNR = 正确通过的许可 / 所有实际通过 (启发式)
            true_passes = n_pass - suspicious_passes
            true_negative_rate = true_passes / n_pass if n_pass > 0 else 1.0

            per_verifier[case_id] = {
                "total": total,
                "n_pass": n_pass,
                "n_fail": n_fail,
                "false_pass_rate": round(false_pass_rate, 4),
                "false_block_rate": round(false_block_rate, 4),
                "true_positive_rate": round(true_positive_rate, 4),
                "true_negative_rate": round(true_negative_rate, 4),
                "suspicious_passes": suspicious_passes,
                "suspicious_fails": suspicious_fails,
            }

            if false_pass_rate > 0.01:
                any_suspicious = True
                if false_pass_rate > highest_fpr:
                    highest_fpr = false_pass_rate
                    highest_fpr_case = case_id

        # ── 构建 metrics ──
        metrics: list[EvalMetric] = [
            EvalMetric(name="verifiers_analyzed", value=float(len(per_verifier))),
        ]
        for case_id, v in sorted(per_verifier.items()):
            metrics.append(
                EvalMetric(
                    name=f"{case_id}.false_pass_rate",
                    value=v["false_pass_rate"],
                    threshold=0.01,
                    unit="%",
                )
            )
            metrics.append(
                EvalMetric(
                    name=f"{case_id}.false_block_rate",
                    value=v["false_block_rate"],
                    unit="%",
                )
            )

        # ── 判定 ──
        duration = (time.time() - start) * 1000

        if any_suspicious:
            status = "FAIL"
            score = max(0.0, 1.0 - highest_fpr)
            detail = (
                f"发现 {sum(1 for v in per_verifier.values() if v['false_pass_rate'] > 0.01)} 个验证器漏放率超标; "
                f"最高: {highest_fpr_case} ({highest_fpr:.2%})"
            )
        else:
            status = "PASS"
            score = 1.0
            detail = f"全部 {len(per_verifier)} 个验证器 false_pass_rate ≤ 1%"

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=score,
            metrics=metrics,
            detail=detail,
            raw={"per_verifier": per_verifier},
            action=self.action if any_suspicious else None,
            duration_ms=round(duration, 1),
        )
