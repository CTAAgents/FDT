"""期限结构因子单元测试"""
from __future__ import annotations

import pandas as pd
import pytest

from data_adapter.factors.types import TermStructureResult
from data_adapter.factors.term_structure import (
    _compute_single_term_structure,
    _find_column,
    _safe_float,
)


def _make_mock_df(rows: list[dict]) -> pd.DataFrame:
    """生成模拟合约行情 DataFrame。"""
    return pd.DataFrame(rows)


class TestTermStructureCalculation:
    """期限结构因子计算测试。"""

    def _make_rb_df(self):
        """生成 RB 多合约模拟数据。"""
        return _make_mock_df([
            {"symbol": "RB2505", "current_price": 4800},
            {"symbol": "RB2506", "current_price": 4850},
            {"symbol": "RB2507", "current_price": 4880},
            {"symbol": "RB2508", "current_price": 4860},
            {"symbol": "RB2509", "current_price": 4840},
            {"symbol": "RB2510", "current_price": 4820},
        ])

    def test_contango_curve(self):
        """远月升水应识别为 contango。"""
        df = _make_mock_df([
            {"symbol": "RB2505", "current_price": 4800},
            {"symbol": "RB2506", "current_price": 4850},
            {"symbol": "RB2507", "current_price": 4880},
            {"symbol": "RB2508", "current_price": 4860},
            {"symbol": "RB2509", "current_price": 4840},
        ])
        result = _compute_single_term_structure(df, "RB", "symbol", "current_price")
        assert result is not None
        assert result.curve_type == "contango"
        assert result.near_contract == "RB2505"
        assert result.far_contract == "RB2509"
        assert result.spread is not None and result.spread > 0  # 远月>近月

    def test_backwardation_curve(self):
        """近月升水应识别为 backwardation。"""
        df = _make_mock_df([
            {"symbol": "SC2505", "current_price": 520},
            {"symbol": "SC2506", "current_price": 510},
            {"symbol": "SC2507", "current_price": 505},
            {"symbol": "SC2508", "current_price": 500},
            {"symbol": "SC2509", "current_price": 495},
        ])
        result = _compute_single_term_structure(df, "SC", "symbol", "current_price")
        assert result is not None
        assert result.curve_type == "backwardation"
        assert result.spread is not None and result.spread < 0  # 远月<近月

    def test_flat_curve(self):
        """价差很小应识别为 flat。"""
        df = _make_mock_df([
            {"symbol": "MA2505", "current_price": 2500},
            {"symbol": "MA2506", "current_price": 2501},
            {"symbol": "MA2507", "current_price": 2500},
            {"symbol": "MA2508", "current_price": 2499},
        ])
        result = _compute_single_term_structure(df, "MA", "symbol", "current_price")
        assert result is not None
        assert result.curve_type == "flat"

    def test_insufficient_contracts(self):
        """不足 2 个合约返回 None。"""
        df = _make_mock_df([
            {"symbol": "RB2510", "current_price": 4800},
        ])
        result = _compute_single_term_structure(df, "RB", "symbol", "current_price")
        assert result is None

    def test_matched_contracts(self):
        """只有匹配品种前缀的合约被选中。"""
        # 混合多个品种的数据
        df = _make_mock_df([
            {"symbol": "RB2505", "current_price": 4800},
            {"symbol": "RB2506", "current_price": 4850},
            {"symbol": "HC2505", "current_price": 5200},  # HC 不应匹配 RB
            {"symbol": "HC2506", "current_price": 5250},
        ])
        result = _compute_single_term_structure(df, "RB", "symbol", "current_price")
        assert result is not None
        assert result.near_contract.startswith("RB")
        assert result.far_contract.startswith("RB")
        assert result.far_contract != "HC2506"

    def test_spread_ratio(self):
        """计算升贴水率。"""
        df = _make_mock_df([
            {"symbol": "TA2505", "current_price": 6000},
            {"symbol": "TA2506", "current_price": 6060},
            {"symbol": "TA2507", "current_price": 6120},
        ])
        result = _compute_single_term_structure(df, "TA", "symbol", "current_price")
        assert result is not None
        assert result.spread_ratio is not None and result.spread_ratio > 0
        # spread = 6120 - 6000 = 120, spread_ratio = 120/6000*100 ≈ 2.0%
        assert 1.5 < result.spread_ratio < 2.5, f"spread_ratio={result.spread_ratio}"

    def test_data_grade(self):
        """正常计算应标记为 PRIMARY。"""
        df = _make_mock_df([
            {"symbol": "RB2505", "current_price": 4800},
            {"symbol": "RB2506", "current_price": 4850},
            {"symbol": "RB2507", "current_price": 4880},
        ])
        result = _compute_single_term_structure(df, "RB", "symbol", "current_price")
        assert result is not None
        assert result.data_grade == "PRIMARY"


class TestHelperFunctions:
    """辅助函数测试。"""

    def test_find_column_exact_match(self):
        """精确匹配列名。"""
        df = pd.DataFrame({"symbol": ["RB"], "current_price": [4800]})
        assert _find_column(df, ["symbol", "代码"]) == "symbol"

    def test_find_column_fuzzy_match(self):
        """模糊匹配列名。"""
        df = pd.DataFrame({"合约代码": ["RB2505"], "最新价": [4800]})
        col = _find_column(df, ["symbol", "代码", "合约代码"])
        assert col == "合约代码"

    def test_find_column_no_match(self):
        """无匹配列名返回 None。"""
        df = pd.DataFrame({"未知字段": [1]})
        assert _find_column(df, ["symbol", "代码"]) is None

    def test_safe_float_valid(self):
        """有效数值应正确提取。"""
        row = pd.Series({"price": "4800.5", "volume": 1000})
        assert _safe_float(row, ["price"]) == 4800.5

    def test_safe_float_nan(self):
        """NaN 值返回 None。"""
        row = pd.Series({"price": float("nan")})
        assert _safe_float(row, ["price"]) is None

    def test_safe_float_none(self):
        """None 值返回 None。"""
        row = pd.Series({"price": None})
        assert _safe_float(row, ["price"]) is None

    def test_safe_float_no_match(self):
        """不存在的列返回 None。"""
        row = pd.Series({"other": 100})
        assert _safe_float(row, ["price", "现价"]) is None
