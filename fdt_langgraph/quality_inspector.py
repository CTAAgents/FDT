"""
明鉴秋质检器 — 辩论输出数据质量校验（Phase 3 Data Governance）。

纯函数，无 IO/无 side effect。规则硬编码自 contracts/debate_quality_schema.py。
输出统一的 QualityReport（PASS / FAIL / SKIP + issues 列表）。

用法:
    report = validate_argument(symbol_data)
    report = validate_verdict(verdict_data)
    report = validate_risk(risk_data)
    report = check_report_integrity(html_path)
"""

from __future__ import annotations

from typing import Any

from contracts.debate_quality_schema import (
    ARGUMENT_RULES, VERDICT_RULES, RISK_RULES,
    QualityReport, QualityIssue,
)


# ═══════════════════════════════════════════════════════════════
#  P3 论据质检
# ═══════════════════════════════════════════════════════════════


def validate_argument(data: dict, symbol: str = "") -> QualityReport:
    """校验 P3 多头/空头 Agent 产出的论据数据。

    Args:
        data: 论据数据 dict（从 state.bullish_arguments/bearish_arguments 取）
        symbol: 品种代码（仅用于提示）

    Returns:
        QualityReport
    """
    issues: list[QualityIssue] = []
    if not data:
        return _fail("数据为空", field="data")

    rules = ARGUMENT_RULES

    # 必填字段
    for field in rules["required_fields"]:
        if field not in data or data[field] is None:
            issues.append(_issue(field, f"缺少必填字段 {field}", "error"))

    # 字段类型
    for field, expected_type in rules["field_types"].items():
        val = data.get(field)
        if val is None:
            continue
        if not isinstance(val, expected_type):
            issues.append(_issue(field, f"类型错误: 期望 {expected_type.__name__}, 实际 {type(val).__name__}", "error"))

    # 论据数量
    args = data.get("arguments", [])
    if isinstance(args, list):
        if len(args) < rules["min_arguments"]:
            issues.append(_issue("arguments", f"论据不足({len(args)}<{rules['min_arguments']})", "error"))
        if len(args) > rules["max_arguments"]:
            issues.append(_issue("arguments", f"论据过多({len(args)}>{rules['max_arguments']})", "warning"))

    # 置信度范围
    conf = data.get("confidence")
    if isinstance(conf, (int, float)):
        if conf < rules["confidence_min"] or conf > rules["confidence_max"]:
            issues.append(_issue("confidence", f"置信度 {conf} 超出 [{rules['confidence_min']}, {rules['confidence_max']}]", "error"))
    elif conf is not None and conf not in ("高", "中", "低"):
        issues.append(_issue("confidence", f"置信度值异常: {conf}", "warning"))

    # 来源引用
    refs = data.get("source_refs", [])
    if rules["source_ref_required"] and not refs:
        issues.append(_issue("source_refs", "缺少来源引用", "warning"))

    return _build_report(issues)


# ═══════════════════════════════════════════════════════════════
#  P4 闫判官裁决质检
# ═══════════════════════════════════════════════════════════════


def validate_verdict(data: dict, symbol: str = "") -> QualityReport:
    """校验 P4 闫判官裁决数据。

    Args:
        data: 裁决数据 dict（从 state.verdict 取）

    Returns:
        QualityReport
    """
    issues: list[QualityIssue] = []
    if not data:
        return _fail("数据为空", field="data")

    rules = VERDICT_RULES

    # 必填字段
    for field in rules["required_fields"]:
        if field not in data or data[field] is None:
            issues.append(_issue(field, f"缺少必填字段 {field}", "error"))

    # 字段类型
    for field, expected_type in rules["field_types"].items():
        val = data.get(field)
        if val is None:
            continue
        if not isinstance(val, expected_type):
            issues.append(_issue(field, f"类型错误: 期望 {expected_type.__name__}, 实际 {type(val).__name__}", "error"))

    # 方向有效性
    direction = data.get("direction")
    if direction and direction not in rules["direction_valid"]:
        issues.append(_issue("direction", f"无效方向 '{direction}'", "error"))

    # 置信度有效性
    confidence = data.get("confidence")
    if confidence and confidence not in rules["confidence_valid"]:
        issues.append(_issue("confidence", f"无效置信度 '{confidence}'", "warning"))

    # 入场与止损间距
    entry = data.get("entry_price")
    stop = data.get("stop_loss")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and entry > 0:
        spacing = abs(entry - stop) / entry * 100
        if spacing < rules["entry_stop_min_spacing_pct"]:
            issues.append(_issue("stop_loss", f"入场-止损间距 {spacing:.2f}% < {rules['entry_stop_min_spacing_pct']}%", "error"))
        if spacing > rules["stop_loss_max_pct"]:
            issues.append(_issue("stop_loss", f"止损幅度 {spacing:.2f}% > {rules['stop_loss_max_pct']}%", "warning"))

    # 盈亏比
    target1 = data.get("target1")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and isinstance(target1, (int, float)):
        if entry > 0 and entry != stop:
            loss = abs(entry - stop)
            gain = abs(target1 - entry)
            ratio = gain / loss if loss > 0 else 0
            if ratio < rules["take_profit_min_ratio"]:
                issues.append(_issue("target1", f"盈亏比 {ratio:.1f} < {rules['take_profit_min_ratio']}", "warning"))

    return _build_report(issues)


