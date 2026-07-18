#!/usr/bin/env python3
"""
裁决记录器 — 将辩论裁决自动写入 execution_followup.json
由闫判官在每轮辩论结束后调用。

用法:
  python record_verdicts.py --input debate_results.json

输出: 追加记录到 memory/execution_followup.json
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path


def load_debate_results(input_path: str) -> dict:
    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_followup(followup_path: str) -> dict:
    if os.path.exists(followup_path):
        with open(followup_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "_schema_version": "1.1",
        "_description": "辩论→实盘执行回溯。每轮辩论后自动追加。由 validate_verdicts.py 消费。",
        "records": []
    }


def save_followup(followup_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(followup_path), exist_ok=True)
    with open(followup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_record(debate_data: dict) -> dict:
    """从 debate_results.json 构建执行跟踪记录"""
    meta = debate_data.get('_meta', {})
    verdicts_raw = debate_data.get('verdicts', {})

    verdict_list = []
    for sym, v in verdicts_raw.items():
        verdict_list.append({
            "symbol": sym,
            "name": v.get("name", ""),
            "direction": v.get("direction", "neutral"),
            "confidence": v.get("confidence", "中"),
            "score": v.get("score", 0),
            "adx": v.get("adx", 0),
            "rsi": v.get("rsi", 0),
            "entry_price": v.get("entry_price", 0),
            "stop_loss": v.get("stop_loss_price", 0),
            "target1": v.get("target_price", 0),
            "target2": v.get("target2_price", 0),
            "position_pct": v.get("position_pct", 0),
            "chain": v.get("chain", ""),
            "conflict": v.get("conflict", False),
            "ft_dir": v.get("ft_dir", "neutral"),
            "resonance": v.get("resonance", 0),
        })

    # Count directions
    sell_count = sum(1 for v in verdict_list if v["direction"] == "bear")
    buy_count = sum(1 for v in verdict_list if v["direction"] == "bull")
    sell_high = sum(1 for v in verdict_list if v["direction"] == "bear" and v["confidence"] == "高")
    buy_mid_plus = sum(1 for v in verdict_list if v["direction"] == "bull" and v["confidence"] in ("高", "中"))

    return {
        "round_id": debate_data.get("round_id", f"debate_{datetime.now().strftime('%Y%m%d_%H%M')}"),
        "generated_at": debate_data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        "data_source": debate_data.get("data_source", ""),
        "total_verdicts": len(verdict_list),
        "sell_count": sell_count,
        "buy_count": buy_count,
        "sell_high_count": sell_high,
        "buy_midplus_count": buy_mid_plus,
        "chains_covered": meta.get("chains_covered", 0),
        "total_exposure_pct": debate_data.get("total_exposure_pct", 0),
        "l1l4_bull": meta.get("l1l4_bull", 0),
        "l1l4_bear": meta.get("l1l4_bear", 0),
        "factor_bull": meta.get("factor_bull", 0),
        "factor_bear": meta.get("factor_bear", 0),
        "verdicts": verdict_list,
        "validated": False,
        "validation_results": None,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="裁决记录器")
    parser.add_argument("--input", required=True, help="debate_results.json 路径")
    parser.add_argument("--followup", default=None, help="execution_followup.json 路径（默认自动定位）")
    args = parser.parse_args()

    # Auto-locate followup path relative to this script
    if args.followup is None:
        script_dir = Path(__file__).parent.parent
        args.followup = str(script_dir / "memory" / "execution_followup.json")

    debate_data = load_debate_results(args.input)
    followup = load_followup(args.followup)

    record = build_record(debate_data)

    # Check for duplicate round_id
    existing_ids = {r["round_id"] for r in followup["records"]}
    if record["round_id"] in existing_ids:
        print(f"⚠️ 轮次 {record['round_id']} 已存在，覆盖旧记录")
        followup["records"] = [r for r in followup["records"] if r["round_id"] != record["round_id"]]

    followup["records"].append(record)
    save_followup(args.followup, followup)

    print(f"✅ 裁决已记录: {record['round_id']}")
    print(f"   品种: {record['total_verdicts']}, SELL={record['sell_count']}(高{record['sell_high_count']}), BUY={record['buy_count']}")
    print(f"   产业链: {record['chains_covered']}, 总敞口: {record['total_exposure_pct']}%")
    print(f"   保存至: {args.followup}")


if __name__ == "__main__":
    main()
