#!/usr/bin/env python3
from __future__ import annotations
"""
明鉴秋 Agent 生命周期管理器 — 用完即走，及时释放硬件资源。

工作流：
  1) spawn 一批 Agent（本脚本不 spawn，由明鉴秋负责）
  2) 每批完成后，调用本脚本 shutdown 这批 Agent
  3) 本脚本监控产出文件就绪 → 发送 shutdown_request → 等待回收确认
  4) 释放资源后，明鉴秋 spawn 下一批

用法:
  # 注册一批 Agent（spawn 后调用）
  python scripts/agent_lifecycle.py register --phase phase2 --agents agent1,agent2,agent3
                                              --files p3_technical_pb.json,p3_technical_sc.json

  # 等待产出就绪 + 自动 shutdown（轮询 + 超时）
  python scripts/agent_lifecycle.py wait-and-shutdown --phase phase2 --timeout 900

  # 强制 shutdown 指定 Agent
  python scripts/agent_lifecycle.py shutdown --agents agent1,agent2

  # 查看当前活跃 Agent
  python scripts/agent_lifecycle.py active

  # 生成生命周期报告（供明鉴秋规划下一批）
  python scripts/agent_lifecycle.py report --workspace <dir>
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_STATE_DIR = Path.home() / ".fdt" / "tmp" / "agent_lifecycle"
_STATE_FILE = _STATE_DIR / "active_agents.json"


def _ensure_state() -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.exists():
        _save_state({"phases": {}, "completed": [], "active_count": 0})


def _load_state() -> dict:
    _ensure_state()
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        state = {"phases": {}, "completed": [], "active_count": 0}
        _save_state(state)
        return state


def _save_state(state: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _poll_file_ready(file_path: str, timeout: int = 900, stable_seconds: int = 5) -> bool:
    """S04: 轮询文件就绪——文件存在且 size≥5 秒不变。"""
    deadline = time.time() + timeout
    last_size = -1
    stable_since = None
    path = Path(file_path)
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            sz = path.stat().st_size
            if sz == last_size:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= stable_seconds:
                    return True
            else:
                last_size = sz
                stable_since = None
        time.sleep(10)
    return False


# ═══════════════════════════════════════════════
# 子命令
# ═══════════════════════════════════════════════

def cmd_register(phase: str, agents: list[str], files: list[str]) -> None:
    """注册一批 Agent：记录其名称和期望产出的文件路径。

    明鉴秋 spawn 完 Agent 后调用，后续 wait-and-shutdown 会监控这些文件。
    """
    state = _load_state()
    entry = {
        "phase": phase,
        "agents": agents,
        "files": files,
        "registered_at": datetime.now().isoformat(),
        "status": "running",  # running / completing / done / shutdown
    }
    phase_entries = state["phases"].get(phase, [])
    phase_entries.append(entry)
    state["phases"][phase] = phase_entries
    state["active_count"] = sum(
        1 for p in state["phases"].values()
        for e in p if e["status"] in ("running", "completing")
    )
    _save_state(state)
    print(f"✅ 注册 {phase}: {len(agents)} Agent, {len(files)} 产出文件")
    print(f"   活跃 Agent 总计: {state['active_count']}")
    return 0


def cmd_wait_and_shutdown(phase: str, timeout: int = 900) -> int:
    """等待指定阶段的所有 Agent 产出就绪，然后自动 shutdown。

    返回 shutdown 的 Agent 数。-1 表示超时。
    """
    state = _load_state()
    entries = state["phases"].get(phase, [])
    if not entries:
        print(f"  ⚠️ 阶段 {phase} 无已注册 Agent")
        return 0

    all_agents = []
    all_files = []
    for entry in entries:
        all_agents.extend(entry["agents"])
        all_files.extend(entry["files"])
        entry["status"] = "completing"
    _save_state(state)

    print(f"⏳ 等待阶段 {phase} 产出就绪: {len(all_agents)} Agent, {len(all_files)} 文件")
    start = time.time()

    # 轮询所有产出文件
    ready_count = 0
    for f in all_files:
        print(f"  等待 {Path(f).name}...", end="")
        ok = _poll_file_ready(f, timeout=timeout)
        if ok:
            ready_count += 1
            print(" ✅")
        else:
            print(" ⏰ 超时")

    elapsed = time.time() - start
    print(f"  文件就绪: {ready_count}/{len(all_files)} ({elapsed:.0f}s)")

    # ── 发送 shutdown_request ──
    # 注意：本脚本不直接发送 shutdown（那是主管 Agent 聊天层的功能）。
    # 本脚本输出 shutdown 指令清单，由明鉴秋（主管 Agent）执行。
    shutdown_plan = [
        {
            "agent": agent,
            "type": "shutdown_request",
            "reason": f"Phase {phase} 完成，释放资源",
        }
        for agent in all_agents
    ]
    shutdown_plan_path = _STATE_DIR / f"shutdown_plan_{phase}_{datetime.now().strftime('%H%M%S')}.json"
    with open(shutdown_plan_path, "w") as f:
        json.dump(shutdown_plan, f, ensure_ascii=False, indent=2)

    # 标记为 done
    for entry in entries:
        entry["status"] = "shutdown"
    state["active_count"] = sum(
        1 for p in state["phases"].values()
        for e in p if e["status"] in ("running", "completing")
    )
    state["completed"].extend(all_agents)
    _save_state(state)

    print(f"📋 shutdown 计划: {shutdown_plan_path}")
    print(f"   共 {len(shutdown_plan)} 个 Agent 待 shutdown")
    print(f"   明鉴秋请执行: SendMessage(type='shutdown_request', recipient='<agent>')")
    print(f"   活跃 Agent 剩余: {state['active_count']}")
    return 0


def cmd_shutdown(agents: list[str]) -> None:
    """生成指定 Agent 的 shutdown 指令清单。"""
    shutdown_plan = [
        {
            "agent": agent,
            "type": "shutdown_request",
            "reason": "明鉴秋主动清理，释放资源",
        }
        for agent in agents
    ]
    print(json.dumps(shutdown_plan, ensure_ascii=False, indent=2))
    print(f"📋 明鉴秋请执行: SendMessage(type='shutdown_request', recipient='<agent>')", file=sys.stderr)
    # 更新状态
    state = _load_state()
    for phase, entries in state["phases"].items():
        for entry in entries:
            entry["agents"] = [a for a in entry["agents"] if a not in agents]
            if not entry["agents"]:
                entry["status"] = "shutdown"
    state["active_count"] = sum(
        1 for p in state["phases"].values()
        for e in p if e["status"] in ("running", "completing")
    )
    _save_state(state)
    print(f"   活跃 Agent 剩余: {state['active_count']}", file=sys.stderr)


def cmd_active() -> None:
    """查看当前活跃 Agent 列表。"""
    state = _load_state()
    active = []
    for phase, entries in state["phases"].items():
        for entry in entries:
            if entry["status"] in ("running", "completing"):
                for agent in entry["agents"]:
                    active.append({
                        "agent": agent,
                        "phase": phase,
                        "status": entry["status"],
                    })
    print(json.dumps({
        "active_count": state["active_count"],
        "active_agents": active,
    }, ensure_ascii=False, indent=2))
    if active:
        print(f"\n📊 活跃 Agent: {len(active)} 个", file=sys.stderr)
        for a in active:
            print(f"  {a['agent']:20s} | phase={a['phase']:8s} | {a['status']}", file=sys.stderr)
    else:
        print("✅ 无活跃 Agent", file=sys.stderr)


def cmd_report(workspace: str) -> None:
    """生成生命周期报告（供明鉴秋规划资源使用）。"""
    state = _load_state()
    ws = Path(workspace)
    report_path = ws / "agent_lifecycle_report.json"

    report = {
        "generated_at": datetime.now().isoformat(),
        "active_count": state["active_count"],
        "completed_count": len(state["completed"]),
        "phases": {},
        "shutdown_ready": [],
    }
    for phase, entries in state["phases"].items():
        running = sum(1 for e in entries if e["status"] == "running")
        completing = sum(1 for e in entries if e["status"] == "completing")
        done = sum(1 for e in entries if e["status"] == "shutdown")
        agents = [a for e in entries for a in e["agents"]]
        report["phases"][phase] = {
            "total": len(entries),
            "running": running,
            "completing": completing,
            "shutdown": done,
            "agents": agents,
        }
        if running + completing > 0:
            report["shutdown_ready"].append(phase)

    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"📊 Agent 生命周期报告: {report_path}")
    print(f"   活跃: {state['active_count']} | 已完成: {len(state['completed'])}")
    for phase, info in report["phases"].items():
        print(f"   {phase:8s}: {info['shutdown']}/{info['total']} shutdown"
              f" ({info['running']} running, {info['completing']} completing)")
    if report["shutdown_ready"]:
        print(f"   待 shutdown 阶段: {', '.join(report['shutdown_ready'])}")
    return 0


def cmd_cleanup() -> None:
    """清理所有状态（谨慎使用）。"""
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()
    print("🗑️ 已清理 Agent 生命周期状态")
    print("   下次 start 时会重新初始化")


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="明鉴秋 Agent 生命周期管理器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # register
    p_reg = sub.add_parser("register", help="注册一批 Agent（spawn 后调用）")
    p_reg.add_argument("--phase", required=True,
                       help="执行阶段名（phase0-7）")
    p_reg.add_argument("--agents", required=True,
                       help="Agent 名称列表（逗号分隔）")
    p_reg.add_argument("--files", required=True,
                       help="期望产出的文件路径列表（逗号分隔）")

    # wait-and-shutdown
    p_ws = sub.add_parser("wait-and-shutdown", help="等待产出就绪 + 自动 shutdown")
    p_ws.add_argument("--phase", required=True)
    p_ws.add_argument("--timeout", type=int, default=900,
                      help="单个文件轮询超时（秒，默认 900=15min）")
    p_ws.add_argument("--skip-wait", action="store_true",
                      help="跳过等待，直接生成 shutdown 计划")

    # shutdown
    p_sd = sub.add_parser("shutdown", help="生成指定 Agent 的 shutdown 指令")
    p_sd.add_argument("--agents", required=True,
                      help="Agent 名称列表（逗号分隔）")

    # active
    sub.add_parser("active", help="查看当前活跃 Agent")

    # report
    p_rep = sub.add_parser("report", help="生成生命周期报告")
    p_rep.add_argument("--workspace", default=".",
                       help="工作空间目录")

    # cleanup
    sub.add_parser("cleanup", help="清理所有状态")

    args = ap.parse_args()

    if args.cmd == "register":
        agents = [a.strip() for a in args.agents.split(",")]
        files = [f.strip() for f in args.files.split(",")]
        return cmd_register(args.phase, agents, files)

    elif args.cmd == "wait-and-shutdown":
        return cmd_wait_and_shutdown(args.phase, args.timeout)

    elif args.cmd == "shutdown":
        agents = [a.strip() for a in args.agents.split(",")]
        return cmd_shutdown(agents)

    elif args.cmd == "active":
        return cmd_active()

    elif args.cmd == "report":
        return cmd_report(args.workspace)

    elif args.cmd == "cleanup":
        return cmd_cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
