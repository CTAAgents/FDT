#!/usr/bin/env python3
"""
FDT A2A 文件桥 — 将辩论结果包装为 Agent-to-Agent 协议兼容格式
==============================================================

用法:
  python scripts/export_a2a.py --workspace <工作空间目录>
  python scripts/export_a2a.py --input debate_results.json --output a2a_results.json

输出: a2a_results.json（A2A Task/Artifact 信封，Content 使用 A2APayload 规范）
  --payloads 模式额外输出 a2a_payloads.json（纯 A2APayload 数组，无信封）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# A2APayload 数据信封
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from contracts.a2a_payload import (  # type: ignore
    A2APayload, a2a_debate, a2a_scan_summary,
    RUNTIME_LLM, RUNTIME_INDEPENDENT,
    GRADE_PRIMARY, GRADE_LLM,
)


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

        direction = v.get("direction", "NEUTRAL")
        action = v.get("action", "wait")
        confidence = v.get("confidence", "")
        reasoning = v.get("reasoning", "")
        entry_price = v.get("entry_price")
        stop_loss = v.get("stop_loss_price")
        target = v.get("target_price")

        dec = decisions_map.get(sym, verdict_to_decision(direction, action, confidence))
        decision = dec.get("decision", "HOLD") if isinstance(dec, dict) else "HOLD"
        conf = dec.get("confidence", 0.5) if isinstance(dec, dict) else 0.5
        if not entry_price:
            entry_price = dec.get("entry_price") if isinstance(dec, dict) else None
        if not target:
            target = dec.get("target_price") if isinstance(dec, dict) else None
        if not stop_loss:
            stop_loss = dec.get("stop_loss_price") if isinstance(dec, dict) else None

        # A2APayload 内容
        payload = a2a_debate(
            symbol=sym,
            decision=decision,
            confidence=conf,
            reasoning=reasoning or "",
            entry=entry_price if entry_price and entry_price > 0 else None,
            stop_loss=stop_loss if stop_loss and stop_loss > 0 else None,
            target=target if target and target > 0 else None,
            direction=direction,
        )

        artifact = {
            "id": f"verdict-{sym}",
            "name": f"{sym} 裁决",
            "contentType": "application/json",
            "content": payload.to_dict(),
        }
        parts.append({"type": "artifact", "artifact": artifact})

    # 产业链汇总 Artifact
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
    ap.add_argument("--payloads", action="store_true",
                    help="额外输出 a2a_payloads.json（纯 A2APayload 数组，无信封）")
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
    artifact_count = len(task['params']['parts'])
    print(
        f"✅ A2A 导出完成: {output_path}"
        f"（{verdict_count} 品种裁决，{artifact_count} 个 Artifact）"
    )

    # ── 可选：纯 A2APayload 数组 ──
    if args.payloads:
        payloads_path = output_path.parent / "a2a_payloads.json"
        payloads_data = []
        for part in task['params']['parts']:
            art = part.get("artifact", {})
            payloads_data.append({
                "type": art.get("content", {}).get("type", "fdt.debate"),
                "runtime_mode": art.get("content", {}).get("runtime_mode", "llm_enhanced"),
                "meta": art.get("content", {}).get("meta", {}),
                "data": art.get("content", {}).get("data", {}),
                "summary": art.get("content", {}).get("summary", ""),
            })
        with open(payloads_path, "w", encoding="utf-8") as f:
            json.dump(payloads_data, f, ensure_ascii=False, indent=2)
        print(f"✅ A2A Payloads 导出: {payloads_path}（{len(payloads_data)} 条）")


if __name__ == "__main__":
    main()
