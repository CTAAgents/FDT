"""
测试 fdt_langgraph.agents 模块
目标覆盖: 71% → 85%+
"""
import json
import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from fdt_langgraph.agents import AgentRegistry, FdtAgentExecutor

# ============================================================
# FdtAgentExecutor 初始化
# ============================================================

class TestFdtAgentExecutorInit:
    """FdtAgentExecutor 初始化测试"""

    def test_init_with_dict(self):
        """使用 dict 类型的 agent_config 初始化"""
        config = {
            "name": "test_agent",
            "role": "analyst",
            "system_prompt": "You are an analyst.",
            "max_tokens": 2048,
            "temperature": 0.5,
        }
        executor = FdtAgentExecutor(config)
        assert executor.agent_name == "test_agent"
        assert executor.role == "analyst"
        assert executor.system_prompt == "You are an analyst."
        assert executor.max_tokens == 2048
        assert executor.temperature == 0.5
        assert executor.agent_config == config

    def test_init_with_dict_minimal(self):
        """使用最小 dict 初始化，验证默认值"""
        config = {"name": "minimal_agent"}
        executor = FdtAgentExecutor(config)
        assert executor.agent_name == "minimal_agent"
        assert executor.role == ""
        assert executor.system_prompt == ""
        assert executor.max_tokens == 4096
        assert executor.temperature == 0.7

    def test_init_with_string_registered(self):
        """使用注册过的 agent name (str) 初始化"""
        config = {
            "name": "pre_registered",
            "role": "helper",
            "system_prompt": "You are a helper.",
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        executor_ref = FdtAgentExecutor(config)
        AgentRegistry.register("pre_registered", executor_ref)

        executor = FdtAgentExecutor("pre_registered")
        assert executor.agent_name == "pre_registered"
        assert executor.role == "helper"
        assert executor.system_prompt == "You are a helper."
        assert executor.max_tokens == 1024
        assert executor.temperature == 0.3

        # cleanup
        AgentRegistry._agents.pop("pre_registered", None)

    def test_init_with_string_not_registered(self):
        """使用未注册的 agent name (str) 初始化，应使用默认值"""
        executor = FdtAgentExecutor("unknown_agent")
        assert executor.agent_name == "unknown_agent"
        assert executor.role == ""
        assert executor.system_prompt == ""
        assert executor.max_tokens == 4096
        assert executor.temperature == 0.7
        assert executor.agent_config == {"name": "unknown_agent"}

    def test_init_with_object_having_get(self):
        """使用支持 .get() 方法的对象初始化"""
        class ConfigLike:
            def get(self, key, default=None):
                return {"name": "obj_agent", "role": "obj_role"}.get(key, default)

        executor = FdtAgentExecutor(ConfigLike())
        assert executor.agent_name == "obj_agent"
        assert executor.role == "obj_role"


# ============================================================
# FdtAgentExecutor.execute() / run()
# ============================================================

class TestFdtAgentExecutorExecute:
    """FdtAgentExecutor.execute() 和 run() 测试"""

    def setup_method(self):
        self.config = {
            "name": "exec_test",
            "role": "tester",
            "system_prompt": "You are a tester.",
            "max_tokens": 2048,
            "temperature": 0.5,
        }
        self.executor = FdtAgentExecutor(self.config)

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value="Mock LLM response")
    def test_execute_success(self, mock_call_llm):
        """execute 成功返回结果"""
        result = self.executor.execute("test prompt", trace_id="trace-001")

        assert result["agent_name"] == "exec_test"
        assert result["role"] == "tester"
        assert result["output"] == "Mock LLM response"
        assert result["trace_id"] == "trace-001"
        assert result["error"] is None
        assert "timestamp" in result
        assert result["metadata"]["prompt_tokens"] == len("test prompt")
        assert result["metadata"]["max_tokens"] == 2048
        assert result["metadata"]["temperature"] == 0.5
        mock_call_llm.assert_called_once_with("test prompt")

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value="Mock LLM response")
    def test_execute_default_trace_id(self, mock_call_llm):
        """execute 不传 trace_id 时使用空字符串"""
        result = self.executor.execute("test prompt")
        assert result["trace_id"] == ""
        assert result["output"] == "Mock LLM response"

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", side_effect=ValueError("LLM failed"))
    def test_execute_error(self, mock_call_llm):
        """execute 在 LLM 调用失败时返回 error 信息"""
        result = self.executor.execute("test prompt", trace_id="trace-err")

        assert result["agent_name"] == "exec_test"
        assert result["error"] == "LLM failed"
        assert result["output"] == ""
        assert result["trace_id"] == "trace-err"

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value="")
    def test_execute_empty_response(self, mock_call_llm):
        """LLM 返回空字符串时应正常处理（非异常）"""
        result = self.executor.execute("test prompt")
        assert result["output"] == ""
        assert result["error"] is None

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value="   ")
    def test_execute_whitespace_response(self, mock_call_llm):
        """LLM 返回空白字符串时应正常处理"""
        result = self.executor.execute("test prompt")
        assert result["output"] == "   "
        assert result["error"] is None

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value='{"key": "value"}')
    def test_execute_json_response(self, mock_call_llm):
        """LLM 返回 JSON 字符串"""
        result = self.executor.execute("test prompt")
        assert result["output"] == '{"key": "value"}'
        # 检查返回的字符串可被解析
        parsed = json.loads(result["output"])
        assert parsed["key"] == "value"

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", side_effect=[Exception("Timeout"), "retry ok"])
    def test_execute_retry_then_success_not_applied(self, mock_call_llm):
        """execute 不负责重试，只捕获异常——所以第一次异常就返回 error"""
        # execute 方法只是 try/except 包裹 _call_llm，不负责重试
        result = self.executor.execute("test prompt")
        assert result["error"] == "Timeout"
        assert result["output"] == ""


