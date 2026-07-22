#!/usr/bin/env python3
"""
测试: D6 Output 输出治理层
测试模块:
  1. output_metrics 输出质量度量
  2. output_versioning 输出版本化
  3. output_feedback 输出反馈闭环
  4. output_audit 输出审计日志
"""

import json
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

from scripts.output_metrics import OutputMetrics
from scripts.output_versioning import OutputVersioning
from scripts.output_feedback import OutputFeedback
from scripts.output_audit import OutputAudit


class TestOutputMetrics:
    """D6 Phase1: 输出质量度量"""

    def test_score_judge_output(self):
        """闫判官输出评分"""
        metrics = OutputMetrics()
        output = {"symbol": "RB", "direction": "long", "confidence": 0.8, "entry_price": 3200}
        result = metrics.score_output(output, agent_name="judge")
        assert 0 <= result["total_score"] <= 100
        assert "completeness" in result["dimensions"]
        assert "consistency" in result["dimensions"]

    def test_score_empty_output(self):
        """空输出评分 (仅 completeness 为0, 其他维度可评分)"""
        metrics = OutputMetrics()
        result = metrics.score_output({}, agent_name="judge")
        assert result["total_score"] < 60.0

    def test_score_low_confidence_deduction(self):
        """低置信度扣分"""
        metrics = OutputMetrics()
        output = {"direction": "long", "confidence": 0.3}
        result = metrics.score_output(output)
        # 0.3 < 0.5 应扣一致性分
        assert result["dimensions"]["consistency"] < 100

    def test_score_risk_mismatch(self):
        """风险颜色和杠杆不匹配"""
        metrics = OutputMetrics()
        output = {"risk_color": "red", "max_leverage": 5}
        result = metrics.score_output(output)
        assert result["dimensions"]["consistency"] < 100

    def test_score_invalid_confidence(self):
        """置信度值域异常"""
        metrics = OutputMetrics()
        output = {"confidence": 1.5}
        result = metrics.score_output(output)
        assert result["dimensions"]["conformity"] < 100

    def test_summary_empty(self):
        """空度量汇总"""
        metrics = OutputMetrics()
        summary = metrics.get_summary()
        assert summary["total_records"] == 0


class TestOutputVersioning:
    """D6 Phase2: 输出版本化"""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def test_save_and_retrieve(self):
        """保存并获取版本"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        vid = v.save_output({"symbol": "RB", "direction": "long"}, agent_name="judge")
        assert vid.startswith("judge_")

        history = v.get_history(agent_name="judge")
        assert len(history) == 1
        assert history[0]["version_id"] == vid

    def test_get_version_by_id(self):
        """按版本 ID 获取"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        vid = v.save_output({"symbol": "RB"}, agent_name="judge")
        record = v.get_version(vid)
        assert record is not None
        assert record["version_id"] == vid

    def test_history_limit(self):
        """历史记录条数限制"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        for i in range(5):
            v.save_output({"symbol": "RB", "seq": i}, agent_name="judge")
        history = v.get_history(agent_name="judge", limit=3)
        assert len(history) <= 3

    def test_history_filter_by_symbol(self):
        """按品种筛选历史"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        v.save_output({"symbol": "RB"}, agent_name="judge")
        v.save_output({"symbol": "SM"}, agent_name="judge")
        rb_history = v.get_history(agent_name="judge", symbol="RB")
        assert len(rb_history) == 1
        assert rb_history[0]["output"]["symbol"] == "RB"

    def test_compare_versions(self):
        """版本比较"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        vid_a = v.save_output({"symbol": "RB", "confidence": 0.7}, agent_name="judge")
        vid_b = v.save_output({"symbol": "RB", "confidence": 0.8}, agent_name="judge")
        diff = v.compare_versions(vid_a, vid_b)
        assert diff["has_diff"] is True
        assert "confidence" in diff["changed_keys"]

    def test_version_not_found(self):
        """版本不存在"""
        v = OutputVersioning("judge", storage_dir=self.temp_dir)
        record = v.get_version("nonexistent")
        assert record is None


class TestOutputFeedback:
    """D6 Phase3: 输出反馈闭环"""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def test_record_feedback(self):
        """记录反馈"""
        fb = OutputFeedback(storage_dir=self.temp_dir)
        fb.record_feedback("v1", is_correct=True, agent_name="judge")
        summary = fb.get_summary()
        assert summary["total_feedback"] == 1
        assert summary["correct"] == 1

    def test_agent_accuracy(self):
        """Agent 准确率"""
        fb = OutputFeedback(storage_dir=self.temp_dir)
        fb.record_feedback("v1", is_correct=True, agent_name="judge")
        fb.record_feedback("v2", is_correct=False, agent_name="judge")
        acc = fb.get_agent_accuracy("judge")
        assert acc["judge"]["accuracy"] == 50.0

    def test_improvement_suggestions(self):
        """改进建议"""
        fb = OutputFeedback(storage_dir=self.temp_dir)
        for i in range(10):
            fb.record_feedback(f"v{i}", is_correct=(i < 5), agent_name="judge")

        suggestions = fb.get_improvement_suggestions()
        assert len(suggestions) > 0

    def test_empty_feedback(self):
        """空反馈"""
        fb = OutputFeedback(storage_dir=self.temp_dir)
        summary = fb.get_summary()
        assert summary["total_feedback"] == 0


class TestOutputAudit:
    """D6 Phase4: 输出审计日志"""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def test_log_and_retrieve(self):
        """记录并获取审计日志"""
        audit = OutputAudit(storage_dir=self.temp_dir)
        audit.log_output("judge", {"symbol": "RB"}, trace_id="t1")
        trail = audit.get_trail(trace_id="t1")
        assert len(trail) == 1
        assert trail[0]["agent_name"] == "judge"

    def test_audit_summary(self):
        """审计汇总"""
        audit = OutputAudit(storage_dir=self.temp_dir)
        audit.log_output("judge", {}, trace_id="t1", compliance_checked=True)
        audit.log_output("bullish", {}, trace_id="t2", compliance_checked=False)
        summary = audit.get_summary(days=30)
        assert summary["total"] == 2
        assert summary["compliance_checked"] == 1

    def test_compliance_gaps(self):
        """合规差距检查"""
        audit = OutputAudit(storage_dir=self.temp_dir)
        audit.log_output("judge", {}, trace_id="t1", compliance_checked=True)
        audit.log_output("bullish", {}, trace_id="t2", compliance_checked=False)
        gaps = audit.check_compliance_gap(days=7)
        assert len(gaps) == 1

    def test_trail_filter_by_agent(self):
        """按 Agent 筛选审计追踪"""
        audit = OutputAudit(storage_dir=self.temp_dir)
        audit.log_output("judge", {}, trace_id="t1")
        audit.log_output("bullish", {}, trace_id="t2")
        judge_trail = audit.get_trail(agent_name="judge")
        assert len(judge_trail) == 1
        assert judge_trail[0]["agent_name"] == "judge"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
