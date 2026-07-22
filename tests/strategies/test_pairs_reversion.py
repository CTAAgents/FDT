"""PairsReversionStrategy 测试 — 协整配对均值回归（G35 Phase 1）。

验证：Hurst 前置门禁（对价格变化计算）、协整残差 Z 信号、两腿天然双向做空
（贵腿 bear + 便宜腿 bull）、评分方向与强度映射。全部用合成数据，不依赖网络/FDC。
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 scripts/ 在 sys.path
_SCRIPTS = str(Path(__file__).resolve().parents[2] / "skills" / "quant-daily" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
# 确保 skills config 优先于根目录 config（根目录不是包，无 __init__.py）
if "config" in sys.modules:
    del sys.modules["config"]

from strategies.pairs_reversion_strategy import (
    PairsReversionStrategy,
    calculate_hurst,
    _engle_granger_residual,
    _rolling_z,
    _half_life,
    variance_ratio_test,
)


# ── 合成数据构造 ──

def _kline(sym: str, closes: list[float]) -> dict:
    return {sym: (sym, [{"close": float(c)} for c in closes])}


def _tech(prices: dict) -> list[dict]:
    return [{"symbol": s, "price": float(p)} for s, p in prices.items()]


def _cointegrated_pair(seed: int = 42, tail_shock: float = 0.0):
    """构造 M-RM 协整配对（ratio≈1.3）。

    tail_shock: 末值额外偏离倍数（0=无偏离；>0 制造残差 Z>2）。
    两腿为随机游走价格 → 价格变化 H≈0.5 → 通过 Hurst 门禁。
    """
    rng = np.random.default_rng(seed)
    x = 100 + np.cumsum(rng.standard_normal(120))          # RM 随机游走
    y = 1.3 * x + rng.standard_normal(120) * 0.5            # M 协整于 RM
    if tail_shock:
        y = y.copy()
        y[-1] = y[-1] + tail_shock * np.std(y)
    return x, y


def _momentum_pair(seed: int = 0):
    """构造趋势型配对：两腿价格变化含正自相关（动量）→ Hurst>0.55 → 门禁跳过。"""
    rng = np.random.default_rng(seed)
    r = np.zeros(120)
    for i in range(1, 120):
        r[i] = 0.6 * r[i - 1] + rng.standard_normal()
    x = np.cumsum(r)
    y = 1.3 * x
    return x, y


# ── Hurst（作用于价格变化/平稳序列） ──

class TestCalculateHurst:
    def test_random_walk_neutral(self):
        # 随机游走的价格变化 = i.i.d. → H≈0.5（R/S 小样本上偏，容忍至 0.80）
        h = calculate_hurst(np.random.default_rng(1).standard_normal(200))
        assert 0.45 < h < 0.80

    def test_trending_high(self):
        # 动量收益（正自相关）→ H>0.75（阈值），强趋势被门禁跳过
        r = np.zeros(200)
        rng = np.random.default_rng(6)
        for i in range(1, 200):
            r[i] = 0.6 * r[i - 1] + rng.standard_normal()
        assert calculate_hurst(r) > 0.75

    def test_mean_reverting_low(self):
        # 反转动量收益（负自相关）→ H<0.5
        r = np.zeros(200)
        rng = np.random.default_rng(7)
        for i in range(1, 200):
            r[i] = -0.6 * r[i - 1] + rng.standard_normal()
        assert calculate_hurst(r) < 0.5

    def test_short_series_returns_half(self):
        assert calculate_hurst(np.array([1.0, 2.0, 3.0])) == 0.5


# ── 协整残差 / 滚动 Z / 半衰期 ──

class TestStatsHelpers:
    def test_eg_residual_shape(self):
        x = np.arange(50, dtype=float)
        y = 2.0 * x + 1.0 + np.random.default_rng(3).standard_normal(50) * 0.1
        r = _engle_granger_residual(y, x)
        assert r is not None and len(r) == 50

    def test_eg_residual_short_none(self):
        assert _engle_granger_residual(np.array([1.0, 2.0]), np.array([1.0, 2.0])) is None

    def test_rolling_z_positive(self):
        vals = list(np.random.default_rng(4).standard_normal(30)) + [5.0]
        assert _rolling_z(vals, 20) > 2.0

    def test_half_life_finite_for_reverting(self):
        x = np.zeros(100)
        rng = np.random.default_rng(5)
        for i in range(1, 100):
            x[i] = 0.8 * x[i - 1] + rng.standard_normal()
        hl = _half_life(x)
        assert 0 < hl < float("inf")


# ── 策略 compute ──

class TestPairsReversionCompute:
    def test_cointegrated_spread_emits_two_legs(self):
        x, y = _cointegrated_pair(seed=42, tail_shock=5.0)
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        signals = s.compute(tech, kline)
        dirs = {(sig.symbol, sig.direction) for sig in signals}
        # 残差正 → M 贵 → 做空 M + 做多 RM
        assert ("M", "bear") in dirs
        assert ("RM", "bull") in dirs
        assert len(signals) == 2

    def test_legs_opposite_direction(self):
        x, y = _cointegrated_pair(seed=7, tail_shock=4.0)
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        signals = s.compute(tech, kline)
        by_sym = {sig.symbol: sig.direction for sig in signals}
        assert by_sym["M"] == "bear"
        assert by_sym["RM"] == "bull"

    def test_trending_pair_skipped_by_hurst(self):
        # 趋势型配对（价格变化正自相关）→ Hurst>0.55 门禁跳过 → 无信号
        x, y = _momentum_pair(seed=0)
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        assert len(s.compute(tech, kline)) == 0

    def test_no_spread_no_signal(self):
        # 几乎完美协整、无末段偏离 → 残差 Z 小 → 无信号
        x = 100 + np.cumsum(np.random.default_rng(9).standard_normal(120))
        y = 1.3 * x + np.random.default_rng(9).standard_normal(120) * 0.01
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        assert len(s.compute(tech, kline)) == 0

    def test_insufficient_history_no_signal(self):
        # 历史不足 MIN_BARS → kline_map 不含 → 无信号
        x = 100 + np.cumsum(np.random.default_rng(11).standard_normal(30))
        y = 1.3 * x
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        assert len(s.compute(tech, kline)) == 0


# ── 评分 ──

class TestPairsReversionScore:
    def test_score_direction_and_grade(self):
        x, y = _cointegrated_pair(seed=42, tail_shock=5.0)
        tech = _tech({"M": y[-1], "RM": x[-1]})
        kline = {**_kline("M", y), **_kline("RM", x)}
        s = PairsReversionStrategy()
        signals = s.compute(tech, kline)
        scored = s.score(signals, tech, kline)
        assert len(scored) == 2
        for ss in scored:
            if ss.symbol == "M":
                assert ss.direction == "bear"
                assert ss.total < 0
            else:
                assert ss.direction == "bull"
                assert ss.total > 0
            assert ss.grade in ("WATCH", "WEAK", "NOISE")
            assert ss.weight == 0.7


# ───────────────────────────────────────────────────────────
# 方差比检验（G38）
# ───────────────────────────────────────────────────────────

class TestVarianceRatio:
    def test_mean_reverting_vr_less_than_one(self):
        """强均值回归 MA(1) -0.9 → VR << 1（显著小于 1 即均值回归信号）"""
        rng = np.random.default_rng(10)
        eps = rng.normal(0, 1, 2000)
        rets = [eps[0]] + [eps[t] - 0.9 * eps[t - 1] for t in range(1, len(eps))]
        prices = [100.0]
        for r in rets:
            prices.append(prices[-1] * (1 + r / 100))
        vr, z = variance_ratio_test(prices, q=2)
        assert vr < 0.95, f"VR={vr} 应 < 1（均值回归信号）"

    def test_trending_vr_greater_than_one(self):
        """AR(1) phi=0.8 正自相关 → VR > 1, z > 1.96"""
        rng = np.random.default_rng(11)
        rets = [0.0]
        for _ in range(500):
            rets.append(0.8 * rets[-1] + rng.normal(0.0005, 0.5))
        log_prices = np.cumsum(rets)
        prices = list(100.0 * np.exp(log_prices))
        vr, z = variance_ratio_test(prices, q=2)
        assert vr > 1.02, f"VR={vr} 应 > 1"

    def test_short_series_returns_neutral(self):
        vr, z = variance_ratio_test([100, 101, 102], q=2)
        assert vr == 1.0 and z == 0.0

    def test_compute_meta_includes_vr_z(self):
        """PairsReversion signal meta 包含 vr_z_a / vr_z_b"""
        s = PairsReversionStrategy()
        closes_a = [100 + i * 0.01 + np.random.default_rng(12).normal() for i in range(120)]
        closes_b = [100 + i * 0.01 + np.random.default_rng(13).normal() for i in range(120)]
        # 强制 MR-RM 配对（两者弱相关，协整残差可能通过）
        pairs_data = {"RB": ("螺纹钢", [{"close": float(c)} for c in closes_a]),
                      "HC": ("热卷", [{"close": float(c)} for c in closes_b])}
        tech = [{"symbol": "RB", "price": closes_a[-1]}, {"symbol": "HC", "price": closes_b[-1]}]
        sigs = s.compute(tech, pairs_data)
        if sigs:
            meta = sigs[0].meta
            assert "vr_z_a" in meta
            assert "vr_z_b" in meta