class TestFdtAgentExecutorRun:
    """FdtAgentExecutor.run() async 方法测试"""

    def setup_method(self):
        self.config = {
            "name": "async_test",
            "role": "async_tester",
            "system_prompt": "You are async tester.",
        }
        self.executor = FdtAgentExecutor(self.config)

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", return_value="Async response")
    @pytest.mark.asyncio
    async def test_run_delegates_to_execute(self, mock_call_llm):
        """run() async 方法委托给 execute()"""
        result = await self.executor.run("async prompt", trace_id="async-001")
        assert result["output"] == "Async response"
        assert result["trace_id"] == "async-001"
        assert result["agent_name"] == "async_test"

    @patch("fdt_langgraph.agents.FdtAgentExecutor._call_llm", side_effect=RuntimeError("Async fail"))
    @pytest.mark.asyncio
    async def test_run_error_handling(self, mock_call_llm):
        """run() 在异常时返回 error 信息"""
        result = await self.executor.run("bad prompt", trace_id="async-err")
        assert result["error"] == "Async fail"
        assert result["output"] == ""


# ============================================================
# FdtAgentExecutor._call_llm
# ============================================================

class TestCallLlm:
    """_call_llm 内部方法测试（通过 mock httpx）"""

    def setup_method(self):
        self.config = {
            "name": "llm_test",
            "role": "tester",
            "system_prompt": "You are a helpful assistant.",
        }
        self.executor = FdtAgentExecutor(self.config)

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "test-key-123", "FDT_LLM_API_BASE": "https://test.api.com/v1", "FDT_LLM_MODEL": "test-model"})
    @patch("httpx.Client")
    def test_call_llm_success(self, mock_client_class):
        """_call_llm 成功调用并返回内容"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from LLM"}}]
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_response
        mock_client_class.return_value = mock_client_instance

        result = self.executor._call_llm("What is AI?")
        assert result == "Hello from LLM"

        # 验证请求参数
        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        assert call_args[0][0] == "https://test.api.com/v1/chat/completions"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-key-123"
        assert call_args[1]["json"]["model"] == "test-model"
        assert call_args[1]["json"]["messages"][0]["role"] == "system"
        assert call_args[1]["json"]["messages"][0]["content"] == "You are a helpful assistant."
        assert call_args[1]["json"]["messages"][1]["role"] == "user"
        assert call_args[1]["json"]["messages"][1]["content"] == "What is AI?"

    @patch.dict(os.environ, {}, clear=True)
    def test_call_llm_no_api_key(self):
        """FDT_LLM_API_KEY 未设置时抛出 ValueError"""
        with pytest.raises(ValueError, match="FDT_LLM_API_KEY environment variable not set"):
            self.executor._call_llm("test")

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "", "OPENAI_API_KEY": ""}, clear=True)
    def test_call_llm_empty_api_key(self):
        """FDT_LLM_API_KEY 和 OPENAI_API_KEY 均为空时抛出 ValueError"""
        with pytest.raises(ValueError, match="FDT_LLM_API_KEY environment variable not set"):
            self.executor._call_llm("test")

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "", "OPENAI_API_KEY": "openai-key-456"}, clear=True)
    @patch("httpx.Client")
    def test_call_llm_fallback_openai_key(self, mock_client_class):
        """FDT_LLM_API_KEY 为空时回退到 OPENAI_API_KEY"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Using fallback"}}]
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_response
        mock_client_class.return_value = mock_client_instance

        result = self.executor._call_llm("test fallback")
        assert result == "Using fallback"
        # 验证使用的是 OPENAI_API_KEY
        call_args = mock_client_instance.post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer openai-key-456"

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "key-retry", "FDT_LLM_API_BASE": "https://api.test.com/v1"})
    @patch("httpx.Client")
    def test_call_llm_retry_on_http_error(self, mock_client_class):
        """_call_llm 在 HTTP 错误时重试，最终成功"""
        mock_response_fail = MagicMock()
        mock_response_fail.raise_for_status.side_effect = __import__("httpx").HTTPError("503 Service Unavailable")

        mock_response_ok = MagicMock()
        mock_response_ok.json.return_value = {
            "choices": [{"message": {"content": "Success after retry"}}]
        }

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        # 第一次失败，第二次成功
        mock_client_instance.post.side_effect = [mock_response_fail, mock_response_ok]
        mock_client_class.return_value = mock_client_instance

        with patch("time.sleep") as mock_sleep:
            result = self.executor._call_llm("retry test")
            assert result == "Success after retry"
            assert mock_client_instance.post.call_count == 2
            mock_sleep.assert_called_once_with(2)

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "key-retry-fail"})
    @patch("httpx.Client")
    def test_call_llm_retry_exhausted(self, mock_client_class):
        """_call_llm 重试耗尽后抛出异常"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = __import__("httpx").HTTPError("Always fails")
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_response
        mock_client_class.return_value = mock_client_instance

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(__import__("httpx").HTTPError, match="Always fails"):
                self.executor._call_llm("retry exhaust test")
            assert mock_client_instance.post.call_count == 3
            assert mock_sleep.call_count == 2  # 两次 sleep（attempt=0 和 attempt=1）

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "key-generic"})
    def test_call_llm_generic_exception(self):
        """_call_llm 遇到通用异常（非 HTTPError）直接抛出"""
        with patch("httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__.return_value = mock_client_instance
            mock_client_instance.post.side_effect = ValueError("Unexpected error")
            mock_client_class.return_value = mock_client_instance

            with pytest.raises(ValueError, match="Unexpected error"):
                self.executor._call_llm("generic error test")


# ============================================================
# AgentRegistry
# ============================================================

class TestAgentRegistry:
    """AgentRegistry 测试"""

    def setup_method(self):
        # 每次测试前清理注册表，避免跨测试污染
        AgentRegistry._agents.clear()

    def test_register_and_get(self):
        """register 后可通过 get 获取"""
        config = {"name": "reg_agent", "role": "reg_role", "system_prompt": "prompt"}
        executor = FdtAgentExecutor(config)
        AgentRegistry.register("reg_agent", executor)

        retrieved = AgentRegistry.get("reg_agent")
        assert retrieved is not None
        assert retrieved.agent_name == "reg_agent"
        assert retrieved.role == "reg_role"

    def test_get_nonexistent(self):
        """get 不存在的 agent 返回 None"""
        result = AgentRegistry.get("nonexistent")
        assert result is None

    def test_register_overwrite(self):
        """重复 register 会覆盖已有 agent"""
        e1 = FdtAgentExecutor({"name": "dup", "role": "v1"})
        e2 = FdtAgentExecutor({"name": "dup", "role": "v2"})

        AgentRegistry.register("dup", e1)
        AgentRegistry.register("dup", e2)

        retrieved = AgentRegistry.get("dup")
        assert retrieved.role == "v2"

    def test_register_multiple_agents(self):
        """注册多个 agent"""
        agents = {
            "agent_a": FdtAgentExecutor({"name": "agent_a", "role": "role_a"}),
            "agent_b": FdtAgentExecutor({"name": "agent_b", "role": "role_b"}),
            "agent_c": FdtAgentExecutor({"name": "agent_c", "role": "role_c"}),
        }
        for name, executor in agents.items():
            AgentRegistry.register(name, executor)

        assert AgentRegistry.get("agent_a").role == "role_a"
        assert AgentRegistry.get("agent_b").role == "role_b"
        assert AgentRegistry.get("agent_c").role == "role_c"
        assert AgentRegistry.get("nonexistent") is None


class TestAgentRegistryLoadFromDirectory:
    """AgentRegistry.load_from_directory() 测试"""

    def setup_method(self):
        AgentRegistry._agents.clear()

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open, read_data="# Analyst\n\n## System Prompt\nYou are an analyst.\n")
    def test_load_from_directory_success(self, mock_open_file, mock_glob):
        """从目录成功加载 agent markdown 文件"""
        mock_glob.return_value = ["agents/analyst.md"]

        AgentRegistry.load_from_directory("agents")

        assert mock_glob.call_count >= 1
        agent = AgentRegistry.get("analyst")
        assert agent is not None
        assert agent.agent_name == "analyst"
        # v9.x 修复：`# ` 不再匹配 `##`，role 为 "# Analyst" 的文本
        assert agent.role == "Analyst"
        # v9.x 修复：system_prompt 收集逻辑正常工作
        assert agent.system_prompt == "You are an analyst."

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open, read_data="# Trader\n\n## system prompt\nExecute trades.\n")
    def test_load_from_directory_case_insensitive_section(self, mock_open_file, mock_glob):
        """解析 agent md 时 ## system 大小写不敏感"""
        mock_glob.return_value = ["agents/trader.md"]

        AgentRegistry.load_from_directory("agents")

        agent = AgentRegistry.get("trader")
        assert agent is not None
        # v9.x 修复：`# Trader` → role="Trader"
        assert agent.role == "Trader"
        assert agent.system_prompt == "Execute trades."

    @patch("glob.glob")
    def test_load_from_directory_no_files(self, mock_glob):
        """目录中没有 .md 文件"""
        mock_glob.return_value = []

        AgentRegistry.load_from_directory("empty_dir")

        assert len(AgentRegistry._agents) == 0

    @patch("glob.glob")
    def test_load_from_directory_parse_failure_skipped(self, mock_glob):
        """解析失败的 md 文件被跳过（log warning）"""
        mock_glob.return_value = ["agents/broken.md"]

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            AgentRegistry.load_from_directory("agents")

        assert AgentRegistry.get("broken") is None
        assert len(AgentRegistry._agents) == 0

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open, read_data="# Multi Role\n\n## System Prompt\nLine 1\nLine 2\nLine 3\n")
    def test_load_from_directory_multiline_prompt(self, mock_open_file, mock_glob):
        """解析多行 system prompt"""
        mock_glob.return_value = ["agents/multi_role.md"]

        AgentRegistry.load_from_directory("agents")

        agent = AgentRegistry.get("multi_role")
        assert agent is not None
        # v9.x 修复：`# Multi Role` → role="Multi Role"
        assert agent.role == "Multi Role"
        # v9.x 修复：system_prompt 收集 "Line 1\nLine 2\nLine 3"
        assert agent.system_prompt == "Line 1\nLine 2\nLine 3"

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open, read_data="# No Prompt\n")
    def test_load_from_directory_no_system_prompt_section(self, mock_open_file, mock_glob):
        """md 文件没有 ## System Prompt 部分"""
        mock_glob.return_value = ["agents/no_prompt.md"]

        AgentRegistry.load_from_directory("agents")

        agent = AgentRegistry.get("no_prompt")
        assert agent is not None
        assert agent.role == "No Prompt"
        assert agent.system_prompt == ""

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open, read_data="# Agent 1\n\n## System Prompt\nAgent1 prompt\n")
    def test_load_from_directory_multiple_files(self, mock_open_file, mock_glob):
        """加载多个 md 文件"""
        mock_glob.return_value = ["agents/agent1.md", "agents/agent2.md"]

        # mock_open 每次返回相同内容，但文件名不同会解析为不同 agent_name
        AgentRegistry.load_from_directory("agents")

        agent1 = AgentRegistry.get("agent1")
        agent2 = AgentRegistry.get("agent2")
        assert agent1 is not None
        assert agent2 is not None


