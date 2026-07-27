"""
品藻质检器 — 辩论输出数据质量校验 EvalCase（Phase 2 fdt_eval 迁移）。

提供 4 个透明代理函数（validate_argument / validate_verdict / validate_risk / check_report_integrity）
供 fdt_langgraph.quality_inspector 导入，以及 QualityInspectorEval 类供评估框架使用。

EvalCase: runtime.quality_inspector.p3_5
  - stage: runtime
  - weight: 0.20
  - threshold: 0.90
  - action: block / retry_spawn
"""

from __future__ import annotations

import json
import time

from contracts.debate_quality_schema import (
    ARGUMENT_RULES,
    RISK_RULES,
    VERDICT_RULES,
    QualityIssue,
    QualityReport,
)
from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction, EvalStage
from fdt_eval.core.registry import eval_registry
from fdt_eval.cases._shared.confidence_validator import validate_confidence_type

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


def validate_verdict(data: dict, symbol: str = "", market_type: str = "commodity_futures") -> QualityReport:
    """校验 P4 闫判官裁决数据。

    Args:
        data: 裁决数据 dict（从 state.verdict 取，经 normalize_verdict 标准化后）
        symbol: 品种代码（仅用于提示）
        market_type: 市场类型（GAP-012: 用于条件必填和阈值差异化）

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

    # GAP-012: 按市场类型条件必填
    mt_cond = rules.get("market_type_conditional", {})
    for field, mt_rules in mt_cond.items():
        required_for = mt_rules.get("required_for", [])
        required_all_except = mt_rules.get("required_for_all_except", [])
        direction_val = data.get("direction", "neutral")

        should_require = False
        if required_for and market_type in required_for:
            should_require = True
        if required_all_except and direction_val not in required_all_except:
            should_require = True

        if should_require and (field not in data or data[field] is None):
            issues.append(_issue(field, f"缺少按市场类型必填字段 {field}（{market_type}/{direction_val}）", "error"))

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
        # GAP-012: 按市场类型读取止损最大幅度
        sl_max_pct = rules["stop_loss_max_pct"]
        if isinstance(sl_max_pct, dict):
            sl_max = sl_max_pct.get(market_type, sl_max_pct.get("__default__", 8.0))
        else:
            sl_max = float(sl_max_pct)
        if spacing > sl_max:
            issues.append(_issue("stop_loss_price", f"止损幅度 {spacing:.2f}% > {sl_max}%（{market_type}）", "warning"))

    # 盈亏比（使用 normalize_verdict 标准化后的字段名）
    target = data.get("target_price")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and isinstance(target, (int, float)):
        if entry > 0 and entry != stop:
            loss = abs(entry - stop)
            gain = abs(target - entry)
            ratio = gain / loss if loss > 0 else 0
            if ratio < rules["take_profit_min_ratio"]:
                issues.append(_issue("target_price", f"盈亏比 {ratio:.1f} < {rules['take_profit_min_ratio']}", "warning"))

    # ── D3 Generation: 内容安全合规检查 ──
    try:
        from scripts.content_filter import ContentFilter
        cf = ContentFilter()
        check = cf.filter(json.dumps(data, ensure_ascii=False))
        if check.get("blocked"):
            issues.append(_issue("content_safety", f"内容安全阻断: {check.get('sensitive_categories', [])}", "error"))
        elif check.get("has_sensitive"):
            from collections import Counter
            cat_counts = Counter(check.get("sensitive_categories", []))
            cats_summary = ", ".join(f"{c}({n})" for c, n in cat_counts.most_common(3))
            issues.append(_issue("content_safety", f"检测到敏感内容: {cats_summary}", "warning"))
    except Exception:
        pass

    # ── D6 Output: OutputMetrics 硬约束 (v9.22.6) ──
    try:
        from scripts.output_metrics import OutputMetrics
        om = OutputMetrics()
        score_result = om.score_output(data)
        total_score = score_result.get("total_score", 100)
        if total_score < 40:
            issues.append(_issue("output_quality", f"输出质量评分 {total_score:.0f}/100 — 强制阻断", "error"))
        elif total_score < 60:
            issues.append(_issue("output_quality", f"输出质量评分 {total_score:.0f}/100 — 低于阈值", "error"))
    except Exception:
        pass

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

    # ── D3 Generation: 内容安全合规检查 ──
    try:
        from scripts.content_filter import ContentFilter
        cf = ContentFilter()
        check = cf.filter(json.dumps(data, ensure_ascii=False))
        if check.get("blocked"):
            issues.append(_issue("content_safety", f"风控内容安全阻断: {check.get('sensitive_categories', [])}", "error"))
        elif check.get("has_sensitive"):
            from collections import Counter
            cat_counts = Counter(check.get("sensitive_categories", []))
            cats_summary = ", ".join(f"{c}({n})" for c, n in cat_counts.most_common(3))
            issues.append(_issue("content_safety", f"风控检测到敏感内容: {cats_summary}", "warning"))
    except Exception:
        pass

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


# ═══════════════════════════════════════════════════════════════
#  QualityInspectorEval — 统一评估用例
# ═══════════════════════════════════════════════════════════════


@eval_registry.register
class QualityInspectorEval(EvalCase):
    """P3.5 辩论质检统一评估 — 包装全部 4 个 quality_inspector 函数。

    从 EvalContext.overrides["state"] 提取辩论阶段数据，逐一调用：
      - validate_argument   (bullish_arguments, bearish_arguments)
      - validate_verdict    (verdict)
      - validate_risk       (risk_check)
      - check_report_integrity (debate_results)

    聚合分数 = 1.0 - total_errors / total_checks
    """

    case_id = "runtime.quality_inspector.p3_5"
    stage: EvalStage = "runtime"
    description = "P3.5 辩论质检：论据/裁决/风控/报告完整性统一校验"
    weight = 0.20
    threshold = 0.90
    action = EvalAction(severity="block", on_fail="retry_spawn")
    cache_ttl = 0  # runtime, never cache

    def run(self, context: EvalContext) -> EvalResult:
        start = time.time()
        trace_id = context.trace_id
        overrides = context.overrides or {}

        state: dict = overrides.get("state", {})
        debate_results: dict = overrides.get("debate_results", {})

        if not state and not debate_results:
            return EvalResult(
                case_id=self.case_id,
                trace_id=trace_id,
                stage=self.stage,
                status="ERROR",
                score=0.0,
                metrics=[],
                detail="EvalContext.overrides 必须包含 state 或 debate_results",
                action=self.action,
                duration_ms=round((time.time() - start) * 1000, 1),
            )

        # ── 逐项校验 ──
        reports: dict[str, QualityReport] = {}
        total_errors = 0
        total_checks = 0

        # validate_argument: bullish_arguments + bearish_arguments
        for agent_key in ("bullish_arguments", "bearish_arguments"):
            data = state.get(agent_key, {})
            symbol = data.get("symbol", agent_key)
            report = validate_argument(data, symbol)
            reports[agent_key] = report
            total_errors += report.get("failed", 0)
            total_checks += 1

        # validate_verdict
        verdict_data = state.get("verdict", {})
        verdict_report = validate_verdict(verdict_data, verdict_data.get("symbol", ""))
        reports["verdict"] = verdict_report
        total_errors += verdict_report.get("failed", 0)
        total_checks += 1

        # validate_risk
        risk_data = state.get("risk_check", {})
        risk_report = validate_risk(risk_data, risk_data.get("symbol", ""))
        reports["risk_check"] = risk_report
        total_errors += risk_report.get("failed", 0)
        total_checks += 1

        # check_report_integrity
        integrity_report = check_report_integrity(debate_results)
        reports["report_integrity"] = integrity_report
        total_errors += integrity_report.get("failed", 0)
        total_checks += 1

        # ── 聚合评分 ──
        score = 1.0 - (total_errors / total_checks) if total_checks > 0 else 1.0
        score = max(0.0, min(1.0, score))

        # 构建指标
        metrics: list[EvalMetric] = []
        for check_name, r in reports.items():
            er = len([i for i in r.get("issues", []) if i.get("severity") == "error"])
            wr = len([i for i in r.get("issues", []) if i.get("severity") == "warning"])
            metrics.append(EvalMetric(name=f"{check_name}.error_count", value=float(er), unit="count"))
            metrics.append(EvalMetric(name=f"{check_name}.warning_count", value=float(wr), unit="count"))
            metrics.append(EvalMetric(name=f"{check_name}.has_errors", value=1.0 if er > 0 else 0.0, threshold=0.0))
            metrics.append(EvalMetric(name=f"{check_name}.status", value=1.0 if r.get("status") == "PASS" else 0.0, threshold=1.0))
        metrics.append(EvalMetric(name="total_errors", value=float(total_errors), unit="count"))
        metrics.append(EvalMetric(name="total_checks", value=float(total_checks), unit="count"))

        total_failures = sum(1 for r in reports.values() if r.get("status") == "FAIL")
        if total_failures == 0:
            status = "PASS"
            detail = "所有质检项通过"
        elif score >= self.threshold:
            status = "PASS"
            detail = f"质检通过（score={score:.2f}），{total_failures} 项 FAIL 但加权达标"
        else:
            status = "FAIL"
            detail = f"质检未通过（score={score:.2f}），{total_failures} 项 FAIL"

        duration = round((time.time() - start) * 1000, 1)

        return EvalResult(
            case_id=self.case_id,
            trace_id=trace_id,
            stage=self.stage,
            status=status,
            score=round(score, 4),
            metrics=metrics,
            detail=detail,
            raw={k: dict(v) for k, v in reports.items()},
            action=self.action,
            duration_ms=duration,
        )
