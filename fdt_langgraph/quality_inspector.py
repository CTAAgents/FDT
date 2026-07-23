"""
品藻质检器 — 辩论输出数据质量校验（Phase 3 Data Governance）。

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

    # 条件必填字段（如 stop_loss/entry_price 在 neutral 方向时不强制）
    cond = rules.get("conditional_required")
    if cond:
        condition_key = cond.get("condition_key", "")
        condition_value = data.get(condition_key)
        if condition_value in cond.get("condition_values", []):
            for field in cond.get("fields", []):
                if field not in data or data[field] is None:
                    issues.append(_issue(field, f"缺少条件必填字段 {field}（方向={condition_value} 时必填）", "error"))

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
        data: 裁决数据 dict（从 state.verdict 取，经 normalize_verdict 标准化后）

    Returns:
        QualityReport
    """
    issues: list[QualityIssue] = []
    if not data:
        return _fail("数据为空", field="data")

    rules = VERDICT_RULES

    # 必填字段
    cond = rules.get("conditional_required")
    cond_fields = set(cond.get("fields", [])) if cond else set()
    cond_key = cond.get("condition_key", "") if cond else ""
    cond_values = cond.get("condition_values", []) if cond else []
    for field in rules["required_fields"]:
        # 条件必填字段由后续逻辑处理，此处跳过
        if field in cond_fields:
            continue
        if field not in data or data[field] is None:
            issues.append(_issue(field, f"缺少必填字段 {field}", "error"))

    # 条件必填字段（如 entry_price/stop_loss_price/target_price 仅在 bull/bear 方向时必填）
    if cond:
        actual_value = data.get(cond_key)
        if actual_value in cond_values:
            for field in cond.get("fields", []):
                if field not in data or data[field] is None:
                    issues.append(_issue(field, f"缺少条件必填字段 {field}（{cond_key}={actual_value} 时必填）", "error"))

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

    # 置信度有效性（支持 float 0-1 和中文等级）
    confidence = data.get("confidence")
    if confidence is not None:
        if isinstance(confidence, (int, float)):
            if confidence < 0.0 or confidence > 1.0:
                issues.append(_issue("confidence", f"置信度 {confidence} 超出 [0.0, 1.0]", "warning"))
        elif isinstance(confidence, str):
            if confidence not in ("高", "中", "低"):
                issues.append(_issue("confidence", f"无效置信度 '{confidence}'", "warning"))

    # 入场与止损间距（使用 normalize_verdict 标准化后的字段名）
    entry = data.get("entry_price")
    stop = data.get("stop_loss_price")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and entry > 0:
        spacing = abs(entry - stop) / entry * 100
        if spacing < rules["entry_stop_min_spacing_pct"]:
            issues.append(_issue("stop_loss_price", f"入场-止损间距 {spacing:.2f}% < {rules['entry_stop_min_spacing_pct']}%", "error"))
        if spacing > rules["stop_loss_max_pct"]:
            issues.append(_issue("stop_loss_price", f"止损幅度 {spacing:.2f}% > {rules['stop_loss_max_pct']}%", "warning"))

    # 盈亏比（使用 normalize_verdict 标准化后的字段名）
    target = data.get("target_price")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and isinstance(target, (int, float)):
        if entry > 0 and entry != stop:
            loss = abs(entry - stop)
            gain = abs(target - entry)
            ratio = gain / loss if loss > 0 else 0
            if ratio < rules["take_profit_min_ratio"]:
                issues.append(_issue("target_price", f"盈亏比 {ratio:.1f} < {rules['take_profit_min_ratio']}", "warning"))

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
    """检查辩论报告的数据完整性（品藻最终自检）。

    检查项目:
      - report_data 非空
      - 必需区块存在
      - 无占位文本
      - 有裁决数据
      - 内容安全合规（D3 Generation Phase 3）

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

    # ── D3 Generation: 内容安全合规检查 ──
    try:
        from scripts.content_filter import ContentFilter
        cf = ContentFilter()
        check = cf.check_sensitive(data_str)
        if check["has_sensitive"]:
            from collections import Counter
            cat_counts = Counter(check.get("sensitive_categories", []))
            cats_summary = ", ".join(f"{c}({n})" for c, n in cat_counts.most_common(3))
            issues.append(_issue("content_safety", f"检测到敏感内容: {cats_summary}", "warning"))
    except Exception:
        pass  # 内容过滤非阻断，失败不影响报告生成

    # ── D6 Output: 输出质量评分 ──
    try:
        from scripts.output_metrics import OutputMetrics
        om = OutputMetrics()
        score = om.score_output(report_data, agent_name="quality_assurance")
        total = score.get("total_score", 100)
        if total < 60:
            issues.append(_issue("output_quality", f"输出质量评分偏低: {total}/100", "warning"))
        elif total < 80:
            issues.append(_issue("output_quality", f"输出质量评分: {total}/100", "info"))
    except Exception:
        pass  # 输出质量评分非阻断

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
