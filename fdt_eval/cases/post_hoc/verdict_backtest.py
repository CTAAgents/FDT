"""
裁决回测验证用例 — 包装 validate_verdicts.py 为 EvalCase。

用后续 30 根 K 线回测历史裁决的方向正确性、目标价达标率、止损率。
输出: execution_followup.json (更新) + validation_stats.json + feedback_entries.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalContext, EvalResult, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry


@eval_registry.register
class VerdictBacktestEval(EvalCase):
    """用后续行情回测验证历史裁决的准确性。"""

    case_id = "post_hoc.verdict_backtest"
    stage = "post_hoc"
    description = "30根K线回测裁决方向正确性、目标价达标率"
    weight = 0.25
    threshold = 0.80
    action = EvalAction(severity="warn", on_fail="log_gap")
    cache_ttl = 3600
    data_cost = "high"
    depends_on = ["debate_output_*.json"]

    def run(self, context: EvalContext) -> EvalResult:
        workspace = Path(context.workspace or os.getcwd())
        script = workspace / "scripts" / "verification" / "validate_verdicts.py"
        followup = workspace / "memory" / "execution_followup.json"

        if not script.exists():
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="ERROR", score=0.0, metrics=[],
                detail=f"脚本不存在: {script}",
                action=self.action,
            )
        if not followup.exists():
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="SKIP", score=0.0, metrics=[],
                detail="execution_followup.json 不存在，无可回测记录",
                action=self.action,
            )

        # 执行验证脚本（数据密集型操作，最多等 600s）
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(script), "--force",
                 "--followup", str(followup)],
                cwd=str(workspace),
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="ERROR", score=0.0, metrics=[],
                detail="回测脚本执行超时(>600s)",
                action=self.action,
            )
        elapsed = (time.time() - t0) * 1000

        if proc.returncode != 0:
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="ERROR", score=0.0, metrics=[],
                detail=f"回测脚本异常退出({proc.returncode}): {proc.stderr[:200]}",
                action=self.action,
                duration_ms=elapsed,
            )

        # 从 execution_followup.json 读取已验证记录并聚合指标
        try:
            with open(followup, encoding="utf-8") as f:
                followup_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="ERROR", score=0.0, metrics=[],
                detail=f"无法解析回测结果: {e}",
                action=self.action,
                duration_ms=elapsed,
            )

        records = followup_data.get("records", [])
        validated = [r for r in records if r.get("validated")
                     and r.get("validation_results")]
        if not validated:
            return EvalResult(
                case_id=self.case_id, trace_id=context.trace_id,
                stage=self.stage, status="SKIP", score=0.0, metrics=[],
                detail="无已验证记录",
                action=self.action,
                duration_ms=elapsed,
            )

        # ── 加权聚合 ──
        total_v = 0
        correct_v = 0
        profit_v = 0
        loss_v = 0
        target_hit_v = 0
        stop_hit_v = 0
        pnl_weighted = 0.0

        for r in validated:
            vr = r["validation_results"]
            n = vr["total"]
            total_v += n
            correct_v += vr["correct"]
            profit_v += vr.get("profit_count", 0)
            loss_v += vr.get("loss_count", 0)
            target_hit_v += vr.get("target_hit_count", 0)
            stop_hit_v += vr.get("stop_hit_count", 0)
            pnl_weighted += vr.get("avg_pnl_pct", 0) * n

        denom = max(total_v, 1)
        accuracy = round(correct_v / denom, 4)
        win_rate = round(profit_v / max(profit_v + loss_v, 1), 4)
        profit_ratio = round(pnl_weighted / denom, 4)
        target_hit_rate = round(target_hit_v / denom, 4)
        stop_rate = round(stop_hit_v / denom, 4)

        # 综合得分 = 40% 方向准确率 + 30% 胜率 + 30% 目标达标率
        score = round(accuracy * 0.4 + win_rate * 0.3 + target_hit_rate * 0.3, 4)
        status = "PASS" if score >= self.threshold else "FAIL"

        return EvalResult(
            case_id=self.case_id,
            trace_id=context.trace_id,
            stage=self.stage,
            status=status,
            score=score,
            metrics=[
                EvalMetric(name="accuracy", value=accuracy),
                EvalMetric(name="win_rate", value=win_rate),
                EvalMetric(name="profit_ratio", value=profit_ratio),
                EvalMetric(name="target_hit_rate", value=target_hit_rate),
                EvalMetric(name="stop_rate", value=stop_rate),
            ],
            detail=(
                f"准确率{accuracy*100:.1f}% "
                f"胜率{win_rate*100:.1f}% "
                f"目标达标{target_hit_rate*100:.1f}% "
                f"止损率{stop_rate*100:.1f}% "
                f"(n={total_v})"
            ),
            action=self.action,
            duration_ms=elapsed,
        )
