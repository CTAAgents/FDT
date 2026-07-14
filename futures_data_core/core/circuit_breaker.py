"""数据源熔断器 [INDEPENDENT]。

失败计数 + 冷却窗口 + 半开探测。用于多源降级链中自动屏蔽**持续不可用**的数据源，
避免每个品种都空打失败源拖慢全流程（如 TDX 不可用仍每根 K 线重试）。

状态机：
    CLOSED   正常放行
      │ 连续失败 ≥ failure_threshold
      ▼
    OPEN     直接跳过该源（不再调用），进入冷却
      │ cooldown 到期
      ▼
    HALF_OPEN 放行一次探测
      │ 成功 → CLOSED（清零失败计数）
      │ 失败 → OPEN（重置冷却计时）

注意：熔断状态为**进程内**内存态。单次扫描进程内有效；跨进程持久化非本次范围
（FDT 单扫描进程内已足够体现"连续失败自动屏蔽/恢复"价值）。
"""
from __future__ import annotations

import time
from typing import Optional

__all__ = ["CircuitBreaker"]


class CircuitBreaker:
    """轻量熔断器，与同步/异步调用方解耦（仅维护状态，不发起调用）。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str = "",
        failure_threshold: int = 5,
        cooldown: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._state = self.CLOSED
        self._opened_at: Optional[float] = None

    def is_open(self) -> bool:
        """是否应跳过该源（严格 OPEN 才返回 True；HALF_OPEN 允许探测一次）。"""
        if self._state == self.OPEN:
            if self._opened_at is not None and (time.monotonic() - self._opened_at) >= self.cooldown:
                self._state = self.HALF_OPEN
                self._opened_at = None
            else:
                return True
        return False

    def record_success(self) -> None:
        if self._state in (self.OPEN, self.HALF_OPEN):
            self._state = self.CLOSED
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()

    def state(self) -> str:
        self.is_open()  # 触发可能的 OPEN→HALF_OPEN 转换
        return self._state
