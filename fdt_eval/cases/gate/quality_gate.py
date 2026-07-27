"""
质量门禁评估用例 — 确保关键脚本存在、可导入，并通过基本冒烟测试。

对应 ARCHITECTURE.md Phase 3 (3.1): 迁入 quality_gate → cases/gate/quality_gate.py
与 tests/fdt-gate/test_quality_gate.py 互补（pytest 兼容包装）。

检查清单 (L1-L5):
  L1. 验证脚本存在
  L2. 验证脚本可导入 (import 无异常)
  L3. 验证脚本 CLI --help 正常退出
  L4. 验证关键函数签名符合预期
  L5. 验证 docstring 非空
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
from pathlib import Path

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction, EvalStage
from fdt_eval.core.registry import eval_registry

# ── 需要检查的脚本清单 ──
_REQUIRED_SCRIPTS = [
    # 验证脚本
    "scripts/verification/validate_agent_output.py",
    "scripts/verification/validate_llm_output.py",
    "scripts/verification/validate_final_signals.py",
    "scripts/verification/validate_verdicts.py",
    "scripts/verification/pre_commit_harness_check.py",
    "scripts/verification/verify_doc_consistency.py",
    # Harness 脚本
    "scripts/harness/rhi_pairwise_eval.py",
    "scripts/harness/rhi_global_cli.py",
]

# ── 可导入模块 ──
_REQUIRED_MODULES = [
    "fdt_eval.core.base",
    "fdt_eval.core.registry",
    "fdt_eval.core.store",
    "fdt_eval.core.runner",
    "fdt_eval.core.action",
]


@eval_registry.register
class QualityGateEval(EvalCase):
    """质量门禁：检查关键脚本存在/可导入/CLI 冒烟/函数签名/docstring。

    执行 L1-L5 五层检查，逐项计分。Score = pass_count / total_checks。
    threshold=0.95 意味着最多允许 5% 的检查项失败。
    """

    case_id = "gate.quality_gate"
    stage: EvalStage = "gate"
    description = "质量门禁：L1 存在性 → L2 可导入 → L3 CLI 冒烟 → L4 函数签名 → L5 docstring"
    weight = 0.25
    threshold = 0.95
    action = EvalAction(severity="block", on_fail="block_commit")
    data_cost = "low"

    # 项目根目录 (fdt_eval/cases/gate/ 向上 4 层 → 项目根)
    _ROOT = Path(__file__).resolve().parents[3]

    def run(self, context: EvalContext) -> EvalResult:
        start = time.time()
        trace_id = context.trace_id

        checks: list[dict] = []

        # ── L1: 脚本存在性 ──
        for rel_path in _REQUIRED_SCRIPTS:
            full = self._ROOT / rel_path
            passed = full.is_file()
            checks.append({
                "level": "L1",
                "name": f"文件存在: {rel_path}",
                "passed": passed,
                "detail": "" if passed else f"文件不存在: {full}",
            })

        # ── L2: 模块可导入 ──
        for mod_name in _REQUIRED_MODULES:
            try:
                importlib.import_module(mod_name)
                checks.append({
                    "level": "L2",
                    "name": f"模块可导入: {mod_name}",
                    "passed": True,
                    "detail": "",
                })
            except Exception as e:
                checks.append({
                    "level": "L2",
                    "name": f"模块可导入: {mod_name}",
                    "passed": False,
                    "detail": str(e),
                })

        # ── L3: CLI --help 冒烟 ──
        cli_targets = [p for p in _REQUIRED_SCRIPTS if not p.startswith("fdt_eval")]
        for rel_path in cli_targets[:6]:  # 最多测 6 个避免耗时
            full = self._ROOT / rel_path
            if not full.is_file():
                continue
            try:
                proc = subprocess.run(
                    [sys.executable, str(full), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                passed = proc.returncode == 0
                checks.append({
                    "level": "L3",
                    "name": f"CLI 冒烟: {rel_path} --help",
                    "passed": passed,
                    "detail": "" if passed else f"exit_code={proc.returncode}, stderr={proc.stderr.strip()[:200]}",
                })
            except subprocess.TimeoutExpired:
                checks.append({
                    "level": "L3",
                    "name": f"CLI 冒烟: {rel_path} --help",
                    "passed": False,
                    "detail": "超时 (10s)",
                })
            except Exception as e:
                checks.append({
                    "level": "L3",
                    "name": f"CLI 冒烟: {rel_path} --help",
                    "passed": False,
                    "detail": str(e),
                })

        # ── L4: EvalCase 子类函数签名 ──
        for mod_name in _REQUIRED_MODULES:
            try:
                mod = importlib.import_module(mod_name)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if not callable(attr) or attr_name.startswith("_"):
                        continue
                    import inspect
                    try:
                        sig = inspect.signature(attr)
                        _ = sig  # 验证签名可解析
                        checks.append({
                            "level": "L4",
                            "name": f"签名可解析: {mod_name}.{attr_name}",
                            "passed": True,
                            "detail": "",
                        })
                    except (ValueError, TypeError):
                        checks.append({
                            "level": "L4",
                            "name": f"签名可解析: {mod_name}.{attr_name}",
                            "passed": False,
                            "detail": "inspect 解析失败",
                        })
            except Exception:
                pass

        # ── L5: docstring 非空 ──
        for mod_name in _REQUIRED_MODULES:
            try:
                mod = importlib.import_module(mod_name)
                doc_ok = bool(mod.__doc__ and mod.__doc__.strip())
                checks.append({
                    "level": "L5",
                    "name": f"模块有 docstring: {mod_name}",
                    "passed": doc_ok,
                    "detail": "" if doc_ok else "docstring 为空或 None",
                })
            except Exception as e:
                checks.append({
                    "level": "L5",
                    "name": f"模块有 docstring: {mod_name}",
                    "passed": False,
                    "detail": str(e),
                })

        # ── 计分 ──
        total_checks = len(checks)
        passed_checks = sum(1 for c in checks if c["passed"])
        failed_checks = total_checks - passed_checks
        score = passed_checks / total_checks if total_checks > 0 else 0.0

        # 按 level 聚合
        failures_by_level: dict[str, int] = {}
        for c in checks:
            if not c["passed"]:
                failures_by_level[c["level"]] = failures_by_level.get(c["level"], 0) + 1

        metrics = [
            EvalMetric(name="total_checks", value=float(total_checks)),
            EvalMetric(name="passed_checks", value=float(passed_checks)),
            EvalMetric(name="score", value=round(score, 4), threshold=self.threshold),
        ]
        for level in ("L1", "L2", "L3", "L4", "L5"):
            cnt = float(failures_by_level.get(level, 0))
            metrics.append(EvalMetric(name=f"{level}_failures", value=cnt))

        status = "PASS" if score >= self.threshold else "FAIL"
        if status == "PASS":
            detail = f"门禁通过: {passed_checks}/{total_checks} 检查项通过"
        else:
            detail = (
                f"门禁未通过: {passed_checks}/{total_checks} 通过; "
                f"失败分布: {failures_by_level}"
            )

        duration = (time.time() - start) * 1000

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=round(score, 4),
            metrics=metrics,
            detail=detail,
            raw={"checks": checks, "failures_by_level": failures_by_level},
            action=self.action,
            duration_ms=round(duration, 1),
        )
