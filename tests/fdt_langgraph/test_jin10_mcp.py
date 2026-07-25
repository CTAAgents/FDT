"""金十数据 MCP 采集器测试。

测试级别：
  - 单元测试：MCP 客户端初始化 / 采集器可用检测
  - 集成测试：使用真实 token 调用 list_flash / search_flash 等（需设置 JIN10_MCP_TOKEN
  - 情绪分析测试：读心 Agent 相关功能
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ─── 单元测试（无需 token ───

class TestMcpClientInit:
    """MCP 客户端基础测试。"""

    def test_import_mcp_client(self):
        """测试导入 McpHttpClient。"""
        from futures_data_core.mcp_client import MCP_PROTOCOL_VERSION, McpHttpClient
        assert MCP_PROTOCOL_VERSION == "2025-11-25"
        client = McpHttpClient(
            server_url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer test-token"},
        )
        assert client.server_url == "https://mcp.example.com/mcp"
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "Bearer test-token"

    def test_mcp_error(self):
        """测试 McpError。"""
        from futures_data_core.mcp_client import McpError
        err = McpError(code=-32601, message="Method not found")
        assert err.code == -32601
        assert "Method not found" in str(err)


class TestJin10FetcherInit:
    """金十采集器初始化测试。"""

    def test_available_false_without_token(self, monkeypatch):
        """未设置 token 时 available 为 False。"""
        monkeypatch.delenv("JIN10_MCP_TOKEN", raising=False)
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        assert fetcher.available is False

    def test_available_true_with_token(self, monkeypatch):
        """设置 token 后 available 为 True。"""
        monkeypatch.setenv("JIN10_MCP_TOKEN", "sk-test-token")
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        assert fetcher.available is True
        assert fetcher.server_url == "https://mcp.jin10.com/mcp"

    def test_custom_server_url(self, monkeypatch):
        """自定义服务地址。"""
        monkeypatch.setenv("JIN10_MCP_URL", "https://custom.example.com/mcp")
        monkeypatch.setenv("JIN10_MCP_TOKEN", "sk-test")
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        assert fetcher.server_url == "https://custom.example.com/mcp"

    def test_wrap_list_result(self):
        """测试列表结果包装。"""
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher(token="sk-test")

        result = fetcher._wrap_list_result(
            {"items": [{"id": "1", "title": "test"}], "next_cursor": "page2", "has_more": True},
            "flash"
        )
        assert len(result["items"]) == 1
        assert result["next_cursor"] == "page2"
        assert result["has_more"] is True
        assert result["category"] == "flash"
        assert result["source"] == "jin10_mcp"
        assert "fetched_at" in result


class TestDataSourceAdapter:
    """data_source_adapter 中金十接口测试。"""

    def test_jin10_available_false(self, monkeypatch):
        """未设置 token 时 jin10_available 返回 False。"""
        monkeypatch.delenv("JIN10_MCP_TOKEN", raising=False)
        import importlib

        import data_source_adapter
        importlib.reload(data_source_adapter)
        # 单例缓存，重置
        data_source_adapter._jin10_fetcher = None
        assert data_source_adapter.jin10_available() is False


# ─── 集成测试（需真实 token） ───

HAS_TOKEN = bool(os.environ.get("JIN10_MCP_TOKEN"))


@pytest.mark.skipif(not HAS_TOKEN, reason="未设置 JIN10_MCP_TOKEN")
@pytest.mark.asyncio
class TestJin10Integration:
    """金十 MCP 集成测试（需真实 token）。"""

    async def test_initialize(self):
        """测试 MCP initialize。"""
        from futures_data_core.mcp_client import McpHttpClient
        token = os.environ["JIN10_MCP_TOKEN"]
        client = McpHttpClient(
            server_url="https://mcp.jin10.com/mcp",
            headers={"Authorization": "Bearer " + token},
        )
        result = await client.initialize()
        assert "protocolVersion" in result
        await client.close()

    async def test_list_tools(self):
        """测试列出工具。"""
        from futures_data_core.mcp_client import McpHttpClient
        token = os.environ["JIN10_MCP_TOKEN"]
        client = McpHttpClient(
            server_url="https://mcp.jin10.com/mcp",
            headers={"Authorization": "Bearer " + token},
        )
        result = await client.list_tools()
        assert "tools" in result
        tool_names = [t["name"] for t in result.get("tools", [])]
        assert "list_flash" in tool_names
        assert "search_flash" in tool_names
        assert "get_quote" in tool_names
        await client.close()

    async def test_list_flash(self):
        """测试获取快讯列表。"""
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        result = await fetcher.list_flash()
        assert "items" in result
        assert isinstance(result["items"], list)
        assert result["source"] == "jin10_mcp"
        await fetcher.close()

    async def test_search_flash(self):
        """测试搜索快讯。"""
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        result = await fetcher.search_flash("黄金")
        assert "items" in result
        assert isinstance(result["items"], list)
        await fetcher.close()

    async def test_list_calendar(self):
        """测试财经日历。"""
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        result = await fetcher.list_calendar()
        assert "items" in result
        assert isinstance(result["items"], list)
        await fetcher.close()

    async def test_get_quote(self):
        """测试获取外盘报价。"""
        from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
        fetcher = Jin10McpFetcher()
        result = await fetcher.get_quote("XAUUSD")
        assert "code" in result or "name" in result
        await fetcher.close()


# ════════════════════════════════════════════════════════════
# 金十 Context 注入测试
# ════════════════════════════════════════════════════════════

class TestNewsRouter:
    """测试 NewsRouter 新闻路由器（替代旧的 _build_jin10_context 测试）。"""

    def test_symbol_to_keywords_mapping(self):
        """验证所有常见品种在 Jin10NewsSource 中有对应的中文关键词映射。"""
        from data_adapter.news.sources.jin10_source import SYMBOL_TO_KEYWORDS

        # 核心品种必须有映射
        core_symbols = ["RB", "CU", "I", "SC", "TA", "M", "P", "PK", "UR", "LH"]
        for sym in core_symbols:
            assert sym in SYMBOL_TO_KEYWORDS, f"{sym} 缺少中文关键词映射"
            assert len(SYMBOL_TO_KEYWORDS[sym]) > 0, f"{sym} 的关键词列表为空"

    def test_build_prompt_context_empty(self):
        """空结果时返回提示信息。"""
        from data_adapter.news import NewsRouter
        from data_adapter.news.types import NewsResult

        text = NewsRouter.build_prompt_context(NewsResult())
        assert "暂无" in text

    def test_build_prompt_context_formats_items(self):
        """非空结果正确格式化。"""
        from data_adapter.news import NewsRouter
        from data_adapter.news.types import NewsItem, NewsResult, NewsSourceType

        result = NewsResult()
        result.items = [
            NewsItem(
                symbol="RB", source_type=NewsSourceType.JIN10, source_name="金十快讯",
                title="螺纹钢周度表需回升", content="螺纹钢周度表需环比回升5%，华东出库加速",
                time="2026-07-22 10:30", confidence=0.8,
                event_type="supply_demand",
            ),
        ]
        text = NewsRouter.build_prompt_context(result)
        assert "【RB】" in text
        assert "螺纹钢" in text
        assert "[jin10]" in text

    def test_build_quality_report_grading(self):
        """验证质量报告的分级逻辑。"""
        from data_adapter.news import NewsRouter
        from data_adapter.news.types import NewsItem, NewsResult, NewsSourceType

        # 6 条 RB 新闻 → RICH, 0 条 CU → NO_DATA
        result = NewsResult()
        for i in range(6):
            result.items.append(NewsItem(
                symbol="RB", source_type=NewsSourceType.JIN10, source_name="金十快讯",
                title=f"新闻{i}", content=f"新闻{i}内容",
                time="2026-07-22 10:00",
            ))

        report = NewsRouter.build_quality_report(result, ["RB", "CU"])
        assert report["RB"]["data_grade"] == "RICH"
        assert report["CU"]["data_grade"] == "NO_DATA"


# ════════════════════════════════════════════════════════════
# 新闻情绪分析（读心）测试
# ════════════════════════════════════════════════════════════

class TestSentimentAnalyst:
    """测试新闻情绪分析相关功能（单元测试，mock 依赖）。"""

    def test_sentiment_contract_import(self):
        """验证情绪契约可以正常导入。"""
        from contracts import SentimentEvent, SentimentStateVector, SymbolSentiment

        assert SentimentStateVector.__name__ == "SentimentStateVector"
        assert SentimentEvent.__name__ == "SentimentEvent"
        assert SymbolSentiment.__name__ == "SymbolSentiment"

    def test_sentiment_contract_fields(self):
        """验证 SentimentStateVector 包含预期字段。"""
        from contracts import SentimentStateVector

        fields = list(SentimentStateVector.model_fields.keys())
        assert "variant" in fields
        assert "per_symbol" in fields
        assert "summary" in fields
        assert "version" in fields
        assert "meta" in fields

    def test_sentiment_event_validation(self):
        """验证情绪事件验证逻辑。"""
        from contracts import SentimentEvent

        event = SentimentEvent(
            event_type="policy",
            content="唐山限产政策加码",
            sentiment=-0.6,
            time="2026-07-22 10:30",
            source="jin10",
            confidence=0.8,
        )
        assert event.sentiment == -0.6
        assert event.source == "jin10"
        assert event.event_type == "policy"

        # sentiment 必须在 -1 ~ 1 范围内
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SentimentEvent(
                event_type="macro",
                content="test",
                sentiment=1.5,
                time="2026-07-22",
                source="web",
            )

    def test_data_sources_includes_sentiment(self):
        """验证 _build_data_sources 在 sentiment_data 存在时添加来源。"""
        from fdt_langgraph.nodes import _build_data_sources
        from fdt_langgraph.state import create_initial_state

        state = create_initial_state("test-trace")
        state["research_data"] = {
            "sentiment_data": {"raw": {"output": "情绪分析结果"}},
        }
        state["fdc_data_status"] = {}

        sources = _build_data_sources(state)
        sent_sources = [s for s in sources if s["source"] == "sentiment"]
        assert len(sent_sources) == 1
        assert sent_sources[0]["agent"] == "读心"

    def test_debate_context_includes_sentiment(self):
        """验证 _build_debate_context 包含情绪区块。"""
        from fdt_langgraph.nodes import _build_debate_context
        from fdt_langgraph.state import create_initial_state

        state = create_initial_state("test-trace")
        state["selected_symbols"] = ["RB"]
        state["research_data"] = {
            "sentiment_data": {
                "raw": {"output": "RB情绪偏空，宏观利空压制"},
            },
        }
        state["scan_results"] = {"all_ranked": []}

        context = _build_debate_context(state)
        assert "[sentiment:读心]" in context
        assert "RB情绪偏空" in context

    @pytest.mark.asyncio
    async def test_node_sentiment_returns_sentiment_data(self, mocker):
        """验证 node_sentiment 返回中包含 sentiment_data 字段。"""
        from fdt_langgraph.nodes import node_sentiment
        from fdt_langgraph.state import create_initial_state

        # Mock 依赖
        mocker.patch("fdt_langgraph.nodes._ensure_llm_key", return_value=None)

        # mock FdtAgentExecutor 实例，让 run() 返回一个 awaitable
        mock_agent_instance = mocker.MagicMock()
        mock_agent_instance.run = mocker.AsyncMock(return_value={"output": "mock情绪分析结果"})

        mocker.patch("fdt_langgraph.nodes.FdtAgentExecutor", return_value=mock_agent_instance)

        # Mock NewsRouter（替代旧的 _build_jin10_context mock）
        from data_adapter.news.types import NewsResult
        mock_router = mocker.MagicMock()
        mock_router.fetch = mocker.AsyncMock(return_value=NewsResult())
        mock_router.build_prompt_context = mocker.MagicMock(return_value="mock新闻上下文")
        mock_router.build_quality_report = mocker.MagicMock(return_value={"RB": {"data_grade": "NO_DATA"}})
        mocker.patch("data_adapter.news.NewsRouter", return_value=mock_router)

        state = create_initial_state("test-trace")
        state["selected_symbols"] = ["RB"]

        result = await node_sentiment(state)
        assert "sentiment_data" in result
        assert "raw" in result["sentiment_data"]
        assert result["sentiment_data"]["raw"]["output"] == "mock情绪分析结果"

    def test_agent_md_exists(self):
        """验证读心 Agent MD 文件存在。"""
        from pathlib import Path

        md_path = Path(__file__).parent.parent.parent / "agents" / "news-sentiment-analyst.md"
        assert md_path.exists(), "读心 Agent MD 文件不存在"
        content = md_path.read_text(encoding="utf-8")
        assert "读心" in content
        assert "SentimentStateVector" in content

    def test_sentiment_node_registered_in_graph(self):
        """验证情绪节点已在 graph 中注册。"""
        from fdt_langgraph.graph import build_debate_graph

        g = build_debate_graph("default")
        # langgraph 不同版本的 graph.nodes 可能是字符串列表或对象列表
        try:
            node_names = {n.id for n in g.get_graph().nodes}
        except AttributeError:
            node_names = set(g.get_graph().nodes)
        assert "sentiment" in node_names, "sentiment 节点未在 graph 中注册"
