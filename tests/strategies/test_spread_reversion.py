"""SpreadReversionStrategy（G36 跨期价差 OU 均值回归）测试。

覆盖：
  - OU 半衰期拟合（均值回复/非回复/趋势/样本不足）
  - 滚动 Z-score & 价差构建
  - fetch_spread_history provider 注入 mock（sync，零网络）
  - SpreadReversionStrategy.compute（偏高/偏低/无偏离/非回复/历史不足/空上下文）
  - SpreadReversionStrategy.score（方向符号 + grade + weight=0.7）
"""

import sys
from pathlib import Path

# 确保 scripts/ 在 sys.path
_SCRIPTS = str(Path(__file__).resolve().parents[2] / "skills" / "quant-daily" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
# 确保 skills config 优先于根目录 config（根目录不是包，无 __init__.py）
if "config" in sys.modules:
    del sys.modules["config"]

import numpy as np
from strategies.spread_reversion_strategy import (
    SpreadReversionStrategy,
    _build_spread_series,
    _fit_ou_half_life,
    _rolling_z,
    fetch_spread_history,
    kalman_filter_ou,
)

# ───────────────────────────────────────────────────────────
# OU 半衰期
# ───────────────────────────────────────────────────────────

class TestOUHalfLife:
    def test_mean_reverting_finite(self):
        # 强均值回复序列：AR(1) φ=0.85 → b≈-0.15 → hl≈4.6
        rng = np.random.default_rng(0)
        x = np.zeros(300)
        for i in range(1, 300):
            x[i] = 0.85 * x[i - 1] + rng.normal(0, 1)
        hl = _fit_ou_half_life(x)
        assert np.isfinite(hl)
        assert 2.0 < hl < 50.0

    def test_non_reverting_returns_inf_or_huge(self):
        # 严格线性趋势 → b=0 → hl=inf；浮点舍入可能出极大有限值
        x = np.arange(5000, dtype=float)
        hl = _fit_ou_half_life(x)
        # 非回复：要么严格 inf，要么远超可交易上限
        assert not np.isfinite(hl) or hl > 1e10

    def test_trending_returns_inf_or_huge(self):
        # 强趋势 + 噪声 → b ≈ 0 → hl 极大
        rng = np.random.default_rng(2)
        x = np.arange(5000, dtype=float) + rng.normal(0, 0.1, 5000)
        hl = _fit_ou_half_life(x)
        assert not np.isfinite(hl) or hl > 1e10

    def test_short_series_returns_inf(self):
        hl = _fit_ou_half_life(np.array([1.0, 2.0, 3.0]))
        assert hl == float("inf")


# ───────────────────────────────────────────────────────────
# 滚动 Z + 价差构建
# ───────────────────────────────────────────────────────────

class TestSpreadHelpers:
    def test_rolling_z_positive_deviation(self):
        # 末值显著高于窗口均值 → 正 z
        vals = [10.0] * 30 + [20.0]
        z = _rolling_z(vals, window=20)
        assert z > 2.0

    def test_rolling_z_negative_deviation(self):
        vals = [10.0] * 30 + [0.0]
        z = _rolling_z(vals, window=20)
        assert z < -2.0

    def test_rolling_z_short_window(self):
        z = _rolling_z([5.0, 6.0], window=20)
        assert isinstance(z, float)

    def test_build_spread_series_aligns(self):
        near = [100, 101, 102, 103, 104]
        far = [98, 97, 96, 95, 94]
        sp = _build_spread_series(np.array(near), np.array(far))
        assert len(sp) == 5
        assert np.allclose(sp, np.array(near) - np.array(far))


# ───────────────────────────────────────────────────────────
# Kalman Filter OU（G37 自适应 z-score）
# ───────────────────────────────────────────────────────────

class TestKalmanFilterOU:
    def test_white_noise_z_around_zero(self):
        # 白噪声 → 无系统性偏离，|z| 应远小于 2
        rng = np.random.default_rng(42)
        series = rng.normal(0, 1, 200)
        kf = kalman_filter_ou(series)
        assert abs(kf["z_score"]) < 1.0

    def test_sharp_jump_detected(self):
        # 平缓系列 + 单 bar 跳变 → |z| >> 2
        series = np.zeros(120)
        series[-1] = 10.0
        kf = kalman_filter_ou(series)
        assert abs(kf["z_score"]) > 2.0

    def test_trend_tracked_no_signal(self):
        # 线性趋势 → KF 自适应跟踪，z 应小于 Z_ENTRY（不触发出场信号）
        series = np.linspace(0, 100, 200)
        kf = kalman_filter_ou(series)
        assert abs(kf["z_score"]) < 2.0

    def test_short_series_fallback(self):
        kf = kalman_filter_ou(np.array([1.0, 2.0, 3.0]))
        assert kf["z_score"] == 0.0

    def test_output_structure(self):
        series = 5.0 + np.random.default_rng(99).normal(0, 0.5, 120)
        kf = kalman_filter_ou(series)
        assert "z_score" in kf
        assert "filtered_mu" in kf
        assert "state_sigma" in kf
        assert len(kf["filtered_mu"]) == len(series)
        assert len(kf["state_sigma"]) == len(series)


# ───────────────────────────────────────────────────────────
# fetch_spread_history provider（注入 mock sync，零网络）
# ───────────────────────────────────────────────────────────

class TestFetchSpreadHistory:
    def _mock_contracts(self, symbol):
        return [
            {"contract": f"{symbol}2408", "month": "2408", "price": 70000.0},
            {"contract": f"{symbol}2410", "month": "2410", "price": 70050.0},
        ]

    def _mock_klines(self, codes, days):
        base = {"CU2408": 70000.0, "CU2410": 70050.0}
        return {c: [base[c] + i for i in range(days)] for c in codes}

    def test_builds_spread_history(self):
        sh = fetch_spread_history(
            "CU", days=120,
            fetch_contracts=self._mock_contracts,
            fetch_klines=self._mock_klines,
        )
        assert sh is not None
        assert sh["near_contract"] == "CU2408"
        assert sh["far_contract"] == "CU2410"
        assert len(sh["spread"]) == 120
        assert sh["spread"][-1] < 0  # 近<远 → 负价差

    def test_insufficient_contracts_returns_none(self):
        sh = fetch_spread_history(
            "CU", days=120,
            fetch_contracts=lambda s: [{"contract": "CU2408", "month": "2408", "price": 1.0}],
            fetch_klines=self._mock_klines,
        )
        assert sh is None

    def test_kline_fetch_failure_returns_none(self):
        sh = fetch_spread_history(
            "CU", days=120,
            fetch_contracts=self._mock_contracts,
            fetch_klines=lambda codes, days: None,
        )
        assert sh is None


# ───────────────────────────────────────────────────────────
# compute 辅助：造价差历史
# ───────────────────────────────────────────────────────────

def _make_spread_history(spread_list, near="CU2408", far="CU2410"):
    return {
        "CU": {
            "near_contract": near,
            "far_contract": far,
            "spread": list(spread_list),
            "dates": [f"d{i}" for i in range(len(spread_list))],
            "spread_pct": [s / 100.0 for s in spread_list],
        }
    }


class TestSpreadReversionCompute:

    def test_near_overpriced_emits_bear_near_bull_far(self):
        # AR(1) 均值回复价差 + 单根 K 线推高 8σ → z>>2, hl≈4-12
        rng = np.random.default_rng(7)
        spread = np.zeros(120)
        for i in range(1, 120):
            spread[i] = 0.85 * spread[i - 1] + rng.normal(0, 1)
        std30 = max(float(np.std(spread[-30:])), 0.01)
        spread[-1] += 8.0 * std30  # 单 bar 极端偏离 → z >> 2

        ctx = {"spread_history": _make_spread_history(list(spread))}
        sigs = SpreadReversionStrategy().compute([], {}, ctx)
        assert len(sigs) == 2, f"期望 2 条信号, 得到 {len(sigs)}"
        dirs = {s.symbol: s.direction for s in sigs}
        assert dirs["CU2408"] == "bear"
        assert dirs["CU2410"] == "bull"

    def test_near_underpriced_emits_bull_near_bear_far(self):
        rng = np.random.default_rng(8)
        spread = np.zeros(120)
        for i in range(1, 120):
            spread[i] = 0.85 * spread[i - 1] + rng.normal(0, 1)
        std30 = max(float(np.std(spread[-30:])), 0.01)
        spread[-1] -= 8.0 * std30

        ctx = {"spread_history": _make_spread_history(list(spread))}
        sigs = SpreadReversionStrategy().compute([], {}, ctx)
        assert len(sigs) == 2
        dirs = {s.symbol: s.direction for s in sigs}
        assert dirs["CU2408"] == "bull"
        assert dirs["CU2410"] == "bear"

    def test_no_deviation_no_signal(self):
        rng = np.random.default_rng(9)
        spread = 10.0 + rng.normal(0, 0.5, 120)
        ctx = {"spread_history": _make_spread_history(list(spread))}
        sigs = SpreadReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_non_reverting_spread_no_signal(self):
        # 线性趋势 → OU 检测为非回复 → 不出信号
        spread = list(np.arange(300, dtype=float))
        ctx = {"spread_history": _make_spread_history(spread)}
        sigs = SpreadReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_insufficient_history_no_signal(self):
        spread = list(np.arange(30))
        ctx = {"spread_history": _make_spread_history(spread)}
        sigs = SpreadReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_empty_context_no_signal(self):
        strat = SpreadReversionStrategy()
        assert strat.compute([], {}, {}) == []
        assert strat.compute([], {}, None) == []


# ───────────────────────────────────────────────────────────
# 评分
# ───────────────────────────────────────────────────────────

class TestSpreadReversionScore:
    def test_score_direction_and_weight(self):
        from strategies.base_v2 import RawSignal
        raw = RawSignal(
            symbol="CU2408", direction="bear",
            signal_type="spread_reversion.near.CU2408",
            raw_score=0.9, strategy_name="spread_reversion",
            meta={"z_score": 3.0, "half_life": 12.0},
        )
        strat = SpreadReversionStrategy()
        scored = strat.score([raw], [], {})
        assert len(scored) == 1
        ss = scored[0]
        assert ss.direction == "bear"
        assert ss.total < 0  # bear 为负
        assert ss.abs_score == 90.0
        assert ss.weight == 0.7
        assert ss.grade == "WATCH"
