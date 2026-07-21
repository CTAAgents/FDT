#!/usr/bin/env python3
"""
tool_circuit_breaker.py — 工具熔断与自动降级 (D2 Tool Phase 4)
===============================================================
功能:
  1. 滑动窗口失败率计算
  2. 熔断状态机 (CLOSED → OPEN → HALF_OPEN → CLOSED)
  3. 自动降级到备用工具
  4. 熔断事件日志

用法:
  from scripts.tool_circuit_breaker import CircuitBreaker
  cb = CircuitBreaker()
  if cb.is_allowed("data_scan"):
      result = call_tool()
      cb.record_success("data_scan")
  else:
      fallback = cb.get_fallback("data_scan")
"""

import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "circuit_breaker"


class CircuitBreaker:
    """工具熔断器"""

    STATES = {"CLOSED": "正常", "OPEN": "熔断", "HALF_OPEN": "半开"}

    def __init__(self, storage_dir: Optional[Path] = None,
                 failure_threshold: int = 5, recovery_timeout: int = 60,
                 window_seconds: int = 300):
        """
        Args:
            failure_threshold: 窗口内失败次数超过此值触发熔断
            recovery_timeout: 熔断持续时间 (秒)
            window_seconds: 滑动窗口大小 (秒)
        """
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_seconds = window_seconds

        # 状态: {tool_name: {"state": str, "last_failure_time": float, "failure_count": int}}
        self._states: dict[str, dict] = {}
        # 失败时间窗口: {tool_name: deque[float]}
        self._failure_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # 备用工具映射
        self._fallbacks: dict[str, list[str]] = {}
        self._events: list[dict] = []
        self._load()

    def _state_file(self) -> Path:
        return self.storage_dir / "circuit_state.json"

    def _events_file(self) -> Path:
        return self.storage_dir / "circuit_events.jsonl"

    def _load(self):
        sf = self._state_file()
        if sf.exists():
            try:
                with open(sf, "r") as f:
                    self._states = json.load(f)
            except Exception:
                pass
        ef = self._events_file()
        if ef.exists():
            with open(ef, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

    def _save_states(self):
        with open(self._state_file(), "w") as f:
            json.dump(self._states, f, indent=2)

    def _save_event(self, event: dict):
        self._events.append(event)
        with open(self._events_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def register_fallback(self, tool_name: str, fallbacks: list[str]):
        """注册备用工具"""
        self._fallbacks[tool_name] = fallbacks

    def get_fallback(self, tool_name: str) -> Optional[str]:
        """获取备用工具"""
        fallbacks = self._fallbacks.get(tool_name, [])
        for fb in fallbacks:
            if self.is_allowed(fb):
                return fb
        return None

    def is_allowed(self, tool_name: str) -> bool:
        """检查是否允许调用"""
        now = time.time()
        state_info = self._states.get(tool_name, {"state": "CLOSED", "last_failure_time": 0})

        if state_info["state"] == "CLOSED":
            return True

        if state_info["state"] == "OPEN":
            # 检查是否过了恢复时间
            if now - state_info["last_failure_time"] >= self.recovery_timeout:
                state_info["state"] = "HALF_OPEN"
                self._save_states()
                self._save_event({
                    "event": "half_open",
                    "tool": tool_name,
                    "timestamp": datetime.now().isoformat(),
                })
                return True
            return False

        # HALF_OPEN: 放行一个请求测试
        return True

    def record_success(self, tool_name: str):
        """记录成功"""
        state_info = self._states.get(tool_name, {})
        if state_info.get("state") in ("OPEN", "HALF_OPEN"):
            state_info["state"] = "CLOSED"
            state_info["failure_count"] = 0
            self._save_states()
            self._save_event({
                "event": "recovered",
                "tool": tool_name,
                "timestamp": datetime.now().isoformat(),
            })
        self._states[tool_name] = self._states.get(tool_name, {"state": "CLOSED", "failure_count": 0, "last_failure_time": 0})

    def record_failure(self, tool_name: str):
        """记录失败"""
        now = time.time()
        self._failure_windows[tool_name].append(now)

        # 清理窗口外的记录
        cutoff = now - self.window_seconds
        while self._failure_windows[tool_name] and self._failure_windows[tool_name][0] < cutoff:
            self._failure_windows[tool_name].popleft()

        recent_failures = len(self._failure_windows[tool_name])

        if tool_name not in self._states:
            self._states[tool_name] = {"state": "CLOSED", "failure_count": 0, "last_failure_time": 0}

        state_info = self._states[tool_name]
        state_info["failure_count"] = state_info.get("failure_count", 0) + 1
        state_info["last_failure_time"] = now

        if recent_failures >= self.failure_threshold and state_info["state"] == "CLOSED":
            state_info["state"] = "OPEN"
            self._save_states()
            self._save_event({
                "event": "opened",
                "tool": tool_name,
                "failures": recent_failures,
                "window": self.window_seconds,
                "timestamp": datetime.now().isoformat(),
            })
            logger.warning(f"Circuit breaker OPENED for {tool_name} ({recent_failures} failures)")

        self._save_states()

    def get_status(self) -> dict:
        """获取所有工具的状态"""
        status = {}
        for name, state_info in self._states.items():
            window_failures = len(self._failure_windows.get(name, []))
            status[name] = {
                "state": state_info["state"],
                "state_label": self.STATES.get(state_info["state"], "?"),
                "failure_count": state_info.get("failure_count", 0),
                "window_failures": window_failures,
                "has_fallback": name in self._fallbacks and len(self._fallbacks[name]) > 0,
            }
        return status

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """获取最近的事件"""
        return sorted(self._events, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="工具熔断管理")
    parser.add_argument("action", choices=["status", "events", "fail", "success"])
    parser.add_argument("--tool", "-t", help="工具名")
    args = parser.parse_args()

    cb = CircuitBreaker()

    if args.action == "fail" and args.tool:
        cb.record_failure(args.tool)
        print(f"Recorded failure for {args.tool}")
    elif args.action == "success" and args.tool:
        cb.record_success(args.tool)
        print(f"Recorded success for {args.tool}")
    elif args.action == "events":
        for e in cb.get_recent_events():
            print(f"  [{e['event']}] {e['tool']} @ {e['timestamp']}")
    else:
        status = cb.get_status()
        for name, s in status.items():
            print(f"  {name:<25} {s['state']:<12} failures={s['failure_count']} fallback={'Y' if s['has_fallback'] else 'N'}")


if __name__ == "__main__":
    main()
