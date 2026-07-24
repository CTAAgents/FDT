#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
from fdt_langgraph.state import DebateState, create_initial_state
from fdt_pg.connection import PGConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("fdt_cli")


def generate_trace_id() -> str:
    return f"fdt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"


async def run_debate(mode: str = "fast", run_evolution: bool = False) -> DebateState:
    from memory.manager import init_memory
    init_memory()

    trace_id = generate_trace_id()
    logger.info(f"Starting debate with trace_id: {trace_id}")

    initial_state = create_initial_state(trace_id, mode)

    graph = build_debate_graph(mode=mode)
    result = await graph.ainvoke(initial_state)
    # v8.8.0: 输出各阶段报告路径
    logger.info(f"Debate completed. Phases: {result.get('completed_phases')}")
    _print_phase_reports(result)

    # 辩论完成后自动触发进化闭环
    if run_evolution:
        try:
            from fdt_langgraph.evolution_graph import run_evolution as run_ev
            log_msg = f"Run evolution after debate: trace_id={trace_id}"
            logger.info(log_msg)
            ev_state = run_ev(source_trace_id=trace_id)
            if ev_state:
                ev_phase = ev_state.get("phase", "unknown")
                ev_errors = len(ev_state.get("errors", []))
                ev_decisions = ev_state.get("decisions", {})
                logger.info(f"Evolution completed: phase={ev_phase}, "
                            f"errors={ev_errors}, decisions={ev_decisions}")
                print("\n=== 🔄 自进化闭环完成 ===")
                print(f"  阶段: {ev_phase}")
                for step, result_data in ev_state.get("step_results", {}).items():
                    icon = "✅" if result_data.get("success") else "❌"
                    print(f"  {icon} {step}: {result_data.get('summary', '')[:80]}")
                print("=" * 40 + "\n")
            else:
                logger.warning("Evolution returned None state, skipping evolution display")
                print("\n=== ⚠️ 自进化闭环返回空状态 ===")
                print("=" * 40 + "\n")
        except Exception as e:
            logger.error(f"Evolution failed: {e}")

    return result


def _print_phase_reports(result: DebateState) -> None:
    """统一输出各阶段报告路径（v8.8.0）+ 数据新鲜度状态（v9.22.3）"""
    # ── 数据新鲜度状态（P0b 闸门） ──
    freshness = result.get("freshness_report")
    if freshness:
        f_status = freshness.get("status", "")
        if f_status in ("ALL_STALE", "NO_VALID_SYMBOLS"):
            print(f"\n⛔ [P0b] 数据新鲜度闸门阻断: {freshness.get('summary', '')}")
            for r in freshness.get("fail_reasons", [])[:3]:
                print(f"      原因: {r}")
        elif f_status == "PASS":
            v = freshness.get("valid_symbols", 0)
            print(f"\n  ✅ [P0b] 数据新鲜度检查通过: {v} 品种有有效数据")

    phase_reports = [
        ("P1 扫描报告", result.get("scan_report_path")),
        ("P3 研究报告", result.get("research_report_path")),
        ("P5 裁决报告", result.get("verdict_report_path")),
        ("P6 辩论报告", result.get("report_path")),
        ("P6a 信号扫描报告", result.get("signal_report_path")),
    ]
    print("\n=== 📑 阶段报告汇总 ===")
    for label, path in phase_reports:
        if path:
            print(f"  ✅ {label}: {path}")
        else:
            print(f"  ⚠️  {label}: 未生成")
    print("=" * 40 + "\n")


async def daemon_mode(cron_expr: str = "", interval: int = 60):
    """守护进程模式 (LangGraph Master Graph 驱动，替代 APScheduler)。

    Args:
        cron_expr: 保留参数兼容，不再使用 (由 master_graph 内部调度判断)
        interval: 检查间隔秒数
    """
    from fdt_langgraph.master_graph import run_master_daemon
    logger.info(f"Daemon mode (LangGraph Master Graph): interval={interval}s")
    run_master_daemon(interval_seconds=interval)


def main():
    parser = argparse.ArgumentParser(description="FDT Futures Debate Team CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a single debate")
    run_parser.add_argument("--mode", choices=["default", "fast", "deep_research", "tournament"], default="fast",
                            help="执行模式: default(深度研究) / fast(默认,跳过辩论) / deep_research / tournament")
    run_parser.add_argument("--evolve", action="store_true", help="Run evolution after debate")

    daemon_parser = subparsers.add_parser("daemon", help="Run as daemon (LangGraph Master Graph)")
    daemon_parser.add_argument("--interval", type=int, default=60,
                               help="Check interval in seconds (default: 60)")

    db_parser = subparsers.add_parser("db", help="Database operations")
    db_parser.add_argument("action", choices=["init", "migrate", "health"])

    evolve_parser = subparsers.add_parser("evolve", help="Run self-evolution standalone (APM-driven)")

    master_parser = subparsers.add_parser("master", help="Run Master Orchestrator once (check & execute due tasks)")

    args = parser.parse_args()

    if args.command == "run":
        # 同时支持 --evolve CLI flag 和 FDT_RUN_EVOLUTION 环境变量
        run_ev = args.evolve or os.environ.get("FDT_RUN_EVOLUTION", "").lower() == "true"
        asyncio.run(run_debate(mode=args.mode, run_evolution=run_ev))
    elif args.command == "daemon":
        asyncio.run(daemon_mode(interval=args.interval))
    elif args.command == "db":
        if args.action == "health":
            PGConnection.initialize()
            healthy = PGConnection.health_check()
            print(f"PostgreSQL health check: {'OK' if healthy else 'FAILED'}")
            sys.exit(0 if healthy else 1)
        elif args.action == "init":
            from fdt_pg.schema import Base
            engine = PGConnection.get_engine()
            Base.metadata.create_all(engine)
            print("Database schema initialized")
    elif args.command == "evolve":
        logger.info("Running self-evolution standalone (APM-driven)...")
        from fdt_langgraph.evolution_graph import run_evolution as run_ev
        ev_state = run_ev()
        print("\n=== 🔄 自进化闭环完成 ===")
        print(f"  Phase: {ev_state.get('phase')}")
        print(f"  APM Scores: {ev_state.get('apm_scores', {})}")
        for step, result_data in ev_state.get("step_results", {}).items():
            icon = "✅" if result_data.get("success") else "❌"
            print(f"  {icon} {step}: {result_data.get('summary', '')[:80]}")
        if ev_state.get("errors"):
            print(f"  ⚠️ Errors: {len(ev_state['errors'])}")
    elif args.command == "master":
        logger.info("Master Orchestrator: checking & executing due tasks...")
        from fdt_langgraph.master_graph import run_master_once
        result = run_master_once()
        tasks = result.get("task_results", {})
        print("\n=== 📋 Master 调度完成 ===")
        if tasks:
            for name, r in tasks.items():
                icon = "✅" if r.get("success") else "❌"
                print(f"  {icon} {name}: {r.get('summary', '')[:80]}")
        else:
            print("  无到期任务 (当前时间无匹配的调度)")


if __name__ == "__main__":
    main()