# ═══════════════════════════════════════════════════════════════
#  P5 风控审核质检
# ═══════════════════════════════════════════════════════════════


def validate_risk(data: dict, symbol: str = "") -> QualityReport:
    """校验 P5 风控明审核数据。

    Args:
        data: 风控数据 dict（从 state.risk_check 取）

    Returns:
        QualityReport
    """
    issues: list[QualityIssue] = []
    if not data:
        return _fail("数据为空", field="data")

    rules = RISK_RULES

    # 必填字段
    for field in rules["required_fields"]:
        if field not in data or data[field] is None:
            issues.append(_issue(field, f"缺少必填字段 {field}", "error"))

    # 字段类型
    for field, expected_type in rules["field_types"].items():
        val = data.get(field)
        if val is None:
            continue
        if not isinstance(val, expected_type):
            issues.append(_issue(field, f"类型错误: 期望 {expected_type.__name__}, 实际 {type(val).__name__}", "error"))

    # 风险等级有效性
    risk_level = data.get("risk_level")
    if risk_level and risk_level not in rules["risk_level_valid"]:
        issues.append(_issue("risk_level", f"无效风险等级 '{risk_level}'", "error"))

    # 检查项数量
    check_items = data.get("check_items", [])
    if isinstance(check_items, list) and len(check_items) < rules["min_check_items"]:
        issues.append(_issue("check_items", f"检查项不足({len(check_items)}<{rules['min_check_items']})", "warning"))

    return _build_report(issues)


# ═══════════════════════════════════════════════════════════════
#  报告完整性检查（明鉴秋自检）
# ═══════════════════════════════════════════════════════════════


def check_report_integrity(report_data: dict) -> QualityReport:
    """检查辩论报告的数据完整性（明鉴秋最终自检）。

    检查项目:
      - report_data 非空
      - 必需区块存在
      - 无占位文本
      - 有裁决数据

    Args:
        report_data: debate_results dict

    Returns:
        QualityReport
    """
    issues: list[QualityIssue] = []
    if not report_data:
        return _fail("报告数据为空", field="report_data")

    # 必需区块
    required_sections = ["symbols", "debate_results", "final_verdicts"]
    for section in required_sections:
        if section not in report_data or not report_data.get(section):
            issues.append(_issue(section, f"缺少必需区块 {section}", "error"))

    # 占位文本
    placeholder_markers = ["（未触发）", "待补充", "TBD", "暂无数据"]
    data_str = str(report_data)
    for marker in placeholder_markers:
        if marker in data_str:
            issues.append(_issue("content", f"存在占位文本 '{marker}'", "warning"))
            break  # 只报一次

    # 有裁决数据
    verdicts = report_data.get("final_verdicts", [])
    if isinstance(verdicts, list) and len(verdicts) == 0:
        issues.append(_issue("final_verdicts", "无裁决数据", "error"))

    return _build_report(issues)


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════


def _issue(field: str, message: str, severity: str = "error") -> QualityIssue:
    return {"field": field, "message": message, "severity": severity}


def _build_report(issues: list[QualityIssue]) -> QualityReport:
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    if errors:
        status = "FAIL"
    elif warnings:
        status = "PASS"  # 仅 warning 不阻断
    else:
        status = "PASS"
    return {
        "status": status,
        "issues": issues,
        "passed": 0 if errors else 1,
        "failed": len(errors),
        "skipped": 0,
    }


def _fail(message: str, field: str = "data") -> QualityReport:
    return {
        "status": "FAIL",
        "issues": [_issue(field, message, "error")],
        "passed": 0,
        "failed": 1,
        "skipped": 0,
    }
