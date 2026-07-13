#!/usr/bin/env python3
"""
FDT 资源看门狗 — 根据系统资源动态计算安全并发数。
在每次 spawn Agent 前调用，返回建议的并发上限。

用法：
  python scripts/resource_watchdog.py [--phase phase1|phase2|...] [--active N]

输出 JSON：
  {"safe_concurrent": 5, "cpu_pct": 45.2, "mem_pct": 62.1,
   "py_processes": 8, "reason": "CPU 45%, 内存 62%, 建议并发5"}

策略：
- CPU < 50% → 满并发；50-80% → 减半；>80% → 只跑1个
- 内存 < 60% → 满并发；60-80% → 七成；>80% → 减半
- Python 进程 > 15 → 减半
- 活跃 Agent > 8 → 等回收
"""

import json
import os
import subprocess
import sys
from pathlib import Path


# ─── 各阶段基础并发（资源充裕时的上限，非固定值）────────────────
PHASE_BASE = {
    "phase1": 6,   # 观澜
    "phase2": 8,   # 证真+慎思
    "phase3": 6,   # 闫判官
    "phase4": 6,   # 一致性裁判
    "phase5": 6,   # 策执远
    "phase6": 6,   # 风控明
}


def _run_ps(cmd: str) -> str:
    """执行 PowerShell 命令并返回 stdout（10 秒超时）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _get_cpu_pct() -> float:
    """获取 CPU 使用率（%）。"""
    raw = _run_ps(
        '(Get-Counter "\\Processor(_Total)\\% Processor Time" -SampleInterval 1 -MaxSamples 1 '
        '| Select-Object -ExpandProperty CounterSamples '
        '| Select-Object -ExpandProperty CookedValue)'
    )
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 50.0  # 拿不到就保守估计


def _get_mem_pct() -> float:
    """获取内存使用率（%）。"""
    raw = _run_ps(
        '(Get-Counter "\\Memory\\% Committed Bytes In Use" '
        '| Select-Object -ExpandProperty CounterSamples '
        '| Select-Object -ExpandProperty CookedValue)'
    )
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 60.0


def _get_py_processes() -> int:
    """获取当前 python 进程数（不含本进程）。"""
    raw = _run_ps(
        '(Get-Process -Name python* -ErrorAction SilentlyContinue).Count'
    )
    try:
        # 减去本进程
        return max(0, int(raw) - 1)
    except (ValueError, TypeError):
        return 0


def compute_safe_concurrent(phase: str = "phase2", active_count: int = 0) -> dict:
    """根据系统资源动态计算安全并发数。

    Args:
        phase: 执行阶段名（决定基础并发上限）
        active_count: 当前活跃（未回收）的 Agent 数量

    Returns:
        {"safe_concurrent": int, "cpu_pct": float, "mem_pct": float,
         "py_processes": int, "reason": str}
    """
    base = PHASE_BASE.get(phase, 6)

    # ── 读取系统资源 ──
    cpu_pct = _get_cpu_pct()
    mem_pct = _get_mem_pct()
    py_procs = _get_py_processes()

    # ── 活跃 Agent 限制 ──
    if active_count >= 8:
        return {
            "safe_concurrent": 0,
            "cpu_pct": round(cpu_pct, 1),
            "mem_pct": round(mem_pct, 1),
            "py_processes": py_procs,
            "reason": f"活跃Agent={active_count}≥8，先回收再spawn",
        }

    # ── 各维度系数 ──
    # CPU
    if cpu_pct > 80:
        cpu_factor = 1 / base  # 只跑1个
    elif cpu_pct > 50:
        cpu_factor = 0.5
    else:
        cpu_factor = 1.0

    # 内存
    if mem_pct > 80:
        mem_factor = 0.5
    elif mem_pct > 60:
        mem_factor = 0.7
    else:
        mem_factor = 1.0

    # Python 进程
    if py_procs > 15:
        proc_factor = 0.5
    elif py_procs > 10:
        proc_factor = 0.75
    else:
        proc_factor = 1.0

    # ── 综合 ──
    raw = base * min(cpu_factor, mem_factor, proc_factor)
    safe = max(1, min(base, round(raw)))
    reasons = []
    reasons.append(f"CPU {cpu_pct:.0f}%{'→系数' + str(cpu_factor) if cpu_factor<1 else ''}")
    reasons.append(f"内存 {mem_pct:.0f}%{'→系数' + str(mem_factor) if mem_factor<1 else ''}")
    reasons.append(f"py进程{py_procs}{'→系数' + str(proc_factor) if proc_factor<1 else ''}")
    if active_count > 0:
        reasons.append(f"活跃Agent={active_count}")
    reasons.append(f"基础{base}→建议{safe}")

    return {
        "safe_concurrent": safe,
        "cpu_pct": round(cpu_pct, 1),
        "mem_pct": round(mem_pct, 1),
        "py_processes": py_procs,
        "active_count": active_count,
        "reason": "，".join(reasons),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FDT 资源看门狗")
    parser.add_argument("--phase", default="phase2", choices=list(PHASE_BASE.keys()))
    parser.add_argument("--active", type=int, default=0, help="当前活跃 Agent 数")
    args = parser.parse_args()
    result = compute_safe_concurrent(args.phase, args.active)
    print(json.dumps(result, ensure_ascii=False))
