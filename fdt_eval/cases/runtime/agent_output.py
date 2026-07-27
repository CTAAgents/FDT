"""
Agent产出验证评估用例 — 包装 validate_agent_output.py。

通过 subprocess 调用 scripts/verification/validate_agent_output.py，
将 CLI 工具的 JSON 输出映射为统一的 EvalResult 契约。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction, EvalStage
from fdt_eval.core.registry import eval_registry


@eval_registry.register
class AgentOutputEval(EvalCase):
    """验证 Agent 产出文件的 JSON 可解析性、Schema 合规性和 confidence 类型。

    对应 scripts/verification/validate_agent_output.py 的全部三项校验：
      1. JSON 可解析（catch 裸引号/未转义字符）
      2. 结构 Schema 合规（必需字段齐全）
      3. confidence 类型合规（数值或受控中文标签）
    """

    case_id = "runtime.agent_output"
    stage: EvalStage = "runtime"
    description = "Agent产出文件校验：JSON解析性 + Schema合规 + confidence类型"
    weight = 1.0
    threshold = 0.9
    action = EvalAction(severity="block", on_fail="retry_spawn")
    data_cost = "low"

    # 脚本路径（相对本文件: ../../scripts/verification/validate_agent_output.py）
    _SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verification" / "validate_agent_output.py"

    def run(self, context: EvalContext) -> EvalResult:
        """执行 Agent 产出验证。

        EvalContext.overrides 需要包含:
            file_path (str): 待校验的 Agent 产出文件路径
            phase (str):     阶段标识，如 P4 / P5_JUDGE / P5_PLAN / P5_RISK
        """
        start = time.time()
        trace_id = context.trace_id
        overrides = context.overrides or {}

        file_path: str = overrides.get("file_path", "")
        phase: str = overrides.get("phase", "")

        # ── 参数校验 ──
        if not file_path:
            return self._error_result(trace_id, "缺少必需参数: file_path",
                                      {"error": "EvalContext.overrides 必须包含 file_path"})
        if not phase:
            return self._error_result(trace_id, "缺少必需参数: phase",
                                      {"error": "EvalContext.overrides 必须包含 phase"})

        # ── 检查脚本存在 ──
        script = self._SCRIPT
        if not script.exists():
            return self._error_result(trace_id, f"脚本不存在: {script}")

        # ── 子进程调用 ──
        try:
            proc = subprocess.run(
                [sys.executable, str(script), "--file", file_path, "--phase", phase],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            duration = (time.time() - start) * 1000
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[EvalMetric(name="timeout", value=1.0)],
                detail=f"脚本执行超时(30s): --file {file_path} --phase {phase}",
                duration_ms=round(duration, 1),
                action=self.action,
            )

        duration = (time.time() - start) * 1000

        # ── 解析输出 ──
        output: dict = {}
        if proc.stdout.strip():
            try:
                output = json.loads(proc.stdout)
            except json.JSONDecodeError:
                output = {}

        valid = output.get("valid", False) and proc.returncode == 0
        error_msg = output.get("error", "")
        normalized_confidence = output.get("normalized_confidence")
        line = output.get("line", 0)
        col = output.get("col", 0)

        # ── 构建指标 ──
        metrics = [
            EvalMetric(name="valid", value=1.0 if valid else 0.0, threshold=1.0),
            EvalMetric(name="exit_code", value=float(proc.returncode)),
            EvalMetric(name="parse_error_line", value=float(line)),
            EvalMetric(name="parse_error_col", value=float(col)),
        ]
        if normalized_confidence is not None:
            metrics.append(
                EvalMetric(name="normalized_confidence", value=float(normalized_confidence), unit="score")
            )

        # ── 判定结果 ──
        if valid:
            status = "PASS"
            score = 1.0
            detail = f"文件校验通过: {Path(file_path).name} (phase={phase})"
        else:
            status = "FAIL"
            score = 0.0
            detail = f"校验失败: {error_msg}" if error_msg else f"退出码={proc.returncode}"

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=score,
            metrics=metrics,
            detail=detail,
            raw={
                "file_path": file_path,
                "phase": phase,
                "valid": valid,
                "error": error_msg,
                "line": line,
                "col": col,
                "normalized_confidence": normalized_confidence,
                "exit_code": proc.returncode,
                "stderr": proc.stderr.strip() or None,
            },
            action=self.action,
            duration_ms=round(duration, 1),
        )

    # ── 内部辅助 ──

    def _error_result(self, trace_id: str, detail: str,
                      raw: dict | None = None) -> EvalResult:
        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status="ERROR",
            score=0.0,
            metrics=[],
            detail=detail,
            raw=raw,
            action=self.action,
        )
