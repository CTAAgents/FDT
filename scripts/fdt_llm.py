"""FDT LLM API 客户端 [INDEPENDENT]。

OpenAI 兼容 API 封装，支持多后端切换（DeepSeek / OpenAI / 本地模型）。

用法:
    from scripts.llm import FdtLlm
    llm = FdtLlm()
    reply = llm.chat("你好", system="你是一个助手")
    
    # 或作为独立 CLI
    python scripts/llm.py --prompt "分析螺纹钢" --system "你是期货分析师"
    python scripts/llm.py --agent judge --context "品种: RB, 信号: bear"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# 默认配置
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# ── Mock 模式 ──
MOCK_MODE = os.environ.get("FDT_LLM_MOCK", "").lower() in ("1", "true", "yes")


def _get_mock_reply(prompt: str, system: str | None = None) -> str:
    """Mock 回复：根据 system prompt 判断角色，返回模拟内容"""
    sys_lower = (system or "").lower()

    if "闫判官" in (system or "") or "judge" in (system or ""):
        return json.dumps({
            "direction": "bear",
            "confidence": "中",
            "grade": "STRONG",
            "reasoning": ["模拟裁决：空头信号确认", "ADX 趋势强度达标"],
            "winner": "空头分析员",
        }, ensure_ascii=False, indent=2)

    if "多头分析员" in (system or "") or "bullish" in (system or ""):
        return json.dumps([
            {"point": "模拟多头论据1", "data": "ADX处于低位，趋势可能反转", "source": "模拟数据"},
            {"point": "模拟多头论据2", "data": "RSI接近超卖区", "source": "模拟数据"},
        ], ensure_ascii=False, indent=2)

    if "空头分析员" in (system or "") or "bearish" in (system or ""):
        return json.dumps([
            {"point": "模拟空头论据1", "data": "价格突破DC20下轨", "source": "模拟数据"},
            {"point": "模拟空头论据2", "data": "持仓量下降配合", "source": "模拟数据"},
        ], ensure_ascii=False, indent=2)

    if "产业链" in (system or "") or "chain" in (system or ""):
        return json.dumps({
            "chain": "黑色系",
            "prosperity": "萧条",
            "analysis": "模拟产业链分析：下游需求疲弱",
        }, ensure_ascii=False, indent=2)

    if "策执远" in (system or "") or "trading" in (system or ""):
        return json.dumps({
            "contract": "RB主力",
            "entry": 3500,
            "stop_loss": 3600,
            "targets": [3400, 3300],
            "position_pct": 5,
        }, ensure_ascii=False, indent=2)

    if "风控明" in (system or "") or "risk" in (system or ""):
        return json.dumps({
            "risk_level": "中",
            "max_position_pct": 8,
            "approval": "bear",
            "notes": "模拟风控审核通过",
        }, ensure_ascii=False, indent=2)

    # 默认 mock 回复
    return json.dumps({
        "analysis": f"模拟分析结果（prompt前50字: {prompt[:50]}...）",
        "source": "MOCK",
    }, ensure_ascii=False, indent=2)


def _get_api_key() -> str:
    """获取 API key，FDT 专用优先"""
    return os.environ.get("FDT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")


def _load_yaml(path: str) -> dict:
    """安全加载 YAML（标准库兼容）"""
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class FdtLlm:
    """FDT LLM 客户端"""

    def __init__(self, agent_type: str | None = None):
        self.api_key = _get_api_key()
        self.config = self._load_config(agent_type)

    def _load_config(self, agent_type: str | None) -> dict:
        """加载配置（按 Agent 类型覆盖）"""
        cfg_path = ROOT / "config" / "llm_config.yaml"
        if not cfg_path.exists():
            return {
                "api_base": DEFAULT_API_BASE,
                "model": DEFAULT_MODEL,
                "temperature": 0.7,
                "max_tokens": 4096,
                "timeout": 120,
            }

        try:
            cfg = _load_yaml(str(cfg_path))
            defaults = cfg.get("defaults", {})
            result = {
                "api_base": defaults.get("api_base", DEFAULT_API_BASE),
                "model": defaults.get("model", DEFAULT_MODEL),
                "temperature": defaults.get("temperature", 0.7),
                "max_tokens": defaults.get("max_tokens", 4096),
                "timeout": defaults.get("timeout", 120),
            }
            # Agent 类型覆盖
            if agent_type:
                per = cfg.get("per_agent", {})
                if agent_type in per:
                    result.update(per[agent_type])
            return result
        except Exception as e:
            print(f"⚠️  LLM 配置加载失败: {e}")
            return {
                "api_base": DEFAULT_API_BASE,
                "model": DEFAULT_MODEL,
                "temperature": 0.7,
                "max_tokens": 4096,
            }

    def chat(self, prompt: str, system: str | None = None,
             temperature: float | None = None,
             max_tokens: int | None = None) -> str:
        """调用 LLM，返回回复文本"""
        if MOCK_MODE:
            return _get_mock_reply(prompt, system)

        if not self.api_key:
            return "⚠️  未配置 API Key（设置 FDT_LLM_API_KEY 或 OPENAI_API_KEY）"

        import urllib.request
        import urllib.error

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": temperature or self.config["temperature"],
            "max_tokens": max_tokens or self.config["max_tokens"],
            "stream": False,
        }

        url = f"{self.config['api_base'].rstrip('/')}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=self.config["timeout"]) as resp:
                result = json.loads(resp.read().decode())
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return f"⚠️  LLM 返回异常: {result}"
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            return f"⚠️  HTTP {e.code}: {body[:200]}"
        except Exception as e:
            return f"⚠️  LLM 调用失败: {e}"

    def chat_json(self, prompt: str, system: str | None = None,
                  temperature: float | None = None) -> dict[str, Any]:
        """调用 LLM 并返回解析后的 JSON。自动追加 JSON 输出指令到 system prompt。"""
        json_instruction = "\n\n请严格以 JSON 格式输出，不要包含 markdown 代码块标记（```）。只返回纯 JSON。"
        sys_with_json = (system or "") + json_instruction
        reply = self.chat(prompt, sys_with_json, temperature)
        # 去噪：去掉 markdown 标记和 BOM
        import re
        cleaned = reply.strip().strip("\ufeff")
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": reply, "_parse_error": "JSON 解析失败", "_cleaned": cleaned[:200]}

    def check_available(self) -> bool:
        """检查 LLM 是否可用"""
        if MOCK_MODE:
            return True
        if not self.api_key:
            return False
        try:
            reply = self.chat("ping", max_tokens=10)
            return not reply.startswith("⚠️")
        except Exception:
            return False


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
        # 从 Agent 配置加载 system_prompt
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
        result = llm.chat_json if args.json else llm.chat
        reply = result(args.context, system=system_prompt)
        print(reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False, indent=2))
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
