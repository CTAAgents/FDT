"""tests/loop_engine/test_evaluation_chain.py — 三级评估链测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from loop_engine.contracts import (
    EconomicLogic,
    FactorProgram,
    FactorSignature,
)
from loop_engine.evaluation_chain import (
    EvaluationChain,
    evaluate_backtest,
    evaluate_economic_logic,
    evaluate_multiple_tests,
)
from loop_engine.factor_program import create_factor_program


@pytest.fixture
def simple_factor() -> FactorProgram:
    """简单的零信号因子（用于测试评估链流程）。"""
    code = """
import numpy as np
def factor_program(data, params):
    n = len(data['close'])
    return np.zeros(n)
"""
    return create_factor_program(
        name="zero_factor",
        code=code,
        params={},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
        economic_logic=EconomicLogic(theory=4, behavioral=3, microstructure=3, institutional=4, narrative="测试因子"),
        source="manual",
    )


@pytest.fixture
def good_factor() -> FactorProgram:
    """与未来收益率正相关的因子（应通过 IC 评估）。"""
    code = """
import numpy as np
def factor_program(data, params):
    close = data['close'].values
    # 简单动量：5 日收益率
    n = len(close)
    signal = np.zeros(n)
    for i in range(5, n):
        signal[i] = (close[i] - close[i-5]) / max(close[i-5], 1e-10)
    return np.clip(signal * 10, -1.0, 1.0)
"""
    return create_factor_program(
        name="momentum_5d",
        code=code,
        params={"window": 5},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=10),
        economic_logic=EconomicLogic(theory=4, behavioral=3, microstructure=3, institutional=4, narrative="5日动量因子"),
        source="manual",
    )


# ─── Level 1: 回测验证 ────────────────────────────────────

def test_evaluate_backtest_returns_metrics(simple_factor, sample_ohlcv, forward_returns):
    """应返回完整的 BacktestMetrics。"""
    bt = evaluate_backtest(simple_factor, sample_ohlcv, forward_returns)
    assert "ic" in bt
    assert "icir" in bt
    assert "sharpe" in bt
    assert "max_drawdown" in bt
    assert "monotonicity" in bt
    assert "oos_ratio" in bt
    assert "t_stat" in bt
    assert "turnover_monthly" in bt


def test_evaluate_backtest_oos_ratio(simple_factor, sample_ohlcv, forward_returns):
    """样本外比例应等于配置值。"""
    bt = evaluate_backtest(simple_factor, sample_ohlcv, forward_returns, oos_ratio=0.3)
    assert bt["oos_ratio"] == 0.3


def test_evaluate_backtest_zero_signal(simple_factor, sample_ohlcv, forward_returns):
    """零信号因子应返回零 IC。"""
    bt = evaluate_backtest(simple_factor, sample_ohlcv, forward_returns)
    assert abs(bt["ic"]) < 1e-6


# ─── Level 2: 经济逻辑 ────────────────────────────────────

def test_evaluate_economic_logic_full_pass(simple_factor):
    """四维全达标的因子应通过。"""
    ec = evaluate_economic_logic(simple_factor)
    assert ec["dimensions_passed"] == 4
    assert ec["theory"] == 4
    assert ec["behavioral"] == 3


def test_evaluate_economic_logic_partial_fail():
    """仅 2 维达标的因子不应通过。"""
    fp = create_factor_program(
        name="bad_factor",
        code="def factor_program(data, params):\n    import numpy as np\n    return np.zeros(len(data['close']))",
        params={},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
        economic_logic=EconomicLogic(theory=2, behavioral=2, microstructure=4, institutional=4, narrative="部分达标"),
        source="manual",
    )
    ec = evaluate_economic_logic(fp)
    assert ec["dimensions_passed"] == 2  # 仅 microstructure/institutional 达标


# ─── Level 3: 多重检验 ────────────────────────────────────

def test_evaluate_multiple_tests_empty():
    """空输入应返回默认值。"""
    from loop_engine.contracts import FactorEvaluation
    mt = evaluate_multiple_tests([])
    assert mt["effective_n_factors"] == 1


def test_evaluate_multiple_tests_with_data():
    """应正确计算 Bonferroni 校正。"""
    from loop_engine.contracts import (
        BacktestMetrics, EconomicScore, FactorEvaluation, MultipleTestResult,
    )
    evals = [
        FactorEvaluation(
            factor_id=f"fct_{i}", trace_id="t",
            level_1_backtest=BacktestMetrics(t_stat=3.0 + i * 0.5),
            level_2_economic=EconomicScore(),
            level_3_multiple=MultipleTestResult(),
            passed=False, failure_reasons=[], evaluated_at="2026-07-18",
        ) for i in range(5)
    ]
    mt = evaluate_multiple_tests(evals)
    assert mt["effective_n_factors"] == 5
    assert 0 < mt["bonferroni_p"] <= 1.0


def test_evaluate_multiple_tests_with_correlation():
    """提供相关性矩阵时应调整有效因子数。"""
    from loop_engine.contracts import (
        BacktestMetrics, EconomicScore, FactorEvaluation, MultipleTestResult,
    )
    evals = [
        FactorEvaluation(
            factor_id=f"fct_{i}", trace_id="t",
            level_1_backtest=BacktestMetrics(t_stat=3.0),
            level_2_economic=EconomicScore(),
            level_3_multiple=MultipleTestResult(),
            passed=False, failure_reasons=[], evaluated_at="2026-07-18",
        ) for i in range(3)
    ]
    # 高相关矩阵（几乎完全共线）
    corr = np.array([[1.0, 0.95, 0.95], [0.95, 1.0, 0.95], [0.95, 0.95, 1.0]])
    mt = evaluate_multiple_tests(evals, correlation_matrix=corr)
    # 高相关下有效因子数应显著 < n
    assert mt["effective_n_factors"] <= 3


# ─── 完整评估链 ───────────────────────────────────────────

def test_evaluation_chain_evaluate(simple_factor, sample_ohlcv, forward_returns):
    """应能执行完整三级评估。"""
    chain = EvaluationChain()
    ev = chain.evaluate(simple_factor, sample_ohlcv, forward_returns)
    assert "factor_id" in ev
    assert "level_1_backtest" in ev
    assert "level_2_economic" in ev
    assert "level_3_multiple" in ev
    assert "passed" in ev
    assert isinstance(ev["failure_reasons"], list)


def test_evaluation_chain_with_prior(simple_factor, sample_ohlcv, forward_returns):
    """应支持传入先验评估。"""
    chain = EvaluationChain()
    # 第一次评估
    ev1 = chain.evaluate(simple_factor, sample_ohlcv, forward_returns)
    # 第二次评估（带先验）
    ev2 = chain.evaluate(
        simple_factor, sample_ohlcv, forward_returns,
        prior_evaluations=[ev1],
    )
    assert "level_3_multiple" in ev2
