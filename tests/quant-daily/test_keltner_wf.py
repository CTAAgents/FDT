"""Keltner 通道 Walk-Forward 参数训练器测试。

覆盖:
  - _score_keltner_signal 打分逻辑
  - _evaluate_params 截面评估
  - walk_forward_keltner 训练+测试分割
  - 参数候选空间完整性
  - 边界条件（空数据、短序列、全中性）
"""
import numpy as np
import pytest

from futures_data_core.indicators.tdx_compat import calculate_keltner


# ─── 辅助: 生成确定性 OHLC ───

def _make_ohlc(n=120, start=100.0, drift=0.5, vol=1.0, seed=42):
    rng = np.random.default_rng(seed)
    close = start + np.arange(n) * drift + rng.normal(0, vol, n).cumsum() * 0.1
    high = close + np.abs(rng.normal(0, vol, n)) + 0.5
    low = close - np.abs(rng.normal(0, vol, n)) - 0.5
    open_ = close + rng.normal(0, 0.2, n)
    return open_, high, low, close


def _make_snapshots(n=80, period=20, seed=42):
    """构造 mock snapshots 供 WF 测试。"""
    o, h, l, c = _make_ohlc(n=n + 10, seed=seed)
    snaps = []
    for i in range(period + 10, n, 5):
        snaps.append({
            "bar_idx": i,
            "high": h[:i + 1],
            "low": l[:i + 1],
            "close": c[:i + 1],
            "last_price": float(c[i]),
            "future_avg_change": float(c[i] - c[i - 1]) * 0.1,
            "future_direction": "bull" if c[i] > c[i - 1] else "bear",
        })
    return snaps


class TestScoreKeltnerSignal:
    """_score_keltner_signal 打分逻辑测试。"""

    def test_bull_breakout(self):
        from optimizer.keltner_wf import _score_keltner_signal
        score, direction = _score_keltner_signal(
            close=3200, kc_u=3100, kc_l=2900, kc_m=3000
        )
        assert direction == "bull"
        assert 0 < score <= 1.0

    def test_bear_breakout(self):
        from optimizer.keltner_wf import _score_keltner_signal
        score, direction = _score_keltner_signal(
            close=2800, kc_u=3100, kc_l=2900, kc_m=3000
        )
        assert direction == "bear"
        assert 0 < score <= 1.0

    def test_in_range_neutral(self):
        from optimizer.keltner_wf import _score_keltner_signal
        score, direction = _score_keltner_signal(
            close=3000, kc_u=3100, kc_l=2900, kc_m=3000
        )
        assert direction == "neutral"
        assert score == 0.0

    def test_zero_kc_returns_neutral(self):
        from optimizer.keltner_wf import _score_keltner_signal
        score, direction = _score_keltner_signal(
            close=3000, kc_u=0, kc_l=0, kc_m=0
        )
        assert direction == "neutral"

    def test_inverted_kc_returns_neutral(self):
        from optimizer.keltner_wf import _score_keltner_signal
        # 上轨 < 下轨 → 异常
        score, direction = _score_keltner_signal(
            close=3000, kc_u=2900, kc_l=3100, kc_m=3000
        )
        assert direction == "neutral"


class TestEvaluateParams:
    """_evaluate_params 截面评估测试。"""

    def test_returns_dict_structure(self):
        from optimizer.keltner_wf import _evaluate_params
        snaps = _make_snapshots(n=120, period=20)
        result = _evaluate_params(snaps, period=20, atr_mult=2.25)
        assert "signals" in result
        assert "correct" in result
        assert "accuracy" in result
        assert "avg_pnl" in result
        assert 0 <= result["accuracy"] <= 1.0

    def test_different_params_different_results(self):
        from optimizer.keltner_wf import _evaluate_params
        snaps = _make_snapshots(n=120, period=20)
        r1 = _evaluate_params(snaps, period=20, atr_mult=1.5)
        r2 = _evaluate_params(snaps, period=40, atr_mult=3.5)
        # 宽通道信号更少
        assert r2["signals"] <= r1["signals"]

    def test_empty_snapshots(self):
        from optimizer.keltner_wf import _evaluate_params
        result = _evaluate_params([], period=20, atr_mult=2.25)
        assert result["signals"] == 0
        assert result["accuracy"] == 0.0


