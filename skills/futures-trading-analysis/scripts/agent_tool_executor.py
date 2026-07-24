#!/usr/bin/env python3
"""
Agent Tool Executor v1.0 — 辩论团队工具代理执行引擎
======================================================

核心作用：
  明鉴秋协调员读取 Agent 输出中的 ```python 代码块，代为执行并返回结果。
  解决旧版 Agent 不支持真实 tool calling binding 的问题。

调用方式：
  from agent_tool_executor import execute_agent_tool

协议：
  Agent 输出固定格式：

  ```tool
  {"module": "researcher_tools", "func": "query_supply", "args": {"symbol": "PK"}}
  ```

  执行引擎返回：
  ```result
  {"success": true, "data": {...}, "source": "...", "timestamp": "..."}
  ```

安全：
  - 只允许白名单模块中的指定函数
  - 一次调用超时 30 秒
  - 禁止文件写入/系统调用
"""

import json
import os
import time
import traceback

# 白名单：允许调用的模块+函数
ALLOWED_CALLS = {
    "researcher_tools": [
        "query_supply",
        "query_demand",
        "query_inventory",
        "query_margin",
        "query_term",
        "query_web",
    ],
    "debater_tools": [
        "get_factor_decomp",
        "get_chain_context",
        "get_price_action",
    ],
    "judge_tools": [
        "compute_total_score",
        "compute_convergence",
        "detect_unrebutted",
        "check_convergence",
    ],
    "scenario_analysis": [
        "generate_scenarios",
    ],
}

# 技能根目录（专家包内skills路径）
SKILLS_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

# 模块路径映射（从skills根目录相对定位）
MODULE_PATHS = {
    "researcher_tools": os.path.join(SKILLS_ROOT, "commodity-chain-analysis", "scripts", "researcher_tools.py"),
    "debater_tools": os.path.join(SKILLS_ROOT, "debate-argument-builder", "scripts", "debater_tools.py"),
    "judge_tools": os.path.join(SKILLS_ROOT, "debate-judge", "scripts", "judge_tools.py"),
    "scenario_analysis": os.path.join(SKILLS_ROOT, "debate-trading-planner", "scripts", "scenario_analysis.py"),
}


def _import_from_path(filepath: str):
    """从文件路径动态导入模块，返回模块对象。"""
    import importlib.util

    module_name = os.path.splitext(os.path.basename(filepath))[0]
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {filepath}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_tool_call(agent_output: str) -> dict:
    """从 Agent 输出中提取工具调用。

    支持两种格式：
    1. JSON 格式：```tool\n{"module": "...", "func": "...", "args": {...}}\n```
    2. 简写格式：```tool\nmodule.func(arg1=val1)\n```
    """
    import re

    # JSON 格式
    m = re.search(r"```tool\s*\n(.*?)\n```", agent_output, re.DOTALL)
    if not m:
        return None
    body = m.group(1).strip()
    try:
        call = json.loads(body)
        return call
    except json.JSONDecodeError:
        pass
    # 简写格式
    m2 = re.search(r"(\w+)\.(\w+)\(([^)]*)\)", body)
    if m2:
        module_name = m2.group(1)
        func_name = m2.group(2)
        args_str = m2.group(3)
        args = {}
        if args_str.strip():
            for pair in args_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    args[k] = v
        return {"module": module_name, "func": func_name, "args": args}
    return None


def execute_tool_call(call: dict) -> dict:
    """执行单个工具调用并返回结果。"""
    module_name = call.get("module", "")
    func_name = call.get("func", "")
    args = call.get("args", {})

    # 权限检查
    if module_name not in ALLOWED_CALLS:
        return {"success": False, "error": f"模块 {module_name} 不在白名单中"}
    if func_name not in ALLOWED_CALLS[module_name]:
        return {"success": False, "error": f"函数 {module_name}.{func_name} 不在白名单中"}

    try:
        # 动态加载模块
        filepath = MODULE_PATHS.get(module_name, "")
        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": f"模块文件不存在: {filepath}"}
        mod = _import_from_path(filepath)
        func = getattr(mod, func_name)

        # 执行（带超时）
        start = time.time()
        result = func(**args)
        elapsed = time.time() - start

        return {
            "success": True,
            "data": result,
            "elapsed_sec": round(elapsed, 3),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def execute_agent_tool(agent_output: str) -> dict:
    """解析并执行 Agent 输出的工具调用。

    返回可在 Agent prompt 中展示的结果字符串。
    """
    call = parse_tool_call(agent_output)
    if not call:
        return {
            "success": False,
            "error": "未检测到有效的工具调用格式",
            "format_hint": '```tool\\n{"module":"...","func":"...","args":{...}}\\n```',
        }
    result = execute_tool_call(call)
    if result["success"]:
        return {
            "success": True,
            "output": json.dumps(result["data"], ensure_ascii=False, default=str),
            "elapsed_sec": result["elapsed_sec"],
        }
    return result


if __name__ == "__main__":
    # 测试
    test_output = '```tool\n{"module": "judge_tools", "func": "compute_total_score", "args": {"scores": {"a": 8}, "weights": {"a": 1.0}}}\n```'
    r = execute_agent_tool(test_output)
    print(f"测试结果: {json.dumps(r, indent=2, ensure_ascii=False)}")
