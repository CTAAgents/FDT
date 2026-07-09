#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDT 鲁棒性 Layer 1: 产出校验器 v1.0
每个Agent spawn完成后调用，自动校验JSON合法性+必填字段+禁止模式。
不合法→打回重写(最多2次)→拒绝→降级记录。

用法:
  python validate_agent_output.py <file_path> --phase P3_guanglan
  python validate_agent_output.py <file_path> --phase P3_tanyuan
  python validate_agent_output.py <file_path> --phase P4_zhengzhen
  python validate_agent_output.py <file_path> --phase P4_zhensi
  python validate_agent_output.py <file_path> --phase P5_judge

返回: 0=通过, 1=可修复错误, 2=致命错误(需降级)
"""

import json, os, sys, re
from datetime import datetime

# ==================== Phase Schema定义 ====================
SCHEMAS = {
    "P3_guanlan": {
        "required_top": ["generated_at", "analyst", "symbols"],
        "per_symbol": ["trend", "support_resistance", "patterns", "volume_analysis", "key_metrics"],
        "desc": "观澜技术面供弹"
    },
    "P3_tanyuan": {
        "required_top": ["generated_at", "analyst", "symbols"],
        "per_symbol": ["supply_demand", "inventory", "profit", "basis_structure", "events"],
        "desc": "探源基本面供弹"
    },
    "P4_zhengzhen": {
        "required_top": ["arguments"],
        "per_symbol_args": ["side", "key_arguments"],
        "per_argument": ["claim", "evidence", "source"],
        "min_args": 3,
        "desc": "证真辩论论据"
    },
    "P4_zhensi": {
        "required_top": ["arguments"],
        "per_symbol_args": ["side", "key_arguments"],
        "per_argument": ["claim", "evidence", "source", "rebuttal_target"],
        "min_args": 3,
        "desc": "慎思辩论论据"
    },
    "P5_judge": {
        "required_top": ["verdicts"],
        "per_verdict": ["direction", "confidence", "winner", "recommendation",
                       "entry_price", "stop_loss_price", "target_price", "target2_price",
                       "position_pct", "scores", "bear_args", "bull_args", "chain", "reasoning"],
        "per_scores": ["证真", "慎思"],
        "per_score_dim": ["logic", "evidence", "consistency", "rebuttal", "risk", "presentation", "total"],
        "min_verdicts": 1,
        "desc": "闫判官裁决"
    },
}

# ==================== 禁止模式检测 ====================
FORBIDDEN_PATTERNS = [
    # 中文双引号在JSON字符串内（破坏JSON结构）
    (r'[\u4e00-\u9fff]\u0022\u0022', "中文ASCII双引号连续(破坏JSON)"),
    (r'[\u4e00-\u9fff]\u0022[^\u0022\n]+\u0022[\u4e00-\u9fff，。；：、！？）\)]', "中文ASCII双引号做强调(应使用「」)"),
]

def _check_json_valid(file_path: str) -> tuple:
    """检查JSON是否可解析。返回 (ok, data_or_error)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return True, data
    except json.JSONDecodeError as e:
        return False, f"JSON解析失败 行{e.lineno}列{e.colno}: {e.msg}"
    except FileNotFoundError:
        return False, f"文件不存在: {file_path}"
    except Exception as e:
        return False, f"读取失败: {e}"

def _check_forbidden_patterns(data: dict) -> list:
    """检查JSON数据中是否包含禁止的文本模式。返回错误列表。"""
    errors = []
    text = json.dumps(data, ensure_ascii=False)

    for pattern, desc in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            # 截取上下文
            for m in matches[:3]:  # 最多报告3处
                idx = text.find(str(m)) if isinstance(m, str) else 0
                ctx = text[max(0, idx-20):idx+len(str(m))+20]
                errors.append(f"禁止模式 [{desc}]: ...{ctx}...")
    return errors

