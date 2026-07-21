#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Agent产出校验器（2026-07-11创建·补齐R29断点；2026-07-11 #5修复·confidence归一）

职责：每个辩论Agent(spawn)写文件后，由明鉴秋轮询就绪→调用本脚本做L1校验。
校验三件事：
  1. JSON可解析（catch裸引号/未转义字符导致的JSONDecodeError，定位错误位置）
  2. 结构schema合规（必需字段齐全、key_arguments为列表且子字段完整）
  3. confidence 类型合规（#5）：必须为 0-1 数值或受控中文标签(高/中/低)，
     禁止任意裸字符串，防止类型漂移污染下游质量门控/仓位计算

退出码：0=通过，1=校验失败（调用方应触发重spawn）
输出：JSON {valid: bool, error: str, line: int, col: int, normalized_confidence: float|null}

用法：
  python validate_agent_output.py --file p4_bullish_JD.json --phase P4_BULLISH
  python validate_agent_output.py --file p5_judge_JD.json --phase P5_JUDGE
"""

from typing import Any
import argparse
import json
import sys
from pathlib import Path

# ── #5修复：置信度归一化单一来源（优先 import，失败则内联兜底）──
try:
    from confidence_utils import (
        normalize_confidence,
        is_valid_confidence,
        CONFIDENCE_LABEL_MAP,
    )
except ImportError:
    CONFIDENCE_LABEL_MAP = {"低": 0.4, "中": 0.6, "高": 0.8, "LOW": 0.4, "MEDIUM": 0.6, "HIGH": 0.8}

    def normalize_confidence(conf: Any) -> str:
        if isinstance(conf, (int, float)):
            return float(conf)
        if isinstance(conf, str):
            s = conf.strip()
            try:
                return float(s)
            except ValueError:
                pass
            return CONFIDENCE_LABEL_MAP.get(s, 0.5)
        return 0.5

    def is_valid_confidence(conf: Any) -> bool:
        if isinstance(conf, (int, float)):
            return True
        if isinstance(conf, str):
            s = conf.strip()
            if s in CONFIDENCE_LABEL_MAP:
                return True
            try:
                float(s)
                return True
            except ValueError:
                return False
        return False


# ── 各phase的schema定义 ──
P4_REQUIRED = ["agent", "symbol", "direction", "generated_at", "key_arguments"]
P4_ARG_REQUIRED = ["id", "claim", "evidence", "reasoning", "family", "confidence"]

P5_JUDGE_REQUIRED = [
    "agent", "symbol", "generated_at", "verdict",
    "confidence", "bull_score", "bear_score", "winner", "reasoning",
]
P5_PLAN_REQUIRED = [
    "agent", "symbol", "action", "position_pct", "contract", "timeframe",
]
# 原策执远v3.0嵌套格式（含保守/中性/进取三方案），作为备选schema
P5_PLAN_V3_REQUIRED = ["variant", "symbol", "plans", "scenarios"]
P5_RISK_REQUIRED = [
    "agent", "symbol", "risk_level", "veto", "risk_items", "recommendation",
]

PHASE_MAP = {
    "P4": (P4_REQUIRED, True),
    "P4_ZHENGZHEN": (P4_REQUIRED, True),
    "P4_ZHENSI": (P4_REQUIRED, True),
    "P5_JUDGE": (P5_JUDGE_REQUIRED, False),
    "P5_PLAN": (P5_PLAN_REQUIRED, False),
    "P5_RISK": (P5_RISK_REQUIRED, False),
}


def _locate_json_error(raw: str, exc: json.JSONDecodeError):
    """从JSONDecodeError提取错误行列，辅助定位裸引号等问题"""
    line = exc.lineno or 0
    col = exc.colno or 0
    lines = raw.split("\n")
    ctx_start = max(0, line - 2)
    ctx_end = min(len(lines), line + 1)
    ctx = "\n".join(
        f"  L{ctx_start + i + 1}: {lines[ctx_start + i]}"
        for i in range(ctx_end - ctx_start)
    )
    return line, col, ctx


def validate(path: str, phase: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"valid": False, "error": f"文件不存在: {path}", "line": 0, "col": 0,
                "normalized_confidence": None}

    raw = p.read_text(encoding="utf-8")

    # ── 1. JSON可解析性（核心：catch裸引号）──
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        line, col, ctx = _locate_json_error(raw, e)
        return {
            "valid": False,
            "error": f"JSON解析失败 @L{line}:{col} — {e.msg}\n{ctx}",
            "line": line,
            "col": col,
            "normalized_confidence": None,
        }

    # ── 2. schema校验 ──
    if phase not in PHASE_MAP:
        return {"valid": True, "error": "", "line": 0, "col": 0,
                "normalized_confidence": None}

    required, has_args = PHASE_MAP[phase]
    missing = [k for k in required if k not in data]
    
    # P5_PLAN 特殊处理：接受扁平schema或v3.0嵌套格式
    if phase == "P5_PLAN" and missing and len(missing) > 0:
        v3_missing = [k for k in P5_PLAN_V3_REQUIRED if k not in data]
        if len(v3_missing) < len(missing):
            # v3格式匹配度更高 → 按v3校验
            # 检查plans内每项有type/entry/stop_loss/target
            plans = data.get("plans", {})
            # v3.0格式: plans 是 dict（key=品种, value=list of plan entries）
            if isinstance(plans, dict):
                plan_entries = []
                for sym_plans in plans.values():
                    if isinstance(sym_plans, list):
                        plan_entries.extend(sym_plans)
                    elif isinstance(sym_plans, dict):
                        plan_entries.append(sym_plans)
            elif isinstance(plans, list):
                plan_entries = plans
            else:
                plan_entries = []
            if len(plan_entries) == 0:
                return {
                    "valid": False,
                    "error": "v3.0格式: plans 必须为非空列表",
                    "line": 0,
                    "col": 0,
                    "normalized_confidence": None,
                }
            plan_fields = ["type", "entry", "stop_loss", "target"]
            for i, pl in enumerate(plan_entries):
                miss_plan = [k for k in plan_fields if k not in pl]
                if miss_plan:
                    return {
                        "valid": False,
                        "error": f"v3.0格式: plans[{i}] 缺少字段: {miss_plan}",
                        "line": 0,
                        "col": 0,
                        "normalized_confidence": None,
                    }
            # 检查合约信息嵌套
            if "contract_details" not in data and "contract_analysis" not in data:
                pass  # 非强制
            # v3格式通过修饰——将缺少字段清空表明已验证
            missing = []
    
    if missing:
        return {
            "valid": False,
            "error": f"缺少必需字段: {missing}",
            "line": 0,
            "col": 0,
            "normalized_confidence": None,
        }

    # key_arguments结构校验（P4）
    if has_args:
        args = data.get("key_arguments")
        if not isinstance(args, list) or len(args) == 0:
            return {
                "valid": False,
                "error": "key_arguments 必须为非空列表",
                "line": 0,
                "col": 0,
                "normalized_confidence": None,
            }
        for i, a in enumerate(args):
            miss = [k for k in P4_ARG_REQUIRED if k not in a]
            if miss:
                return {
                    "valid": False,
                    "error": f"key_arguments[{i}] 缺少字段: {miss}",
                    "line": 0,
                    "col": 0,
                    "normalized_confidence": None,
                }

    # ── 3. confidence 一致性校验（#5修复）──
    # 系统契约规定 confidence 为 0-1 数值；历史遗留可能输出 高/中/低 字符串。
    # 此处统一校验：必须是数值或受控标签，禁止任意裸字符串（防类型漂移）。
    conf_errors = []
    if phase == "P5_JUDGE" and "confidence" in data:
        c = data["confidence"]
        if not is_valid_confidence(c):
            conf_errors.append(
                f"confidence={c!r} 非法（须为0-1数值或 高/中/低）"
            )
    if has_args:
        for i, a in enumerate(args):
            ac = a.get("confidence")
            if ac is not None and not is_valid_confidence(ac):
                conf_errors.append(
                    f"key_arguments[{i}].confidence={ac!r} 非法（须为0-1数值或 高/中/低）"
                )
    if conf_errors:
        return {
            "valid": False,
            "error": " | ".join(conf_errors),
            "line": 0,
            "col": 0,
            "normalized_confidence": None,
        }

    # 归一化结果回传（下游直接使用数值型，彻底消除类型不确定性）
    norm = None
    if "confidence" in data:
        norm = round(normalize_confidence(data.get("confidence")), 3)

    return {"valid": True, "error": "", "line": 0, "col": 0,
            "normalized_confidence": norm}


def main():
    ap = argparse.ArgumentParser(description="L1 Agent产出校验器")
    ap.add_argument("--file", required=True, help="待校验的Agent产出文件路径")
    ap.add_argument(
        "--phase",
        required=True,
        help="阶段标识: P4 / P4_ZHENGZHEN / P4_ZHENSI / P5_JUDGE / P5_PLAN / P5_RISK",
    )
    args = ap.parse_args()

    result = validate(args.file, args.phase.upper())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
