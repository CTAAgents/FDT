"""
品藻质检器 — 代理层（Phase 2 fdt_eval 迁移）。

实际实现在 fdt_eval.cases.runtime.quality_inspector。
本模块仅做透明重新导出，保持原有导入路径不变。
"""

from __future__ import annotations

from fdt_eval.cases.runtime.quality_inspector import (
    validate_argument,
    validate_verdict,
    validate_risk,
    check_report_integrity,
)

__all__ = [
    "validate_argument",
    "validate_verdict",
    "validate_risk",
    "check_report_integrity",
]
