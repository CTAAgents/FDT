#!/usr/bin/env python3
"""
FDT A2A 文件桥 — 将辩论结果包装为 Agent-to-Agent 协议兼容格式
==============================================================

用法:
  python scripts/export_a2a.py --workspace <工作空间目录>
  python scripts/export_a2a.py --input debate_results.json --output a2a_results.json

输出: a2a_results.json（符合 A2A Task/Artifact 信封规范）
       agent-card.json（FDT Agent Card，已存在根目录）

A2A 协议版本: 1.0 (Google Agent-to-Agent Protocol)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verdict_to_decision(
    direction: str, action: str, confidence: str
) -> dict:
    """将 FDT 裁决映射为 A2A 交易信号。"""
    # action map: execute→BUY/SELL, hold→WATCH, wait→HOLD
    dir_upper = direction.upper() if direction else ""
    act = action.lower() if action else "wait"

    if act == "execute":
        decision = "BUY" if dir_upper in ("BULL", "BUY") else "SELL"
    elif act == "hold":
        decision = "WATCH"
    else:
        decision = "HOLD"

    # 置信度归一化（文字→数值）
    conf_map = {"高": 0.8, "中": 0.6, "低": 0.4, "HIGH": 0.8, "MEDIUM": 0.6, "LOW": 0.4}
    conf_numeric = conf_map.get(confidence, 0.5)

    return {"decision": decision, "confidence": conf_numeric}


def build_task(debate: dict, intermediate: dict | None = None) -> dict:
    """将 debate_results.json 包装为 A2A Task 格式。

    A2A 规范: Task 包含 sessionId + 一组 Artifact Parts。
    每个品种的裁决是一个 Artifact，包含交易信号。
    """
    verdicts = debate.get("verdicts", {})
    meta = debate.get("_meta", {})

    # 从 intermediate_data 读取 all_actionable（含决策映射）
    decisions_map = {}
    if intermediate:
        for sig in intermediate.get("all_actionable", []):
            sym = sig.get("symbol", "")
            if sym:
                decisions_map[sym] = {
                    "decision": sig.get("decision", "HOLD"),
                    "confidence": sig.get("confidence", 0.5),
                    "direction": sig.get("direction", ""),
                    "price": sig.get("price", 0),
                    "entry_price": sig.get("entry_price", sig.get("price", 0)),
                    "target_price": sig.get("target_price"),
                    "stop_loss_price": sig.get("stop_loss_price"),
                    "position_size": sig.get("position_size"),
                    "signal_type": sig.get("signal_type", ""),
                    "grade": sig.get("grade", ""),
                    "chain": sig.get("chain", ""),
                }

    session_id = f"fdt-{debate.get('round_id', 'unknown')}"

    parts = []
    for sym, v in verdicts.items():
        if not isinstance(v, dict):
            continue

        # 从 verdict 提取基本信息
        direction = v.get("direction", "")
        action = v.get("action", "wait")
        confidence = v.get("confidence", "")
        entry_price = v.get("entry_price")
        stop_loss = v.get("stop_loss_price")
        target = v.get("target_price")
        pos_size = v.get("position_size")
        reasoning = v.get("reasoning", "")
        grade = v.get("grade", "")

        # 若 intermediate 有更完善的决策数据，从此取
        dec = decisions_map.get(sym, verdict_to_decision(direction, action, confidence))
        if isinstance(dec, dict):
            decision = dec.get("decision", "HOLD")
            conf = dec.get("confidence", 0.5)
            if not entry_price:
                entry_price = dec.get("entry_price")
            if not target:
                target = dec.get("target_price")
            if not stop_loss:
                stop_loss = dec.get("stop_loss_price")
        else:
            decision = dec
            conf = 0.5

        # 构建 A2A Artifact
        artifact = {
            "id": f"verdict-{sym}",
            "name": f"{sym} 裁决",
            "contentType": "application/json",
            "content": {
                "symbol": sym,
                "decision": decision,
                "direction": direction or "NEUTRAL",
                "confidence": conf,
                "grade": grade,
                "action": action,
                "reasoning": reasoning[:500] if reasoning else "",
                "entry": {
                    "type": "limit",
                    "price": entry_price if entry_price and entry_price > 0 else None,
                },
                "stop_loss": {
                    "price": stop_loss if stop_loss and stop_loss > 0 else None,
                },
                "targets": [
                    {"level": 1, "price": target if target and target > 0 else None}
                ],
                "position_size": pos_size if pos_size and pos_size > 0 else None,
                "judge_verdict": v.get("verdict", ""),
                "debate_winner": v.get("winner", ""),
                "technical_indicators": {
                    "adx": v.get("adx"),
                    "rsi": v.get("rsi"),
                    "total_score": v.get("total_score"),
                },
            },
        }

        parts.append({"type": "artifact", "artifact": artifact})

    # 若 intermediate 有产业链信息，加入汇总 Artifact
    if intermediate and intermediate.get("chain_results"):
        chains = []
        for chain_key, chain_data in intermediate["chain_results"].items():
            chains.append({
                "chain": chain_data.get("chain", chain_key),
                "name": chain_data.get("chain_name", chain_key),
                "members": chain_data.get("chain_members", []),
                "term_structure": chain_data.get("term_structure", "flat"),
            })
        parts.append({
            "type": "artifact",
            "artifact": {
                "id": "chain-summary",
                "name": "产业链汇总",
                "contentType": "application/json",
                "content": {"chains": chains},
            },
        })

    return {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "status": "completed",
            "parts": parts,
        },
    }


def main():
    ap = argparse.ArgumentParser(description="FDT A2A 文件桥")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--workspace", "-w", help="工作空间目录（含 debate_results.json）")
    group.add_argument("--input", "-i", help="debate_results.json 路径")

    ap.add_argument("--output", "-o", help="输出路径（默认: 与 input 同目录的 a2a_results.json）")
    ap.add_argument("--intermediate", help="intermediate_data.json 路径（可选，增强决策数据）")
    args = ap.parse_args()

    # ── 确定输入输出路径 ──
    if args.workspace:
        ws = Path(args.workspace)
        input_path = ws / "debate_results.json"
        output_path = Path(args.output) if args.output else ws / "a2a_results.json"
        intermediate_path = (
            Path(args.intermediate) if args.intermediate else ws / "intermediate_data.json"
        )
    else:
        input_path = Path(args.input)
        output_path = (
            Path(args.output) if args.output
            else input_path.parent / "a2a_results.json"
        )
        intermediate_path = (
            Path(args.intermediate) if args.intermediate else None
        )

    # ── 加载 ──
    if not input_path.exists():
        print(f"[FATAL] 未找到: {input_path}", file=sys.stderr)
        sys.exit(1)

    debate = load_json(str(input_path))
    intermediate = None
    if intermediate_path and intermediate_path.exists():
        try:
            intermediate = load_json(str(intermediate_path))
        except Exception as e:
            print(f"[WARN] intermediate_data.json 加载失败: {e}", file=sys.stderr)

    # ── 转换 ──
    task = build_task(debate, intermediate)

    # ── 写入 ──
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)

    verdict_count = len(debate.get("verdicts", {}))
    print(
        f"✅ A2A 导出完成: {output_path}"
        f"（{verdict_count} 品种裁决，{len(task['params']['parts'])} 个 Artifact）"
    )


if __name__ == "__main__":
    main()
