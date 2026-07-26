"""因子一致性看板单元测试"""
from __future__ import annotations

import pytest

from data_adapter.factors.types import (
    CrossSpreadResult,
    FactorDashboardResult,
    FactorSignal,
    HoldingSentimentResult,
    TermStructureResult,
    VolatilityResult,
)
from data_adapter.factors.dashboard import build_dashboard, format_dashboard_for_prompt, _compute_divergence


class TestDashboard:
    """因子一致性看板测试。"""

    def test_no_signals(self):
        """无信号时 data_grade 应为 NO_DATA。"""
        dashboard = build_dashboard(["RB"], {}, {}, {}, [])
        assert dashboard.data_grade == "NO_DATA"
        assert dashboard.divergence.get("RB", 0) == 1.0

    def test_single_signal(self):
        """单因子信号。"""
        term = {
            "RB": TermStructureResult(symbol="RB", curve_type="contango", spread=50,
                                       spread_ratio=2.0, data_grade="PRIMARY"),
        }
        dashboard = build_dashboard(["RB"], term, {}, {}, [])
        assert "RB" in dashboard.signals
        assert len(dashboard.signals["RB"]) >= 1
        assert dashboard.data_grade == "PRIMARY"

    def test_convergence(self):
        """因子共振时分歧度低。"""
        term = {
            "RB": TermStructureResult(symbol="RB", curve_type="backwardation", spread=-50,
                                       spread_ratio=-2.5, data_grade="PRIMARY"),
        }
        hs = {
            "RB": HoldingSentimentResult(symbol="RB", total_long=100000, total_short=80000,
                                          long_short_ratio=1.25, data_grade="PRIMARY"),
        }
        dashboard = build_dashboard(["RB"], term, {}, hs, [])
        # 期限结构 backwardation → +1，多空持仓 > 1.2 → +1
        assert dashboard.consensus.get("RB", 0) >= 2
        # 分歧度应较低
        assert dashboard.divergence.get("RB", 1.0) < 0.5

    def test_divergence(self):
        """因子分歧时分歧度高。"""
        term = {
            "RB": TermStructureResult(symbol="RB", curve_type="contango", spread=50,
                                       spread_ratio=2.0, data_grade="PRIMARY"),
        }
        hs = {
            "RB": HoldingSentimentResult(symbol="RB", total_long=100000, total_short=50000,
                                          long_short_ratio=2.0, data_grade="PRIMARY"),
        }
        dashboard = build_dashboard(["RB"], term, {}, hs, [])
        # 期限结构 contango → -1，多空持仓 > 1.2 → +1
        # 分歧度应较高
        assert dashboard.divergence.get("RB", 0) >= 0.3

    def test_format_empty(self):
        """空看板的格式化。"""
        dashboard = FactorDashboardResult(data_grade="NO_DATA")
        text = format_dashboard_for_prompt(dashboard)
        assert "暂无" in text

    def test_format_with_signals(self):
        """格式化含信号的看板。"""
        term = {
            "RB": TermStructureResult(symbol="RB", curve_type="contango", spread=50,
                                       spread_ratio=2.0, data_grade="PRIMARY"),
        }
        dashboard = build_dashboard(["RB"], term, {}, {}, [])
        text = format_dashboard_for_prompt(dashboard)
        assert "多因子信号一致性看板" in text
        assert "RB" in text
        assert "分歧度" in text

    def test_divergence_formula(self):
        """分歧度公式验证。"""
        assert _compute_divergence([1, 1, 1]) == 0.0  # 完全一致
        assert _compute_divergence([-2, 2]) == 1.0   # 完全分歧
        d = _compute_divergence([1, -1])
        assert d == 0.5                         # 标准差归一化后为0.5

    # ── 资金流向信号 ──

    def test_money_flow_bullish(self):
        """主力净流入 > 0 → +1"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        mf = {"symbol": "600519", "main_net_inflow": 5000, "retail_net_inflow": 1000,
              "mid_net_inflow": 500, "data_grade": "PRIMARY"}
        sig = _signal_from_money_flow(mf)
        assert sig is not None
        assert sig.direction == 1
        assert sig.source == "money_flow"

    def test_money_flow_bearish(self):
        """主力净流入 < 0 → -1"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        mf = {"symbol": "600519", "main_net_inflow": -3000, "retail_net_inflow": 500,
              "mid_net_inflow": 200, "data_grade": "PRIMARY"}
        sig = _signal_from_money_flow(mf)
        assert sig is not None
        assert sig.direction == -1

    def test_money_flow_no_data(self):
        """无数据 → None"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        assert _signal_from_money_flow(None) is None
        assert _signal_from_money_flow({"data_grade": "UNAVAILABLE"}) is None

    # ── 北向资金信号 ──

    def test_north_flow_bullish(self):
        """北向净买入 > 0 → +1"""
        from data_adapter.factors.dashboard import _signal_from_north_flow
        nf = {"symbol": "600519", "north_net_buy": 2000, "north_holding_pct": 5.0,
              "data_grade": "PRIMARY"}
        sig = _signal_from_north_flow(nf)
        assert sig is not None
        assert sig.direction == 1
        assert sig.source == "north_flow"

    def test_north_flow_bearish(self):
        """北向净买入 < 0 → -1"""
        from data_adapter.factors.dashboard import _signal_from_north_flow
        nf = {"symbol": "600519", "north_net_buy": -1000, "north_holding_pct": 3.0,
              "data_grade": "PRIMARY"}
        sig = _signal_from_north_flow(nf)
        assert sig is not None
        assert sig.direction == -1

    # ── ETF 溢价信号 ──

    def test_etf_premium_overheat(self):
        """溢价 > 1% → -1（看空）"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": 2.5, "data_grade": "PRIMARY"}
        sig = _signal_from_etf_premium(ep)
        assert sig is not None
        assert sig.direction == -1
        assert sig.source == "etf_premium"

    def test_etf_premium_discount(self):
        """折价 > 1% → +1（看多）"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": -1.8, "data_grade": "PRIMARY"}
        sig = _signal_from_etf_premium(ep)
        assert sig is not None
        assert sig.direction == 1

    def test_etf_premium_normal(self):
        """溢价在 ±1% 内 → 无信号"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": 0.3, "data_grade": "PRIMARY"}
        assert _signal_from_etf_premium(ep) is None
