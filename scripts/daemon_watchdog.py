#!/usr/bin/env python3
"""
daemon_watchdog.py — Master Graph 守护进程看门狗

功能:
  检查 master_graph 守护进程是否存活，如果挂了则重启。
  由平台automation 每30分钟触发一次。

两种模式:
  1. 直接运行: python scripts/daemon_watchdog.py
     → 检查状态，挂了就重启，存活就静默
  2. 与平台automation配合: 作为cron任务触发

不依赖平台API，可独立运行。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 日志轮转：单文件上限 2MB，保留 5 个备份
ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / "memory" / "daemon.pid"
LOG_DIR = ROOT / "memory" / "logs"
DAEMON_LOG = LOG_DIR / "daemon.log"


def _get_watchdog_logger() -> logging.Logger:
    logger = logging.getLogger("fdt_watchdog")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = str(LOG_DIR / "watchdog.log")
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(
        logging.Formatter("[%(asctime)s] [watchdog] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(fh)
    return logger


_watchdog_logger = _get_watchdog_logger()


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [watchdog] {msg}"
    print(line)
    _watchdog_logger.info(msg)


def is_process_alive(pid: int) -> bool:
    """检查进程是否存活（跨平台）"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def find_daemon_python() -> str:
    """寻找合适的Python解释器"""
    def _try_pythonw(path: str) -> str | None:
        p = Path(path)
        pw = p.with_name("pythonw.exe")
        if pw.exists():
            return str(pw)
        return None

    candidates = [
        str(Path("C:/Users/yangd/.fdt/binaries/python/envs/default/Scripts/python.exe")),
        str(ROOT / "venv" / "Scripts" / "python.exe"),
        sys.executable,
    ]
    for c in candidates:
        if os.path.exists(c):
            pw = _try_pythonw(c)
            if pw:
                return pw
            return c
    pw = _try_pythonw(sys.executable)
    return pw if pw else sys.executable


def start_daemon() -> bool:
    """启动 Master Graph 守护进程"""
    python = find_daemon_python()
    root_cli = str(ROOT / "fdt_cli.py")
    log_file = str(DAEMON_LOG)

    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    _log("正在启动 Master Graph 守护进程...")

    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

    try:
        proc = subprocess.Popen(
            [python, root_cli, "daemon"],
            cwd=str(ROOT),
            creationflags=flags,
            startupinfo=si,
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        _log(f"✅ Master Graph 守护进程已启动 (PID: {proc.pid})")
        return True
    except Exception as e:
        _log(f"❌ 启动失败: {e}")
        return False


def check_daemon() -> tuple[bool, str]:
    """检查守护进程状态"""
    # 检查PID文件
    if PID_FILE.exists():
        pid_str = PID_FILE.read_text().strip()
        if pid_str:
            try:
                pid = int(pid_str)
                if is_process_alive(pid):
                    return True, f"运行中 (PID: {pid})"
            except ValueError:
                pass

    # 检查心跳日志是否在最近3分钟内更新
    heartbeat_file = LOG_DIR / "master_heartbeat.log"
    if heartbeat_file.exists():
        mtime = heartbeat_file.stat().st_mtime
        now = datetime.now().timestamp()
        if now - mtime < 180:
            return True, "心跳正常（3分钟内更新）"
        else:
            return False, f"心跳停滞（最后更新: {datetime.fromtimestamp(mtime).strftime('%H:%M:%S')}）"

    return False, "无心跳日志"


def main() -> None:
    _log("看门狗检查...")

    alive, status = check_daemon()

    if alive:
        _log(f"✅ {status} — 无需操作")
        return 0

    _log(f"⚠️ {status} — 需要重启")
    if start_daemon():
        import time
        time.sleep(2)
        alive2, status2 = check_daemon()
        if alive2:
            _log(f"✅ 恢复成功: {status2}")
            return 0
        else:
            _log(f"❌ 启动后仍不可用: {status2}")
            return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
