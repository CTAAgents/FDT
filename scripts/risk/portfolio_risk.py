#!/usr/bin/env python3
"""
组合风控模块 — 跨品种组合级风险评估 (portfolio-risk Loop)。

功能:
    --collect   汇总所有品种当前信号
    --check     检查组合风控约束
    --report    输出组合风控报告

约束阈值 (从 contract 读取):
    - max_total_position_pct: 30%   # 总仓位上限
    - max_single_chain_pct: 15%     # 单产业链上限
    - max_direction_bias: 20%       # 方向偏差
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 约束 (与 portfolio-risk.contract.yaml 一致)
MAX_TOTAL_POSITION_PCT = 30.0
MAX_SINGLE_CHAIN_PCT = 15.0
MAX_DIRECTION_BIAS_PCT = 20.0

# 产业链映射 (从 settings.py 提取子集)
CHAIN_MAP = {
    "RB": "黑色系", "HC": "黑色系", "I": "黑色系", "J": "黑色系", "JM": "黑色系",
    "TA": "聚酯链", "PF": "聚酯链", "EG": "聚酯链",
    "MA": "塑化链", "V": "塑化链", "PP": "塑化链", "L": "塑化链",
    "AU": "贵金属", "AG": "贵金属",
    "CU": "有色金属", "AL": "有色金属", "ZN": "有色金属",
    "A": "油脂油料", "B": "油脂油料", "M": "油脂油料",
    "CF": "农产品", "SR": "农产品", "C": "农产品",
}


def _load_active_signals() -> list[dict]:
    """从 signal_output 或 ConfigStore 读取活跃信号。"""
    # 尝试从 memory/debates 读取最新 debate_results
    debates_dir = PROJECT_ROOT / "memory" / "debates"
    if debates_dir.exists():
        dates = sorted(debates_dir.iterdir(), reverse=True)
        for d in dates[:3]:
            result_file = d / "debate_results.json"
            if result_file.exists():
                data = json.loads(result_file.read_text(encoding="utf-8"))
                verdicts = data if isinstance(data, list) else data.get("final_verdicts", data.get("verdicts", []))
                if verdicts:  # found
                    return [
                        {
                            "symbol": v.get("symbol", "").split(".")[0].upper(),
                            "direction": v.get("direction", "neutral"),
                            "position_pct": v.get("position_pct", v.get("position_size", 0)),
                            "confidence": v.get("confidence", 0.5),
                        }
                        for v in verdicts if v.get("direction") in ("bull", "bear", "BUY", "SELL")
                    ]
    return []


def _cmd_collect() -> dict:
    """汇总所有活跃信号。"""
    signals = _load_active_signals()
    print(f"组合风控: 汇总 {len(signals)} 个活跃信号")
    for s in signals:
        chain = CHAIN_MAP.get(s["symbol"], "其他")
        print(f"  {s['symbol']:6s} {chain:<8s} {s['direction']:6s} {s['position_pct']}%")
    return {"signals": signals, "count": len(signals), "collected_at": datetime.now().isoformat()}


def _cmd_check(signals: list[dict] | None = None) -> dict:
    """检查组合风控约束。"""
    if signals is None:
        signals = _load_active_signals()

    issues: list[str] = []
    
    # 总仓位
    total_long = sum(s["position_pct"] for s in signals if s["direction"] in ("bull", "BUY"))
    total_short = sum(s["position_pct"] for s in signals if s["direction"] in ("bear", "SELL"))
    total = total_long + total_short

    if total > MAX_TOTAL_POSITION_PCT:
        issues.append(f"总仓位 {total:.1f}% > {MAX_TOTAL_POSITION_PCT}%")

    # 方向偏差
    direction_bias = abs(total_long - total_short)
    if direction_bias > MAX_DIRECTION_BIAS_PCT:
        dir_label = "偏多" if total_long > total_short else "偏空"
        issues.append(f"方向偏差 {direction_bias:.1f}% ({dir_label}) > {MAX_DIRECTION_BIAS_PCT}%")

    # 产业链集中度
    chain_exposure: dict[str, float] = defaultdict(float)
    for s in signals:
        chain = CHAIN_MAP.get(s["symbol"], "其他")
        chain_exposure[chain] += s["position_pct"]
    for chain, exposure in chain_exposure.items():
        if exposure > MAX_SINGLE_CHAIN_PCT:
            issues.append(f"产业链 {chain} 暴露 {exposure:.1f}% > {MAX_SINGLE_CHAIN_PCT}%")

    status = "CRITICAL" if any(">" in i for i in issues) else ("WARN" if issues else "OK")
    for i in issues:
        print(f"  ❌ {i}")
    if not issues:
        print(f"  ✅ 所有组合风控约束通过 (总仓位 {total:.1f}%)")

    return {"status": status, "issues": issues, "total_exposure": total, "chain_exposure": dict(chain_exposure)}


def _cmd_report() -> None:
    """输出组合风控报告。"""
    signals = _load_active_signals()
    check = _cmd_check(signals)
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "active_signals": len(signals),
        "total_exposure_pct": check["total_exposure"],
        "status": check["status"],
        "issues": check["issues"],
        "chain_exposure": check["chain_exposure"],
    }
    report_dir = PROJECT_ROOT / "memory" / "risk"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"portfolio_{datetime.now().strftime('%Y%m%d')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"组合风控报告已写入: {report_path}")


def _main() -> int:
    parser = argparse.ArgumentParser(description="组合风控 — portfolio-risk Loop")
    parser.add_argument("action", choices=["collect", "check", "report"], help="操作")
    args = parser.parse_args()

    if args.action == "collect":
        _cmd_collect()
    elif args.action == "check":
        _cmd_check()
    elif args.action == "report":
        _cmd_report()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
