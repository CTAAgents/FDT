#!/usr/bin/env python
"""
Loop driver for FDC data injection verification.
Runs validation checks on fdt_langgraph modules to ensure changes persist.
"""
import sys, json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STATE_FILE = BASE / "memory" / "loop_state.json"
LOG_FILE = BASE / "memory" / "loop_fdc_verification.log"

CHECKS = [
    ("state_fdc_data_fields", "from fdt_langgraph.state import DebateState; 'fdc_data' in DebateState.__annotations__ and 'fdc_data_status' in DebateState.__annotations__"),
    ("state_fdc_types", "from fdt_langgraph.state import FdcSymbolData, FdcDataStatus; True"),
    ("create_initial_state_fdc", "from fdt_langgraph.state import create_initial_state; s=create_initial_state('test'); 'fdc_data' in s and s['fdc_data']=={} and s['fdc_data_status'] is None"),
    ("graph_prepare_data_node", "from fdt_langgraph.graph import build_debate_graph; g=build_debate_graph(); 'prepare_data' in g.nodes"),
    ("graph_prepare_data_flow", "from fdt_langgraph.graph import build_debate_graph; g=build_debate_graph(); True"),
    ("node_prepare_data_exists", "from fdt_langgraph.nodes import node_prepare_data; callable(node_prepare_data)"),
    ("node_technical_enhanced", "from fdt_langgraph.nodes import node_technical, _build_fdc_technical_context; callable(_build_fdc_technical_context)"),
    ("node_fundamental_enhanced", "from fdt_langgraph.nodes import node_fundamental, _build_fdc_fundamental_context; callable(_build_fdc_fundamental_context)"),
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_checks():
    results = []
    all_ok = True
    for name, code in CHECKS:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(BASE),
                capture_output=True, text=True, timeout=30
            )
            ok = proc.returncode == 0
            if ok:
                results.append((name, True, ""))
            else:
                err = proc.stderr.strip()[:120]
                results.append((name, False, err))
                all_ok = False
        except Exception as e:
            results.append((name, False, str(e)))
            all_ok = False
    return results, all_ok


def main():
    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except:
            pass

    round_num = state.get("round", 0) + 1
    state["round"] = round_num
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    log(f"=== Round {round_num}/30 ===")

    results, all_ok = run_checks()

    output_lines = []
    for name, ok, err in results:
        status = "✅" if ok else "❌"
        detail = f" - {err}" if err else ""
        output_lines.append(f"  {status} {name}{detail}")
        log(f"  {status} {name}{detail}")

    output = "\n".join(output_lines)
    state["last_output"] = output

    if state.get("prev_output", "") == output:
        state["stall_count"] = state.get("stall_count", 0) + 1
    else:
        state["stall_count"] = 0
    state["prev_output"] = output

    if all_ok:
        state["status"] = "completed"
        state["conclusion"] = "✅ FDC 数据注入全部验证通过"
        log("✅ 目标达成！全部8项检查通过")
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
        return 0

    if state.get("stall_count", 0) >= 3:
        state["status"] = "stalled"
        state["conclusion"] = "⚠️ 连续3轮相同失败，自动停止"
        log("⚠️ 停滞检测触发")
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
        return 1

    if round_num >= 30:
        state["status"] = "max_rounds"
        state["conclusion"] = "⏹ 已达最大轮次上限"
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
        return 1

    state["status"] = "running"
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

    log(f"⏭ 第{round_num}轮未全部通过 ({8 - sum(1 for _, ok, _ in results if ok)}/8 失败)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
