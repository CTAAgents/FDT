#!/usr/bin/env python3
"""
FDT 前向基准（ViBench 层）— 历史场景回放测试集。

设计来源: CLQT (arXiv:2606.29771) 的 ViBench 思想 —— 任何对 prompt/流程/规则的修改,
发布前必须用固定历史场景回放集衡量"是否变好", 而非仅看单一 PnL 分数。

本脚本两种模式:
  python run_benchmark.py --build      从 execution_followup.json 抽取金标准测试集 → benchmarks/test_cases.json
  python run_benchmark.py [--run]      加载测试集, 报告基线指标 + 回放引擎状态

重要约束:
  - 真实"回放"需要每轮辩论的原始输入快照(scan信号/产业链/基本面), 当前 debate_journal
    未捕获这些输入, 故回放引擎状态为 BLOCKED。本脚本在回放就绪前, 以 ground_truth 提供
    基线指标(等价于当前系统在该固定集上的表现), 供阶段三 harness 自改进对照使用。
  - test_cases.json 是阶段三 self_improve.py 的 before/after 对照基线; 任何 prompt 修改
    在输入捕获就绪后, 可通过本脚本回放得到 before/after 分数差。

数据铁律: 所有期货数据/裁决来自 quant-daily + execution_followup, 不在本脚本内重复拉取。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _norm_variety(sym: str) -> str:
    """品种代码归一：CU.SHF -> CU（与 validate_verdicts 一致）"""
    return (sym or "").split(".")[0].upper().strip()


def _futures_team_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _verdict_snapshot(v: dict) -> dict:
    """提取裁决快照(可重放输入的核心字段)"""
    return {
        "symbol": v.get("symbol"),
        "name": v.get("name"),
        "direction": v.get("direction"),
        "confidence": v.get("confidence"),
        "score": v.get("score"),
        "adx": v.get("adx"),
        "rsi": v.get("rsi"),
        "resonance": v.get("resonance"),
        "ft_dir": v.get("ft_dir"),
        "conflict": v.get("conflict"),
        "chain": v.get("chain"),
        "position_pct": v.get("position_pct"),
        "entry_price": v.get("entry_price"),
        "stop_loss": v.get("stop_loss"),
        "target1": v.get("target1"),
        "target2": v.get("target2"),
    }


def build_seed(followup_path: str, benchmarks_dir: str, cost_bps: float = 2.0) -> dict:
    """从 execution_followup.json 抽取金标准测试集。

    仅纳入已验证(validated)且结果非 unknown 的裁决, 保证 ground_truth 可靠。
    """
    with open(followup_path, 'r', encoding='utf-8') as f:
        followup = json.load(f)

    # 关联 debate_record 作为输入快照（ViBench 回放输入）
    debate_map = {}
    try:
        root = Path(followup_path).resolve().parent.parent
        journal_path = root / "memory" / "debate_journal.json"
        if journal_path.exists():
            with open(journal_path, 'r', encoding='utf-8') as f:
                j = json.load(f)
            for e in j.get("entries", []):
                if e.get("action") == "debate_record":
                    debate_map[(_norm_variety(e.get("round_id")), _norm_variety(e.get("symbol") or e.get("variety")))] = e
    except (json.JSONDecodeError, IOError):
        debate_map = {}

    cases = []
    skipped = 0
    for rec in followup.get("records", []):
        if not rec.get("validated"):
            continue
        vr = rec.get("validation_results", {})
        if not vr:
            continue
        verdicts = rec.get("verdicts", [])
        results = vr.get("results", [])
        for i, v in enumerate(verdicts):
            if i >= len(results):
                break
            r = results[i]
            if r.get("correct") is None:
                skipped += 1
                continue
            snap = debate_map.get((_norm_variety(rec.get("round_id")), _norm_variety(v.get("symbol"))))
            if snap is None:
                snap = debate_map.get((None, _norm_variety(v.get("symbol"))))
            case = {
                "case_id": f"TC-{len(cases)+1:03d}",
                "round_id": rec.get("round_id"),
                "generated_at": rec.get("generated_at"),
                "verdict_snapshot": _verdict_snapshot(v),
                "debate_input_snapshot": (
                    {"pro_args": snap.get("pro_args"), "con_args": snap.get("con_args"),
                     "verdict": snap.get("verdict"), "held_out_judge": snap.get("held_out_judge")}
                    if snap else None
                ),
                "ground_truth": {
                    "correct": r.get("correct"),
                    "correct_net": r.get("correct_net"),
                    "realized_pnl_pct": r.get("realized_pnl_pct"),
                    "net_pnl_pct": r.get("net_pnl_pct"),
                    "hit_stop": r.get("hit_stop"),
                    "hit_target1": r.get("hit_target1"),
                    "hit_target2": r.get("hit_target2"),
                    "gap_stop": r.get("gap_stop"),
                    "data_source": r.get("data_source"),
                    "cost_bps": r.get("cost_bps", cost_bps),
                    "notes": r.get("reason", ""),
                },
            }
            cases.append(case)

    payload = {
        "benchmark_version": "v0.1-seed",
        "built_from": os.path.basename(followup_path),
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cost_bps": cost_bps,
        "total_cases": len(cases),
        "skipped_unknown": skipped,
        "replay_status": "ACTIVE — debate_journal.json 已升级 schema 捕获 debate_record(含 pro_args/con_args/verdict/held_out_judge), 回放引擎可消费",
        "replay_unlock_condition": "持续积累 debate_record（每轮辩论由 futures-judge-heldout 产出 held_out_judge）",
        "cases": cases,
    }

    os.makedirs(benchmarks_dir, exist_ok=True)
    out_path = os.path.join(benchmarks_dir, "test_cases.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ 金标准测试集已构建: {out_path}")
    print(f"   案例数: {len(cases)} (跳过 unknown: {skipped})")
    return payload


def run_benchmark(test_cases_path: str, out_dir: str) -> dict:
    """加载测试集, 报告基线指标 + 回放引擎状态。

    在回放引擎 BLOCKED 期间, baseline = ground_truth 聚合(当前系统在该固定集上的表现)。
    """
    with open(test_cases_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cases = data.get("cases", [])
    total = len(cases)
    correct = sum(1 for c in cases if c["ground_truth"]["correct"] is True)
    correct_net = sum(1 for c in cases if c["ground_truth"]["correct_net"] is True)
    dir_acc = round(correct / total * 100, 1) if total else 0
    net_acc = round(correct_net / total * 100, 1) if total else 0
    net_pnls = [c["ground_truth"]["net_pnl_pct"] for c in cases if c["ground_truth"].get("net_pnl_pct") is not None]
    avg_net = round(sum(net_pnls) / len(net_pnls), 2) if net_pnls else 0.0
    gross_pnls = [c["ground_truth"]["realized_pnl_pct"] for c in cases if c["ground_truth"].get("realized_pnl_pct") is not None]
    avg_gross = round(sum(gross_pnls) / len(gross_pnls), 2) if gross_pnls else 0.0

    baseline = {
        "benchmark_version": data.get("benchmark_version"),
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_cases": total,
        "cost_bps": data.get("cost_bps"),
        "direction_accuracy": dir_acc,
        "net_accuracy": net_acc,
        "avg_gross_pnl_pct": avg_gross,
        "avg_net_pnl_pct": avg_net,
        "replay_status": data.get("replay_status"),
        "note": "回放引擎 BLOCKED 期间, baseline 直接聚合 ground_truth (等价于当前系统在该固定集表现)。"
                "输入捕获就绪后, 此处将改为回放当前 prompt 并对比 ground_truth。",
    }

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "benchmark_baseline.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)

    print(f"\n📊 ViBench 基线报告 (回放状态: {data.get('replay_status', 'UNKNOWN')[:40]})")
    print(f"   测试集版本: {data.get('benchmark_version')}  案例数: {total}  (成本 {data.get('cost_bps')}bp)")
    print(f"   方向准确率(毛): {dir_acc}%  ({correct}/{total})")
    print(f"   方向准确率(净): {net_acc}%  ({correct_net}/{total})")
    print(f"   均盈(毛): {avg_gross:+.2f}%  | (净): {avg_net:+.2f}%")
    print(f"   回放引擎: {data.get('replay_status')}")
    print(f"   基线已保存: {out_path}")
    return baseline


def run_replay_benchmark(journal_path: str, followup_path: str, out_dir: str) -> dict:
    """运行 ViBench 回放：消费 debate_record，join ground_truth，产出结构一致性报告。"""
    from replay_harness import run_replay as _rp
    with open(journal_path, 'r', encoding='utf-8') as f:
        journal = json.load(f)
    debate_records = [e for e in journal.get("entries", []) if e.get("action") == "debate_record"]
    with open(followup_path, 'r', encoding='utf-8') as f:
        followup = json.load(f)
    report = _rp(debate_records, followup)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "benchmark_replay.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n🔁 ViBench 回放报告 (引擎: {report['replay_engine']})")
    print(f"   debate_record 数: {report['total_debate_records']}")
    print(f"   ground_truth 匹配: {report['ground_truth_matched']}")
    print(f"   结构一致性率: {report['structural_consistency_rate']}%  ({report['structurally_consistent']}/{report['total_debate_records']})")
    print(f"   coherence_weighted_accuracy: {report['coherence_weighted_accuracy']}")
    print(f"   回放状态: {report['replay_status']}")
    for r in report["rows"]:
        print(f"   - {r['round_id']}/{r['symbol']}: 推导={r['derived_direction']} 裁决={r['verdict_direction']} "
              f"一致={r['direction_consistent']} coh={r['coherence']} gt匹配={r['has_ground_truth']}")
    print(f"   回放报告已保存: {out_path}")
    return report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="FDT 前向基准 (ViBench 层)")
    parser.add_argument("--build", action="store_true", help="从 execution_followup.json 构建金标准测试集")
    parser.add_argument("--run", action="store_true", help="运行基线报告(默认)")
    parser.add_argument("--replay", action="store_true", help="运行 ViBench 历史回放(消费 debate_record)")
    parser.add_argument("--cost-bps", type=float, default=2.0, help="成本(基点), 默认 2.0")
    parser.add_argument("--followup", default=None, help="execution_followup.json 路径")
    parser.add_argument("--benchmarks", default=None, help="benchmarks/ 目录路径")
    args = parser.parse_args()

    root = _futures_team_root()
    followup_path = args.followup or str(root / "memory" / "execution_followup.json")
    benchmarks_dir = args.benchmarks or str(root / "benchmarks")
    test_cases_path = os.path.join(benchmarks_dir, "test_cases.json")

    if args.replay:
        journal_path = str(root / "memory" / "debate_journal.json")
        run_replay_benchmark(journal_path, followup_path, benchmarks_dir)
        return

    if args.build:
        build_seed(followup_path, benchmarks_dir, cost_bps=args.cost_bps)
    else:
        if not os.path.exists(test_cases_path):
            print("⚠️ 测试集不存在, 先执行 --build")
            build_seed(followup_path, benchmarks_dir, cost_bps=args.cost_bps)
        run_benchmark(test_cases_path, benchmarks_dir)


if __name__ == "__main__":
    main()
