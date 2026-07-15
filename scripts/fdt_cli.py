"""FDT 统一 CLI 入口 [INDEPENDENT] v2.1 — 模式开关层 + 资源感知并发。

伪信号过滤开关 + 辩论流程开关 → 8种执行模式。
明鉴秋在 spawn 前自动检测硬件资源（CPU/内存/磁盘/Python进程），动态调整并发数。

两种调用方式:
  1) 高级模式: python scripts/fdt_cli.py pipeline --mode <MODE> [options]
  2) 低级命令: python scripts/fdt_cli.py scan|debate|finalize|report|health ...

用法:
  # 模式一: 全流程（信号计算→伪信号过滤→辩论）
  python scripts/fdt_cli.py pipeline --mode full --workspace <dir>
                                    [--scan-prefix <px>] [--no-cache]

  # 模式二: 不过滤（信号计算→辩论，跳过伪信号过滤）
  python scripts/fdt_cli.py pipeline --mode no-filter --workspace <dir>

  # 模式三: 仅信号计算（不过滤不辩论）
  python scripts/fdt_cli.py pipeline --mode scan-only --workspace <dir>

  # 模式四: 信号计算+过滤（不辩论）
  python scripts/fdt_cli.py pipeline --mode scan-filter --workspace <dir>

  # 模式五: 指定品种辩论（跳过扫描）
  python scripts/fdt_cli.py pipeline --mode debate --workspace <dir> --symbols <A,B,C>

  # 模式六: 指定产业链辩论
  python scripts/fdt_cli.py pipeline --mode debate-group --workspace <dir> --chain <NAME>

  # 模式七: 强制全品种辩论
  python scripts/fdt_cli.py pipeline --mode debate-all --workspace <dir>

  # 明鉴秋资源检查（spawn 前调用）
  python scripts/fdt_cli.py pre-spawn-check --phase phase3 --base 5 --active 2

  # 快速查看系统资源
  python scripts/fdt_cli.py resource [--json]

  # 自检（Pre-flight + 故障追溯）
  python scripts/fdt_cli.py self-check [--workspace <dir>] [--scan <json>]

  # 低级命令（与原有用法兼容）
  python scripts/fdt_cli.py scan --output-dir <dir>
  python scripts/fdt_cli.py debate plan --scan <json> --workspace <ws>
  python scripts/fdt_cli.py debate finalize --scan <json> --workspace <ws>
  python scripts/fdt_cli.py report --workspace <ws>
  python scripts/fdt_cli.py health [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_QUANT = _ROOT / "skills" / "quant-daily" / "scripts"

_SCAN_PY = _QUANT / "scan_all.py"
_RUN_DEBATE_PY = _SCRIPTS / "run_debate.py"


def _run(cmd: list[str], **kwargs) -> int:
    print(f"▶ {' '.join(str(c) for c in cmd)}")
    return subprocess.call(cmd, **kwargs)


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _now_hhmm() -> str:
    return datetime.now().strftime("%H%M")


def _normalize_path(p: str) -> str:
    """归一化路径：将 Git Bash 的 /d/xx 转为 Windows D:/xx，避免 os.path/glob 不认。"""
    m = re.match(r"^/([a-zA-Z])/(.*)", p.strip())
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return p


def _resolve_workspace(ws: str | None) -> str:
    """解析工作空间路径，未指定则使用默认路径+日期子目录。"""
    if ws:
        return _normalize_path(ws)
    default = _ROOT / "data" / f"scan_{_today_str()}"
    return str(default)


def cmd_pipeline(args: argparse.Namespace) -> int:
    """高级模式入口：根据 --mode 执行对应流程。"""
    mode = args.mode
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    scan_prefix = getattr(args, "scan_prefix", f"scan_pipe_{_now_hhmm()}")
    no_cache = getattr(args, "no_cache", False)
    check_resources = getattr(args, "check_resources", False)
    py = sys.executable

    # ── 启动时检测系统资源 ──
    try:
        rc = subprocess.run(
            [py, str(_SCRIPTS / "resource_watchdog.py"),
             "--phase", "phase0", "--active", "0"],
            capture_output=True, text=True, timeout=15,
        )
        if rc.returncode == 0:
            rdata = json.loads(rc.stdout)
            risk = rdata.get("risk_level", "?")
            cpu = rdata.get("cpu_pct", "?")
            mem = rdata.get("mem_pct", "?")
            safe = rdata.get("safe_concurrent", "?")
            print(f"🔍 系统资源: CPU={cpu}% 内存={mem}% "
                  f"risk={risk} 建议并发={safe}")
            if risk == "red":
                print("⛔ 系统资源红色警戒，建议降低负载后重试")
                if not getattr(args, "force", False):
                    return 1
    except Exception as e:
        print(f"  ⚠️ 资源检测不可用: {e}")

    # 确保工作空间目录存在
    Path(workspace).mkdir(parents=True, exist_ok=True)

    # ── 模式5-7: 直接辩论（跳过扫描）──
    if mode in ("debate", "debate-group", "debate-all"):
        deb_cmd = [py, str(_RUN_DEBATE_PY), "debate",
                   "--workspace", workspace]
        if no_cache:
            deb_cmd.append("--no-cache")
        if check_resources:
            deb_cmd.append("--check-resources")
        if mode == "debate":
            symbols = getattr(args, "symbols", None)
            if not symbols:
                print("⛔ --mode debate 需要 --symbols 参数")
                return 1
            deb_cmd += ["--symbols", symbols]
        elif mode == "debate-group":
            chain = getattr(args, "chain", None)
            if not chain:
                print("⛔ --mode debate-group 需要 --chain 参数")
                return 1
            deb_cmd += ["--chain", chain]
        else:  # debate-all
            deb_cmd.append("--all")
        return _run(deb_cmd)

    # ── 模式1-4: 需要先运行扫描 ──
    # 构建 scan 参数
    scan_cmd = [py, str(_SCAN_PY),
                "--output", workspace,
                "--prefix", scan_prefix]

    # 多策略管线 vs 单策略
    use_pipeline = getattr(args, "pipeline", False)
    if use_pipeline:
        scan_cmd.append("--pipeline")
    else:
        scan_cmd += ["--strategy", "channel_breakout"]

    # 模式1(full) = 过滤开，模式2(no-filter) = 过滤关 → 在 scan 阶段控制
    # 模式3(scan-only) = 扫描后结束，模式4(scan-filter) = 扫描+过滤后结束
    if mode in ("no-filter", "scan-only"):
        scan_cmd.append("--disable-filter")
    if getattr(args, "symbols", None):
        scan_cmd += ["--symbols", args.symbols]
    if getattr(args, "strategies", None):
        scan_cmd += ["--strategies", args.strategies]

    # 执行扫描
    rc = _run(scan_cmd)
    if rc != 0:
        print(f"⛔ 扫描失败 (exit={rc})")
        return rc

    # 模式3(scan-only): 扫描后即结束
    if mode == "scan-only":
        print("✅ scan-only 模式完成（伪信号过滤已禁用，未进入辩论）")
        return 0

    # 模式4(scan-filter): 扫描+过滤后结束
    if mode == "scan-filter":
        print("✅ scan-filter 模式完成（已过滤，未进入辩论）")
        return 0

    # ── 模式1-2: 进入辩论阶段前自动自检 ──
    skip_check = getattr(args, "skip_self_check", False)
    if not skip_check:
        print(f"\n🔍 自动自检...")
        sc_py = str(_SCRIPTS / "self_check.py")
        sc_rc = subprocess.run(
            [py, sc_py, "--workspace", workspace],
            capture_output=True, text=True, timeout=30,
        )
        sc_out = sc_rc.stdout.strip() or sc_rc.stderr.strip()
        if sc_out:
            print(sc_out)
        if sc_rc.returncode == 2:
            print("⛔ 自检发现致命错误，终止流程")
            return 2

    # ── 找到扫描生成的 JSON 文件
    import glob
    today = _today_str()
    json_candidates = []
    # 兼容两种命名模式:
    #   {prefix}_{middle}_{date}.json  → scan_pipe_0354_20260716.json
    #   {prefix}_{date}.json           → scan_daily_20260716.json
    for ptn in [f"{scan_prefix}_*_{today}.json",
                f"{scan_prefix}_{today}.json"]:
        p = str(Path(workspace) / ptn)
        json_candidates.extend(glob.glob(p))
    if not json_candidates:
        print(f"⛔ 在 {workspace} 中未找到扫描 JSON")
        print(f"   尝试模式: {scan_prefix}_*_{today}.json / {scan_prefix}_{today}.json")
        return 1
    json_candidates.sort(key=os.path.getmtime, reverse=True)
    scan_json = json_candidates[0]
    print(f"  使用扫描文件: {scan_json}")

    # plan → spawnAgent → finalize
    plan_cmd = [py, str(_RUN_DEBATE_PY), "plan",
                "--scan", scan_json,
                "--workspace", workspace]
    if no_cache:
        plan_cmd.append("--no-cache")
    if check_resources:
        plan_cmd.append("--check-resources")
    if mode == "no-filter":
        plan_cmd.append("--disable-filter")
    rc = _run(plan_cmd)
    if rc != 0:
        print(f"⛔ 辩论计划生成失败 (exit={rc})")
        return rc

    # 提示用户 spawn Agent
    print(f"\n{'='*60}")
    print(f"⚡ 请根据 spawn_plan_*.json 手动 spawn 辩论 Agent")
    print(f"   (在 WorkBuddy 中依 spawn_prompts 逐个 spawn 证真/慎思/闫判官等)")
    print(f"   跑完所有 Agent 后，再执行:")
    print(f"   python scripts/fdt_cli.py pipeline --mode finalize-only "
          f"--workspace {workspace}")
    print(f"{'='*60}")
    return 0


def cmd_finalize_only(args: argparse.Namespace) -> int:
    """仅执行最终化和报告生成（不 spawn Agent）。"""
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    py = sys.executable

    # 找最新的 scan JSON（按 mtime 排序，取最新）
    import glob
    today = _today_str()
    json_pattern = str(Path(workspace) / f"scan_*_{today}.json")
    json_files = sorted(glob.glob(json_pattern), key=os.path.getmtime)
    if not json_files:
        # 再试一次：列出目录下所有 json 供诊断
        all_json = glob.glob(str(Path(workspace) / "*.json"))
        print(f"⛔ 未找到匹配 scan_*_{today}.json 在: {workspace}")
        if all_json:
            print(f"  目录下 JSON 文件 ({len(all_json)}): {', '.join(os.path.basename(p) for p in sorted(all_json)[:15])}")
            if len(all_json) > 15:
                print(f"  ... 还有 {len(all_json) - 15} 个")
        return 1
    scan_json = json_files[-1]

    # 从 scan JSON 的 _meta 判断是否禁用过滤
    _disable_filter = False
    try:
        with open(scan_json, encoding="utf-8") as _sf:
            _sd = json.load(_sf)
        _meta = _sd.get("_meta", {})
        _disable_filter = _meta.get("filter_disabled", False)
    except Exception:
        pass
    fin_cmd = [py, str(_RUN_DEBATE_PY), "finalize",
               "--scan", scan_json, "--workspace", workspace]
    if _disable_filter:
        fin_cmd.append("--disable-filter")
    rc = _run(fin_cmd)
    if rc != 0:
        print(f"⛔ finalize 失败 (exit={rc})")
    return rc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="FDT 统一入口 v2.0 — 模式开关层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ── pipeline 高级模式 ──
    p_pipe = sub.add_parser("pipeline", help="高级模式：开关驱动的全/半自动流程")
    p_pipe.add_argument("--mode", required=True,
                        choices=["full", "no-filter", "scan-only", "scan-filter",
                                 "debate", "debate-group", "debate-all",
                                 "finalize-only"],
                        help="""执行模式:
    full          信号计算→伪信号过滤→辩论 (全流程)
    no-filter     信号计算→辩论 (跳过伪信号过滤)
    scan-only     仅信号计算 (不过滤不辩论)
    scan-filter   信号计算→伪信号过滤 (不辩论)
    debate        指定品种辩论 (跳过扫描，需 --symbols)
    debate-group  指定产业链辩论 (跳过扫描，需 --chain)
    debate-all    强制全品种辩论 (跳过扫描)
    finalize-only 仅 finalize (spawn 完 Agent 后收口)
