"""
主力合约解析器测试 — 换月判定 / 持久化 / 合约解析 / 跳空调整。
"""

from __future__ import annotations

import pytest

from futures_data_core.core.dominant_resolver import (
    DominantResolver,
    _safe_dt,
    has_month_suffix,
)

# ── 辅助：模拟合约信息 ──────────────────────────────────

class FakeContract:
    """模拟合约信息，适配 dominant_resolver._calculate_dominant 参数。"""

    def __init__(
        self,
        code: str,
        volume: int = 0,
        open_interest: int = 0,
        last_trade_date: str = "2099-12-31",
        close_price: float = 0.0,
        delivery_month: str = "9900",
    ):
        self.code = code
        self.volume = volume
        self.open_interest = open_interest
        self.last_trade_date = last_trade_date
        self.close_price = close_price
        self.delivery_month = delivery_month


# ── 测试用例 ────────────────────────────────────────────


class TestHasMonthSuffix:
    def test_with_suffix(self):
        assert has_month_suffix("CU2409") is True

    def test_without_suffix(self):
        assert has_month_suffix("CU") is False

    def test_short_symbol(self):
        assert has_month_suffix("") is False
        assert has_month_suffix("A") is False

    def test_numeric_suffix_only(self):
        assert has_month_suffix("ABC1234") is True
        assert has_month_suffix("ABC12") is False  # len <= 4


class TestResolve:
    def test_resolve_default_fallback(self, resolver):
        """空映射时 resolve 返回 '{symbol}00'。"""
        assert resolver.resolve("CU") == "CU00"

    def test_resolve_after_manual_set(self, resolver):
        """手动设置映射后能正确解析。"""
        resolver._mapping["CU"] = {"main": "CU2409"}
        assert resolver.resolve("CU") == "CU2409"

    def test_resolve_after_load(self, resolver, tmp_path):
        """加载映射后能正确解析。"""
        # 先保存再重新加载
        resolver._mapping["RB"] = {"main": "RB2501"}
        resolver.save()

        r2 = DominantResolver(storage_path=str(tmp_path / "dominant_map.json"))
        r2.load()
        assert r2.resolve("RB") == "RB2501"


class TestSaveAndLoad:
    def test_save_and_load(self, resolver, tmp_path):
        """持久化后再加载，数据完整。"""
        resolver._mapping["CU"] = {
            "variety": "CU",
            "main": "CU2409",
            "next_main": "CU2501",
            "index": "CU99",
        }
        resolver.save()

        r2 = DominantResolver(storage_path=str(tmp_path / "dominant_map.json"))
        r2.load()
        assert r2.get_mapping()["CU"]["main"] == "CU2409"
        assert r2.get_mapping()["CU"]["next_main"] == "CU2501"

    def test_save_with_rollover_events(self, resolver, tmp_path):
        """持久化包含换月事件的数据。"""
        resolver._rollover_history.append({
            "variety": "CU",
            "prev_main": "CU2408",
            "new_main": "CU2409",
            "switch_date": "2026-07-15",
            "gap": 580.0,
        })
        resolver.save()

        r2 = DominantResolver(storage_path=str(tmp_path / "dominant_map.json"))
        r2.load()
        events = r2.get_rollover_events()
        assert len(events) == 1
        assert events[0]["prev_main"] == "CU2408"


