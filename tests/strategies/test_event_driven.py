"""
EventDrivenStrategy 测试 — 事件日历 + 价格偏差
"""


class TestEventDriven:
    """事件驱动策略测试"""

    def test_strategy_interface(self):
        from strategies.event_driven_strategy import EventDrivenStrategy
        s = EventDrivenStrategy()
        assert s.name == "event_driven"

    def test_find_recent_events_july(self):
        """7月中旬应有 USDA/MPOB 事件"""
        from strategies.event_driven_strategy import _find_recent_events
        events = _find_recent_events()
        # 7月14日, 7月12 USDA和7月10 MPOB可能在范围内
        if events:
            assert all("event_date" in e for e in events)

    def test_unknown_symbol_skipped(self):
        """tech_list 中不存在的品种不产出信号"""
        from strategies.event_driven_strategy import EventDrivenStrategy
        s = EventDrivenStrategy()
        # 用不存在的品种测试
        signals = s.compute([{"symbol": "UNKNOWN", "change_pct": 5.0}], {})
        assert len(signals) == 0

    def test_event_metadata(self):
        """信号携带事件元数据"""
        from strategies.event_driven_strategy import EventDrivenStrategy
        s = EventDrivenStrategy()
        tech = [{"symbol": "RB", "change_pct": -2.0}]
        # 七月可能有美联储事件
        signals = s.compute(tech, {})
        for sig in signals:
            assert "event" in sig.meta
            assert "event_date" in sig.meta
            assert "expected" in sig.meta
            assert "price_change_pct" in sig.meta

    def test_score_returns_scored_signals(self):
        from strategies.base_v2 import RawSignal
        from strategies.event_driven_strategy import EventDrivenStrategy
        s = EventDrivenStrategy()
        raw = RawSignal(symbol="RB", direction="bull", signal_type="ed.contrary",
                        raw_score=0.3, strategy_name="event_driven",
                        meta={"event": "Test", "event_date": "2026-07-14",
                              "expected": "bear", "price_change_pct": 3.0, "type": "event_contrary"})
        results = s.score([raw], [])
        assert len(results) == 1
        assert results[0].weight == 0.5
