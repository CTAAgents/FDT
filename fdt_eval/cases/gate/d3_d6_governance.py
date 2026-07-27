"""
D3/D6 治理门禁 — 检查 D3 (Decode Control) 和 D6 (Output Control) 测试是否通过。

对应 HARNEES §10 (10-coding-standards.md §12, C16 代码-推理边界):
  D3 = decode_control: 解码层控制逻辑的独立性验证
  D6 = output_control:  输出层控制逻辑的独立性验证

验证方式:
  1. 检查 test_decode_control.py 存在且可导入
  2. 检查 test_output_control.py 存在且可导入
  3. 使用 pytest 运行两项测试
  4. Score = passed / (passed + failed)
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry

# ── 需要检查的测试文件 ──
_TEST_FILES = [
    "tests/test_decode_control.py",
    "tests/test_output_control.py",
]

_TEST_MODULES = [
    "tests.test_decode_control",
    "tests.test_output_control",
]

_TIMEOUT_SECONDS = 60


@eval_registry.register
class D3D6GovernanceEval(EvalCase):
    """D3/D6 治理门禁：验证解码/输出控制测试的独立性和正确性。

    检查 test_decode_control.py 和 test_output_control.py 存在、可导入，
    并通过 pytest 运行，确保 D3/D6 层控制逻辑未被 LLM 推理污染。
    """

    case_id = "gate.d3_d6_governance"
    stage = "gate"
    description = "D3/D6 治理: decode_control + output_control 测试通过率"
    weight = 0.25
    threshold = 0.95
    action = EvalAction(severity="block", on_fail="block_commit")
    cache_ttl = 300
    data_cost = "low"

    # 项目根目录 (fdt_eval/cases/gate/ 向上 4 层 → 项目根)
    _ROOT = Path(__file__).resolve().parents[3]

    def run(self, context: EvalContext) -> EvalResult:
        start = time.time()
        trace_id = context.trace_id

        checks: list[dict] = []

        # ── 1. 文件存在性检查 ──
        for rel_path in _TEST_FILES:
            full = self._ROOT / rel_path
            passed = full.is_file()
            checks.append({
                "level": "exist",
                "name": f"文件存在: {rel_path}",
                "passed": passed,
                "detail": "" if passed else f"文件不存在: {full}",
            })

        # ── 2. 模块可导入检查 ──
        for mod_name in _TEST_MODULES:
            try:
                importlib.import_module(mod_name)
                checks.append({
                    "level": "import",
                    "name": f"模块可导入: {mod_name}",
                    "passed": True,
                    "detail": "",
                })
            except Exception as e:
                checks.append({
                    "level": "import",
                    "name": f"模块可导入: {mod_name}",
                    "passed": False,
                    "detail": str(e),
                })

        # ── 3. 检查是否有任何前置检查失败，提前退出 ──
        any_precheck_failed = any(
            c["level"] in ("exist", "import") and not c["passed"]
            for c in checks
        )

        passed_count = 0
        failed_count = 0

        if any_precheck_failed:
            # 前置检查失败，跳过 pytest
            score = 0.0
            detail_parts = [c["detail"] for c in checks if not c["passed"]]
            detail = f"D3/D6 门禁: 前置检查失败: {'; '.join(detail_parts)}"
        else:
            # ── 4. 运行 pytest ──
            test_files = [str(self._ROOT / rel_path) for rel_path in _TEST_FILES]
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest"] + test_files + ["--no-cov", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                    cwd=str(self._ROOT),
                )

                stdout = proc.stdout
                stderr = proc.stderr

                # 解析 pytest 输出格式: "X passed, Y failed" 或 "X passed"
                import re
                passed_match = re.search(r"(\d+) passed", stdout)
                failed_match = re.search(r"(\d+) failed", stdout)

                passed_count = int(passed_match.group(1)) if passed_match else 0
                failed_count = int(failed_match.group(1)) if failed_match else 0

                if proc.returncode == 0:
                    score = 1.0 if passed_count > 0 else 1.0
                else:
                    score = passed_count / (passed_count + failed_count) if (passed_count + failed_count) > 0 else 0.0

                detail = (
                    f"D3/D6 pytest: {passed_count} passed, {failed_count} failed"
                    f"  (score={score:.2f})"
                )

            except subprocess.TimeoutExpired:
                score = 0.0
                passed_count = 0
                failed_count = -1  # 标记超时
                detail = f"D3/D6 pytest 超时 ({_TIMEOUT_SECONDS}s)"

            except Exception as e:
                score = 0.0
                passed_count = 0
                failed_count = -1
                detail = f"D3/D6 pytest 执行异常: {e}"

        # ── 计分 ──
        status = "PASS" if score >= self.threshold else "FAIL"

        metrics = [
            EvalMetric(name="passed", value=float(passed_count)),
            EvalMetric(name="failed", value=float(failed_count)),
            EvalMetric(name="total", value=float(passed_count + failed_count) if failed_count >= 0 else 0.0),
            EvalMetric(name="score", value=round(score, 4), threshold=self.threshold),
        ]

        duration = (time.time() - start) * 1000

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=round(score, 4),
            metrics=metrics,
            detail=detail,
            raw={"checks": checks, "passed": passed_count, "failed": failed_count},
            action=self.action,
            duration_ms=round(duration, 1),
        )
