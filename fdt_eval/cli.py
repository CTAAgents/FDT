#!/usr/bin/env python3
"""
FDT Eval Framework CLI — python -m fdt_eval [command]

命令:
    run         执行评估（--profile / --case / --stage）
    list        列出所有已注册的评估用例
    trend       查询某个 case 的运行趋势
    dashboard   引擎整体评分概览

用法:
    python -m fdt_eval run --profile ci
    python -m fdt_eval run --case runtime.quality_inspector.p3_5
    python -m fdt_eval list
    python -m fdt_eval trend --case runtime.quality_inspector.p3_5 --last 30
    python -m fdt_eval dashboard
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from fdt_eval.core.base import EvalContext
from fdt_eval.core.calibrator import calibrate_weights
from fdt_eval.core.registry import eval_registry
from fdt_eval.core.runner import EvalRunner
from fdt_eval.core.store import EvalStore

# 触发 EvalCase 自动发现注册
import fdt_eval.cases  # noqa: F401


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m fdt_eval", description="FDT Eval Framework")
    sub = p.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser("run", help="执行评估")
    run_p.add_argument("--profile", default="dev", help="Profile 名称 (dev/ci/nightly/release)")
    run_p.add_argument("--case", nargs="+", help="指定 case_id 列表")
    run_p.add_argument("--stage", help="过滤阶段 (runtime/post_hoc/gate/evolution/meta)")
    run_p.add_argument("--force", action="store_true", help="强制不缓存")
    run_p.add_argument("--trace-id", default="", help="trace_id（默认自动生成）")
    run_p.add_argument("--update-docs", action="store_true", help="运行后同步 06-testing.md 的 case 清单")

    # list
    list_p = sub.add_parser("list", help="列出所有注册的评估用例")
    list_p.add_argument("--stage", help="按阶段过滤")

    # trend
    trend_p = sub.add_parser("trend", help="查询运行趋势")
    trend_p.add_argument("--case", required=True, help="case_id")
    trend_p.add_argument("--last", type=int, default=30, help="最近 N 次")

    # dashboard
    sub.add_parser("dashboard", help="引擎整体评分概览")

    # calibrate
    cal_p = sub.add_parser("calibrate", help="权重校准 (LOO Spearman)")
    cal_p.add_argument("--last", type=int, default=100, help="分析的最近记录数 (default: 100)")
    cal_p.add_argument("--output", default="", help="weight_history.json 输出路径 (default: profiles/weight_history.json)")

    return p


def _cmd_run(args: argparse.Namespace) -> int:
    context = EvalContext(trace_id=args.trace_id or f"eval-cli-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    runner = EvalRunner()
    report = runner.run(
        profile=args.profile,
        context=context,
        cases=args.case,
        stage=args.stage,
        force=args.force,
    )

    passed = sum(1 for r in report.results if r.status == "PASS")
    failed = sum(1 for r in report.results if r.status == "FAIL")
    errored = sum(1 for r in report.results if r.status == "ERROR")
    print(f"\n{'='*60}")
    print(f"Profile: {report.profile}  |  Duration: {report.duration_ms:.0f}ms")
    print(f"Total: {len(report.results)}  |  PASS: {passed}  |  FAIL: {failed}  |  ERROR: {errored}")
    print(f"{'='*60}")
    for r in report.results:
        icon = {"PASS": "✓", "FAIL": "✗", "ERROR": "!", "SKIP": "−"}.get(r.status, "?")
        print(f"  {icon} [{r.case_id}] {r.status}  score={r.score:.2f}  {r.detail}")

    # --update-docs: 占位同步
    if args.update_docs:
        case_ids = sorted(r.case_id for r in report.results)
        print(f"\nℹ [--update-docs] 以下 {len(case_ids)} 个 case 将同步到 06-testing.md:")
        for cid in case_ids:
            print(f"    • {cid}")
        print(f"  完整自动同步待实现")

    return 1 if failed > 0 else 0


def _cmd_list(args: argparse.Namespace) -> int:
    cases = eval_registry.list(stage=args.stage)
    if not cases:
        print("(暂无注册的评估用例)")
        return 0
    print(f"{'case_id':<50} {'stage':<12} {'weight':<8} {'threshold':<10}")
    print("-" * 80)
    for c in sorted(cases, key=lambda x: x.case_id):
        print(f"{c.case_id:<50} {c.stage:<12} {c.weight:<8} {c.threshold:<10}")
    print(f"\n总计: {len(cases)} 个评估用例")
    return 0


def _cmd_trend(args: argparse.Namespace) -> int:
    store = EvalStore()
    rows = store.trend(args.case, last=args.last)
    if not rows:
        print(f"case_id '{args.case}' 暂无运行记录")
        return 0
    print(f"\n{args.case} — 最近 {len(rows)} 次运行:")
    print(f"{'#':<4} {'时间':<22} {'状态':<8} {'得分':<8} {'详情'}")
    print("-" * 80)
    for i, r in enumerate(rows, 1):
        print(f"{i:<4} {r['created_at']:<22} {r['status']:<8} {r['score']:<8.2f} {r['detail']}")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    store = EvalStore()
    agg = store.aggregate_score(last=100)
    print(f"\n{'='*50}")
    print(f"FDT Eval Dashboard")
    print(f"{'='*50}")
    print(f"Total runs: {agg['total']}")
    print(f"Pass rate:  {agg['pass_rate']:.2%}")
    print(f"\nBreakdown by stage:")
    for row in agg.get("breakdown", []):
        print(f"  {row['stage']:<12} {row['status']:<8} {row['cnt']}")
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    """执行权重校准并输出结果表格。"""
    output_path = args.output or None  # None → calibrator 使用默认路径
    result = calibrate_weights(last_n=args.last, output_path=output_path)

    print(f"\n{'='*60}")
    print(f"权重校准结果")
    print(f"{'='*60}")
    print(f"方法:             {result['method']}")
    print(f"分析样本数:       {result['samples']}")
    print(f"历史版本数:       {result['history_entries']}")
    print()

    # 当前权重表格
    print(f"{'阶段':<20} {'当前权重':<12} {'校准后权重':<12}")
    print(f"{'-'*44}")
    all_stages = ["runtime", "gate", "post_hoc", "evolution"]
    cw = result["current_weights"]
    cal = result["calibrated_weights"]
    for stage in all_stages:
        cur = cw.get(stage, 0.0)
        cal_val = cal.get(stage, cur)
        changed = " ←" if cal_val != cur else ""
        print(f"{stage:<20} {cur:<12.2f} {cal_val:<12.2f}{changed}")

    total_cal = sum(cal.get(s, 0.0) for s in all_stages)
    print(f"{'-'*44}")
    print(f"{'合计':<20} {sum(cw.values()):<12.2f} {total_cal:<12.2f}")

    if result["method"] == "default":
        print(f"\n⚠ 校准使用默认权重（历史数据不足或缺少裁决正确性标签）。")
        print(f"   LOO Spearman 扫描需要 ≥20 条 eval 记录和外部裁决正确性数据。")
    else:
        print(f"\n✓ 已应用 LOO Spearman 校准。")

    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    commands = {
        "run": _cmd_run,
        "list": _cmd_list,
        "trend": _cmd_trend,
        "dashboard": _cmd_dashboard,
        "calibrate": _cmd_calibrate,
    }
    cmd_fn = commands.get(args.command)
    if cmd_fn:
        return cmd_fn(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
