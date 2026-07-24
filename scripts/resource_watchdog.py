#!/usr/bin/env python3
"""
FDT 资源看门狗 v2 — 明鉴秋在每次 spawn Agent 前调用，动态控制并发。

用法:
  python scripts/resource_watchdog.py [--phase phase1|phase2|...] [--active N]

输出 JSON:
  {"safe_concurrent": 5, "risk_level": "green", "cpu_pct": 45.2, "mem_pct": 62.1,
   "disk_pct": 55.0, "py_processes": 8, "reason": "CPU 45%, 内存 62%, 建议并发5",
   "recommendation": "proceed"}

策略:
- CPU < 50% → 满并发；50-80% → 减半；>80% → 只跑1个
- 内存 < 60% → 满并发；60-80% → 七成；>80% → 减半
- 磁盘 > 90% → 警告但仍允许运行
- Python 进程 > 15 → 减半
- 活跃 Agent > 8 → 暂停等待回收

新阶段映射 (2026-07-14 闫判官驱动架构):
  phase0=闫判官初判(1), phase1=链分析(1), phase2=观澜(5), phase3=辩论(6),
  phase4=闫判官终裁(5), phase5=一致性(5), phase6=闫判官(5)(含交易参数), phase7=风控明(5)
"""
from __future__ import annotations

import json
import subprocess

# ─── 新架构阶段映射（闫判官驱动，2026-07-14）─────────────────
PHASE_BASE = {
    "phase0": 1,   # 闫判官初判 — 单次spawn
    "phase1": 1,   # 链证源 — 自动运行（非spawn）
    "phase2": 5,   # 观澜技术分析
    "phase3": 6,   # 证真+慎思辩论
    "phase4": 5,   # 闫判官终裁
    "phase5": 5,   # 一致性裁判
    "phase6": 5,   # 闫判官（含原交易策略参数）
    "phase7": 5,   # 风控明审核
    # 兼容旧名
    "technical": 5,
    "zhengzhen": 6,
    "zhensi": 6,
    "judge": 5,
    "judge_initial": 1,
    "coherence": 5,
    "trading_plan": 5,
    "risk": 5,
}