class TestCalculateDominant:
    def test_no_switch(self, resolver):
        """持仓量最大即当前主力，不触发换月。"""
        contracts = [
            FakeContract("CU2408", open_interest=80000, delivery_month="2408", last_trade_date="2026-08-15"),
            FakeContract("CU2409", open_interest=150000, delivery_month="2409", last_trade_date="2026-09-15"),
            FakeContract("CU2410", open_interest=120000, delivery_month="2410", last_trade_date="2026-10-15"),
        ]
        result = resolver._calculate_dominant(
            variety="CU",
            contracts=contracts,
            current_main="CU2409",
            trade_date="2026-06-27",
            is_financial=False,
        )
        assert result["main"] == "CU2409"
        assert result["switched"] is False

    def test_switch(self, resolver):
        """新合约持仓量 >= 旧主力×1.1 触发换月。"""
        contracts = [
            FakeContract("CU2408", open_interest=80000, delivery_month="2408", last_trade_date="2026-08-15"),
            FakeContract("CU2409", open_interest=150000, delivery_month="2409", last_trade_date="2026-09-15"),
            FakeContract("CU2410", open_interest=180000, delivery_month="2410", last_trade_date="2026-10-15"),
        ]
        result = resolver._calculate_dominant(
            variety="CU",
            contracts=contracts,
            current_main="CU2409",
            trade_date="2026-06-27",
            is_financial=False,
        )
        assert result["main"] == "CU2410"
        assert result["switched"] is True
        assert result["switch_date"] == "2026-06-27"

    def test_no_switch_below_threshold(self, resolver):
        """新合约持仓量不够 1.1 倍时不切换。"""
        contracts = [
            FakeContract("CU2408", open_interest=80000, delivery_month="2408", last_trade_date="2026-08-15"),
            FakeContract("CU2409", open_interest=150000, delivery_month="2409", last_trade_date="2026-09-15"),
            FakeContract("CU2410", open_interest=155000, delivery_month="2410", last_trade_date="2026-10-15"),
        ]
        result = resolver._calculate_dominant(
            variety="CU",
            contracts=contracts,
            current_main="CU2409",
            trade_date="2026-06-27",
            is_financial=False,
        )
        assert result["main"] == "CU2409"
        assert result["switched"] is False

    def test_all_near_delivery(self, resolver):
        """所有合约临近交割时返回空结果。"""
        contracts = [
            FakeContract("CU2407", open_interest=80000, delivery_month="2407", last_trade_date="2026-06-28"),
            FakeContract("CU2408", open_interest=150000, delivery_month="2408", last_trade_date="2026-06-29"),
        ]
        result = resolver._calculate_dominant(
            variety="CU",
            contracts=contracts,
            current_main="CU2407",
            trade_date="2026-06-27",
            is_financial=False,
        )
        assert result["main"] is None
        assert result["error"] is not None
        assert result["switched"] is False

    def test_financial_use_volume(self, resolver):
        """金融期货按成交量判定主力。"""
        contracts = [
            FakeContract("IF2408", volume=80000, open_interest=50000, delivery_month="2408", last_trade_date="2026-08-15"),
            FakeContract("IF2409", volume=150000, open_interest=100000, delivery_month="2409", last_trade_date="2026-09-15"),
        ]
        result = resolver._calculate_dominant(
            variety="IF",
            contracts=contracts,
            current_main="IF2408",
            trade_date="2026-06-27",
            is_financial=True,
        )
        # IF2409 成交量更大应成为主力
        assert result["main"] == "IF2409"
        assert result["switched"] is True

    def test_index_price(self, resolver):
        """指数加权价格计算正确。"""
        contracts = [
            FakeContract("CU2408", open_interest=100000, close_price=78000, delivery_month="2408", last_trade_date="2026-08-15"),
            FakeContract("CU2409", open_interest=200000, close_price=78500, delivery_month="2409", last_trade_date="2026-09-15"),
        ]
        result = resolver._calculate_dominant(
            variety="CU",
            contracts=contracts,
            trade_date="2026-06-27",
            is_financial=False,
        )
        # (100000 * 78000 + 200000 * 78500) / 300000 = 78333.33...
        expected = (100000 * 78000 + 200000 * 78500) / 300000
        assert result["index_price"] == pytest.approx(expected, rel=1e-3)
        assert result["index"] == "CU99"


class TestNextMain:
    def test_resolve_next_existing(self, resolver):
        resolver._mapping["CU"] = {"next_main": "CU2501"}
        assert resolver.resolve_next("CU") == "CU2501"

    def test_resolve_next_missing(self, resolver):
        assert resolver.resolve_next("CU") is None