def _check_schema(data: dict, phase: str) -> list:
    """检查是否符合schema。返回错误列表。"""
    errors = []
    schema = SCHEMAS.get(phase, {})
    if not schema:
        return [f"未知phase: {phase}"]

    # 顶层字段
    for k in schema.get("required_top", []):
        if k not in data:
            errors.append(f"缺少顶层字段: {k}")
        elif data[k] is None:
            errors.append(f"顶层字段为空: {k}")

    # 品种级字段
    symbols_data = data.get("symbols", data.get("arguments", data.get("verdicts", {})))
    if not symbols_data:
        errors.append(f"无品种数据: symbols/arguments/verdicts为空")
        return errors

    for sym, sym_data in symbols_data.items():
        # P3检查
        for k in schema.get("per_symbol", []):
            if k not in sym_data:
                errors.append(f"[{sym}] 缺少字段: {k}")
            elif sym_data[k] is None:
                errors.append(f"[{sym}] 字段为空: {k}")
            elif isinstance(sym_data[k], str) and len(sym_data[k]) < 10:
                errors.append(f"[{sym}] 字段内容过短: {k} ({len(sym_data[k])}字符)")

        # P4检查论据
        args = sym_data.get("key_arguments", [])
        min_args = schema.get("min_args", 1)
        if len(args) < min_args:
            errors.append(f"[{sym}] 论据数量不足: {len(args)}/{min_args}")
        for i, arg in enumerate(args):
            for k in schema.get("per_argument", []):
                if k not in arg:
                    errors.append(f"[{sym}] 论据{i+1}缺少字段: {k}")
                elif isinstance(arg.get(k), str) and len(arg.get(k, "")) < 5:
                    errors.append(f"[{sym}] 论据{i+1}.{k}内容过短")

    # P5检查裁决
    for sym, vd in symbols_data.items():
        for k in schema.get("per_verdict", []):
            if k not in vd:
                errors.append(f"[{sym}] 裁决缺少: {k}")

        # 评分检查
        scores = vd.get("scores", {})
        for scorer in schema.get("per_scores", []):
            if scorer not in scores:
                errors.append(f"[{sym}] 缺少评分方: {scorer}")
            else:
                for dim in schema.get("per_score_dim", []):
                    if dim not in scores[scorer]:
                        errors.append(f"[{sym}] {scorer}.{dim}缺失")
                    elif not isinstance(scores[scorer].get(dim), (int, float)):
                        errors.append(f"[{sym}] {scorer}.{dim}非数值")

        # 论据非空
        for k in ["bear_args", "bull_args"]:
            if not vd.get(k):
                errors.append(f"[{sym}] {k}为空列表")

    return errors

def validate(file_path: str, phase: str) -> dict:
    """
    校验Agent产出文件。
    返回: {"pass": bool, "grade": "PASS|RETRY|FATAL", "errors": [str], "warnings": [str]}
    """
    result = {"pass": False, "grade": "FATAL", "errors": [], "warnings": [],
              "file": file_path, "phase": phase, "checked_at": datetime.now().isoformat()}

    # Step 1: JSON合法性
    ok, data_or_err = _check_json_valid(file_path)
    if not ok:
        result["errors"].append(data_or_err)
        return result  # FATAL - JSON不合法

    data = data_or_err

    # Step 2: Schema校验
    schema_errors = _check_schema(data, phase)
    for e in schema_errors:
        result["errors"].append(e)

    # Step 3: 禁止模式
    forbidden_errors = _check_forbidden_patterns(data)
    for e in forbidden_errors:
        result["errors"].append(e)

    # 判定等级
    fatal_count = sum(1 for e in result["errors"] if "JSON解析失败" in e or "文件不存在" in e)
    if fatal_count > 0:
        result["grade"] = "FATAL"
    elif len(result["errors"]) > 3:
        result["grade"] = "RETRY"
    elif len(result["errors"]) > 0:
        result["grade"] = "RETRY"
    else:
        result["grade"] = "PASS"
        result["pass"] = True

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FDT Agent产出校验器")
    parser.add_argument("file", help="要校验的JSON文件路径")
    parser.add_argument("--phase", "-p", required=True,
                       choices=list(SCHEMAS.keys()),
                       help="产出阶段")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出结果")
    args = parser.parse_args()

    result = validate(args.file, args.phase)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
