"""
scheduler/engine.py — 心跳发动机

两种运行模式：
  1. run_forever()  — 后台守护进程，每60秒心跳
  2. run_once()     — 单次检查，适合集成到自循环前置

心跳循环：
  [启动] → 每60秒 → 检查所有触发器 → 触发匹配的任务 → 记录日志
"""

import json
import os
import sys
import time
import signal
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    from .triggers import (
        get_default_triggers,
        _set_triggered,
        _get_trigger_state,
        _save_json,
    )
    from .tasks import get_task
except ImportError:
    # 直接运行时（非包导入模式）
    # 在 __main__ 部分会处理路径注入
    pass


# ─── 日志 ───────────────────────────────────────────────

_LOG_PATH = "scheduler/scheduler.log"


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _append_log(line)


def _append_log(line: str):
    """追加日志到文件"""
    root = Path(__file__).resolve().parent.parent
    log_file = root / _LOG_PATH
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─── 状态保存 ───────────────────────────────────────────

def save_heartbeat():
    """每次心跳后保存状态"""
    root = Path(__file__).resolve().parent.parent
    state = _get_trigger_state()
    state["last_heartbeat"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["pid"] = os.getpid()
    _save_json("memory/schedule_state.json", state)


# ─── 发动机 ─────────────────────────────────────────────

class SchedulerEngine:
    """
    调度发动机。

    参数:
        triggers: 触发器列表（默认用 get_default_triggers()）
        heartbeat_interval: 心跳间隔秒数（默认60）
        max_tasks_per_beat: 每次心跳最多触发的任务数（默认3）
    """

    def __init__(
        self,
        triggers: list | None = None,
        heartbeat_interval: int = 60,
        max_tasks_per_beat: int = 3,
    ):
        self.triggers = triggers or get_default_triggers()
        self.heartbeat_interval = heartbeat_interval
        self.max_tasks_per_beat = max_tasks_per_beat
        self._running = False

    def check_and_run(self) -> list[dict]:
        """
        单次检查：检查所有触发器，运行匹配的任务。
        返回触发记录列表。
        """
        now = datetime.now()
        triggered = []

        for trigger in self.triggers:
            should_fire, reason = trigger.check(now)
            if not should_fire:
                continue

            task = get_task(trigger.task_name)
            if task is None:
                _log(f"⚠️  任务未注册: {trigger.task_name}")
                continue

            _log(f"🔔  触发: {trigger.task_name} — {reason}")
            try:
                result = task()
                status = "✅" if result.success else "❌"
                _log(f"  {status} 完成: {result.summary[:120]}")
            except Exception as e:
                _log(f"  ❌ 异常: {e}")
                result = None

            _set_triggered(trigger.task_name)
            triggered.append({
                "trigger": trigger.task_name,
                "reason": reason,
                "success": result.success if result else False,
                "time": datetime.now().strftime("%H:%M:%S"),
            })

            if len(triggered) >= self.max_tasks_per_beat:
                _log(f"⏸ 本心跳已达上限({self.max_tasks_per_beat})，停止检查")
                break

        return triggered

    def _daemonize(self):
        """衍生后台进程，当前进程立即返回"""
        import subprocess

        root = Path(__file__).resolve().parent.parent
        script = str(root / "scheduler" / "engine.py")
        venv = root / "venv" / "Scripts" / "python.exe"
        python = str(venv) if venv.exists() else sys.executable

        # 使用 bootstrap.py 启动守护进程（避免模块相对导入问题）
        bootstrap_script = str(root / "bootstrap.py")

        log_file = str(root / "scheduler" / "daemon.log")
        pid_file = str(root / "memory" / "daemon.pid")

        # Windows: DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = 0x00000008 | 0x00000200

        try:
            proc = subprocess.Popen(
                [python, bootstrap_script, "daemon"],
                cwd=str(root),
                creationflags=flags,
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            with open(pid_file, "w") as f:
                f.write(str(proc.pid))

            _log(f"   守护进程已启动 (PID: {proc.pid})")
            print(f"\n✅ 守护进程已启动")
            print(f"   PID: {proc.pid}")
            print(f"   日志: scheduler/daemon.log")
            print(f"   心跳: 每60秒")
            print(f"\n  停止: python scheduler/engine.py stop")
        except Exception as e:
            print(f"\n❌ 守护进程启动失败: {e}")

    def run_forever(self, daemon: bool = False):
        """
        后台守护模式：每 heartbeat_interval 秒执行一次 check_and_run()。

        参数:
            daemon: 如True，使用subprocess衍生后台进程，当前进程立即返回
        """
        if daemon:
            return self._daemonize()

        self._running = True
        _log(f"🚀 调度器启动 | 心跳={self.heartbeat_interval}s | {len(self.triggers)}个触发器")
        _log(f"   可用任务: {', '.join(t for t in _get_task_names() if t)}")

        # 注册信号处理
        def _handle_sig(sig, frame):
            self._running = False
            _log("📴 收到停止信号，调度器退出")

        signal.signal(signal.SIGINT, _handle_sig)
        signal.signal(signal.SIGTERM, _handle_sig)

        heartbeat_count = 0
        while self._running:
            heartbeat_count += 1
            _log(f"\n--- 心跳 #{heartbeat_count} @ {datetime.now().strftime('%H:%M:%S')} ---")

            triggered = self.check_and_run()

            if not triggered:
                _log(f"  无触发任务")

            save_heartbeat()

            if self._running:
                time.sleep(self.heartbeat_interval)

        _log(f"调度器停止（共运行{heartbeat_count}次心跳）")


def _get_task_names() -> list[str]:
    try:
        from .tasks import list_tasks as lt
        return lt()
    except ImportError:
        return []


# ─── 便捷函数 ───────────────────────────────────────────

def run_once(triggers: list | None = None) -> list[dict]:
    """
    单次调度检查。适用于集成到自循环前置中：
      from scheduler import run_once
      triggered = run_once()

    返回: [{"trigger":..., "reason":..., "success":...}, ...]
    """
    engine = SchedulerEngine(triggers=triggers)
    return engine.check_and_run()


# ─── 直接运行 ───────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os
    from pathlib import Path

    # 确保路径正确
    _root = Path(__file__).resolve().parent.parent
    os.chdir(str(_root))
    sys.path.insert(0, str(_root))

    # 直接导入（避开相对导入）
    from scheduler.triggers import get_default_triggers, _set_triggered, _get_trigger_state, _save_json
    from scheduler.tasks import get_task, list_tasks

    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "daemon":
        engine = SchedulerEngine()
        engine.run_forever(daemon=True)
    elif mode == "stop":
        pid_file = Path(__file__).resolve().parent.parent / "memory" / "daemon.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                pid_file.unlink()
                print(f"✅ 已停止守护进程 (PID: {pid})")
            except ProcessLookupError:
                pid_file.unlink()
                print(f"ℹ️  进程(PID:{pid})已不存在，清理pid文件")
            except Exception as e:
                print(f"❌ 停止失败: {e}")
        else:
            print(f"ℹ️  未找到守护进程 (pid文件不存在)")
    elif mode == "once":
        triggered = run_once()
        print(f"\n本次触发: {len(triggered)} 个任务")
        for t in triggered:
            icon = "✅" if t["success"] else "❌"
            print(f"  {icon} {t['trigger']}: {t['reason']}")
    elif mode == "forever":
        engine = SchedulerEngine()
        engine.run_forever()
    else:
        print(f"用法: python scheduler/engine.py [once|forever|daemon]")
        print(f"  once    — 单次检查（默认）")
        print(f"  forever — 持续运行（每60秒心跳）")
        print(f"  daemon  — 后台模式（进程分离）")
