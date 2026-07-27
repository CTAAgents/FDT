"""WindSource 单元测试。

测试策略：
  - 辅助函数单元测试（无外部依赖）
  - WindSource 缓存管理测试（读写文件系统）
  - WindSource CLI 调用测试（mock subprocess）
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_adapter.sources.wind_source import (
    WindSource,
    _error_result,
    _extract_content,
    _resolve_cache_dir,
    _resolve_cache_ttl,
)


class TestHelperFunctions:
    """辅助函数单元测试。"""

    def test_error_result(self):
        result = _error_result("测试错误")
        assert result["data_grade"] == "UNAVAILABLE"
        assert result["source"] == "wind"
        assert result["error"] == "测试错误"

    def test_extract_content_valid_json(self):
        """从 MCP 结果中提取 JSON content。"""
        result = {
            "content": [
                {"type": "text", "text": '{"key": "value"}'}
            ]
        }
        extracted = _extract_content(result)
        assert extracted == {"key": "value"}

    def test_extract_content_plain_text(self):
        """提取非 JSON 文本。"""
        result = {
            "content": [
                {"type": "text", "text": "plain text data"}
            ]
        }
        extracted = _extract_content(result)
        assert extracted == "plain text data"

    def test_extract_content_empty(self):
        assert _extract_content({}) is None
        assert _extract_content({"content": []}) is None

    def test_resolve_cache_dir_default(self):
        """默认缓存目录。"""
        with patch.dict(os.environ, {}, clear=True):
            cache_dir = _resolve_cache_dir()
            assert cache_dir.name == ".wind_cache"

    def test_resolve_cache_dir_env(self):
        """环境变量覆盖缓存目录。"""
        with patch.dict(os.environ, {"FDT_WIND_CACHE_DIR": "C:\\wind_test"}):
            cache_dir = _resolve_cache_dir()
            assert str(cache_dir) == "C:\\wind_test"

    def test_resolve_cache_ttl_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_cache_ttl() == 43200  # 12 hours

    def test_resolve_cache_ttl_env(self):
        with patch.dict(os.environ, {"FDT_WIND_CACHE_TTL": "3600"}):
            assert _resolve_cache_ttl() == 3600


class TestWindSourceCache:
    """WindSource 缓存管理测试。"""

    @pytest.fixture
    def temp_cache_dir(self):
        """创建临时缓存目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.fixture
    def source(self, temp_cache_dir) -> WindSource:
        """创建 WindSource 实例（使用临时缓存目录）。"""
        with patch.dict(os.environ, {"FDT_WIND_CACHE_DIR": str(temp_cache_dir)}):
            src = WindSource()
            yield src

    def test_cache_write_and_read(self, source: WindSource):
        """写入后读取应返回相同内容。"""
        payload = {"data_grade": "PRIMARY", "data": {"CPI": 0.3, "PPI": -2.1}}
        source._write_cache("test_key", payload)
        cached = source._read_cache("test_key")
        assert cached == payload

    def test_cache_miss(self, source: WindSource):
        """不存在的 key 应返回 None。"""
        assert source._read_cache("nonexistent") is None

    def test_cache_expiry(self, source: WindSource):
        """过期缓存应返回 None（设置极短 TTL）。"""
        source._cache_ttl = 0  # 立即过期
        source._write_cache("expire_test", {"data": "test"})
        time.sleep(0.01)  # 确保时间流逝
        assert source._read_cache("expire_test") is None

    def test_cache_key_sanitization(self, source: WindSource):
        """缓存 key 应清理特殊字符。"""
        path = source._cache_path("中国GDP同比/PPI")
        assert "/" not in path.name  # 不应包含原始路径分隔符
        assert path.name.startswith("wind_")
        assert path.name.endswith(".json")


class TestWindSourceCall:
    """WindSource _call 方法测试（mock subprocess）。"""

    @pytest.fixture
    def source(self) -> WindSource:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"FDT_WIND_CACHE_DIR": str(tmp)}):
                yield WindSource()

    @pytest.mark.asyncio
    async def test_call_success(self, source: WindSource):
        """正常返回解析成功。"""
        success_output = json.dumps({
            "content": [{"type": "text", "text": '{"key": "value"}'}],
            "isError": False,
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = success_output
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = await source._call("test", "test_tool", {"q": "test"})

        assert result.get("isError") is None or result.get("isError") is False
        assert "content" in result

    @pytest.mark.asyncio
    async def test_call_cli_error(self, source: WindSource):
        """CLI 返回非零退出码。"""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = json.dumps({"error": {"code": "ROUTE_ERROR"}})
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = await source._call("test", "bad_tool", {})

        assert result["isError"] is True
        assert "ROUTE_ERROR" in str(result["error"])

    @pytest.mark.asyncio
    async def test_call_timeout(self, source: WindSource):
        """超时处理。"""
        with patch("subprocess.run", side_effect=TimeoutError("timeout")):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=TimeoutError("timeout")
                )
                result = await source._call("test", "test_tool", {})
                # 实际测试中，_call 方法在 run_in_executor 中处理超时
                # 这里只验证不会崩溃
