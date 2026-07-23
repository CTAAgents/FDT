"""测试 parse_llm_output 统一解析入口 (v9.22.2)"""

import pytest
from fdt_langgraph.llm_provider import parse_llm_output


def test_valid_json():
    """有效 JSON 应成功解析"""
    result = parse_llm_output('{"key": "value"}', agent_name="test")
    assert result["success"] is True
    assert result["data"]["key"] == "value"
    assert len(result["errors"]) == 0


def test_invalid_json_with_fallback():
    """无效 JSON 应使用提供的 default"""
    result = parse_llm_output("not json", agent_name="test", default={"fallback": True})
    assert result["success"] is False
    assert result["data"]["fallback"] is True
    assert len(result["errors"]) > 0


def test_empty_output():
    """空输出应返回失败"""
    result = parse_llm_output("", agent_name="test", default={"empty": True})
    assert result["success"] is False


def test_agent_name_none():
    """空 agent_name 应不影响 JSON 解析"""
    result = parse_llm_output('{"a": 1}', agent_name="")
    assert result["success"] is True
    assert result["data"]["a"] == 1


def test_default_none():
    """default=None 应自动转为空 dict"""
    result = parse_llm_output("bad json", agent_name="test")
    assert result["success"] is False
    assert result["data"] == {}
    assert len(result["errors"]) > 0


def test_fixable_json():
    """略有瑕疵的 JSON 应被修复（外部库能力）"""
    result = parse_llm_output('{"key": "value",}', agent_name="test")
    assert result["success"] is True
    assert result["data"]["key"] == "value"
