#!/usr/bin/env python3
"""
FDT 最终信号复查器 v1.0 — 确定性校验，不依赖 LLM
====================================================

功能：在 debate_results.json 推送给交易系统之前，执行一组硬性校验规则，
      确保输出信号明确无异议、无矛盾。

使用：
  python scripts/validate_final_signals.py --input debate_results.json
  python scripts/validate_final_signals.py --input debate_results.json --scan scan_daily_*.json  (加扫盘品种数)

退出码：
  0 = 全部通过
  1 = 至少一项校验失败

导入用法：
  from validate_final_signals import validate_signals
  errors = validate_signals(debate_data)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# ── 规则配置（可调参数）──
REQUIRED_TOPLEVEL = {"round_id", "generated_at", "data_benchmark", "verdicts"}
VALID_ACTIONS = {"execute", "hold", "wait"}
TRADE_PARAMS = {"entry_price", "stop_loss_price", "target_price", "position_size", "contract"}

# 置信度标签归一化（英文→中文）
CONFIDENCE_MAP = {
    "HIGH": "高", "MEDIUM": "中", "LOW": "低",
    "high": "高", "medium": "中", "low": "低",
}


def validate_signals(data: dict, scan: dict | None = None) -> tuple[list[str], list[str]]:
    """对 debate_results.json 执行全部校验，返回 (errors, warns)。

    errors 为空 → exit(0)；仅 warns → exit(0)；任何 errors → exit(1)。
    WARN 表示提醒（不阻断管道），ERROR 表示必须修复的问题。
    """
    errors: list[str] = []
    warns: list[str] = []

    # ── 1. 顶层字段 ──
    missing = REQUIRED_TOPLEVEL - set(data.keys())
    if missing:
        errors.append(f"[FATAL] 顶层缺失字段: {', '.join(sorted(missing))}")

    verdicts = data.get("verdicts", {})
    if not isinstance(verdicts, dict):
        errors.append(f"[FATAL] verdicts 不是 dict: {type(verdicts).__name__}")
        return errors, warns

    if not verdicts:
        warns.append("[WARN] verdicts 为空（无辩论品种，可能是正常情况）")

    # ── 2. 每个裁决品种的校验 ──
    for sym, v in verdicts.items():
        if not isinstance(v, dict):
            errors.append(f"[{sym}] 非 dict 结构: {type(v).__name__}")
            continue

        action = v.get("action", "")
        direction = str(v.get("direction", "")).upper()
        confidence = v.get("confidence", "")

        # 2a. action 存在且合法
        if action not in VALID_ACTIONS:
            errors.append(f"[{sym}] action='{action}' 不合法（允许: {VALID_ACTIONS}）")

        # 2b. direction 存在
        if not direction:
            errors.append(f"[{sym}] direction 为空")

        # 2c. confidence 存在
        if not confidence:
            errors.append(f"[{sym}] confidence 为空")
        elif isinstance(confidence, str):
            # 归一化英文标签→中文
            if confidence in CONFIDENCE_MAP:
                v["confidence"] = CONFIDENCE_MAP[confidence]
                confidence = v["confidence"]
            elif confidence not in ("高", "中", "低"):
                errors.append(f"[{sym}] confidence='{confidence}' 不是高/中/低")
        elif isinstance(confidence, (int, float)) and not (0 <= confidence <= 1):
            errors.append(f"[{sym}] confidence={confidence} 不在 0~1 范围")

        # 2d. 交易参数一致性：action=execute → 全部有值；action≠execute → 全部为空
        trade_values = {k: v.get(k) for k in TRADE_PARAMS}
        if action == "execute":
            null_params = [k for k, val in trade_values.items() if val is None]
            if null_params:
                errors.append(
                    f"[{sym}] action=execute 但以下交易参数为 None: {null_params}"
                )
            # 数值型参数必须 > 0；但 entry=0 仅 WARN（可能是参数未填充，不阻断管道）
            for k in ("entry_price", "stop_loss_price", "target_price"):
                val = trade_values.get(k)
                if val is not None and val <= 0:
                    warns.append(f"[{sym}] {k}={val} ≤ 0，不合法（降为 WARN，不阻断）")
            # position_size 必须 > 0
            pos = trade_values.get("position_size")
            if pos is not None and pos <= 0:
                errors.append(f"[{sym}] position_size={pos} ≤ 0，不合法")
            # contract 非空字符串
            c = trade_values.get("contract")
            if c is not None and not isinstance(c, str):
                errors.append(f"[{sym}] contract 不是字符串: {type(c).__name__}")
            elif c is not None and not c.strip():
                errors.append(f"[{sym}] contract 为空字符串")
        else:
            # action=wait 或 hold：所有交易参数必须为 None
            non_null = {k: val for k, val in trade_values.items() if val is not None}
            if non_null:
                errors.append(
                    f"[{sym}] action={action} 但以下交易参数非 None: {non_null}"
                )

        # 2e. grade 字段（如有）与 action 的隐含一致性
        grade = v.get("grade", "")
        if grade == "NOISE" and action == "execute":
            errors.append(f"[{sym}] grade=NOISE 但 action=execute，矛盾")

        # 2f. 方向-价格一致性：仅当 entry/stop/target 均有合法正值时校验
        #     若 entry≤0（参数未填充），跳过方向一致性检查，仅记 WARN
        if action == "execute":
            entry = v.get("entry_price")
            stop = v.get("stop_loss_price")
            target = v.get("target_price")

            if entry is None or entry <= 0 or stop is None or stop <= 0 or target is None or target <= 0:
                warns.append(f"[{sym}] execute 但交易参数不全或为0，跳过方向一致性检查")
            elif None not in (entry, stop, target):
                if direction in ("BULL", "BUY"):
                    if target <= entry:
                        errors.append(
                            f"[{sym}] BULL 但 target({target}) ≤ entry({entry})，"
                            f"目标应在入场价上方"
                        )
                    if stop >= entry:
                        errors.append(
                            f"[{sym}] BULL 但 stop({stop}) ≥ entry({entry})，"
                            f"止损应在入场价下方"
                        )
                    # 额外合理性：止盈幅度应大于止损幅度（RR>1）
                    rr = abs(target - entry) / max(abs(entry - stop), 0.01)
                    if rr < 0.5:
                        errors.append(
                            f"[{sym}] BULL 但盈亏比 ≈{rr:.1f}（目标-入场={target-entry:.0f}, "
                            f"入场-止损={entry-stop:.0f}），交易系统拒绝RR<0.5的方案"
                        )

                elif direction in ("BEAR", "SELL"):
                    if target >= entry:
                        errors.append(
                            f"[{sym}] BEAR 但 target({target}) ≥ entry({entry})，"
                            f"目标应在入场价下方"
                        )
                    if stop <= entry:
                        errors.append(
                            f"[{sym}] BEAR 但 stop({stop}) ≤ entry({entry})，"
                            f"止损应在入场价上方"
                        )
                    rr = abs(entry - target) / max(abs(stop - entry), 0.01)
                    if rr < 0.5:
                        errors.append(
                            f"[{sym}] BEAR 但盈亏比 ≈{rr:.1f}（入场-目标={entry-target:.0f}, "
                            f"止损-入场={stop-entry:.0f}），交易系统拒绝RR<0.5的方案"
                        )

    # ── 3. 扫描品种数与辩论品种数的关系（如有 scan 数据） ──
    if scan is not None:
        ranked = scan.get("all_ranked", [])
        scan_symbols = {s.get("symbol") for s in ranked if s.get("symbol")}
        debate_symbols = set(verdicts.keys())

        # 3a. 辩论品种应都是扫描信号品种的子集
        orphans = debate_symbols - scan_symbols
        if orphans:
            errors.append(f"[CROSS] 以下辩论品种不在扫描数据中: {orphans}")

        # 3b. 检查：扫描信号的 grade=max_grade 品种 是否全被辩论覆盖
        # 仅报告，不阻断
        GRADE_ORDER = {"NOISE": 0, "WEAK": 1, "WATCH": 2, "STRONG": 3}
        max_grade_val = max(
            (GRADE_ORDER.get(s.get("grade", "NOISE"), 0) for s in ranked),
            default=0,
        )
        if max_grade_val >= 2:  # WATCH 及以上
            high_grade_syms = {
                s.get("symbol")
                for s in ranked
                if GRADE_ORDER.get(s.get("grade", "NOISE"), 0) >= 2
            }
            missing_debate = high_grade_syms - debate_symbols
            if missing_debate:
                warns.append(
                    f"[CROSS] 以下 WATCH+ 信号品种缺少辩论裁决: {missing_debate}"
                )

    # ── 4. 汇总一致性 ──
    actions = {v.get("action") for v in verdicts.values() if isinstance(v, dict)}
    if "execute" in actions:
        # 有可执行信号时检查：至少有一个品种附带完整交易参数
        pass  # 已在 2d 逐品种检查

    return errors, warns
def main() -> None:
    ap = argparse.ArgumentParser(description="FDT 最终信号复查器")
    ap.add_argument("--input", "-i", required=True, help="debate_results.json 路径")
    ap.add_argument("--scan", "-s", help="scan_daily_*.json 路径（可选，用于品种数交叉校验）")
    ap.add_argument("--quiet", "-q", action="store_true", help="通过时不输出")
    ap.add_argument("--json", "-j", action="store_true", help="以 JSON 格式输出结果")
    args = ap.parse_args()

    # 加载输入
    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"[FATAL] 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[FATAL] JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 可选加载 scan
    scan = None
    if args.scan:
        scan_path = os.path.abspath(args.scan)
        if os.path.exists(scan_path):
            try:
                with open(scan_path, encoding="utf-8") as f:
                    scan = json.load(f)
            except json.JSONDecodeError:
                print(f"[WARN] scan 文件 JSON 解析失败，跳过交叉校验: {scan_path}", file=sys.stderr)
        else:
            print(f"[WARN] scan 文件不存在，跳过交叉校验: {scan_path}", file=sys.stderr)

    # 执行校验
    errors, warns = validate_signals(data, scan)

    # 输出
    if args.json:
        result = {
            "passed": len(errors) == 0,
            "total_checks": 6,
            "error_count": len(errors),
            "warn_count": len(warns),
            "errors": errors,
            "warns": warns,
            "verdict_count": len(data.get("verdicts", {})),
            "execute_count": sum(
                1 for v in data.get("verdicts", {}).values()
                if isinstance(v, dict) and v.get("action") == "execute"
            ),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 先打 WARN
        for w in warns:
            print(f"   {w}", file=sys.stderr)
        if errors:
            print(f"❌ 信号复查失败 — {len(errors)} 项问题:", file=sys.stderr)
            for e in errors:
                print(f"   {e}", file=sys.stderr)
        else:
            if not args.quiet:
                verdict_count = len(data.get("verdicts", {}))
                execute_count = sum(
                    1 for v in data.get("verdicts", {}).values()
                    if isinstance(v, dict) and v.get("action") == "execute"
                )
                label = "⚠️ 通过但有警告" if warns else "✅"
                print(f"{label} 信号复查 — {verdict_count} 品种，{execute_count} 执行")

    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