class TestWalkForwardKeltner:
    """walk_forward_keltner 训练+测试分割测试。"""

    def test_returns_result_with_valid_data(self):
        from optimizer.keltner_wf import walk_forward_keltner
        snaps = _make_snapshots(n=200, period=20)
        result = walk_forward_keltner("TEST", snaps, verbose=False)
        if result is not None:
            assert "period" in result
            assert "atr_mult" in result
            assert "train" in result
            assert "test" in result
            assert result["period"] in [10, 15, 20, 25, 30, 40]
            assert result["atr_mult"] in [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]

    def test_insufficient_data_returns_none(self):
        from optimizer.keltner_wf import walk_forward_keltner
        result = walk_forward_keltner("TEST", [], verbose=False)
        assert result is None

    def test_very_short_snapshots(self):
        from optimizer.keltner_wf import walk_forward_keltner
        snaps = _make_snapshots(n=30, period=20)
        result = walk_forward_keltner("TEST", snaps, verbose=False)
        # 数据太少可能返回 None 或少量结果
        if result is not None:
            assert result["train"]["signals"] + result["test"]["signals"] >= 0


class TestParamSpaceCompleteness:
    """参数候选空间完整性测试。"""

    def test_period_candidates(self):
        from optimizer.keltner_wf import KELTNER_PERIOD_CANDIDATES
        assert KELTNER_PERIOD_CANDIDATES == [10, 15, 20, 25, 30, 40]

    def test_atr_mult_candidates_spacing(self):
        from optimizer.keltner_wf import KELTNER_ATR_MULT_CANDIDATES
        expected = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]
        assert KELTNER_ATR_MULT_CANDIDATES == expected
        # 验证间距 0.25
        for i in range(1, len(KELTNER_ATR_MULT_CANDIDATES)):
            diff = KELTNER_ATR_MULT_CANDIDATES[i] - KELTNER_ATR_MULT_CANDIDATES[i - 1]
            assert abs(diff - 0.25) < 1e-9

    def test_total_combinations(self):
        from optimizer.keltner_wf import KELTNER_PERIOD_CANDIDATES, KELTNER_ATR_MULT_CANDIDATES
        assert len(KELTNER_PERIOD_CANDIDATES) * len(KELTNER_ATR_MULT_CANDIDATES) == 54


class TestKeltnerConsistencyWithStrategy:
    """Keltner 打分逻辑与 trend_following_strategy._score_keltner 一致性测试。"""

    def test_bull_consistent(self):
        from optimizer.keltner_wf import _score_keltner_signal
        from strategies.trend_following_strategy import _score_keltner
        # 突破上轨
        s1, d1 = _score_keltner_signal(3200, 3100, 2900, 3000)
        s2, d2 = _score_keltner(3200, 3100, 2900, 3000)
        assert d1 == d2 == "bull"
        assert abs(s1 - s2) < 1e-9

    def test_bear_consistent(self):
        from optimizer.keltner_wf import _score_keltner_signal
        from strategies.trend_following_strategy import _score_keltner
        s1, d1 = _score_keltner_signal(2800, 3100, 2900, 3000)
        s2, d2 = _score_keltner(2800, 3100, 2900, 3000)
        assert d1 == d2 == "bear"
        assert abs(s1 - s2) < 1e-9

    def test_neutral_consistent(self):
        from optimizer.keltner_wf import _score_keltner_signal
        from strategies.trend_following_strategy import _score_keltner
        s1, d1 = _score_keltner_signal(3000, 3100, 2900, 3000)
        s2, d2 = _score_keltner(3000, 3100, 2900, 3000)
        assert d1 == d2 == "neutral"
        assert s1 == s2 == 0.0
