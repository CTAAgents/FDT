import json
import logging
import os
import re
from typing import Dict, Optional, Any, List
from datetime import datetime

logger = logging.getLogger("fdt_agents")


class FdtAgentExecutor:
    def __init__(self, agent_config: Any):
        if isinstance(agent_config, str):
            self._load_from_registry(agent_config)
        else:
            self.agent_config = agent_config
            self.agent_name = agent_config.get("name", "")
            self.role = agent_config.get("role", "")
            self.system_prompt = agent_config.get("system_prompt", "")
            self.max_tokens = agent_config.get("max_tokens", 4096)
            self.temperature = agent_config.get("temperature", 0.7)

    @staticmethod
    def _normalize_env_name(agent_name: str) -> str:
        """将 Agent 名称转换为环境变量命名格式：大写 + 非字母数字下划线转为下划线"""
        name = agent_name.upper()
        name = re.sub(r"[^A-Z0-9_]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        return name

    def _resolve_llm_config(self, suffix: str, default: str) -> str:
        """解析逐Agent LLM 配置。优先级：逐Agent 环境变量 > 全局环境变量 > 传入默认值"""
        if not self.agent_name:
            return default
        env_key = f"FDT_LLM_{self._normalize_env_name(self.agent_name)}_{suffix}"
        return os.environ.get(env_key, default)

    def _load_from_registry(self, agent_name: str):
        agent = AgentRegistry.get(agent_name)
        if agent:
            self.agent_name = agent.agent_name
            self.role = agent.role
            self.system_prompt = agent.system_prompt
            self.max_tokens = agent.max_tokens
            self.temperature = agent.temperature
            self.agent_config = agent.agent_config
        else:
            self.agent_name = agent_name
            self.role = ""
            self.system_prompt = ""
            self.max_tokens = 4096
            self.temperature = 0.7
            self.agent_config = {"name": agent_name}

    def execute(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]:
        logger.info(f"[trace_id={trace_id}] Executing agent: {self.agent_name}")

        result = {
            "agent_name": self.agent_name,
            "role": self.role,
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "output": "",
            "error": None,
            "metadata": {
                "prompt_tokens": len(prompt),
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        try:
            llm_output = self._call_llm(prompt, **kwargs)
            result["output"] = llm_output
            logger.info(f"[trace_id={trace_id}] Agent {self.agent_name} completed successfully")
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"[trace_id={trace_id}] Agent {self.agent_name} failed: {e}")

        return result

    async def run(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]:
        return self.execute(prompt, trace_id, **kwargs)

    def _call_llm(self, prompt: str, **kwargs) -> str:
        import httpx
        import time

        # 逐Agent LLM 配置（动态解析，支持环境变量在运行时修改）
        api_key = self._resolve_llm_config("API_KEY", os.environ.get("FDT_LLM_API_KEY"))
        api_base = self._resolve_llm_config("API_BASE", os.environ.get("FDT_LLM_API_BASE", "https://api.deepseek.com/v1"))
        model = self._resolve_llm_config("MODEL", os.environ.get("FDT_LLM_MODEL", "deepseek-chat"))

        logger.debug(f"[LLM] Agent={self.agent_name}, API_BASE={api_base}, "
                     f"API_KEY present: {bool(api_key)}, len={len(api_key) if api_key else 0}")

        if not api_key:
            # 尝试从其他环境变量获取（OPENAI_API_KEY 作为兜底 fallback）
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if api_key:
                logger.info(f"[LLM] Agent={self.agent_name}, Using OPENAI_API_KEY instead (len={len(api_key)})")
            else:
                raise ValueError("FDT_LLM_API_KEY environment variable not set")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        data = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        max_retries = 3
        backoff = 2

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=120) as client:
                    response = client.post(f"{api_base}/chat/completions", headers=headers, json=data)
                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
            except httpx.HTTPError as e:
                if attempt < max_retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise e
            except Exception as e:
                raise e


class AgentRegistry:
    _agents: Dict[str, FdtAgentExecutor] = {}

    @classmethod
    def register(cls, agent_name: str, executor: FdtAgentExecutor):
        cls._agents[agent_name] = executor
        logger.info(f"Registered agent: {agent_name}")

    @classmethod
    def get(cls, agent_name: str) -> Optional[FdtAgentExecutor]:
        return cls._agents.get(agent_name)

    @classmethod
    def load_from_directory(cls, agents_dir: str = "agents"):
        import glob

        md_files = glob.glob(os.path.join(agents_dir, "*.md"))
        for md_file in md_files:
            agent_name = os.path.basename(md_file).replace(".md", "")
            try:
                config = cls._parse_agent_md(md_file)
                executor = FdtAgentExecutor(config)
                cls.register(agent_name, executor)
            except Exception as e:
                logger.warning(f"Failed to load agent {agent_name}: {e}")

    @classmethod
    def _parse_agent_md(cls, md_path: str) -> Dict[str, Any]:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        config = {
            "name": os.path.basename(md_path).replace(".md", ""),
            "role": "",
            "system_prompt": "",
        }

        in_role = False
        in_system_prompt = False
        system_prompt_lines = []

        for line in lines:
            if line.startswith("#"):
                config["role"] = line.replace("#", "").strip()
                in_role = True
                continue
            if line.startswith("##") and "system" in line.lower():
                in_system_prompt = True
                continue
            if line.startswith("##") and in_system_prompt:
                break
            if in_system_prompt:
                system_prompt_lines.append(line)

        config["system_prompt"] = "\n".join(system_prompt_lines).strip()
        return config


class DebateAgentExecutor:
    def __init__(self):
        self.registry = AgentRegistry()
        self.registry.load_from_directory()

    def execute_agent(self, agent_name: str, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]:
        executor = self.registry.get(agent_name)
        if not executor:
            raise ValueError(f"Agent {agent_name} not registered")
        return executor.execute(prompt, trace_id, **kwargs)

    def execute_parallel(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for task in tasks:
            try:
                result = self.execute_agent(
                    agent_name=task["agent_name"],
                    prompt=task["prompt"],
                    trace_id=task.get("trace_id", ""),
                    **task.get("kwargs", {})
                )
                results.append(result)
            except Exception as e:
                results.append({
                    "agent_name": task["agent_name"],
                    "error": str(e),
                    "trace_id": task.get("trace_id", ""),
                })
        return results

    @staticmethod
    def run_single(agent_name: str, context: str,
                   output: str = "",
                   system_override: str = "",
                   temperature: float = 0.0,
                   max_tokens: int = 0,
                   json_mode: bool = False) -> str:
        """运行单个 Agent (G95: 替代 agent_runner.run_agent)"""
        from scripts.fdt_llm import FdtLlm
        import yaml
        import os
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        cfg_path = root / "config" / "agents" / f"{agent_name}.yaml"
        if not cfg_path.exists():
            return f"⚠️ Agent 配置未找到: {agent_name}"

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        system_prompt = system_override or cfg.get("system_prompt", "")
        if not system_prompt:
            return f"⚠️ {agent_name} 无 system_prompt"

        llm = FdtLlm(agent_type=agent_name)
        if json_mode:
            import json as _json
            reply = llm.chat_json(context, system=system_prompt)
            output_text = _json.dumps(reply, ensure_ascii=False, indent=2)
        else:
            output_text = llm.chat(context, system=system_prompt,
                                   temperature=temperature or None,
                                   max_tokens=max_tokens or None)

        if output:
            tmp = output + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(output_text)
            os.replace(tmp, output)

        return output_text


AgentRegistry.load_from_directory()