#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 输出质量校验器测试用例

覆盖场景：
  1. 价格偏差正常 — 无幻觉
  2. 价格偏差超过阈值 — 检测到幻觉
  3. 置信度超出范围 — 数值异常
  4. 批量校验统计 — 汇总报告正确性
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 清除 scripts 缓存，确保从已设置的 sys.path 加载
if "scripts" in sys.modules:
    del sys.modules["scripts"]
for k in list(sys.modules.keys()):
    if k.startswith("scripts."):
        del sys.modules[k]

import pytest

from scripts.validate_llm_output import (
    batch_validate,
    validate_confidence,
    validate_price_deviation,
    validate_score_range,
    validate_single_verdict,
)


class TestValidatePriceDeviation:
    """价格偏差校验测试"""

    def test_normal_deviation(self):
        """正常偏差 — 在阈值内"""
        is_valid, deviation = validate_price_deviation(100, 110, threshold=0.20)
        assert is_valid is True
        assert deviation == pytest.approx(0.0909, abs=0.0001)

    def test_exceeds_threshold(self):
        """偏差超过阈值 — FG 案例：900 vs 1420"""
        is_valid, deviation = validate_price_deviation(1420, 900, threshold=0.20)
        assert is_valid is False
        assert deviation == pytest.approx(0.5778, abs=0.0001)

    def test_zero_scan_price(self):
        """扫描价格为 0 — 返回有效"""
        is_valid, deviation = validate_price_deviation(100, 0)
        assert is_valid is True
        assert deviation == 0.0

    def test_negative_prices(self):
        """负数价格（如国债期货）"""
        is_valid, deviation = validate_price_deviation(-99.5, -100.0)
        assert is_valid is True
        assert deviation == pytest.approx(0.005, abs=0.0001)


class TestValidateConfidence:
    """置信度校验测试"""

    def test_normal_confidence(self):
        """正常置信度 0.5"""
        is_valid, value = validate_confidence(0.5)
        assert is_valid is True
        assert value == 0.5

    def test_confidence_at_boundaries(self):
        """边界值 0.0 和 1.0"""
        is_valid, value = validate_confidence(0.0)
        assert is_valid is True
        assert value == 0.0

        is_valid, value = validate_confidence(1.0)
        assert is_valid is True
        assert value == 1.0

    def test_confidence_exceeds_range(self):
        """超出范围的置信度"""
        is_valid, value = validate_confidence(1.5)
        assert is_valid is False
        assert value == 1.5

        is_valid, value = validate_confidence(-0.1)
        assert is_valid is False
        assert value == -0.1

    def test_confidence_invalid_type(self):
        """无效类型的置信度"""
        is_valid, value = validate_confidence("invalid")
        assert is_valid is False
        assert value == 0.5


class TestValidateScoreRange:
    """评分范围校验测试"""

    def test_normal_score(self):
        """正常评分"""
        is_valid, value = validate_score_range(50)
        assert is_valid is True
        assert value == 50.0

    def test_score_at_boundaries(self):
        """边界值"""
        is_valid, value = validate_score_range(-100)
        assert is_valid is True
        assert value == -100.0

        is_valid, value = validate_score_range(100)
        assert is_valid is True
        assert value == 100.0

    def test_score_exceeds_range(self):
        """超出范围的评分"""
        is_valid, value = validate_score_range(150)
        assert is_valid is False
        assert value == 150.0


class TestValidateSingleVerdict:
    """单个裁决校验测试"""

    def test_no_hallucination(self):
        """无幻觉的正常裁决"""
        verdict = {
            "symbol": "RB",
            "entry_price": 4500,
            "stop_loss": 4400,
            "take_profit": 4700,
            "confidence": 0.7,
            "bull_score": 60,
            "bear_score": 30,
        }
        scan_data = {"symbol": "RB", "price": 4480}

        result = validate_single_verdict(verdict, scan_data)

        assert result["symbol"] == "RB"
        assert result["is_hallucinated"] is False
        assert len(result["issues"]) == 0
        assert result["price_validation"]["is_valid"] is True
        assert result["confidence_validation"]["is_valid"] is True

    def test_hallucinated_price(self):
        """价格幻觉 — FG 案例"""
        verdict = {
            "symbol": "FG",
            "entry_price": 1420,
            "confidence": 0.8,
        }
        scan_data = {"symbol": "FG", "price": 900}

        result = validate_single_verdict(verdict, scan_data)

        assert result["is_hallucinated"] is True
        assert len(result["issues"]) == 1
        assert "价格偏差" in result["issues"][0]

    def test_no_scan_data(self):
        """无扫描数据 — 跳过价格校验"""
        verdict = {
            "symbol": "RB",
            "entry_price": 4500,
            "confidence": 0.7,
        }

        result = validate_single_verdict(verdict, None)

        assert result["is_hallucinated"] is False
        assert result["price_validation"] is None
        assert result["confidence_validation"]["is_valid"] is True

    def test_confidence_issue(self):
        """置信度超出范围"""
        verdict = {
            "symbol": "RB",
            "confidence": 1.5,
        }

        result = validate_single_verdict(verdict, None)

        assert result["is_hallucinated"] is False
        assert result["confidence_validation"]["is_valid"] is False
        assert "置信度" in result["issues"][0]


class TestBatchValidate:
    """批量校验测试"""

    def test_empty_verdicts(self):
        """空裁决列表"""
        stats = batch_validate([])
        assert stats["total_verdicts"] == 0
        assert stats["hallucination_rate"] == 0.0

    def test_mixed_hallucinations(self):
        """混合正常和幻觉裁决"""
        verdicts = [
            {
                "symbol": "RB",
                "entry_price": 4500,
                "confidence": 0.7,
            },
            {
                "symbol": "FG",
                "entry_price": 1420,
                "confidence": 0.8,
            },
            {
                "symbol": "CU",
                "entry_price": 68000,
                "confidence": 2.0,
            },
        ]
        scan_results = {
            "RB": {"price": 4480},
            "FG": {"price": 900},
            "CU": {"price": 68500},
        }

        stats = batch_validate(verdicts, scan_results)

        assert stats["total_verdicts"] == 3
        assert stats["hallucinated_count"] == 1
        assert stats["hallucination_rate"] == pytest.approx(33.33, abs=0.01)
        assert stats["confidence_issues"] == 1

    def test_all_normal(self):
        """全部正常裁决"""
        verdicts = [
            {"symbol": "RB", "entry_price": 4500, "confidence": 0.7},
            {"symbol": "CU", "entry_price": 68000, "confidence": 0.6},
        ]
        scan_results = {
            "RB": {"price": 4480},
            "CU": {"price": 68200},
        }

        stats = batch_validate(verdicts, scan_results)

        assert stats["hallucinated_count"] == 0
        assert stats["hallucination_rate"] == 0.0
        assert stats["confidence_issues"] == 0
