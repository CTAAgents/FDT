"""
EvalCase: runtime.signal_review — 最终信号复查验证。

包装 scripts/verification/validate_final_signals.py 的 validate_signals()
函数为 EvalCase，接入 fdt_eval 统一评估框架。
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry

# ── 动态导入 validate_signals ──

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "scripts" / "verification" / "validate_final_signals.py"
)


def _load_validate_signals():
    spec = importlib.util.spec_from_file_location(
        "validate_final_signals", str(_SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.validate_signals


validate_signals = _load_validate_signals()


@eval_registry.register
class SignalReviewEval(EvalCase):
    """最终信号复查验证 — 确定性校验，不依赖 LLM。

    包装 validate_final_signals.py 的全部硬性校验规则：
      - 顶层字段完整性
      - action/direction/confidence 合法性
      - 交易参数一致性
      - 方向-价格一致性
      - 扫描品种交叉校验
    """

    case_id = "runtime.signal_review"
    stage = "runtime"
    description = "对 debate_results.json 执行硬性校验规则，确保输出信号明确无异议"
    weight = 0.15
    threshold = 1.0
    action = EvalAction(severity="block", on_fail="block_publish")

    def run(self, context: EvalContext) -> EvalResult:
        overrides = context.overrides or {}

        # 从 overrides 获取路径
        debate_path = overrides.get("debate_data")
        scan_path = overrides.get("scan_data")

        if not debate_path:
            return EvalResult(
                case_id=self.case_id,
                trace_id=context.trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail="缺少 debate_data 路径（通过 EvalContext.overrides['debate_data'] 传入）",
                action=self.action,
            )

        debate_path = os.path.abspath(debate_path)
        if not os.path.exists(debate_path):
            return EvalResult(
                case_id=self.case_id,
                trace_id=context.trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail=f"debate_data 文件不存在: {debate_path}",
                action=self.action,
            )

        # 加载数据
        with open(debate_path, encoding="utf-8") as f:
            data = json.load(f)

        # 可选加载 scan 数据
        scan = None
        if scan_path:
            scan_path = os.path.abspath(scan_path)
            if os.path.exists(scan_path):
                with open(scan_path, encoding="utf-8") as f:
                    scan = json.load(f)

        # 执行校验
        errors, warns = validate_signals(data, scan)

        # ── 映射结果 ──
        error_count = len(errors)
        warn_count = len(warns)

        if error_count > 0:
            status = "FAIL"
            score = 0.0
            detail = f"信号复查失败 — {error_count} 项错误, {warn_count} 项警告"
        elif warn_count > 0:
            status = "PASS"
            score = 0.8
            detail = f"信号复查通过但有 {warn_count} 项警告"
        else:
            status = "PASS"
            score = 1.0
            detail = "信号复查全部通过"

        metrics = [
            EvalMetric(name="error_count", value=float(error_count), threshold=0.0, unit="count"),
            EvalMetric(name="warn_count", value=float(warn_count), unit="count"),
        ]

        raw = {
            "errors": errors,
            "warns": warns,
            "debate_path": debate_path,
            "scan_path": os.path.abspath(scan_path) if scan_path else None,
        }

        return EvalResult(
            case_id=self.case_id,
            trace_id=context.trace_id,
            stage=self.stage,
            status=status,
            score=score,
            metrics=metrics,
            detail=detail,
            raw=raw,
            action=self.action,
        )
