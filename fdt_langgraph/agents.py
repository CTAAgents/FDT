import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fdt_agents")

# D3 Generation 解码控制：加载 decode_config.yaml
_DECODE_CONFIG_CACHE: Optional[dict] = None


def _get_decode_config() -> dict:
    """懒加载 decode_config.yaml，供 FdtAgentExecutor 使用。"""
    global _DECODE_CONFIG_CACHE
    if _DECODE_CONFIG_CACHE is not None:
        return _DECODE_CONFIG_CACHE
    path = Path(__file__).resolve().parent.parent / "config" / "agents" / "decode_config.yaml"
    if not path.exists():
        _DECODE_CONFIG_CACHE = {}
        return _DECODE_CONFIG_CACHE
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            _DECODE_CONFIG_CACHE = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"[DecodeControl] 加载 decode_config.yaml 失败: {e}")
        _DECODE_CONFIG_CACHE = {}
    return _DECODE_CONFIG_CACHE


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
        # D3 Generation: decode_config.yaml 覆盖（优先级最高）
        self._apply_decode_config()

    def _apply_decode_config(self):
        """用 decode_config.yaml 的解码参数覆盖当前配置（优先级最高）。"""
        if not self.agent_name:
            return
        cfg = _get_decode_config().get("agents", {}).get(self.agent_name, {})
        if not cfg:
            return
        if "temperature" in cfg:
            self.temperature = cfg["temperature"]
        if "max_tokens" in cfg:
            self.max_tokens = cfg["max_tokens"]
        # v9.23.0: 注入 response_format + model
        if "response_format" in cfg:
            self.response_format = cfg["response_format"]
        if "model" in cfg:
            self.model = cfg["model"]
        logger.debug(
            f"[DecodeControl] {self.agent_name}: "
            f"temperature={self.temperature}, max_tokens={self.max_tokens}"
        )

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
            self.response_format = getattr(agent, "response_format", None)
            self.agent_config = agent.agent_config
        else:
            self.agent_name = agent_name
            self.role = ""
            self.system_prompt = ""
            self.max_tokens = 4096
            self.temperature = 0.7
            self.response_format = None
            self.agent_config = {"name": agent_name}

    def execute(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]:
        logger.info(f"[trace_id={trace_id}] Executing agent: {self.agent_name}")

        # ── D2 Tool: 工具调用记录 ──
        import time
        _start = time.time()
        try:
            from scripts.tool_metrics import ToolMetrics
            _tm = ToolMetrics()
        except Exception:
            _tm = None

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
            if _tm:
                _tm.record_call(self.agent_name, success=True,
                                latency_ms=(time.time() - _start) * 1000)
            logger.info(f"[trace_id={trace_id}] Agent {self.agent_name} completed successfully")
        except Exception as e:
            result["error"] = str(e)
            if _tm:
                _tm.record_call(self.agent_name, success=False,
                                latency_ms=(time.time() - _start) * 1000)
            logger.error(f"[trace_id={trace_id}] Agent {self.agent_name} failed: {e}")

        return result

    async def run(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]:
        return self.execute(prompt, trace_id, **kwargs)

    def _call_llm(self, prompt: str, **kwargs) -> str:
        import time

        import httpx

        # 逐Agent LLM 配置（动态解析，支持环境变量在运行时修改）
        api_key = self._resolve_llm_config("API_KEY", os.environ.get("FDT_LLM_API_KEY"))
        api_base = self._resolve_llm_config("API_BASE", os.environ.get("FDT_LLM_API_BASE", "https://api.deepseek.com/v1"))
        model = self._resolve_llm_config("MODEL", os.environ.get("FDT_LLM_MODEL", "deepseek-v4-flash"))

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

        # ── 统一使用 OpenAI 标准消息格式 ──
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

        # v9.23.0: 注入 response_format 硬件约束
        # 改成vendor-aware：适配器自动过滤目标模型不支持的字段
        _use_json_response = False
        if getattr(self, "response_format", None):
            data["response_format"] = {"type": "json_object"}
            _use_json_response = True

        # ── 通过适配器进行参数清洗 + 厂商兼容转换 ──
        from fdt_langgraph.llm_adapter import adapt_request, adapt_response, pre_validate_request
        data = adapt_request(data, api_base)

        # ── DeepSeek json_object 兼容：prompt 必须含 "json" ──
        if _use_json_response:
            _all_text = ""
            for m in data.get("messages", []):
                if isinstance(m.get("content"), str):
                    _all_text += m["content"]
            if "json" not in _all_text.lower():
                # 在 user message 末尾追加 JSON 格式要求
                for m in data.get("messages", []):
                    if m.get("role") == "user":
                        m["content"] = str(m.get("content", "")) + "\n\n请以 JSON 格式输出。"
                        break

        # ── 前置校验：在发请求前拦截非法结构 ──
        violations = pre_validate_request(data)
        if violations:
            logger.warning(f"[LLM] Agent={self.agent_name}, 请求前置校验问题: {violations}")
            # 松弛处理：仅警告不阻断，避免空 system_prompt 阻挡调试

        # ── 硬截断：防止 3M tokens 打爆模型 ──
        _MAX_MSG_CHARS = 500_000  # ≈ 125K tokens 安全余量留给 system prompt
        for i, m in enumerate(data.get("messages", [])):
            if isinstance(m.get("content"), str):
                _len = len(m["content"])
                if _len > _MAX_MSG_CHARS:
                    logger.warning(f"[LLM] Agent={self.agent_name}, messages[{i}] role={m.get('role')} 超长({_len} chars)，截断至 {_MAX_MSG_CHARS}")
                    m["content"] = m["content"][:_MAX_MSG_CHARS] + "\n\n[系统截断: 消息超长]"
                elif _len > 100_000:
                    logger.warning(f"[LLM] Agent={self.agent_name}, messages[{i}] role={m.get('role')} 较大({_len} chars)")
                elif _len == 0:
                    logger.warning(f"[LLM] Agent={self.agent_name}, messages[{i}] role={m.get('role')} content 为空")

        # ── 请求日志 Dump（调试用） ──
        import json as _json
        _dump_flag = os.environ.get("FDT_LLM_DUMP", "").lower() in ("1", "true", "yes")
        if _dump_flag:
            _dump_path = os.path.join(
                os.environ.get("FDT_REPORT_WORKSPACE", "."),
                f"llm_request_{self.agent_name}_{int(time.time())}.json"
            )
            try:
                _dump_data = {"api_base": api_base, "payload": data}
                with open(_dump_path, "w", encoding="utf-8") as _f:
                    _json.dump(_dump_data, _f, ensure_ascii=False, indent=2)
                logger.info("[LLM_DUMP] Agent=%s payload written to %s", self.agent_name, _dump_path)
            except Exception as _e:
                logger.warning("[LLM_DUMP] Agent=%s dump failed: %s", self.agent_name, _e)

        max_retries = 3
        backoff = 2

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=120) as client:
                    response = client.post(f"{api_base}/chat/completions", headers=headers, json=data)
                    response.raise_for_status()
                    raw = response.json()
                    # 响应反向归一化
                    normalized = adapt_response(raw)
                    return normalized["choices"][0]["message"]["content"]
            except httpx.HTTPError as e:
                # 记录响应体以诊断 400 等错误
                _resp_text = ""
                _status = "?"
                try:
                    if hasattr(e, "response") and e.response is not None:
                        _resp_text = e.response.text[:1000]
                        _status = e.response.status_code
                except Exception:
                    pass
                logger.error(f"[LLM] Agent={self.agent_name}, HTTP error: {e}, status={_status}, body={_resp_text}")
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
        """加载 Agent 配置。优先从 config/agents/*.yaml 加载（含完整 system_prompt），
        回退到 agents/*.md（仅基础信息）。

        YAML 文件含 `name`、`system_prompt`、`temperature`、`max_tokens` 等完整配置。
        Markdown 文件在移行期后废弃（2026-07-24）。
        """
        import glob

        import yaml as _yaml

        # 优先：config/agents/*.yaml
        yaml_dir = os.path.join(os.path.dirname(__file__), "..", "config", "agents")
        yaml_files = glob.glob(os.path.join(yaml_dir, "*.yaml"))
        loaded = set()
        for yf in sorted(yaml_files):
            if os.path.basename(yf) in ("decode_config.yaml",):
                continue
            try:
                with open(yf, "r", encoding="utf-8") as f:
                    cfg = _yaml.safe_load(f) or {}
                if not cfg.get("name"):
                    continue
                agent_name = cfg["name"]
                config = {
                    "name": agent_name,
                    "role": cfg.get("display_name", cfg.get("profession", "")),
                    "system_prompt": cfg.get("system_prompt", ""),
                    "max_tokens": cfg.get("max_tokens", 4096),
                    "temperature": cfg.get("temperature", 0.7),
                }
                # 尝试从 decode_config.yaml 补充解码配置
                _dc = _get_decode_config().get("agents", {}).get(agent_name, {})
                if "response_format" in _dc:
                    config["response_format"] = _dc["response_format"]
                executor = FdtAgentExecutor(config)
                cls.register(agent_name, executor)
                loaded.add(agent_name)
            except Exception as e:
                logger.warning(f"Failed to load agent YAML {yf}: {e}")

        # 回退：agents/*.md（传统方式）
        md_files = glob.glob(os.path.join(agents_dir, "*.md"))
        for md_file in md_files:
            agent_name = os.path.basename(md_file).replace(".md", "")
            if agent_name in loaded:
                continue
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

        in_system_prompt = False
        system_prompt_lines = []

        for line in lines:
            # 单 # 号 → 角色名（仅 `# ` 而非 `##`）
            if line.startswith("# ") and not line.startswith("##"):
                config["role"] = line[2:].strip()
                continue
            # 双 # 号 + "system" 或 "prompt" → system prompt 开始
            if line.startswith("##") and ("system" in line.lower() or "prompt" in line.lower()):
                in_system_prompt = True
                continue
            # 另一个双 # 号节 → system prompt 结束
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
        import os
        from pathlib import Path

        import yaml

        from fdt_langgraph.llm_provider import FdtLlm

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
