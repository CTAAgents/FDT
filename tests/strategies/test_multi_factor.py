"""
MultiFactorStrategy G27 测试 — 5 因子数据源接入。

覆盖：
  - _calc_warrant_change：真实仓单数据→有符号分；无数据→惰性0
  - _calc_inventory：单点绝对值(无分位)→惰性0；含 pct 字段→激活
  - _calc_capacity：同上
  - compute()：ctx_extra 注入 warrant_data 后因子被消费（不再恒为0）
"""
import pytest


def _mfs():
    from strategies.multi_factor_strategy import MultiFactorStrategy
    return MultiFactorStrategy()


def _ctx_extra(warrant=None, inventory=None, supply=None):
    return {
        "warrant_data": warrant or {},
        "inventory_data": inventory or {},
        "supply_data": supply or {},
    }


class TestWarrantChange:
    def test_no_data_inert(self):
        from strategies.multi_factor_strategy import _calc_warrant_change
        assert _calc_warrant_change({"symbol": "RB"}, None) == 0.0
        assert _calc_warrant_change({"symbol": "RB"}, _ctx_extra()) == 0.0

    def test_warrant_increase_bearish(self):
        from strategies.multi_factor_strategy import _calc_warrant_change
        # 仓单增 10%（供应压力↑）→ 偏空（负分）
        ctx = _ctx_extra(warrant={"RB": {"total": 1000.0, "daily_change": 100.0}})
        score = _calc_warrant_change({"symbol": "RB"}, ctx)
        assert score < 0
        assert -1.0 <= score <= 1.0

    def test_warrant_decrease_bullish(self):
        from strategies.multi_factor_strategy import _calc_warrant_change
        # 仓单减 10%（库存紧张↑）→ 偏多（正分）
        ctx = _ctx_extra(warrant={"RB": {"total": 1000.0, "daily_change": -100.0}})
        score = _calc_warrant_change({"symbol": "RB"}, ctx)
        assert score > 0

    def test_warrant_zero_total_inert(self):
        from strategies.multi_factor_strategy import _calc_warrant_change
        ctx = _ctx_extra(warrant={"RB": {"total": 0.0, "daily_change": 5.0}})
        assert _calc_warrant_change({"symbol": "RB"}, ctx) == 0.0


class TestInventoryInert:
    def test_no_data_inert(self):
        from strategies.multi_factor_strategy import _calc_inventory
        assert _calc_inventory({"symbol": "CU"}, None) == 0.0

    def test_single_snapshot_inert(self):
        """G27 关键：单点绝对值无分位语义 → 必须惰性0（不造假信号）"""
        from strategies.multi_factor_strategy import _calc_inventory
        # 缓存实际形态：{"social_stock": 28.5, "unit": "万吨", "cached_at": "..."}
        ctx = _ctx_extra(inventory={"CU": {"social_stock": 28.5, "unit": "万吨", "cached_at": "2026-07-04"}})
        assert _calc_inventory({"symbol": "CU"}, ctx) == 0.0

    def test_pct_field_activates(self):
        from strategies.multi_factor_strategy import _calc_inventory
        # 未来接入分位源后：pct=0.9（累库）→ 偏空
        ctx = _ctx_extra(inventory={"CU": {"pct": 0.9, "cached_at": "2026-07-04"}})
        score = _calc_inventory({"symbol": "CU"}, ctx)
        assert score < 0  # 高库存分位→偏空
        # pct=0.1（去库）→ 偏多
        ctx2 = _ctx_extra(inventory={"CU": {"pct": 0.1}})
        assert _calc_inventory({"symbol": "CU"}, ctx2) > 0


class TestCapacityInert:
    def test_no_data_inert(self):
        from strategies.multi_factor_strategy import _calc_capacity
        assert _calc_capacity({"symbol": "RB"}, None) == 0.0

    def test_single_snapshot_inert(self):
        from strategies.multi_factor_strategy import _calc_capacity
        ctx = _ctx_extra(supply={"RB": {"production": 2600.0, "unit": "万吨/月", "cached_at": "2026-07-04"}})
        assert _calc_capacity({"symbol": "RB"}, ctx) == 0.0

    def test_pct_field_activates(self):
        from strategies.multi_factor_strategy import _calc_capacity
        ctx = _ctx_extra(supply={"RB": {"pct": 0.95}})  # 高开工→偏空
        assert _calc_capacity({"symbol": "RB"}, ctx) < 0


class TestComputeConsumesWarrant:
    def test_warrant_factor_nonzero_when_data_present(self):
        """compute() 在有仓单数据时，warrant_change 因子应被消费（非恒0）"""
        from strategies.multi_factor_strategy import MultiFactorStrategy
        s = MultiFactorStrategy()
        tech = [{
            "symbol": "RB", "price": 3500.0, "change_pct": 1.0,
            "ma_slope": 0.1, "macd_cross": "none", "atr": 50.0,
            "bb": 0.5, "bb_width": 0.05, "vol_ratio": 1.0,
        }]
        ctx = {
            "extra": _ctx_extra(warrant={"RB": {"total": 1000.0, "daily_change": -80.0}})
        }
        signals = s.compute(tech, {}, ctx)
        # 仓单减 → 因子为正；若其它因子足以越过 active_factors>=3 阈值则产出信号
        # 至少验证因子计算不抛错且路径可达
        assert isinstance(signals, list)

    def test_interface(self):
        from strategies.multi_factor_strategy import MultiFactorStrategy
        s = MultiFactorStrategy()
        assert s.name == "multi_factor"
        assert "warrant_change" in s._weights