""")
    p_pipe.add_argument("--workspace", default=None,
                        help="工作空间目录，缺省=FDT根/data/scan_YYYYMMDD")
    p_pipe.add_argument("--scan-prefix", default=None,
                        help="扫描文件前缀，缺省=scan_pipe_HHMM")
    p_pipe.add_argument("--symbols", default=None,
                        help="指定品种（逗号分隔），用于 --mode debate / full / no-filter")
    p_pipe.add_argument("--chain", default=None,
                        help="指定产业链名称，用于 --mode debate-group")
    p_pipe.add_argument("--no-cache", action="store_true",
                        help="忽略辩论缓存，强制重新辩论")
    p_pipe.add_argument("--check-resources", action="store_true",
                        help="资源感知动态并发")
    p_pipe.add_argument("--pipeline", action="store_true",
                        help="启用多策略管线（6策略并行）代替单策略通道突破")
    p_pipe.add_argument("--strategies", default=None,
                        help='管线策略子集（逗号分隔），如 "trend_following,arbitrage"。不传=全部6策略')
    p_pipe.add_argument("--skip-self-check", action="store_true",
                        help="跳过辩论前的自动自检")

    # ── 低级命令保持兼容 ──
    p_scan = sub.add_parser("scan", help="运行信号扫描 (pass-through)")
    p_scan.add_argument("--output-dir", required=True)
    p_scan.add_argument("--symbols", default=None)
    p_scan.add_argument("--strategy", default=None)
    p_scan.add_argument("--disable-filter", action="store_true",
                        help="禁用P0-4伪信号过滤")

    p_deb = sub.add_parser("debate", help="辩论驱动层 (pass-through)")
    deb_sub = p_deb.add_subparsers(dest="deb_action", required=True)
    for name, args_list in [
        ("plan", [
            ("--scan", {"required": True}),
            ("--workspace", {"required": True}),
            ("--no-cache", {"action": "store_true"}),
            ("--check-resources", {"action": "store_true"}),
            ("--mode", {"choices": ["trigger", "all", "symbols"], "default": "trigger"}),
            ("--symbols", {"default": None}),
        ]),
        ("finalize", [
            ("--scan", {"required": True}),
            ("--workspace", {"required": True}),
        ]),
    ]:
        p = deb_sub.add_parser(name)
        for arg, kwargs in args_list:
            p.add_argument(arg, **kwargs)

    p_rep = sub.add_parser("report", help="生成辩论报告")
    p_rep.add_argument("--workspace", required=True)

    p_h = sub.add_parser("health", help="健康钩子")
    p_h.add_argument("--date", default=None)

    # ── 明鉴秋资源检查 —— spawn 前调用 ──
    p_rc = sub.add_parser("pre-spawn-check",
                          help="明鉴秋资源检查：spawn 前检测硬件并发能力")

    # ── Agent 生命周期管理 ──
    p_lc = sub.add_parser("agent-lifecycle",
                          help="明鉴秋 Agent 生命周期：注册/等待/shutdown")
    lc_sub = p_lc.add_subparsers(dest="lc_action", required=True)
    for name, args_list in [
        ("register", [
            ("--phase", {"required": True}),
            ("--agents", {"required": True}),
            ("--files", {"required": True}),
        ]),
        ("wait-and-shutdown", [
            ("--phase", {"required": True}),
            ("--timeout", {"type": int, "default": 900}),
        ]),
        ("shutdown", [
            ("--agents", {"required": True}),
        ]),
        ("active", []),
        ("cleanup", []),
    ]:
        p = lc_sub.add_parser(name)
        for arg, kwargs in args_list:
            p.add_argument(arg, **kwargs)
    p_rc.add_argument("--phase", required=True,
                      help="执行阶段（phase0-7 或角色名）")
    p_rc.add_argument("--base", type=int, default=5,
                      help="该阶段计划并发数")
    p_rc.add_argument("--active", type=int, default=0,
                      help="当前活跃未回收 Agent 数")

    # ── 一键资源扫描 —— 快速查看系统状态 ──
    p_rs = sub.add_parser("resource", help="快速查看系统资源状态")
    p_rs.add_argument("--json", action="store_true",
                      help="JSON 格式输出")

    # ── 自检 —— Pre-flight + 故障追溯 ──
    p_sc = sub.add_parser("self-check", help="FDT 自检：Pre-flight + 故障追溯")
    p_sc.add_argument("--workspace", default=None,
                      help="工作空间目录（检查扫描文件用）")
    p_sc.add_argument("--scan", default=None,
                      help="指定扫描 JSON 路径（覆盖 workspace 自动查找）")

    # ── 守护进程 —— 内置调度器 ──
    p_daemon = sub.add_parser("daemon",
                              help="FDT 守护进程：内置定时调度器（替代 WorkBuddy automation）")
    p_daemon.add_argument("action", choices=["start", "stop", "status"],
                          help="start=启动调度器, stop=停止, status=查看状态")
    p_daemon.add_argument("--job", choices=["daily_debate"],
                          default="daily_debate",
                          help="要运行的作业（默认 daily_debate）")
    p_daemon.add_argument("--background", action="store_true",
                          help="后台运行（start 时生效）")

    # ── Web 服务 ──
    p_serve = sub.add_parser("serve",
                             help="启动 Web Dashboard（独立界面，替代 WorkBuddy 界面）")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="监听地址（默认 127.0.0.1）")
    p_serve.add_argument("--port", type=int, default=8765,
                         help="监听端口（默认 8765）")
    p_serve.add_argument("--workspace", default=None,
                         help="工作空间数据目录（默认自动发现）")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    # ── 分发 ──
    if args.cmd == "pipeline":
        if args.mode == "finalize-only":
            return cmd_finalize_only(args)
        return cmd_pipeline(args)

    py = sys.executable

    if args.cmd == "scan":
        cmd = [py, str(_SCAN_PY),
               "--output", args.output_dir]
        if args.symbols:
            cmd += ["--symbols", args.symbols]
        if args.strategy:
            cmd += ["--strategy", args.strategy]
        if args.disable_filter:
            cmd.append("--disable-filter")
        return _run(cmd)

    if args.cmd == "debate":
        if args.deb_action == "plan":
            cmd = [py, str(_RUN_DEBATE_PY), "plan",
                   "--scan", args.scan, "--workspace", args.workspace,
                   "--mode", args.mode]
            if args.no_cache:
                cmd.append("--no-cache")
            if args.check_resources:
                cmd.append("--check-resources")
            if args.symbols:
                cmd += ["--symbols", args.symbols]
            return _run(cmd)
        if args.deb_action == "finalize":
            return _run([py, str(_RUN_DEBATE_PY), "finalize",
                         "--scan", args.scan, "--workspace", args.workspace])

    if args.cmd == "report":
        return _run([py, str(_RUN_DEBATE_PY), "report",
                     "--workspace", args.workspace])

    if args.cmd == "health":
        return _run([py, str(_SCRIPTS / "health_check.py")] +
                    (["--date", args.date] if args.date else []))

    # ── 明鉴秋资源检查 ──
    if args.cmd == "pre-spawn-check":
        return _run([
            py, str(_SCRIPTS / "spawn_resource_check.py"),
            "--phase", args.phase,
            "--base", str(args.base),
            "--active", str(args.active),
        ])

    # ── Agent 生命周期管理 ──
    if args.cmd == "agent-lifecycle":
        lc = args.lc_action
        lc_script = str(_SCRIPTS / "agent_lifecycle.py")
        if lc == "register":
            return _run([py, lc_script, "register",
                         "--phase", args.phase,
                         "--agents", args.agents,
                         "--files", args.files])
        elif lc == "wait-and-shutdown":
            return _run([py, lc_script, "wait-and-shutdown",
                         "--phase", args.phase,
                         "--timeout", str(args.timeout)])
        elif lc == "shutdown":
            return _run([py, lc_script, "shutdown",
                         "--agents", args.agents])
        elif lc == "active":
            return _run([py, lc_script, "active"])
        elif lc == "cleanup":
            return _run([py, lc_script, "cleanup"])

    # ── 快速资源扫描 ──
    if args.cmd == "resource":
        import json as _json
        try:
            r = subprocess.run(
                [py, str(_SCRIPTS / "resource_watchdog.py"),
                 "--phase", "phase3", "--active", "0"],
                capture_output=True, text=True, timeout=15,
            )
            data = _json.loads(r.stdout) if r.returncode == 0 else None
        except Exception:
            data = None
        if not data:
            print("⚠️ 资源扫描失败")
            return 1
        if args.json:
            print(_json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"📊 系统资源状态:")
            print(f"  CPU:   {data.get('cpu_pct', '?')}%")
            print(f"  内存:  {data.get('mem_pct', '?')}%")
            print(f"  磁盘:  {data.get('disk_pct', '?')}%")
            print(f"  Python进程: {data.get('py_processes', '?')}")
            print(f"  风险等级: {data.get('risk_level', '?')}")
            print(f"  实际并发建议: {data.get('safe_concurrent', '?')}")
            print(f"  详情: {data.get('reason', '')}")
        return 0

    # ── 自检 ──
    if args.cmd == "self-check":
        sc_args = [py, str(_SCRIPTS / "self_check.py")]
        if getattr(args, "workspace", None):
            sc_args += ["--workspace", args.workspace]
        if getattr(args, "scan", None):
            sc_args += ["--scan", args.scan]
        return _run(sc_args)

    # ── 守护进程 —— 内置调度器 ──
    if args.cmd == "daemon":
        action = args.action
        job = getattr(args, "job", "daily_debate")
        bg = getattr(args, "background", False)
        sch_args = [py, str(_SCRIPTS / "scheduler.py")]
        if action == "start":
            sch_args += ["--job", job]
            if bg:
                sch_args.append("--daemon")
        elif action == "stop":
            sch_args.append("--stop")
        elif action == "status":
            sch_args.append("--status")
        return _run(sch_args)

    # ── Web 服务 ──
    if args.cmd == "serve":
        import uvicorn
        sys.path.insert(0, str(_ROOT))
        sys.path.insert(0, str(_SCRIPTS))
        from webui import app
        ws = getattr(args, "workspace", None)
        if ws:
            os.environ["FDT_WORKSPACE"] = ws
            print(f"  工作空间: {ws}")
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8765)
        print(f"🌐 FDT Dashboard: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