class TestRolloverEvents:
    def test_get_all(self, resolver):
        resolver._rollover_history = [
            {"variety": "CU", "prev_main": "CU2408", "new_main": "CU2409", "switch_date": "2026-07-15"},
            {"variety": "RB", "prev_main": "RB2408", "new_main": "RB2409", "switch_date": "2026-07-16"},
        ]
        events = resolver.get_rollover_events()
        assert len(events) == 2

    def test_filter_by_variety(self, resolver):
        resolver._rollover_history = [
            {"variety": "CU", "prev_main": "CU2408", "new_main": "CU2409", "switch_date": "2026-07-15"},
            {"variety": "RB", "prev_main": "RB2408", "new_main": "RB2409", "switch_date": "2026-07-16"},
        ]
        events = resolver.get_rollover_events(variety="CU")
        assert len(events) == 1
        assert events[0]["variety"] == "CU"

    def test_filter_by_since(self, resolver):
        resolver._rollover_history = [
            {"variety": "CU", "prev_main": "CU2408", "new_main": "CU2409", "switch_date": "2026-07-15"},
            {"variety": "CU", "prev_main": "CU2409", "new_main": "CU2410", "switch_date": "2026-07-18"},
        ]
        events = resolver.get_rollover_events(since="2026-07-16")
        assert len(events) == 1
        assert events[0]["switch_date"] == "2026-07-18"


class TestGapAdjustment:
    def test_gap_adjustment_no_events(self, resolver):
        """无换月事件时 K 线不变。"""
        bars = [FakeBar("2026-07-01", 100), FakeBar("2026-07-02", 101)]
        result = resolver.resolve_with_gap_adjustment("CU", bars)
        assert result[0].close == 100
        assert result[1].close == 101

    def test_gap_adjustment_with_events(self, resolver):
        """有换月事件时 K 线价格被调整。"""
        resolver._rollover_history = [
            {"variety": "CU", "gap": 500.0, "switch_date": "2026-07-15"},
        ]
        bars = [FakeBar("2026-07-01", 100), FakeBar("2026-07-16", 105)]
        result = resolver.resolve_with_gap_adjustment("CU", bars)
        assert result[0].close == pytest.approx(100 - 500)
        assert result[1].close == pytest.approx(105 - 500)

    def test_gap_adjustment_single_bar(self, resolver):
        """单个 K 线无调整。"""
        resolver._rollover_history = [
            {"variety": "CU", "gap": 500.0, "switch_date": "2026-07-15"},
        ]
        bars = [FakeBar("2026-07-01", 100)]
        result = resolver.resolve_with_gap_adjustment("CU", bars)
        assert len(result) == 1
        assert result[0].close == 100


class TestRefreshAll:
    def test_refresh_all_no_collector(self, resolver):
        """无 collector 时 refresh_all 返回现有映射。"""
        mapping = resolver.refresh_all(None)  # type: ignore[arg-type]
        assert mapping == {}

    def test_refresh_all_with_empty_collector(self, resolver):
        """collector 无数据时返回空映射。"""
        class FakeCollector:
            name = "fake"
            priority = 99
            async def get_all_contracts(self):
                return {}

        mapping = resolver.refresh_all(FakeCollector())  # type: ignore[arg-type]
        assert mapping == {}


# ── 辅助类 ──────────────────────────────────────────────

class FakeBar:
    def __init__(self, date: str, close: float):
        self.date = date
        self.open = close
        self.high = close
        self.low = close
        self.close = close
        self.volume = 0
        self.amount = 0
        self.open_interest = 0


def test_safe_dt_valid():
    dt = _safe_dt("2026-06-27")
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.day == 27


def test_safe_dt_invalid():
    dt = _safe_dt("")
    assert dt.year == 2099


def test_safe_dt_none():
    dt = _safe_dt(None)  # type: ignore
    assert dt.year == 2099
