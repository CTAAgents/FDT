"""FDT Agent 执行器 [INDEPENDENT]。

读取 config/agents/ 中的 Agent 配置，构造 prompt，调用 LLM，输出到文件。
替代 WorkBuddy 的 spawn 机制，实现 FDT 自有的 Agent 运行时。

用法:
    python scripts/agent_runner.py --agent judge --context "..."
    python scripts/agent_runner.py --agent bullish_analyst --context "..." --output p4_bullish.json

流程模式（模拟 spawn_plan）:
    python scripts/agent_runner.py flow --plan spawn_plan.json --workspace ./data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_agent_config(agent_name: str) -> dict | None:
    """加载 Agent 配置"""
    import yaml
    cfg_path = ROOT / "config" / "agents" / f"{agent_name}.yaml"
    if not cfg_path.exists():
        return None
    try:
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _atomic_write(path: str, content: str):
    """原子写入"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run_agent(agent_name: str, context: str,
              output: str | None = None,
              system_override: str | None = None,
              temperature: float | None = None,
              max_tokens: int | None = None,
              json_mode: bool = False) -> str:
    """运行一个 Agent（同步调用 LLM）"""
    from scripts.fdt_llm import FdtLlm

    # 加载 Agent 配置
    cfg = _load_agent_config(agent_name)
    if not cfg:
        msg = f"⚠️  Agent 配置未找到: {agent_name}"
        print(msg)
        return msg

    display = cfg.get("display_name", agent_name)
    version = cfg.get("version", "?")

    # 构建 system prompt
    system_prompt = system_override or cfg.get("system_prompt", "")
    if not system_prompt:
        msg = f"⚠️  {agent_name} 无 system_prompt"
        print(msg)
        return msg

    # 构建用户消息
    user_msg = context.strip()
    if json_mode:
        user_msg += "\n\n请以 JSON 格式输出。"

    print(f"[{_now()}] 🎯 {display} (v{version}) — 调用 LLM...")

    # 调用 LLM
    llm = FdtLlm(agent_type=agent_name)
    if json_mode:
        reply = llm.chat_json(user_msg, system=system_prompt)
        output_text = json.dumps(reply, ensure_ascii=False, indent=2)
    else:
        output_text = llm.chat(user_msg, system=system_prompt,
                               temperature=temperature, max_tokens=max_tokens)

    # 写入输出文件
    if output:
        _atomic_write(output, output_text)
        print(f"[{_now()}] ✅ 输出已写入: {output} ({len(output_text)} bytes)")

    return output_text


def flow_from_plan(plan_path: str, workspace: str):
    """从 spawn_plan.json 执行辩论流程"""
    from scripts.fdt_llm import FdtLlm

    # 检查 LLM 可用性
    llm = FdtLlm()
    if not llm.check_available():
        print("❌ LLM 不可用，请设置 FDT_LLM_API_KEY")
        return 1

    # 加载计划
    if not os.path.exists(plan_path):
        # 尝试从 workspace 找最新 spawn_plan
        import glob
        plans = sorted(glob.glob(os.path.join(workspace, "spawn_plan_*.json")),
                       key=os.path.getmtime)
        if not plans:
            print(f"❌ 未找到 spawn_plan 在 {workspace}")
            return 1
        plan_path = plans[-1]
        print(f"  使用计划: {plan_path}")

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    phases = plan.get("execution_phases", [])
    if not phases:
        # 尝试其他格式
        for key in ["phases", "plan", "steps"]:
            if key in plan:
                phases = plan[key]
                break

    if not phases:
        print(f"⚠️  计划中未找到 execution_phases，直接执行所有 Agent")
        agents = plan.get("agents", plan.get("debate_agents", []))
        if agents:
            phases = [{"name": "batch", "agents": agents}]

    print(f"\n{'='*60}")
    print(f"FDT 自主辩论流程: {len(phases)} 个阶段")
    print(f"{'='*60}")

    for phase in phases:
        pname = phase.get("name", phase.get("phase", "?"))
        agents = phase.get("agents", [])
        print(f"\n--- 阶段 {pname}: {len(agents)} 个 Agent ---")

        for agent_cfg in agents:
            aname = agent_cfg.get("name") if isinstance(agent_cfg, dict) else agent_cfg
            prompt = agent_cfg.get("prompt", agent_cfg.get("context", "")) if isinstance(agent_cfg, dict) else ""
            output_file = agent_cfg.get("output", "") if isinstance(agent_cfg, dict) else ""

            # 输出路径
            if output_file and not os.path.isabs(output_file):
                output_file = os.path.join(workspace, output_file)

            print(f"  [{aname}] 执行中...")
            result = run_agent(aname, prompt or "请进行分析",
                               output=output_file, json_mode=True)
            print(f"  [{aname}] 完成 ({len(result)} chars)")
            time.sleep(1)  # API 限流保护

    print(f"\n✅ 辩论流程完成")
    print(f"  工作空间: {workspace}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FDT Agent 执行器")
    ap.add_argument("--agent", default=None, help="Agent 名称")
    ap.add_argument("--context", default="", help="上下文/用户消息")
    ap.add_argument("--output", default=None, help="输出文件路径")
    ap.add_argument("--system", default=None, help="覆盖 system_prompt")
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="JSON 模式")

    sub = ap.add_subparsers(dest="cmd")
    p_flow = sub.add_parser("flow", help="从 spawn_plan 执行辩论流程")
    p_flow.add_argument("--plan", default=None, help="spawn_plan.json 路径")
    p_flow.add_argument("--workspace", required=True, help="工作空间目录")
    p_flow.add_argument("--check-llm", action="store_true", help="先检查 LLM 可用性")

    args = ap.parse_args()

    if args.cmd == "flow":
        if args.check_llm:
            from scripts.fdt_llm import FdtLlm
            llm = FdtLlm()
            if not llm.check_available():
                print("❌ LLM 不可用，设置 FDT_LLM_API_KEY 环境变量")
                return 1
        return flow_from_plan(args.plan, args.workspace)

    if args.agent:
        output_text = run_agent(args.agent, args.context,
                                output=args.output,
                                system_override=args.system,
                                temperature=args.temperature,
                                max_tokens=args.max_tokens,
                                json_mode=args.json)
        if not args.output:
            print(output_text[:2000])
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
