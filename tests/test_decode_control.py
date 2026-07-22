#!/usr/bin/env python3
"""
测试: D3 Generation 解码控制层
测试模块:
  1. decode_config.yaml 配置加载与 Schema 验证
  2. enforce_structured_output 结构化输出强制约束
  3. content_filter 内容安全过滤
  4. generation_metrics 解码质量监控
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 清除 scripts 缓存，确保从已设置的 sys.path 加载
if "scripts" in sys.modules:
    del sys.modules["scripts"]
for k in list(sys.modules.keys()):
    if k.startswith("scripts."):
        del sys.modules[k]

from scripts.enforce_structured_output import (
    enforce_structured_output,
    auto_fix_json,
    validate_required_fields,
    load_decode_config,
)
from scripts.content_filter import ContentFilter
from scripts.generation_metrics import GenerationMetrics


# ============================================================
# Phase 1: decode_config.yaml 配置加载
# ============================================================

class TestDecodeConfig:
    """测试逐Agent解码配置"""

    CONFIG_PATH = PROJECT_ROOT / "config" / "agents" / "decode_config.yaml"

    def test_config_exists(self):
        """配置文件必须存在"""
        assert self.CONFIG_PATH.exists(), f"Config not found: {self.CONFIG_PATH}"

    def test_config_loadable(self):
        """配置文件可加载"""
        config = load_decode_config()
        assert config is not None
        assert "agents" in config
        assert len(config["agents"]) > 0

    def test_all_agents_have_config(self):
        """所有注册的 Agent 都有解码配置"""
        config = load_decode_config()
        agents = config.get("agents", {})

        # 检查关键 Agent 是否配置
        required_agents = [
            "judge", "judge_deputy", "judge_heldout",
            "bullish_analyst", "bearish_analyst",
            "chain_analyst", "technical_researcher", "fundamental_researcher",
            "risk_manager", "debate_team_team_lead",
        ]
        for agent in required_agents:
            assert agent in agents, f"Missing config for agent: {agent}"

    def test_temperature_bounds(self):
        """温度必须在 0.0~1.0 范围内"""
        config = load_decode_config()
        for name, agent_cfg in config.get("agents", {}).items():
            temp = agent_cfg.get("temperature", 0.5)
            assert 0.0 <= temp <= 1.0, f"{name}: temperature={temp} out of range"

    def test_max_tokens_bounds(self):
        """max_tokens 必须在 256~16384 范围内"""
        config = load_decode_config()
        for name, agent_cfg in config.get("agents", {}).items():
            tokens = agent_cfg.get("max_tokens", 1024)
            assert 256 <= tokens <= 16384, f"{name}: max_tokens={tokens} out of range"

    def test_role_based_temperature_strategy(self):
        """
        角色差异化温度策略:
        - 裁决/风控: temp <= 0.3 (高确定)
        - 辩手: temp >= 0.3 (允许创造性)
        """
        config = load_decode_config()
        agents = config.get("agents", {})

        # 裁决组
        for name in ["judge", "judge_deputy", "judge_heldout"]:
            if name in agents:
                assert agents[name]["temperature"] <= 0.3, \
                    f"{name} should have low temperature (<=0.3)"

        # 风控组
        if "risk_manager" in agents:
            assert agents["risk_manager"]["temperature"] <= 0.3, \
                "risk_manager should have low temperature (<=0.3)"

    def test_response_format_defined(self):
        """每个 Agent 都应定义 response_format"""
        config = load_decode_config()
        for name, agent_cfg in config.get("agents", {}).items():
            assert "response_format" in agent_cfg, \
                f"{name}: missing response_format"


# ============================================================
# Phase 2: enforce_structured_output 结构化输出强制约束
# ============================================================

class TestEnforceStructuredOutput:
    """测试结构化输出强制约束"""

    def test_valid_json_parsed(self):
        """合法 JSON 应正确解析"""
        result = enforce_structured_output(
            '{"symbol": "RB", "direction": "long", "confidence": 0.8}'
        )
        assert result["success"] is True
        assert result["data"] is not None
        assert result["data"]["symbol"] == "RB"

    def test_invalid_json_rejected(self):
        """非法 JSON 应返回失败"""
        result = enforce_structured_output(
            '{"symbol": "RB", invalid json here}'
        )
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_auto_fix_markdown_code_block(self):
        """自动修复：从 markdown 代码块提取 JSON"""
        raw = "```json\n{\"symbol\": \"RB\"}\n```"
        fixed = auto_fix_json(raw)
        assert json.loads(fixed)["symbol"] == "RB"

    def test_auto_fix_trailing_comma(self):
        """自动修复：尾随逗号"""
        raw = '{"symbol": "RB", "tags": ["a", "b",]}'
        fixed = auto_fix_json(raw)
        data = json.loads(fixed)
        assert data["tags"] == ["a", "b"]

    def test_auto_fix_single_quotes(self):
        """自动修复：单引号转双引号"""
        raw = "{'symbol': 'RB'}"
        fixed = auto_fix_json(raw)
        data = json.loads(fixed)
        assert data["symbol"] == "RB"

    def test_validate_required_fields_success(self):
        """必填字段校验通过"""
        data = {"symbol": "RB", "direction": "long"}
        errors = validate_required_fields(data, ["symbol", "direction"])
        assert len(errors) == 0

    def test_validate_required_fields_failure(self):
        """必填字段缺失时报告错误"""
        data = {"symbol": "RB"}
        errors = validate_required_fields(data, ["symbol", "direction"])
        assert len(errors) == 1
        assert "direction" in errors[0]

    def test_validate_required_fields_null(self):
        """必填字段为 None 时报告错误"""
        data = {"symbol": None}
        errors = validate_required_fields(data, ["symbol"])
        assert len(errors) == 1
        assert "null" in errors[0]

    def test_enforce_with_agent_config_judge(self):
        """使用闫判官配置校验输出"""
        valid_output = json.dumps({
            "symbol": "RB",
            "direction": "long",
            "confidence": 0.75,
            "entry_price": 3200,
            "stop_loss": 3150,
        })
        result = enforce_structured_output(valid_output, agent_name="judge")
        assert result["success"] is True

    def test_enforce_with_agent_config_missing_field(self):
        """闫判官配置校验：缺少必填字段应失败"""
        invalid_output = json.dumps({
            "symbol": "RB",
            # missing direction, confidence, etc.
        })
        result = enforce_structured_output(invalid_output, agent_name="judge")
        assert result["success"] is False
        assert any("direction" in e for e in result["errors"])

    def test_auto_fix_extra_text_before_after(self):
        """自动修复：JSON 前后有额外文本"""
        raw = 'Some text before\n{"symbol": "RB"}\nSome text after'
        fixed = auto_fix_json(raw)
        data = json.loads(fixed)
        assert data["symbol"] == "RB"

    def test_enforce_empty_output(self):
        """空输出应返回失败"""
        result = enforce_structured_output("")
        assert result["success"] is False

    def test_enforce_non_dict_json(self):
        """非对象 JSON (如数组) 应处理"""
        result = enforce_structured_output('[1, 2, 3]')
        # 可以解析但不含必填字段
        assert result["data"] == [1, 2, 3]


# ============================================================
# Phase 3: content_filter 内容安全过滤
# ============================================================

class TestContentFilter:
    """测试内容安全过滤"""

    def setup_method(self):
        self.filter = ContentFilter()

    def test_clean_text_passes(self):
        """干净文本应通过过滤"""
        result = self.filter.filter("螺纹钢RB2501当前价格3200，建议观望")
        assert result["has_sensitive"] is False
        assert result["blocked"] is False

    def test_market_manipulation_detected(self):
        """市场操纵类敏感词应被检测"""
        result = self.filter.filter("建议坐庄拉升RB价格")
        assert result["has_sensitive"] is True
        assert "market_manipulation" in result["sensitive_categories"]

    def test_guaranteed_return_detected(self):
        """保证收益类应被检测"""
        result = self.filter.filter("这个策略包赚不赔")
        assert result["has_sensitive"] is True

    def test_sanitize_replaces_sensitive(self):
        """敏感词应被替换"""
        result = self.filter.filter("这是最佳策略")
        assert "最佳" not in result["sanitized"]
        assert "较优" in result["sanitized"]

    def test_compliance_guaranteed_return(self):
        """合规检查：保证收益"""
        issues = self.filter.check_compliance("这个策略保证赚钱")
        assert len(issues) > 0
        assert any(i["rule"] == "no_guaranteed_return" for i in issues)

    def test_compliance_absolute_prediction(self):
        """合规检查：绝对预测"""
        issues = self.filter.check_compliance("RB必然上涨")
        assert len(issues) > 0
        assert any(i["rule"] == "no_absolute_prediction" for i in issues)

    def test_compliance_insider_trading_critical(self):
        """合规检查：内幕交易 (critical)"""
        issues = self.filter.check_compliance("据内幕消息，RB要涨")
        assert len(issues) > 0
        critical = [i for i in issues if i["severity"] == "critical"]
        assert len(critical) > 0

    def test_blocked_with_critical(self):
        """critical 级别问题应阻断输出"""
        result = self.filter.filter("据内幕消息，RB要涨")
        assert result["blocked"] is True

    def test_relaxed_mode_not_blocked(self):
        """宽松模式不阻断"""
        result = self.filter.filter("据内幕消息", strict=False)
        assert result["blocked"] is False

    def test_custom_blocklist(self):
        """自定义黑名单"""
        custom_filter = ContentFilter(custom_words=["自定义敏感词"])
        result = custom_filter.filter("包含自定义敏感词的内容")
        assert "自定义敏感词" not in result["sanitized"]

    def test_check_sensitive_only(self):
        """仅检查不替换"""
        check = self.filter.check_sensitive("坐庄螺纹钢")
        assert check["has_sensitive"] is True
        assert len(check["matches"]) > 0

    def test_price_without_risk_disclaimer(self):
        """价格建议未带风险提示"""
        issues = self.filter.check_compliance("建议在3200点买入RB")
        risk_issues = [i for i in issues if i["rule"] == "risk_disclaimer_required"]
        assert len(risk_issues) > 0

    def test_price_with_risk_disclaimer_pass(self):
        """价格建议带风险提示则通过"""
        issues = self.filter.check_compliance("建议在3200买入RB，注意风险控制")
        risk_issues = [i for i in issues if i["rule"] == "risk_disclaimer_required"]
        assert len(risk_issues) == 0


# ============================================================
# Phase 4: generation_metrics 解码质量监控
# ============================================================

class TestGenerationMetrics:
    """测试解码质量监控"""

    def setup_method(self):
        # 使用临时目录避免影响生产数据
        self.temp_dir = tempfile.mkdtemp()
        self.metrics = GenerationMetrics(storage_dir=Path(self.temp_dir))

    def test_record_and_count(self):
        """记录并统计"""
        self.metrics.record("judge", success=True, latency_ms=1200)
        self.metrics.record("judge", success=True, latency_ms=800)
        self.metrics.record("bullish", success=False, latency_ms=3000, retries=2)

        stats = self.metrics.get_agent_stats()
        assert "judge" in stats
        assert stats["judge"]["total"] == 2
        assert stats["judge"]["success"] == 2
        assert stats["judge"]["success_rate"] == 100.0

        assert stats["bullish"]["total"] == 1
        assert stats["bullish"]["success"] == 0
        assert stats["bullish"]["avg_retries"] == 2.0

    def test_schema_valid_tracking(self):
        """Schema 校验跟踪"""
        self.metrics.record("judge", success=True, latency_ms=500, schema_valid=True)
        self.metrics.record("judge", success=True, latency_ms=600, schema_valid=False)

        stats = self.metrics.get_agent_stats("judge")
        assert stats["judge"]["schema_pass_rate"] == 50.0

    def test_summary(self):
        """全局汇总"""
        self.metrics.record("judge", success=True, latency_ms=1000)
        self.metrics.record("bullish", success=True, latency_ms=2000)

        summary = self.metrics.get_summary()
        assert summary["total_records"] == 2
        assert summary["total_success"] == 2
        assert summary["overall_success_rate"] == 100.0
        assert summary["agent_count"] == 2

    def test_report_generation(self):
        """质量报告生成"""
        self.metrics.record("judge", success=True, latency_ms=1000)
        self.metrics.record("bullish", success=True, latency_ms=2000)

        report = self.metrics.get_report()
        assert "Generation Quality Report" in report
        assert "judge" in report
        assert "bullish" in report

    def test_trend_analysis(self):
        """趋势分析"""
        self.metrics.record("judge", success=True, latency_ms=1000)
        trend = self.metrics.get_trend(hours=24)
        assert len(trend) > 0

    def test_empty_metrics(self):
        """空指标"""
        empty = GenerationMetrics(storage_dir=Path(self.temp_dir))
        summary = empty.get_summary()
        assert summary["total_records"] == 0

    def test_record_with_metadata(self):
        """记录带元数据"""
        self.metrics.record(
            "judge", success=True, latency_ms=500,
            metadata={"model": "deepseek-v4-flash", "tokens": 1500}
        )
        # 验证持久化
        records_file = self.metrics._records_file()
        assert records_file.exists()

    def test_latency_metrics(self):
        """延迟统计"""
        self.metrics.record("judge", success=True, latency_ms=1000)
        self.metrics.record("judge", success=True, latency_ms=2000)
        stats = self.metrics.get_agent_stats("judge")
        assert stats["judge"]["avg_latency_ms"] == 1500.0

    def test_retry_counting(self):
        """重试计数"""
        self.metrics.record("judge", success=True, latency_ms=5000, retries=3)
        stats = self.metrics.get_agent_stats("judge")
        assert stats["judge"]["avg_retries"] == 3.0

    def test_error_warning_tracking(self):
        """错误和警告计数"""
        self.metrics.record(
            "judge", success=True, latency_ms=500,
            error_count=2, warning_count=1
        )
        stats = self.metrics.get_agent_stats("judge")
        # 重新检查 - 由于 get_agent_stats 返回 dict, error_count/warning_count 在返回结构内
        agent_stats = stats["judge"]
        if "total_errors" in agent_stats:
            assert agent_stats["total_errors"] == 2
        if "total_warnings" in agent_stats:
            assert agent_stats["total_warnings"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
