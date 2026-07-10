"""
Scheduler 集成测试 — G6
=======================

覆盖: TimeTrigger/DataTrigger/EventTrigger 触发逻辑 + SchedulerEngine 心跳上限。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


class TestTimeTrigger:
    """时间触发器测试"""

    @pytest.fixture(autouse=True)
    def _inject(self, monkeypatch):
        """注入 scheduler 路径并 mock 状态文件"""
        monkeypatch.setattr(
            "scheduler.triggers._get_trigger_state",
            lambda: {"last_triggered": {}}
        )
        monkeypatch.setattr(
            "scheduler.triggers._save_json",
            lambda p, d: None
        )

    def test_fires_at_correct_time(self):
        """时间匹配 + 星期匹配 → 触发"""
        from scheduler.triggers import TimeTrigger
        t = TimeTrigger("test", weekdays=[4], hour=10, minute=30)
        now = datetime(2026, 7, 10, 10, 30)  # 周五 10:30
        fire, reason = t.check(now)
        assert fire
        assert "时间触发" in reason

    def test_skips_wrong_hour(self):
        """小时不匹配 → 跳过"""
        from scheduler.triggers import TimeTrigger
        t = TimeTrigger("test", weekdays=[4], hour=10, minute=30)
        now = datetime(2026, 7, 10, 11, 30)
        fire, _ = t.check(now)
        assert not fire

    def test_skips_wrong_minute(self):
        """分钟不匹配 → 跳过"""
        from scheduler.triggers import TimeTrigger
        t = TimeTrigger("test", weekdays=[4], hour=10, minute=30)
        now = datetime(2026, 7, 10, 10, 31)
        fire, _ = t.check(now)
        assert not fire

    def test_skips_wrong_weekday(self):
        """星期不匹配 → 跳过"""
        from scheduler.triggers import TimeTrigger
        t = TimeTrigger("test", weekdays=[4], hour=10, minute=30)
        now = datetime(2026, 7, 11, 10, 30)  # 周六
        fire, _ = t.check(now)
        assert not fire

    def test_dedup_prevents_double_fire(self, monkeypatch):
        """同一天同任务触发超过 max_per_day → 跳过"""
        from scheduler.triggers import TimeTrigger
        t = TimeTrigger("test", weekdays=[4], hour=10, minute=30, max_per_day=1)

        # 已经触发过 1 次
        monkeypatch.setattr(
            "scheduler.triggers._get_trigger_state",
            lambda: {"last_triggered": {"test_count": 1}}
        )
        now = datetime(2026, 7, 10, 10, 30)
        fire, reason = t.check(now)
        assert not fire
        assert "已触发" in reason


class TestDataTrigger:
    """数据量触发器测试"""

    def test_fires_when_threshold_met(self, monkeypatch):
        """数据量 ≥ 阈值 → 触发"""
        monkeypatch.setattr(
            "scheduler.triggers._load_json",
            lambda p: {"records": [1, 2, 3]}  # 3条
        )
        monkeypatch.setattr(
            "scheduler.triggers._get_trigger_state",
            lambda: {"last_triggered": {}}
        )

        from scheduler.triggers import DataTrigger
        t = DataTrigger("test", "data.json", count_key="records", threshold=2)
        fire, reason = t.check(datetime.now())
        assert fire
        assert "数据触发" in reason

    def test_skips_when_below_threshold(self, monkeypatch):
        """数据量 < 阈值 → 跳过"""
        monkeypatch.setattr(
            "scheduler.triggers._load_json",
            lambda p: {"records": [1]}
        )
        monkeypatch.setattr(
            "scheduler.triggers._get_trigger_state",
            lambda: {"last_triggered": {}}
        )

        from scheduler.triggers import DataTrigger
        t = DataTrigger("test", "data.json", count_key="records", threshold=5)
        fire, _ = t.check(datetime.now())
        assert not fire

    def test_skips_empty_data(self, monkeypatch):
        """数据文件为空 → 跳过"""
        monkeypatch.setattr("scheduler.triggers._load_json", lambda p: {})
        monkeypatch.setattr(
            "scheduler.triggers._get_trigger_state",
            lambda: {"last_triggered": {}}
        )

        from scheduler.triggers import DataTrigger
        t = DataTrigger("test", "data.json", threshold=1)
        fire, _ = t.check(datetime.now())
        assert not fire


class TestSchedulerEngine:
    """SchedulerEngine 心跳上限测试"""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("scheduler.engine._get_trigger_state", lambda: {"last_triggered": {}})
        monkeypatch.setattr("scheduler.engine._save_json", lambda p, d: None)
        monkeypatch.setattr("scheduler.engine._log", lambda msg: None)
        monkeypatch.setattr("scheduler.engine.save_heartbeat", lambda: None)

    def _mock_triggers(self, count: int):
        """构造 N 个始终触发的 mock trigger"""
        class AlwaysTrigger:
            def __init__(self, name):
                self.task_name = name
            def check(self, now):
                return True, f"always: {self.task_name}"

        return [AlwaysTrigger(f"task_{i}") for i in range(count)]

    def _mock_task(self, name, monkeypatch):
        """mock get_task 返回一个假任务"""
        from collections import namedtuple
        Result = namedtuple("TaskResult", ["success", "summary"])
        monkeypatch.setattr(
            "scheduler.engine.get_task",
            lambda n: (lambda: Result(True, f"{n} done")) if n.startswith("task_") else None
        )
        monkeypatch.setattr("scheduler.engine._set_triggered", lambda n: None)

    def test_max_tasks_per_beat_caps(self, monkeypatch):
        """有 10 个触发项但 max_tasks=3 → 只执行 3 个"""
        from scheduler.engine import SchedulerEngine

        engine = SchedulerEngine(
            triggers=self._mock_triggers(10),
            max_tasks_per_beat=3,
        )
        self._mock_task("task_0", monkeypatch)

        triggered = engine.check_and_run()

        # 不会崩溃，且最多 3 个
        assert len(triggered) <= 3

    def test_run_once_returns_triggered(self, monkeypatch):
        """run_once 返回触发记录列表"""
        monkeypatch.setattr("scheduler.engine._get_trigger_state", lambda: {"last_triggered": {}})
        monkeypatch.setattr("scheduler.engine._save_json", lambda p, d: None)

        from scheduler.engine import run_once, SchedulerEngine

        class MyTrigger:
            task_name = "task_runonce"
            def check(self, now):
                return True, "test"

        monkeypatch.setattr("scheduler.engine.get_default_triggers", lambda: [MyTrigger()])
        self._mock_task("task_runonce", monkeypatch)
        monkeypatch.setattr("scheduler.engine._set_triggered", lambda n: None)
        monkeypatch.setattr("scheduler.engine._log", lambda msg: None)

        triggered = run_once(triggers=[MyTrigger()])
        assert len(triggered) == 1
        assert triggered[0]["trigger"] == "task_runonce"
