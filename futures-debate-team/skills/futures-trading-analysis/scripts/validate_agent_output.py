#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Agent产出校验器 — SKILL层适配（v1.1 · 单一来源收敛）

⚠️ 压力测试 F3 修复：此前本文件维护独立 schema（verdicts 列表）+ 无 confidence 校验，
与真实产出格式（flat dict，已由 2026-07-11 真实样本 p5_judge_JD.json 等验证）及
主校验器 scripts/validate_agent_output.py 严重分歧 → L2 门禁语义错乱。

现改为【薄适配层】：唯一真实校验逻辑位于
  C:/.../futures-debate-team/scripts/validate_agent_output.py
本模块通过 importlib 加载该 canonical 模块并适配其返回结构
（{valid, error, line, col, normalized_confidence} → {pass, grade, errors, warnings}），
供 L2 debate_orchestrator.py 的 `from validate_agent_output import validate, SCHEMAS` 使用。

真实 Agent 产出格式（已验证）：
  P4 / P4_ZHENGZHEN / P4_ZHENSI : flat dict {agent,symbol,direction,generated_at,key_arguments[...]}
  P5_JUDGE                      : flat dict {agent,symbol,verdict,confidence,bull_score,bear_score,winner,reasoning,...}
  P5_PLAN / P5_RISK             : flat dict
"""

import os
import sys
import importlib.util

# ── 加载唯一真实来源（canonical），用独立模块名避免与主模块名 shadowing ──
_CANON_FILE = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "scripts", "validate_agent_output.py",
    )
)


def _load_canonical():
    spec = importlib.util.spec_from_file_location("fdt_canonical_validator", _CANON_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_canon = _load_canonical()
validate_canonical = _canon.validate
PHASE_MAP = _canon.PHASE_MAP

# SCHEMAS 仅用于保留 argparse choices 兼容性（与 canonical PHASE_MAP 对齐 + 旧版别名）
SCHEMAS = {k: {"desc": "canonical phase"} for k in PHASE_MAP.keys()}
# 兼容 debate_orchestrator 旧版 phase 命名（实际校验时透传给 canonical，未知 phase 走 lenient）
_LEGACY_ALIAS = {
    "P3_guanlan": "P4",
    "P3_tanyuan": "P4",
    "P4_zhengzhen": "P4_ZHENGZHEN",
    "P4_zhensi": "P4_ZHENSI",
    "P5_judge": "P5_JUDGE",
}
for _old in _LEGACY_ALIAS:
    SCHEMAS.setdefault(_old, {"desc": "legacy alias"})


def validate(file_path: str, phase: str) -> dict:
    """
    适配 canonical 返回结构供 L2 orchestrator 使用。
    canonical.validate 返回 {valid, error, line, col, normalized_confidence}。
    """
    res = validate_canonical(file_path, phase)
    err = res.get("error", "")
    if res.get("valid"):
        return {
            "pass": True, "grade": "PASS", "errors": [], "warnings": [],
            "file": file_path, "phase": phase,
        }
    is_fatal = ("JSON解析失败" in err) or ("文件不存在" in err)
    return {
        "pass": False,
        "grade": "FATAL" if is_fatal else "RETRY",
        "errors": [err] if err else ["未知校验错误"],
        "warnings": [],
        "file": file_path,
        "phase": phase,
    }


# ── CLI 入口（保持与原 SKILL 副本行为一致，便于回归）──
if __name__ == "__main__":
    import argparse
    import json as _json
    parser = argparse.ArgumentParser(description="FDT Agent产出校验器（SKILL适配层·单一来源）")
    parser.add_argument("file", help="要校验的JSON文件路径")
    parser.add_argument("--phase", "-p", required=True,
                       choices=list(SCHEMAS.keys()),
                       help="产出阶段")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出结果")
    args = parser.parse_args()

    result = validate(args.file, args.phase)

    if args.json:
        print(_json.dumps(result, ensure_ascii=False, indent=2))
    else:
        icon = "✅" if result["pass"] else "❌" if result["grade"] == "FATAL" else "⚠️"
        print(f"\n{icon} 校验 [{result['phase']}] {os.path.basename(result['file'])}")
        print(f"   等级: {result['grade']}")
        if result["errors"]:
            print(f"   错误 ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"     - {e}")
        if result["pass"]:
            print("   ✅ 通过 — 可进入下一阶段")

    sys.exit(0 if result["pass"] else 1)
