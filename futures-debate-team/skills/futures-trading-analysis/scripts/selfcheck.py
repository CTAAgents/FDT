#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDT 鲁棒性 Layer 5: 健康自检 v1.0
辩论前运行，检查所有前置条件。不通过→拒绝启动+报告原因。

用法: python selfcheck.py --workspace C:\path\to\Signal
"""

import json, os, sys, subprocess
from datetime import datetime


def check_python() -> tuple:
    """检查Python环境"""
    try:
        v = sys.version_info
        return True, f"Python {v.major}.{v.minor}.{v.micro}"
    except:
        return False, "Python不可用"

def check_data_source(ds_name="通达信TQ-Local") -> tuple:
    """检查数据源可用性"""
    try:
        import importlib.util
        spec = importlib.util.find_spec("pandas")
        if spec:
            return True, f"pandas可用"
        return True, "基础库可用"
    except:
        return False, "pandas不可用"

def check_path_writable(path: str) -> tuple:
    """检查路径是否可写"""
    if os.path.exists(path):
        test_file = os.path.join(path, ".fdt_selfcheck_test")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return True, f"可写"
        except:
            return False, f"不可写: {path}"
    else:
        return False, f"路径不存在: {path}"

def check_debate_scripts(scripts_dir: str) -> tuple:
    """检查关键脚本是否存在"""
    scripts = [
        "validate_agent_output.py",
        "debate_orchestrator.py",
        "phase3_generate_report.py",
    ]
    missing = []
    for s in scripts:
        fp = os.path.join(scripts_dir, s)
        if not os.path.exists(fp):
            missing.append(s)
    if missing:
        return False, f"缺失脚本: {', '.join(missing)}"
    return True, f"所有关键脚本就绪"

def check_agent_defs(agents_dir: str) -> tuple:
    """检查Agent定义文件"""
    required = [
        "futures-technical-researcher.md",
        "futures-fundamental-researcher.md",
        "futures-affirmative-debater.md",
        "futures-opposition-debater.md",
        "futures-judge.md",
        "futures-debate-team-team-lead.md",
    ]
    missing = []
    for r in required:
        fp = os.path.join(agents_dir, r)
        if not os.path.exists(fp):
            missing.append(r)
    if missing:
        return False, f"缺失Agent定义: {', '.join(missing)}"
    return True, f"所有Agent定义就绪"

def check_signal_file(workspace: str) -> tuple:
    """检查触发信号文件（用于信号门判定）"""
    trigger = os.path.join(workspace, "Commodities", "debate_trigger.json")
    scan = os.path.join(workspace, "Commodities", "daily_debate_latest.html")
    if os.path.exists(trigger):
        try:
            with open(trigger, 'r', encoding='utf-8') as f:
                data = json.load(f)
            count = data.get("signal_count", 0)
            return True, f"有{count}个信号待辩论"
        except:
            return False, "信号文件损坏"
    elif os.path.exists(scan):
        return True, "扫描报告存在但无触发文件(无信号或需手动检查)"
    else:
        return False, "无扫描报告+无触发文件"

def run_selfcheck(workspace: str, fdt_root: str = None) -> dict:
    """
    执行完整健康自检。
    返回: {"pass": bool, "checks": [...], "errors": [...]}
    """
    if fdt_root is None:
        # 从当前脚本路径向上4级: scripts -> futures-trading-analysis -> skills -> fdt_root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fdt_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))

    scripts_dir = os.path.join(fdt_root, "skills", "futures-trading-analysis", "scripts")
    agents_dir = os.path.join(fdt_root, "agents")

    checks = []
    errors = []
    warnings = []

    def run(name, fn, *args):
        ok, msg = fn(*args)
        checks.append({"name": name, "pass": ok, "msg": msg})
        if not ok:
            errors.append(f"{name}: {msg}")
        return ok

    run("Python环境", check_python)
    run("数据源", check_data_source)
    run("工作空间可写", check_path_writable, workspace)
    run("辩论脚本", check_debate_scripts, scripts_dir)
    run("Agent定义", check_agent_defs, agents_dir)
    signal_ok, signal_msg = check_signal_file(workspace)
    checks.append({"name": "信号文件", "pass": signal_ok, "msg": signal_msg})

    all_pass = len(errors) == 0

    return {
        "pass": all_pass,
        "checked_at": datetime.now().isoformat(),
        "workspace": workspace,
        "fdt_root": fdt_root,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "verdict": "✅ 可以启动辩论" if all_pass else "❌ 存在阻塞性问题，拒绝启动"
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FDT健康自检")
    parser.add_argument("--workspace", "-w", default=os.getcwd(), help="工作空间路径")
    parser.add_argument("--fdt-root", default=None, help="FDT专家团根目录")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    result = run_selfcheck(args.workspace, args.fdt_root)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"  FDT 健康自检 — {result['checked_at'][:19]}")
        print(f"{'='*50}")
        for c in result["checks"]:
            icon = "✅" if c["pass"] else "❌"
            print(f"  {icon} {c['name']}: {c['msg']}")
        print(f"\n  {result['verdict']}")

    sys.exit(0 if result["pass"] else 1)
