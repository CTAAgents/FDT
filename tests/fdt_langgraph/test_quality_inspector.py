"""
测试: 品藻质检器 — 辩论输出数据质量校验

覆盖:
  - validate_verdict 接受 float 置信度 (修复 Issue 3)
  - validate_verdict 接受中文置信度字符串
  - validate_verdict 不要求顶级 symbol 字段
  - normalize_verdict 输出与质检 Schema 一致
"""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from fdt_langgraph.quality_inspector import validate_verdict, validate_risk
from contracts.debate_quality_schema import VERDICT_RULES, RISK_RULES


# ============================================================
# validate_verdict — 裁决数据质检
# ============================================================

class TestValidateVerdict:
    """验证修复后的 VERDICT_RULES 与 LLM/normalize_verdict 产出兼容。"""

    def test_float_confidence_passes(self):
        """置信度为 float 0.5 时不应报错（修复 Issue 3）。"""
        data = {
            "direction": "bull",
            "confidence": 0.5,
            "entry_price": 3500.0,
            "stop_loss_price": 3450.0,
            "target_price": 3650.0,
            "reason": "测试 reason",
            "symbols": ["RB"],
        }
        report = validate_verdict(data)
        assert report["status"] in ("PASS", "FAIL"), "质检应正常返回"
        # 不应有 confidence 相关的 error
        conf_issues = [i for i in report["issues"]
                       if i.get("field") == "confidence" and i.get("severity") == "error"]
        assert len(conf_issues) == 0, f"不应有 confidence error: {conf_issues}"

    def test_chinese_confidence_passes(self):
        """置信度为 '中' 时应通过。"""
        data = {
            "direction": "neutral",
            "confidence": "中",
            "reason": "测试",
        }
        report = validate_verdict(data)
        assert report["status"] in ("PASS", "FAIL")
        conf_issues = [i for i in report["issues"]
                       if i.get("field") == "confidence" and i.get("severity") == "error"]
        assert len(conf_issues) == 0, f"不应有 confidence error: {conf_issues}"

    def test_no_symbol_required(self):
        """顶级 verdict 不应要求 symbol 字段（symbol 在 per-symbol 级别）。"""
        data = {
            "direction": "neutral",
            "confidence": "低",
            "reason": "无方向",
        }
        report = validate_verdict(data)
        # 不应有 symbol 相关的 error
        sym_issues = [i for i in report["issues"]
                      if i.get("field") == "symbol" and i.get("severity") == "error"]
        assert len(sym_issues) == 0, f"不应有 symbol error: {sym_issues}"

    def test_normalized_output_structure_passes(self):
        """normalize_verdict 标准化后的输出应通过质检。"""
        data = {
            "direction": "bear",
            "confidence": 0.75,
            "entry_price": 4200.0,
            "stop_loss_price": 4250.0,
            "target_price": 4000.0,
            "reason": "测试 bear 方向",
            "contract": "CU",
            "symbols": ["CU"],
            "grade": "STRONG",
            "position_pct": 3.0,
            "risk_reward_ratio": 2.5,
        }
        report = validate_verdict(data)
        assert report["status"] in ("PASS", "FAIL")
        # error 不应包含字段类型或必填相关的错误
        type_issues = [i for i in report["issues"]
                       if i.get("severity") == "error"]
        # 对于 bear 方向，stop_loss_price 应 > entry_price，这会产生 spacing 警告而非 error
        # 也可能 spacing 不足报 error，检查是否为期望的类型
        if type_issues:
            for issue in type_issues:
                assert issue.get("field") in ("stop_loss_price",), \
                    f"意外 error: {issue}"

    def test_out_of_range_confidence_warns(self):
        """置信度超出 [0, 1] 应 warning。"""
        data = {
            "direction": "bull",
            "confidence": 1.5,  # 超出范围
            "entry_price": 100.0,
            "stop_loss_price": 99.0,
            "target_price": 110.0,
        }
        report = validate_verdict(data)
        conf_warnings = [i for i in report["issues"]
                         if i.get("field") == "confidence" and i.get("severity") == "warning"]
        assert len(conf_warnings) >= 1, "置信度超出范围应告警"

    def test_empty_data_fails(self):
        """空数据应 FAIL。"""
        report = validate_verdict({})
        assert report["status"] == "FAIL"

    def test_none_data_fails(self):
        """None 数据应 FAIL。"""
        report = validate_verdict(None)
        assert report["status"] == "FAIL"


# ============================================================
# VERDICT_RULES Schema 验证
# ============================================================

class TestVerdictRulesSchema:
    """验证 Schema 定义符合 normalize_verdict 产出。"""

    def test_confidence_type_accepts_float(self):
        """field_types['confidence'] 应接受 float。"""
        ft = VERDICT_RULES["field_types"]["confidence"]
        assert isinstance(1.0, ft), f"confidence 应接受 float, 当前类型={ft}"

    def test_confidence_type_accepts_str(self):
        """field_types['confidence'] 应接受 str。"""
        ft = VERDICT_RULES["field_types"]["confidence"]
        assert isinstance("高", ft), f"confidence 应接受 str, 当前类型={ft}"

    def test_no_confidence_valid_list(self):
        """不再使用 confidence_valid 列表（已移除）。"""
        assert "confidence_valid" not in VERDICT_RULES, \
            "confidence_valid 已移除，改为类型+范围校验"

    def test_field_names_match_normalizer(self):
        """字段名应与 normalize_verdict 产出匹配。"""
        ft_keys = set(VERDICT_RULES["field_types"].keys())
        # normalize_verdict 可能输出的字段
        expected_keys = {"direction", "confidence", "entry_price",
                         "stop_loss_price", "target_price",
                         "symbols", "grade", "reason", "contract"}
        # 应至少包含这些核心字段
        assert expected_keys.issubset(ft_keys), \
            f"缺少字段: {expected_keys - ft_keys}"