class TestAgentRegistryParseAgentMd:
    """AgentRegistry._parse_agent_md 内部解析逻辑"""

    @patch("builtins.open", new_callable=mock_open, read_data="# Senior Analyst\n\n## System Prompt\nYou are a senior analyst.\n")
    def test_parse_basic(self, mock_open_file):
        """基本解析：`# ` 设置 role，`##` + role 开启 system_prompt 收集"""
        config = AgentRegistry._parse_agent_md("/fake/path/analyst.md")
        assert config["name"] == "analyst"
        # v9.x 修复：`# ` 不再匹配 `##`，role 为 "Senior Analyst"
        assert config["role"] == "Senior Analyst"
        # v9.x 修复：system_prompt 收集逻辑正常工作
        assert config["system_prompt"] == "You are a senior analyst."

    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_parse_empty_file(self, mock_open_file):
        """空文件解析"""
        config = AgentRegistry._parse_agent_md("/fake/path/empty.md")
        assert config["name"] == "empty"
        assert config["role"] == ""
        assert config["system_prompt"] == ""

    @patch("builtins.open", new_callable=mock_open, read_data="Some text without heading\n\nNo markdown structure.\n")
    def test_parse_no_heading(self, mock_open_file):
        """无 # 标题的文件"""
        config = AgentRegistry._parse_agent_md("/fake/path/no_heading.md")
        assert config["name"] == "no_heading"
        assert config["role"] == ""
        assert config["system_prompt"] == ""

    @patch("builtins.open", new_callable=mock_open, read_data="# Role\n\n## System Prompt\nLine1\n\n## Another Section\nNot system prompt\n")
    def test_parse_stops_at_next_section(self, mock_open_file):
        """解析器：`# ` 设置 role，system_prompt 收集到下一个 `##` 为止"""
        config = AgentRegistry._parse_agent_md("/fake/path/sectioned.md")
        # v9.x 修复：`# Role` → role="Role"
        assert config["role"] == "Role"
        # v9.x 修复：system_prompt 收集 "## System Prompt" 和 "## Another Section" 之间的内容
        assert config["system_prompt"] == "Line1"


