"""FDT 独立定时调度器 [INDEPENDENT]。

不依赖 WorkBuddy automation，FDT 自己管理定时任务。
支持 cron 风格的调度规则。

用法:
    python scripts/scheduler.py --job daily_debate          # 前台运行
    python scripts/scheduler.py --job daily_debate --daemon # 后台守护
    python scripts/scheduler.py --status                     # 查看状态
    python scripts/scheduler.py --stop                       # 停止守护
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / "scheduler" / "scheduler.pid"
LOG_DIR = ROOT / "memory" / "logs"
LOG_FILE = LOG_DIR / "scheduler.log"
SCHEDULER_DIR = ROOT / "scheduler"

# ── 简单的 cron 匹配（dow, hour, min） ──

WEEKDAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6,
}


def _parse_dow(spec: str) -> set[int]:
    """解析星期几表达式: mon-fri, 1,5 等"""
    spec = spec.lower().strip()
    result = set()

    # mon-fri 范围
    if "-" in spec:
        parts = spec.split("-")
        if len(parts) == 2:
            start = WEEKDAY_MAP.get(parts[0])
            end = WEEKDAY_MAP.get(parts[1])
            if start is not None and end is not None:
                for d in range(start, end + 1):
                    result.add(d)
                return result

    # 逗号分隔
    for part in spec.split(","):
        part = part.strip()
        if part in WEEKDAY_MAP:
            result.add(WEEKDAY_MAP[part])
        elif part.isdigit():
            result.add(int(part) % 7)

    return result


def _match_cron(dow_spec: str, hour: int, minute: int) -> bool:
    """检查当前时间是否匹配 cron 规则。dow_spec 格式: 'mon-fri'"""
    now = datetime.now()
    if now.hour != hour or now.minute != minute:
        return False
    dows = _parse_dow(dow_spec)
    return now.weekday() in dows


# ── 作业定义 ──

FDT_CLI = sys.executable + " " + str(ROOT / "scripts" / "fdt_cli.py")


def _job_daily_debate() -> None:
    """每日全量扫描+辩论"""
    today = date.today().strftime("%Y%m%d")
    ws = str(ROOT / "data" / f"scan_{today}")
    cmd = f"{FDT_CLI} pipeline --mode no-filter --workspace {ws}"
    _log(f"[daily_debate] 启动: {cmd}")
    rc = os.system(cmd)
    _log(f"[daily_debate] 完成 (exit={rc})")

    # 推送通知
    notifier = str(ROOT / "scripts" / "notifier.py")
    push_cmd = f"{sys.executable} {notifier} --workspace {ws} --channel wecom_bot 2>&1"
    _log(f"[notify] 推送中...")
    push_out = os.popen(push_cmd).read().strip()
    for line in push_out.split("\n"):
        _log(f"[notify] {line}")


JOBS = {
    "daily_debate": {
        "description": "交易日 20:15 全量扫描+辩论",
        "cron": {"dow": "mon-fri", "hour": 20, "minute": 15},
        "fn": _job_daily_debate,
    },
}


def _log(msg: str) -> None:
    """写日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 守护进程管理 ──


def _write_pid(pid: int) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), encoding="utf-8")


def _read_pid() -> int | None:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None
    return None


def _is_running(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False  # 保守返回
    # Unix
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_daemon_start(job_name: str) -> None:
    """后台启动调度器"""
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"⚠️  调度器已在运行 (PID={pid})")
        return 1

    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    pid = os.fork() if hasattr(os, "fork") else 0
    if pid == 0:
        # 子进程
        _write_pid(os.getpid())
        _run_scheduler(job_name)
    elif pid > 0:
        # Unix fork: 父进程
        _write_pid(pid)
        print(f"✅ 调度器已启动 (PID={pid})")
    else:
        # Windows: 没有 fork，用线程模拟
        t = threading.Thread(target=_run_scheduler, args=(job_name,), daemon=True)
        t.start()
        _write_pid(os.getpid())
        print(f"✅ 调度器已启动 (PID={os.getpid()})")
    return 0


def cmd_daemon_stop() -> None:
    """停止调度器"""
    pid = _read_pid()
    if not pid:
        print("ℹ️  调度器未运行")
        return 0
    if not _is_running(pid):
        print("ℹ️  调度器已停止（残留 PID 文件）")
        PID_FILE.unlink(missing_ok=True)
        return 0

    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.TerminateProcess(kernel32.OpenProcess(1, False, pid), 0)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"✅ 调度器已停止 (PID={pid})")
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        print(f"❌ 停止失败: {e}")
        return 1
    return 0


def cmd_daemon_status() -> None:
    """查看状态"""
    pid = _read_pid()
    if not pid:
        print("ℹ️  调度器未运行")
        return 0

    running = _is_running(pid)
    if running:
        print(f"✅ 调度器运行中 (PID={pid})")
    else:
        print(f"❌ PID 文件存在但进程不活动 (PID={pid})")
        PID_FILE.unlink(missing_ok=True)

    # 显示最近日志
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
        print(f"\n最近日志 ({len(lines)} 行):")
        for line in lines[-5:]:
            print(f"  {line}")
    return 0


# ── 调度循环 ──


def _run_scheduler(job_name: str) -> None:
    """调度主循环"""
    job = JOBS.get(job_name)
    if not job:
        _log(f"未知作业: {job_name}")
        return

    cron = job["cron"]
    fn = job["fn"]
    _log(f"调度器启动: {job['description']}")
    _log(f"  规则: {cron['dow']} {cron['hour']}:{cron['minute']:02d}")
    _log(f"  PID: {os.getpid()}")

    last_run_date = None

    try:
        while True:
            now = datetime.now()
            # 每分钟检查一次
            if (_match_cron(cron["dow"], cron["hour"], cron["minute"])
                    and last_run_date != now.date()):
                _log("触发作业...")
                fn()
                last_run_date = now.date()
                _log(f"作业完成，下次等待 {cron['hour']}:{cron['minute']:02d}")
            time.sleep(30)  # 每 30 秒检查一次
    except KeyboardInterrupt:
        _log("调度器手动停止")
    except Exception as e:
        _log(f"调度器异常: {e}")
        raise


# ── CLI ──


def main() -> int:
    ap = argparse.ArgumentParser(description="FDT 独立定时调度器")
    ap.add_argument("--job", choices=list(JOBS.keys()), default=None,
                    help="要运行的作业")
    ap.add_argument("--daemon", action="store_true",
                    help="后台守护模式")
    ap.add_argument("--status", action="store_true",
                    help="查看调度器状态")
    ap.add_argument("--stop", action="store_true",
                    help="停止调度器")
    args = ap.parse_args()

    if args.status:
        return cmd_daemon_status()
    if args.stop:
        return cmd_daemon_stop()
    if args.job:
        if args.daemon:
            return cmd_daemon_start(args.job)
        _run_scheduler(args.job)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
