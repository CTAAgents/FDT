"""
FDT LLM Provider — 独立 LLM 客户端，无 scripts/ 依赖。

切断 fdt_langgraph <-> scripts 设计层面循环依赖：
fdt_langgraph/ 通过本地 llm_provider 直接调用 LLM，不再依赖 scripts.fdt_llm。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FDT_ROOT = Path(__file__).resolve().parent.parent

# 默认配置
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# Mock 模式
MOCK_MODE = os.environ.get("FDT_LLM_MOCK", "").lower() in ("1", "true", "yes")


def _get_api_key() -> str:
    return os.environ.get("FDT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")


def _load_yaml(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_mock_reply(prompt: str, system: str | None = None) -> str:
    """Mock 回复"""
    if "闫判官" in (system or "") or "judge" in (system or ""):
        return json.dumps({"direction": "bear", "confidence": "中",
                           "reasoning": "模拟闫判官裁决"}, ensure_ascii=False)
    if "风控" in (system or "") or "risk" in (system or ""):
        return json.dumps({"risk_level": "中", "approval": "bear",
                           "notes": "模拟风控审核通过"}, ensure_ascii=False)
    return json.dumps({"analysis": f"模拟分析结果（prompt前50字: {prompt[:50]}...）"},
                      ensure_ascii=False)


class FdtLlm:
    """FDT LLM 客户端 — OpenAI 兼容 API 封装"""

    def __init__(self, agent_type: str | None = None) -> None:
        self.api_key = _get_api_key()
        self.config = self._load_config(agent_type)

    def _load_config(self, agent_type: str | None) -> dict:
        cfg_path = FDT_ROOT / "config" / "llm_config.yaml"
        if not cfg_path.exists():
            return {"api_base": DEFAULT_API_BASE, "model": DEFAULT_MODEL,
                    "temperature": 0.7, "max_tokens": 4096, "timeout": 120}
        try:
            cfg = _load_yaml(str(cfg_path))
            defaults = cfg.get("defaults", {})
            result = {"api_base": defaults.get("api_base", DEFAULT_API_BASE),
                      "model": defaults.get("model", DEFAULT_MODEL),
                      "temperature": defaults.get("temperature", 0.7),
                      "max_tokens": defaults.get("max_tokens", 4096),
                      "timeout": defaults.get("timeout", 120)}
            if agent_type:
                per = cfg.get("per_agent", {})
                if agent_type in per:
                    result.update(per[agent_type])
            return result
        except Exception as e:
            print(f"⚠️ LLM 配置加载失败: {e}")
            return {"api_base": DEFAULT_API_BASE, "model": DEFAULT_MODEL,
                    "temperature": 0.7, "max_tokens": 4096}

    def chat(self, prompt: str, system: str | None = None,
             temperature: float | None = None,
             max_tokens: int | None = None) -> str:
        if MOCK_MODE:
            return _get_mock_reply(prompt, system)
        if not self.api_key:
            return "⚠️ 未配置 API Key（设置 FDT_LLM_API_KEY 或 OPENAI_API_KEY）"
        import urllib.request
        import urllib.error
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.config["model"], "messages": messages,
                   "temperature": temperature or self.config["temperature"],
                   "max_tokens": max_tokens or self.config["max_tokens"],
                   "stream": False}
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
            return f"⚠️ LLM 返回异常: {result}"
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            return f"⚠️ HTTP {e.code}: {body[:200]}"
        except Exception as e:
            return f"⚠️ LLM 调用失败: {e}"

    def chat_json(self, prompt: str, system: str | None = None,
                  temperature: float | None = None) -> dict[str, Any]:
        import re
        reply = self.chat(prompt, system, temperature)
        cleaned = reply.strip().strip("\ufeff")
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": reply, "_parse_error": "JSON 解析失败", "_cleaned": cleaned[:200]}

    def check_available(self) -> bool:
        if MOCK_MODE:
            return True
        if not self.api_key:
            return False
        try:
            reply = self.chat("ping", max_tokens=10)
            return not reply.startswith("⚠️")
        except Exception:
            return False


__all__ = ["FdtLlm"]