# ============================================================
# DebateAgentExecutor
# ============================================================

class TestDebateAgentExecutor:
    """DebateAgentExecutor 测试"""

    def setup_method(self):
        AgentRegistry._agents.clear()

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_init_calls_load_from_directory(self, mock_load):
        """DebateAgentExecutor 初始化时调用 load_from_directory"""
        from fdt_langgraph.agents import DebateAgentExecutor

        executor = DebateAgentExecutor()
        mock_load.assert_called_once()

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_execute_agent_not_registered(self, mock_load):
        """execute_agent 使用未注册的 agent 应抛出 ValueError"""
        from fdt_langgraph.agents import DebateAgentExecutor

        executor = DebateAgentExecutor()
        with pytest.raises(ValueError, match="Agent nonexistent_agent not registered"):
            executor.execute_agent("nonexistent_agent", "test prompt")

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_execute_agent_success(self, mock_load):
        """execute_agent 成功执行"""
        from fdt_langgraph.agents import DebateAgentExecutor

        # 注册一个 agent
        config = {"name": "debater1", "role": "debater", "system_prompt": "Debate!"}
        agent_executor = FdtAgentExecutor(config)
        AgentRegistry.register("debater1", agent_executor)

        debate = DebateAgentExecutor()
        with patch.object(agent_executor, "_call_llm", return_value="Debate argument") as mock_llm:
            result = debate.execute_agent("debater1", "Argue for X", trace_id="deb-001")
            assert result["output"] == "Debate argument"
            assert result["agent_name"] == "debater1"
            assert result["trace_id"] == "deb-001"
            mock_llm.assert_called_once_with("Argue for X")

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_execute_parallel_all_success(self, mock_load):
        """execute_parallel 所有任务成功"""
        from fdt_langgraph.agents import DebateAgentExecutor

        config1 = {"name": "bull", "role": "bullish", "system_prompt": "Bull"}
        config2 = {"name": "bear", "role": "bearish", "system_prompt": "Bear"}
        e1 = FdtAgentExecutor(config1)
        e2 = FdtAgentExecutor(config2)
        AgentRegistry.register("bull", e1)
        AgentRegistry.register("bear", e2)

        debate = DebateAgentExecutor()
        with patch.object(e1, "_call_llm", return_value="Bullish case") as mock_bull:
            with patch.object(e2, "_call_llm", return_value="Bearish case") as mock_bear:
                tasks = [
                    {"agent_name": "bull", "prompt": "Argue bullish", "trace_id": "p-001"},
                    {"agent_name": "bear", "prompt": "Argue bearish", "trace_id": "p-002"},
                ]
                results = debate.execute_parallel(tasks)
                assert len(results) == 2
                assert results[0]["output"] == "Bullish case"
                assert results[1]["output"] == "Bearish case"

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_execute_parallel_partial_failure(self, mock_load):
        """execute_parallel 部分任务失败不应影响其他任务"""
        from fdt_langgraph.agents import DebateAgentExecutor

        config = {"name": "worker", "role": "worker", "system_prompt": "Work"}
        worker = FdtAgentExecutor(config)
        AgentRegistry.register("worker", worker)

        debate = DebateAgentExecutor()
        with patch.object(worker, "_call_llm", side_effect=[RuntimeError("Fail"), "Success"]):
            tasks = [
                {"agent_name": "worker", "prompt": "Task 1", "trace_id": "fail-1"},
                {"agent_name": "worker", "prompt": "Task 2", "trace_id": "fail-2"},
            ]
            results = debate.execute_parallel(tasks)
            assert results[0]["error"] == "Fail"
            assert results[1]["output"] == "Success"

    @patch("fdt_langgraph.agents.AgentRegistry.load_from_directory")
    def test_execute_parallel_unknown_agent(self, mock_load):
        """execute_parallel 中未知 agent 返回 error 字典"""
        from fdt_langgraph.agents import DebateAgentExecutor

        debate = DebateAgentExecutor()
        tasks = [
            {"agent_name": "unknown", "prompt": "test", "trace_id": "unk-001"},
        ]
        results = debate.execute_parallel(tasks)
        assert results[0]["error"] == "Agent unknown not registered"
        assert results[0]["agent_name"] == "unknown"
        assert results[0]["trace_id"] == "unk-001"


