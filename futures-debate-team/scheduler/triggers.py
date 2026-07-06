"""
scheduler/triggers.py — 触发器定义

三种触发类型：
  1. TimeTrigger     — 按时间/星期触发（如：工作日19:15）
  2. DataTrigger     — 按数据量触发（如：≥50条新样本训练ML）
  3. EventTrigger    — 按事件触发（如：新K线就绪、辩论完成）

每个触发器返回 (should_fire: bool, reason: str)
"""

import json
import os
from datetime import datetime, date, time
from pathlib import Path
from typing import Callable


# ─── 工具 ───────────────────────────────────────────────

def _project_root() -> Path:
    """返回专家团根目录"""
    return Path(__file__).resolve().parent.parent


def _load_json(rel_path: str) -> dict:
    fp = _project_root() / rel_path
    if not fp.exists():
        return {}
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(rel_path: str, data: dict):
    fp = _project_root() / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 触发状态文件 ──────────────────────────────────────

_TRIGGER_STATE_PATH = "memory/schedule_state.json"


def _get_trigger_state() -> dict:
    """读取上次触发记录，防止同一天重复触发同一任务"""
    state = _load_json(_TRIGGER_STATE_PATH)
    if not state:
        state = {"last_triggered": {}}
    return state


def _set_triggered(task_name: str):
    """记录任务已触发"""
    state = _get_trigger_state()
    state["last_triggered"][task_name] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save_json(_TRIGGER_STATE_PATH, state)


def _was_triggered_today(task_name: str) -> bool:
    """检查任务今天是否已触发过"""
    state = _get_trigger_state()
    last = state.get("last_triggered", {}).get(task_name, "")
    return last.startswith(datetime.now().strftime("%Y-%m-%d"))


# ─── Trigger 1: 时间触发器 ─────────────────────────────

