"""
Eval-to-Action 闭环 — 评估结果触发自动动作。

支持的动作:
    block_commit:   阻断 git commit / CI
    block_publish:  阻断信号推送
    retry_spawn:    触发 LangGraph 重试
    log_gap:        自动登记到 gap-analysis.md
    trigger_retrain: 触发 RHI 权重重校
    notify:         stderr 告警
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fdt_eval.core.base import EvalAction, EvalResult

# gap-analysis.md 路径
GAP_ANALYSIS_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "harness" / "08-gap-analysis.md"


def execute_action(result: EvalResult) -> None:
    """根据 EvalResult 触发对应的闭环动作。"""
    if result.status == "PASS":
        _on_pass(result)
        return

    if result.status != "FAIL" or result.action is None:
        return

    action = result.action
    fail_action = action.on_fail

    if fail_action == "block_commit":
        _do_block(result, "commit")
    elif fail_action == "block_publish":
        _do_block(result, "publish")
    elif fail_action == "retry_spawn":
        _do_retry(result)
    elif fail_action == "log_gap":
        _do_log_gap(result)
    elif fail_action == "trigger_retrain":
        _do_trigger_retrain(result)
    elif fail_action == "notify":
        _do_notify(result)


def _on_pass(result: EvalResult) -> None:
    if result.action and result.action.on_pass == "auto_update_doc":
        _update_testing_doc(result)


def _do_block(result: EvalResult, target: str) -> None:
    print(f"\n❌ [EVAL BLOCK] {result.case_id}: {result.detail}", file=sys.stderr)
    print(f"    target: {target}, trace_id: {result.trace_id}", file=sys.stderr)
    sys.exit(1)


def _do_retry(result: EvalResult) -> None:
    print(f"⚠ [EVAL RETRY] {result.case_id}: {result.detail}", file=sys.stderr)


def _do_log_gap(result: EvalResult) -> None:
    """自动追加到 08-gap-analysis.md。"""
    entry = (
        f"\n## [自动登记] Eval: {result.case_id} — {result.detail}\n\n"
        f"| 字段 | 值 |\n"
        f"|:-----|:---|\n"
        f"| 登记时间 | {datetime.now().isoformat()} |\n"
        f"| 来源 | fdt_eval action pipeline |\n"
        f"| 严重度 | {result.action.severity if result.action else 'warn'} |\n"
        f"| 状态 | open |\n"
        f"| 影响 | {result.detail} |\n"
    )
    try:
        with open(GAP_ANALYSIS_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"ℹ [EVAL GAP] 已登记到 {GAP_ANALYSIS_PATH}", file=sys.stderr)
    except OSError as e:
        print(f"⚠ [EVAL GAP] 写入失败: {e}", file=sys.stderr)


def _do_trigger_retrain(result: EvalResult) -> None:
    print(f"ℹ [EVAL RETRAIN] {result.case_id}: 漏放率超标，建议触发 RHI 重校", file=sys.stderr)


def _do_notify(result: EvalResult) -> None:
    print(f"⚠ [EVAL NOTIFY] {result.case_id}: {result.detail}", file=sys.stderr)


def _update_testing_doc(result: EvalResult) -> None:
    """更新 06-testing.md 的验证器清单（占位实现）。"""
    print(f"ℹ [EVAL DOC] {result.case_id}: 建议更新 06-testing.md", file=sys.stderr)
