"""
Runtime LLM 输出质量校验 — EvalCase 包装。

直接导入 validate_llm_output.py 的纯函数，避免子进程开销。
使用 _shared/confidence_validator.py 的 validate_confidence_type 替代 inline 置信度校验逻辑。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fdt_eval.core.base import EvalCase, EvalContext, EvalResult, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry
from fdt_eval.cases._shared.confidence_validator import validate_confidence_type

# 直接导入原脚本的纯函数
from scripts.verification.validate_llm_output import (
    load_scan_results,
    load_verdicts,
    batch_validate,
    validate_price_deviation,
    validate_score_range,
    PRICE_DEVIATION_THRESHOLD,
)


@eval_registry.register
class LLMValidationEval(EvalCase):
    """LLM 输出质量校验 — 检测价格偏差、置信度和评分范围异常。"""

    case_id = "runtime.llm_validation"
    stage = "runtime"
    description = "LLM 输出质量校验 — 价格偏差/置信度/评分范围"
    weight = 0.20
    threshold = 0.90
    action = EvalAction(severity="block", on_fail="notify")
    data_cost = "low"

    def run(self, context: EvalContext) -> EvalResult:
        overrides = context.overrides or {}

        # 从 context.overrides 获取文件路径，或使用默认查找逻辑
        scan_file = self._resolve_path(overrides.get("scan_file"))
        verdict_file = self._resolve_path(overrides.get("verdict_file"))

        # 如果未显式指定，尝试自动查找
        if not scan_file or not os.path.exists(scan_file):
            scan_file = self._resolve_default_scan()
        if not verdict_file or not os.path.exists(verdict_file):
            verdict_file = self._resolve_default_verdict()

        # 加载数据
        try:
            scan_results = (
                load_scan_results(scan_file)
                if scan_file and os.path.exists(scan_file)
                else None
            )
            verdicts = (
                load_verdicts(verdict_file)
                if verdict_file and os.path.exists(verdict_file)
                else []
            )
        except (FileNotFoundError, ValueError, OSError) as e:
            return EvalResult(
                case_id=self.case_id,
                trace_id=context.trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"数据加载失败: {e}",
                action=self.action,
            )

        if not verdicts:
            return EvalResult(
                case_id=self.case_id,
                trace_id=context.trace_id,
                stage=self.stage,
                status="SKIP",
                score=1.0,
                metrics=[],
                detail="无裁决数据可校验",
                action=self.action,
            )

        # ── 1. 使用 shared confidence_validator 替换 inline 置信度校验 ──
        confidence_issues_by_shared = 0
        for verdict in verdicts:
            conf = verdict.get("confidence")
            if conf is not None:
                is_valid, _ = validate_confidence_type(conf)
                if not is_valid:
                    confidence_issues_by_shared += 1

        # ── 2. 执行批量校验（原脚本内部仍使用 validate_confidence，互不影响） ──
        stats = batch_validate(verdicts, scan_results)

        # ── 3. 从 stats.details 提取评分异常数 ──
        score_issue_count = 0
        for detail in stats.get("details", []):
            sv = detail.get("score_validation")
            if not sv:
                continue
            for key in ("bull_score", "bear_score"):
                entry = sv.get(key)
                if entry and not entry.get("is_valid", True):
                    score_issue_count += 1

        # ── 4. 构建 EvalMetric ──
        price_deviation_count = stats.get("hallucinated_count", 0)
        metrics = [
            EvalMetric(
                name="price_deviation_count",
                value=float(price_deviation_count),
                unit="个",
            ),
            EvalMetric(
                name="confidence_issues",
                value=float(confidence_issues_by_shared),
                unit="个",
            ),
            EvalMetric(
                name="score_issues",
                value=float(score_issue_count),
                unit="个",
            ),
        ]

        # ── 5. 综合评分 ──
        total_verdicts = stats.get("total_verdicts", len(verdicts))
        total_issues = (
            price_deviation_count + confidence_issues_by_shared + score_issue_count
        )
        max_possible = max(total_verdicts * 3, 1)
        score = max(0.0, 1.0 - total_issues / max_possible)

        status = "PASS" if score >= self.threshold else "FAIL"

        # ── 6. 构建 detail ──
        detail_parts = []
        if price_deviation_count:
            detail_parts.append(
                f"价格偏差 {price_deviation_count}/{total_verdicts}"
            )
        if confidence_issues_by_shared:
            detail_parts.append(f"置信度异常 {confidence_issues_by_shared}")
        if score_issue_count:
            detail_parts.append(f"评分异常 {score_issue_count}")
        detail = (
            "; ".join(detail_parts)
            if detail_parts
            else f"全部通过 ({total_verdicts} 份裁决)"
        )

        raw: dict[str, Any] = {
            "total_verdicts": total_verdicts,
            "hallucinated_count": price_deviation_count,
            "hallucination_rate": stats.get("hallucination_rate"),
            "confidence_issues_shared": confidence_issues_by_shared,
            "score_issues": score_issue_count,
            "max_deviation_rate": stats.get("max_deviation_rate"),
            "price_deviation_mean": stats.get("price_deviation_mean"),
        }

        return EvalResult(
            case_id=self.case_id,
            trace_id=context.trace_id,
            stage=self.stage,
            status=status,
            score=round(score, 4),
            metrics=metrics,
            detail=detail,
            raw=raw,
            action=self.action,
        )

    # ── 路径解析辅助 ──

    @staticmethod
    def _resolve_path(path: str | None) -> str | None:
        """当 path 是相对路径时从 cwd 展开。"""
        if not path:
            return None
        p = Path(path)
        return str(p.resolve()) if not p.is_absolute() else path

    @staticmethod
    def _resolve_default_scan() -> str | None:
        """查找最新的扫描结果文件。"""
        candidates = [
            Path.cwd() / "outputs" / "scans",
            Path.cwd() / "data" / "scans",
        ]
        for scan_dir in candidates:
            if scan_dir.exists():
                files = sorted(scan_dir.glob("*.json"), reverse=True)
                if files:
                    return str(files[0])
        return None

    @staticmethod
    def _resolve_default_verdict() -> str | None:
        """查找最新的裁决文件。"""
        candidates = [
            Path.cwd() / "outputs" / "verdicts",
            Path.cwd() / "data" / "verdicts",
        ]
        for verdict_dir in candidates:
            if verdict_dir.exists():
                files = sorted(
                    verdict_dir.glob("*verdict*.json"), reverse=True
                )
                if files:
                    return str(files[0])
        return None