class TimeTrigger:
    """
    按时间/星期触发。

    参数:
        task_name: 任务标识（用于去重）
        weekdays: 星期列表 0=周一 6=周日。None=每天
        hour: 触发小时（0-23）
        minute: 触发分钟（0-59）
        max_per_day: 每天最多触发次数（默认1，防重复频繁触发）
    """

    def __init__(
        self,
        task_name: str,
        weekdays: list[int] | None = None,
        hour: int = 0,
        minute: int = 0,
        max_per_day: int = 1,
    ):
        self.task_name = task_name
        self.weekdays = weekdays
        self.hour = hour
        self.minute = minute
        self.max_per_day = max_per_day

    def check(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now()

        # 星期检查
        if self.weekdays is not None and now.weekday() not in self.weekdays:
            return False, f"今天星期{now.weekday()}不在触发日{self.weekdays}"

        # 时间检查（精确到分钟）
        if now.hour != self.hour or now.minute != self.minute:
            return False, f"当前{now.hour:02d}:{now.minute:02d}，目标{self.hour:02d}:{self.minute:02d}"

        # 去重检查
        trigger_count = _get_trigger_state().get("last_triggered", {}).get(self.task_name + "_count", 0)
        if trigger_count >= self.max_per_day:
            return False, f"今日已触发{trigger_count}次，上限{self.max_per_day}"

        return True, f"时间触发: {self.task_name} @ {self.hour:02d}:{self.minute:02d}"


# ─── Trigger 2: 数据量触发器 ───────────────────────────

class DataTrigger:
    """
    按数据积累量触发（如 samples ≥ threshold 时触发训练）。

    参数:
        task_name: 任务标识
        data_path: 数据文件路径（相对项目根）
        count_key: json内用于计数的key路径（如 "records"）
        threshold: 触发阈值
        cooldown_minutes: 触发后的冷却时间（防止频繁触发）
    """

    def __init__(
        self,
        task_name: str,
        data_path: str,
        count_key: str = "records",
        threshold: int = 50,
        cooldown_minutes: int = 1440,  # 默认24小��冷却
    ):
        self.task_name = task_name
        self.data_path = data_path
        self.count_key = count_key
        self.threshold = threshold
        self.cooldown_minutes = cooldown_minutes

    def check(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now()

        # 冷却检查
        state = _get_trigger_state()
        last_fired = state.get("last_triggered", {}).get(self.task_name, "")
        if last_fired:
            try:
                last_dt = datetime.strptime(last_fired, "%Y-%m-%d %H:%M")
                elapsed = (now - last_dt).total_seconds() / 60
                if elapsed < self.cooldown_minutes:
                    return False, f"冷却中（距上次触发{elapsed:.0f}分钟，需{self.cooldown_minutes}分钟）"
            except ValueError:
                pass

        # 数据量检查
        data = _load_json(self.data_path)
        if not data:
            return False, f"数据文件{self.data_path}为空"

        # 支持简单的key路径（只取第一级，因为数据格式简单）
        if isinstance(data, dict) and self.count_key in data:
            val = data[self.count_key]
            if isinstance(val, list):
                count = len(val)
            elif isinstance(val, (int, float)):
                count = int(val)
            else:
                count = 0
        else:
            count = 0
        if count < self.threshold:
            return False, f"数据量{count}<{self.threshold}，不触发"

        return True, f"数据触发: {self.task_name} ({count}≥{self.threshold})"


# ─── Trigger 3: 事件触发器 ─────────────────────────────

class EventTrigger:
    """
    按外部事件触发（通过 event_queue 或文件信号）。

    参数:
        task_name: 任务标识
        signal_file: 事件信号文件路径（存在且内容为"trigger"时触发）
        cleanup: 触发后是否清除信号文件
    """

    def __init__(self, task_name: str, signal_file: str, cleanup: bool = True):
        self.task_name = task_name
        self.signal_file = signal_file
        self.cleanup = cleanup

    def check(self, now: datetime | None = None) -> tuple[bool, str]:
        fp = _project_root() / self.signal_file
        if not fp.exists():
            return False, f"信号文件不存在: {self.signal_file}"

        content = fp.read_text(encoding="utf-8").strip()
        if content != "trigger":
            return False, f"信号文件内容={content}，期望=trigger"

        if self.cleanup:
            fp.unlink()

        return True, f"事件触发: {self.task_name} (信号文件: {self.signal_file})"


# ─── 注册表：所有预配置触发器 ───────────────────────────

def get_default_triggers() -> list:
    """返回默认触发器列表"""
    return [
        # 1. 日常辩论：工作日19:15 → 已迁移到 WorkBuddy Automation
        # （由 WB cron 触发，不再依赖守护进程调度器）
        # TimeTrigger(
        #     task_name="daily_debate",
        #     weekdays=[0, 1, 2, 3, 4],  # 周一到周五
        #     hour=19,
        #     minute=15,
        # ),
        # 2. 自动发布：每日23:05
        TimeTrigger(
            task_name="auto_publish",
            weekdays=None,  # 每天
            hour=23,
            minute=5,
        ),
        # 3. 主力映射更新：每日15:30（收盘后）
        TimeTrigger(
            task_name="update_dominant_mapping",
            weekdays=[0, 1, 2, 3, 4],  # 工作日收盘后
            hour=15,
            minute=30,
        ),
        # 4. 验证+校准+进化：每日首次启动时（数据量触发）
        DataTrigger(
            task_name="validate_and_evolve",
            data_path="memory/execution_followup.json",
            count_key="records",
            threshold=1,  # 有未验证记录就触发
            cooldown_minutes=1440,
        ),
        # 5. ML训练检查：新样本≥50条
        DataTrigger(
            task_name="ml_training_check",
            data_path="memory/debate_journal.json",
            count_key="entries",
            threshold=50,
            cooldown_minutes=4320,  # 每3天最多检查一次
        ),
    ]