# ─── 资源阈值 ──────────────────────────────────
THRESHOLDS = {
    "cpu_yellow": 50,    # CPU > 50% → 黄色
    "cpu_red": 80,       # CPU > 80% → 红色
    "mem_yellow": 60,    # 内存 > 60% → 黄色
    "mem_red": 80,       # 内存 > 80% → 红色
    "disk_red": 90,      # 磁盘 > 90% → 红色警告
    "py_procs_warn": 10, # Python进程 > 10 → 注意
    "py_procs_red": 15,  # Python进程 > 15 → 红色
    "active_max": 8,     # 活跃Agent > 8 → 暂停
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


def _run_wmic(cmd: str) -> str:
    """执行 wmic 命令（备选数据源）。"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, shell=True,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _get_cpu_pct() -> float:
    """获取 CPU 使用率（%）。"""
    raw = _run_ps(
        '(Get-Counter "\\Processor(_Total)\\% Processor Time" '
        '-SampleInterval 1 -MaxSamples 1 '
        '| Select-Object -ExpandProperty CounterSamples '
        '| Select-Object -ExpandProperty CookedValue)'
    )
    try:
        return float(raw)
    except (ValueError, TypeError):
        # 备选：wmic
        wmic = _run_wmic('wmic cpu get loadpercentage /value')
        for line in wmic.splitlines():
            if "LoadPercentage" in line:
                return float(line.split("=")[-1].strip())
        return 50.0


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
        wmic = _run_wmic(
            'wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /value'
        )
        total, free = 0.0, 0.0
        for line in wmic.splitlines():
            line = line.strip()
            if line.startswith("TotalVisibleMemorySize"):
                try:
                    total = float(line.split("=", 1)[-1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith("FreePhysicalMemory"):
                try:
                    free = float(line.split("=", 1)[-1].strip())
                except (ValueError, IndexError):
                    pass
        if total > 0:
            return round((1 - free / total) * 100, 1)
        return 60.0


def _get_disk_pct() -> float:
    """获取系统盘（C:）使用率（%）。"""
    raw = _run_ps(
        '(Get-PSDrive C '
        '| Select-Object @{n="Pct";e={[math]::Round(($_.Used/($_.Used+$_.Free))*100,1)}} '
        '| Select-Object -ExpandProperty Pct)'
    )
    try:
        return float(raw)
    except (ValueError, TypeError):
        wmic = _run_wmic('wmic LogicalDisk where "DeviceID=\'C:\'" get Size,FreeSpace /value')
        total, free = 0.0, 0.0
        for line in wmic.splitlines():
            line = line.strip()
            if line.startswith("Size"):
                try:
                    total = float(line.split("=", 1)[-1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith("FreeSpace"):
                try:
                    free = float(line.split("=", 1)[-1].strip())
                except (ValueError, IndexError):
                    pass
        if total > 0:
            return round((1 - free / total) * 100, 1)
        return 50.0


def _get_py_processes() -> int:
    """获取当前 python 进程数（不含本进程）。"""
    raw = _run_ps(
        '(Get-Process -Name python* -ErrorAction SilentlyContinue).Count'
    )
    try:
        return max(0, int(raw) - 1)
    except (ValueError, TypeError):
        return 0


def _assess_risk_level(
    cpu: float, mem: float, disk: float,
    py_procs: int, active_count: int,
) -> tuple[str, str]:
    """综合评估风险等级和操作建议。

    Returns:
        (risk_level, recommendation)
        risk: green / yellow / red
        recommendation: proceed / cautious / stop
    """
    flags = []

    # CPU
    if cpu > THRESHOLDS["cpu_red"]:
        flags.append("CPU超载")
    elif cpu > THRESHOLDS["cpu_yellow"]:
        flags.append("CPU偏高")

    # 内存
    if mem > THRESHOLDS["mem_red"]:
        flags.append("内存不足")
    elif mem > THRESHOLDS["mem_yellow"]:
        flags.append("内存偏高")

    # 磁盘
    if disk > THRESHOLDS["disk_red"]:
        flags.append("磁盘空间紧张")

    # Python进程
    if py_procs > THRESHOLDS["py_procs_red"]:
        flags.append("Python进程过多")
    elif py_procs > THRESHOLDS["py_procs_warn"]:
        flags.append("Python进程偏多")

    # 活跃Agent
    if active_count >= THRESHOLDS["active_max"]:
        flags.append("活跃Agent积压")

    # 定级
    red_flags = [f for f in flags if f in ("CPU超载", "内存不足", "Python进程过多", "活跃Agent积压")]
    if red_flags:
        return "red", "stop"
    if flags:
        return "yellow", "cautious"
    return "green", "proceed"


def compute_safe_concurrent(phase: str = "phase3", active_count: int = 0) -> dict:
    """根据系统资源动态计算安全并发数。

    Args:
        phase: 执行阶段名（决定基础并发上限）
        active_count: 当前活跃（未回收）的 Agent 数量

    Returns:
        {"safe_concurrent": int, "risk_level": str, "recommendation": str,
         "cpu_pct": float, "mem_pct": float, "disk_pct": float,
         "py_processes": int, "active_count": int, "reason": str}
    """
    base = PHASE_BASE.get(phase, 4)

    # ── 读取系统资源 ──
    cpu_pct = _get_cpu_pct()
    mem_pct = _get_mem_pct()
    disk_pct = _get_disk_pct()
    py_procs = _get_py_processes()

    # ── 风险定级 ──
    risk_level, recommendation = _assess_risk_level(
        cpu_pct, mem_pct, disk_pct, py_procs, active_count,
    )

    # ── 活跃 Agent 限制（硬上限）──
    if active_count >= THRESHOLDS["active_max"]:
        return {
            "safe_concurrent": 0,
            "risk_level": "red",
            "recommendation": "stop",
            "cpu_pct": round(cpu_pct, 1),
            "mem_pct": round(mem_pct, 1),
            "disk_pct": round(disk_pct, 1),
            "py_processes": py_procs,
            "active_count": active_count,
            "reason": f"活跃Agent={active_count}≥{THRESHOLDS['active_max']}，先回收再spawn",
        }

    # ── 各维度系数 ──
    # CPU
    if cpu_pct > 80:
        cpu_factor = 1.0 / base  # 只跑1个
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
    reasons.append(f"CPU {cpu_pct:.0f}%{'→系数'+str(cpu_factor) if cpu_factor<1 else ''}")
    reasons.append(f"内存 {mem_pct:.0f}%{'→系数'+str(mem_factor) if mem_factor<1 else ''}")
    reasons.append(f"磁盘 {disk_pct:.0f}%")
    reasons.append(f"py进程{py_procs}{'→系数'+str(proc_factor) if proc_factor<1 else ''}")
    if active_count > 0:
        reasons.append(f"活跃Agent={active_count}")
    reasons.append(f"等级={risk_level} 建议={recommendation}")
    reasons.append(f"基础{base}→建议{safe}")

    return {
        "safe_concurrent": safe,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "cpu_pct": round(cpu_pct, 1),
        "mem_pct": round(mem_pct, 1),
        "disk_pct": round(disk_pct, 1),
        "py_processes": py_procs,
        "active_count": active_count,
        "reason": "，".join(reasons),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FDT 资源看门狗 v2")
    parser.add_argument(
        "--phase", default="phase3",
        choices=list(PHASE_BASE.keys()),
        help="执行阶段（决定基础并发上限）",
    )
    parser.add_argument(
        "--active", type=int, default=0,
        help="当前活跃（未回收）Agent 数",
    )
    args = parser.parse_args()
    result = compute_safe_concurrent(args.phase, args.active)
    print(json.dumps(result, ensure_ascii=False))