# ============================================================
# 辅助函数 / 初始化逻辑
# ============================================================

class TestModuleInit:
    """模块级初始化行为测试"""

    def test_module_level_load_from_directory_called(self):
        """模块加载时调用了 AgentRegistry.load_from_directory()
        （验证 agents.py 最后一行已被执行）"""
        # 由于 import 时已经执行了 load_from_directory()
        # 且 conftest 不会影响这个调用，我们只需验证该方法可被导入即可
        from fdt_langgraph import agents
        assert hasattr(agents, "AgentRegistry")
        assert hasattr(agents, "FdtAgentExecutor")


# ============================================================
# 逐Agent LLM 配置测试 (v8.9.1)
# ============================================================

class TestPerAgentLlmConfig:
    """逐Agent LLM 配置功能测试"""

    def test_normalize_env_name_simple(self):
        """_normalize_env_name: 简单名称转为大写"""
        assert FdtAgentExecutor._normalize_env_name("judge") == "JUDGE"
        assert FdtAgentExecutor._normalize_env_name("risk_manager") == "RISK_MANAGER"
        assert FdtAgentExecutor._normalize_env_name("TECHNICAL_RESEARCHER") == "TECHNICAL_RESEARCHER"

    def test_normalize_env_name_special_chars(self):
        """_normalize_env_name: 特殊字符转下划线"""
        assert FdtAgentExecutor._normalize_env_name("my-agent") == "MY_AGENT"
        assert FdtAgentExecutor._normalize_env_name("agent.v2") == "AGENT_V2"
        assert FdtAgentExecutor._normalize_env_name("agent@special!") == "AGENT_SPECIAL"

    def test_normalize_env_name_multiple_underscores(self):
        """_normalize_env_name: 多重下划线合并"""
        assert FdtAgentExecutor._normalize_env_name("a__b___c") == "A_B_C"

    def test_normalize_env_name_empty(self):
        """_normalize_env_name: 空字符串"""
        assert FdtAgentExecutor._normalize_env_name("") == ""

    def test_normalize_env_name_only_special(self):
        """_normalize_env_name: 仅含特殊字符"""
        result = FdtAgentExecutor._normalize_env_name("@#$%")
        assert result == "" or result == "_"

    @patch.dict(os.environ, {"FDT_LLM_TECHNICAL_RESEARCHER_API_KEY": "per-agent-key-123"})
    def test_resolve_llm_config_per_agent_takes_priority(self):
        """_resolve_llm_config: 逐Agent 环境变量优先于全局变量"""
        executor = FdtAgentExecutor({"name": "technical_researcher"})
        assert executor._resolve_llm_config("API_KEY", "") == "per-agent-key-123"

    @patch.dict(os.environ, {
        "FDT_LLM_API_KEY": "global-key",
        "FDT_LLM_TECHNICAL_RESEARCHER_API_KEY": "per-agent-key",
    })
    def test_resolve_llm_config_per_agent_overrides_global(self):
        """_resolve_llm_config: 逐Agent 环境变量覆盖全局"""
        executor = FdtAgentExecutor({"name": "technical_researcher"})
        assert executor._resolve_llm_config("API_KEY", "") == "per-agent-key"

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "global-key"})
    def test_resolve_llm_config_fallback_to_global(self):
        """_resolve_llm_config: 无逐Agent 变量时回退到全局（通过 default 参数传递）"""
        executor = FdtAgentExecutor({"name": "some_agent"})
        # _call_llm 中的实际调用模式：_resolve_llm_config("API_KEY", os.environ.get("FDT_LLM_API_KEY"))
        result = executor._resolve_llm_config("API_KEY", os.environ.get("FDT_LLM_API_KEY", ""))
        assert result == "global-key"

    @patch.dict(os.environ, {}, clear=True)
    def test_resolve_llm_config_fallback_to_default(self):
        """_resolve_llm_config: 无任何环境变量时使用传入默认值"""
        executor = FdtAgentExecutor({"name": "some_agent"})
        assert executor._resolve_llm_config("API_BASE", "https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"
        assert executor._resolve_llm_config("MODEL", "deepseek-chat") == "deepseek-chat"
        assert executor._resolve_llm_config("API_KEY", "") == ""  # 无环境变量时返回传入的默认值

    @patch.dict(os.environ, {}, clear=True)
    def test_resolve_llm_config_defaults_for_empty_name(self):
        """_resolve_llm_config: agent_name 为空时使用传入的默认值"""
        executor = FdtAgentExecutor({"name": ""})
        assert executor._resolve_llm_config("API_KEY", "default-key") == "default-key"

    def test_resolve_llm_config_via_dict_init(self):
        """通过 dict 初始化时仍正确解析逐Agent 配置"""
        executor = FdtAgentExecutor({"name": "risk_manager", "role": "Risk Manager"})
        assert executor.agent_name == "risk_manager"
        # _resolve_llm_config 使用当前 os.environ 的值
        key = executor._resolve_llm_config("API_KEY", "some-default")
        base = executor._resolve_llm_config("API_BASE", "https://api.deepseek.com/v1")
        model = executor._resolve_llm_config("MODEL", "deepseek-chat")
        assert base is not None
        assert model is not None

    def test_resolve_llm_config_per_agent_api_base_and_model(self):
        """逐Agent API_BASE 和 MODEL 独立解析"""
        with patch.dict(os.environ, {
            "FDT_LLM_FUNDAMENTAL_RESEARCHER_API_BASE": "https://custom.api.com/v1",
            "FDT_LLM_FUNDAMENTAL_RESEARCHER_MODEL": "custom-model",
        }):
            executor = FdtAgentExecutor({"name": "fundamental_researcher"})
            assert executor._resolve_llm_config("API_BASE", "") == "https://custom.api.com/v1"
            assert executor._resolve_llm_config("MODEL", "") == "custom-model"

    @patch.dict(os.environ, {"FDT_LLM_TECHNICAL_RESEARCHER_API_KEY": "tech-key", "FDT_LLM_API_KEY": "global-key"})
    @patch("httpx.Client")
    def test_call_llm_uses_per_agent_config(self, mock_client_class):
        """_call_llm 实际调用时使用逐Agent API Key"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Per-agent LLM response"}}]
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_response
        mock_client_class.return_value = mock_client_instance

        executor = FdtAgentExecutor({"name": "technical_researcher", "system_prompt": "Tech analyst"})
        result = executor._call_llm("Analyze technicals")
        assert result == "Per-agent LLM response"

        # 验证使用的是逐Agent 的 API Key
        call_args = mock_client_instance.post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer tech-key"
        assert call_args[1]["json"]["model"] == "deepseek-chat"  # 默认模型

    @patch.dict(os.environ, {"FDT_LLM_API_KEY": "global-key"})
    @patch("httpx.Client")
    def test_call_llm_uses_global_config_when_no_per_agent(self, mock_client_class):
        """_call_llm: 无逐Agent 配置时使用全局配置"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Global LLM response"}}]
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_response
        mock_client_class.return_value = mock_client_instance

        executor = FdtAgentExecutor({"name": "unknown_agent"})
        result = executor._call_llm("Test")
        assert result == "Global LLM response"

        call_args = mock_client_instance.post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer global-key"

    @patch.dict(os.environ, {
        "FDT_LLM_RISK_MANAGER_API_KEY": "rm-key",
        "FDT_LLM_RISK_MANAGER_API_BASE": "https://rm.api.com/v1",
        "FDT_LLM_RISK_MANAGER_MODEL": "rm-model-v2",
        "FDT_LLM_API_KEY": "global-key",
        "FDT_LLM_API_BASE": "https://global.api.com/v1",
        "FDT_LLM_MODEL": "global-model",
    })
    def test_per_agent_full_config_override(self):
        """逐Agent 完全配置覆盖：API_KEY + API_BASE + MODEL 全部独立"""
        executor = FdtAgentExecutor({"name": "risk_manager"})
        assert executor._resolve_llm_config("API_KEY", "") == "rm-key"
        assert executor._resolve_llm_config("API_BASE", "") == "https://rm.api.com/v1"
        assert executor._resolve_llm_config("MODEL", "") == "rm-model-v2"
