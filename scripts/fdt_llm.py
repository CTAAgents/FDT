"""FDT LLM API 客户端 [INDEPENDENT] — 向后兼容重导出。

说明：
  FdtLlm 类已迁移至 fdt_langgraph/llm_provider.py 以切断 fdt_langgraph <-> scripts 循环依赖。
  此文件保留为向后兼容引用。新代码请直接：from fdt_langgraph.llm_provider import FdtLlm

OpenAI 兼容 API 封装，支持多后端切换（DeepSeek / OpenAI / 本地模型）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdt_langgraph.llm_provider import FdtLlm

ROOT = Path(__file__).resolve().parent.parent

# 辅助函数（fdt_llm.py 独有的 CLI 入口功能）
def _load_yaml(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description="FDT LLM 客户端")
    ap.add_argument("--prompt", default=None, help="用户提示")
    ap.add_argument("--system", default=None, help="系统提示")
    ap.add_argument("--agent", default=None,
                    help="Agent 类型（从 config/agents/ 加载 system_prompt）")
    ap.add_argument("--context", default=None, help="上下文（与 --agent 配合使用）")
    ap.add_argument("--json", action="store_true", help="JSON 模式输出")
    ap.add_argument("--check", action="store_true", help="仅检查可用性")
    args = ap.parse_args()

    if args.check:
        llm = FdtLlm()
        ok = llm.check_available()
        print(f"LLM 可用: {'✅' if ok else '❌'}")
        if not ok:
            print("  提示: 设置 FDT_LLM_API_KEY 或 OPENAI_API_KEY 环境变量")
        return 0 if ok else 1

    if args.agent and args.context:
        cfg_path = ROOT / "config" / "agents" / f"{args.agent}.yaml"
        if not cfg_path.exists():
            print(f"❌ Agent 配置不存在: {cfg_path}")
            return 1
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"❌ Agent 配置加载失败: {e}")
            return 1
        system_prompt = cfg.get("system_prompt", "")
        llm = FdtLlm(agent_type=args.agent)
        reply = llm.chat_json if args.json else llm.chat
        result = reply(args.context, system=system_prompt)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.prompt:
        llm = FdtLlm()
        reply = llm.chat_json(args.prompt, args.system) if args.json else llm.chat(args.prompt, args.system)
        print(reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
