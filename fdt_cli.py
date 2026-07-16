#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fdt_langgraph.state import DebateState, create_initial_state
from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
from fdt_pg.connection import PGConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("fdt_cli")


def generate_trace_id() -> str:
    return f"fdt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"


async def run_debate(mode: str = "default") -> DebateState:
    trace_id = generate_trace_id()
    logger.info(f"Starting debate with trace_id: {trace_id}")

    initial_state = create_initial_state(trace_id, mode)

    graph = build_debate_graph(mode=mode)
    result = await graph.ainvoke(initial_state)
    logger.info(f"Debate completed: {result.get('report_path')}")
    logger.info(f"Completed phases: {result.get('completed_phases')}")
    return result


async def daemon_mode(cron_expr: str, timezone: str = "Asia/Shanghai"):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(run_debate, CronTrigger.from_crontab(cron_expr))
    logger.info(f"Daemon mode started with cron: {cron_expr}")
    scheduler.start()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Daemon mode stopped")


def main():
    parser = argparse.ArgumentParser(description="FDT Futures Debate Team CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a single debate")
    run_parser.add_argument("--mode", choices=["default", "fast", "deep_research", "tournament"], default="default")

    daemon_parser = subparsers.add_parser("daemon", help="Run in daemon mode")
    daemon_parser.add_argument("--cron", default="0 9 * * 1-5")
    daemon_parser.add_argument("--timezone", default="Asia/Shanghai")

    db_parser = subparsers.add_parser("db", help="Database operations")
    db_parser.add_argument("action", choices=["init", "migrate", "health"])

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_debate(mode=args.mode))
    elif args.command == "daemon":
        asyncio.run(daemon_mode(cron_expr=args.cron, timezone=args.timezone))
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


if __name__ == "__main__":
    main()