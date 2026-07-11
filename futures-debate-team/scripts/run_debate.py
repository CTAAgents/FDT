# -*- coding: utf-8 -*-
"""
FDT 辩论主动驱动层 (B 项优化 · 2026-07-11)
==========================================

设计意图：
- 把每轮手工的多步易碎操作（识别触发品种 / 手写 spawn 提示 / 手写内联 Python 组装
  debate_results.json / 逐品种 extract_knowledge / 误用手写 HTML）收敛进**一个脚本**，
  消除"零胶水代码"红线被踩的问题。
- **不 spawn Agent**（spawn 是团队主管 WorkBuddy Agent 的固有职责，Python 也 spawn 不了
  子 Agent）。本脚本产出**标准化 spawn 计划 JSON**，主管按此计划 spawn。
- 提供 assemble / extract / report 子命令，复用既有 CLI（extract_knowledge.py、
  phase3_generate_report.py），不重复造轮子。

用法：
  # 1) 产出 spawn 计划（主管据此 spawn 各辩论 Agent）
  python scripts/run_debate.py plan \
      --scan 2026-07-11/scan_daily_1824_20260711.json \
      --workspace 2026-07-11

  # 2) 主管 spawn 完毕、各 p4/p5 文件就绪后，收口组装+萃取+报告
  python scripts/run_debate.py finalize \
      --scan 2026-07-11/scan_daily_1824_20260711.json \
      --workspace 2026-07-11

依赖：
  - 阈值单一真相源：skills/quant-daily/scripts/config/settings.py:DEBATE_ENTRY_MIN_ABS
    （经 importlib 按路径加载，不写死；FDT 根 config/settings.py 不存在，故走量化子技能配置）
  - 萃取：skills/futures-trading-analysis/scripts/extract_knowledge.py ingest --from
  - 报告：skills/futures-trading-analysis/scripts/phase3_generate_report.py --debate
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── FDT 根目录（本文件在 scripts/ 下）──
ROOT = Path(__file__).resolve().parent.parent
QUANT_DAILY = ROOT / "skills" / "quant-daily" / "scripts"
FTA_SCRIPTS = ROOT / "skills" / "futures-trading-analysis" / "scripts"


# ─────────────────────────────────────────────
# 阈值单一真相源（按路径加载，禁止写死 20）
# ─────────────────────────────────────────────
def load_debate_threshold() -> int:
    """从量化子技能 config/settings.py 读取 DEBATE_ENTRY_MIN_ABS（唯一真相源）。"""
    cand = QUANT_DAILY / "config" / "settings.py"
    if cand.exists():
        try:
            spec = importlib.util.spec_from_file_location("qd_settings", str(cand))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return int(getattr(mod, "DEBATE_ENTRY_MIN_ABS", 20))
        except Exception:
            pass
    return 20  # 仅文件缺失时兜底；正常路径不应命中


# ─────────────────────────────────────────────
# 数据基准（G 项：写入 debate_results.json 顶层）
# ─────────────────────────────────────────────
def derive_data_benchmark(scan: dict) -> str:
    """从扫描 JSON 派生的'数据基准'时间戳。

    优先取 _meta.klines_latest_date；无则取 generated_at；均无则用扫描文件 mtime。
    标注 收盘/盘中：16:00 后或 09:00-15:00 之间按时刻语义，简化处理为'收盘'若时刻≥15:00 否则'盘中'。
    """
    meta = scan.get("_meta", {}) or {}
    kl = meta.get("klines_latest_date") or scan.get("klines_latest_date")
    gen = scan.get("generated_at") or scan.get("scan_generated_at")
    base = kl or gen
    if not base:
        try:
            mtime = datetime.fromtimestamp((ROOT / "pyproject.toml").stat().st_mtime)
            base = mtime.strftime("%Y-%m-%d %H:%M")
        except Exception:
            base = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 标注收盘/盘中
    try:
        hh = int(str(base).split(" ")[-1].split(":")[0])
        suffix = "收盘" if hh >= 15 else "盘中"
    except Exception:
        suffix = "收盘"
    return f"{base} {suffix}"


# ─────────────────────────────────────────────
# 触发品种识别（信号检查闸门）
# ─────────────────────────────────────────────
def select_triggers(scan: dict, threshold: int) -> list:
    """|total| >= DEBATE_ENTRY_MIN_ABS 即进候选（grade 仅作优先级标签）。"""
    ranked = scan.get("all_ranked", [])
    cands = [s for s in ranked if abs(s.get("total", 0)) >= threshold]
    # 优先级：STRONG > WATCH > 其余
    order = {"STRONG": 0, "WATCH": 1, "WEAK": 2, "NOISE": 3}
    cands.sort(key=lambda s: (order.get(s.get("grade", "NOISE"), 9), -abs(s.get("total", 0))))
    return cands


# ─────────────────────────────────────────────
# 固定注入规则（ADX 角色反转 / WATCH 语义 / 置信度归一）
# 与 fdt-spawn-debate SKILL.md 铁律一致，集中于此单一来源
# ─────────────────────────────────────────────
def _adx_reversal_rule() -> str:
    return ("ADX角色反转：ADX低位(<20)视为趋势启动早期而非'无趋势不交易'；"
            "ADX高位(≥60)为过热警示；ADX不得作为致命伤，提及占比≤1/3。")


def build_spawn_plan(symbols: list, workspace: str, data_benchmark: str) -> dict:
    """产出标准化 spawn 计划 JSON（主管据此 spawn，spawn 本身仍是主管职责）。"""
    ws = Path(workspace)
    plan = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "data_benchmark": data_benchmark,
             "injected_rules": {
                 "adx_reversal": _adx_reversal_rule(),
                 "watch_semantics": "WATCH等级=监控观察信号，非直接触发；需结合辩论强度决定是否进候选。",
                 "confidence": "confidence由confidence_utils归一化，输出0-1数值或高/中/低标签均可，禁止任意裸字符串。",
             },
             "symbols": []}

    for s in symbols:
        sym = s.get("symbol")
        direction = s.get("direction", "neutral")      # bull / bear
        grade = s.get("grade", "")
        pro_side = "多头" if direction == "bull" else ("空头" if direction == "bear" else "中性")
        p4_z = ws / f"p4_zhengzhen_{sym}.json"
        p4_s = ws / f"p4_zhensi_{sym}.json"
        p5_j = ws / f"p5_judge_{sym}.json"
        p5_t = ws / f"p5_trading_plan_{sym}.json"
        p5_c = ws / f"p5_coherence_{sym}.json"
        p5_r = ws / f"p5_risk_review_{sym}.json"

        # 证真（正方 = 信号方向）
        zhengzhen_prompt = (
            f"你是证真(正方)辩手，论证品种 {sym} 的{direction}信号({grade})有效性。\n"
            f"{_adx_reversal_rule()}\n"
            f"数据基准: {data_benchmark}。\n"
            f"从研究员/链证源资料中提炼≥3条{direction}论据，每条附来源标注。\n"
            f"写完用 SendMessage(recipient='main') 通知，并把论据写入 {p4_z}（key_arguments 列表，每项含 claim/evidence/source）。"
        )
        # 慎思（反方）
        zhensi_prompt = (
            f"你是慎思(反方)辩手，质疑品种 {sym} 的{direction}信号({grade})可靠性。\n"
            f"{_adx_reversal_rule()}\n"
            f"数据基准: {data_benchmark}。\n"
            f"从研究员/链证源资料中提炼≥3条反向论据，每条附来源标注。\n"
            f"写完用 SendMessage(recipient='main') 通知，并把论据写入 {p4_s}（key_arguments 列表，每项含 claim/evidence/source）。"
        )
        # 闫判官
        judge_prompt = (
            f"你是闫判官，裁决品种 {sym}（方向信号 {direction}/{grade}）。\n"
            f"{_adx_reversal_rule()}\n"
            f"读取 {p4_z} 与 {p4_s}，主持交叉质询后输出裁决到 {p5_j}：\n"
            f"final_direction( bull/bear/neutral )、confidence(0-1数值或高/中/低)、reasoning、score_breakdown(6维0-100)。\n"
            f"禁止向其他 Agent 发消息，仅读文件。"
        )
        # 策执远
        plan_prompt = (
            f"你是策执远，基于 {p5_j} 裁决为 {sym} 制定可执行方案，写入 {p5_t}：\n"
            f"entry/stop_loss/target_1/target_2/position_pct/contract。\n"
            f"监控条件不以ADX为首要触发，价格突破+量确认排第一。"
        )
        # 一致性裁判（非阻断审计）
        coherence_prompt = (
            f"你是一致性裁判，审计 {sym} 裁决是否真正源于辩论论据（不重写论据）。\n"
            f"读取 {p4_z}/{p4_s}/{p5_j}，输出 coherence_score(0-100)+rationale 到 {p5_c}。"
        )
        # 风控明
        risk_prompt = (
            f"你是风控明，审核 {sym} 方案 {p5_t}。\n"
            f"ADX风险标记降级为辅助参考，不独立构成否决理由。\n"
            f"输出 risk_level(高/中/低)/veto/risk_items 到 {p5_r}。"
        )

        plan["symbols"].append({
            "symbol": sym, "direction": direction, "grade": grade,
            "files": {
                "p4_zhengzhen": str(p4_z), "p4_zhensi": str(p4_s),
                "p5_judge": str(p5_j), "p5_trading_plan": str(p5_t),
                "p5_coherence": str(p5_c), "p5_risk_review": str(p5_r),
            },
            "spawn_prompts": {
                "zhengzhen": zhengzhen_prompt, "zhensi": zhensi_prompt,
                "judge": judge_prompt, "trading_plan": plan_prompt,
                "coherence": coherence_prompt, "risk": risk_prompt,
            },
        })
    return plan


# ─────────────────────────────────────────────
# 文件就绪轮询（S04 标准实现）
# ─────────────────────────────────────────────
def poll_file_ready(path: str, timeout: int = 900, stable_seconds: int = 5) -> bool:
    import time
    deadline = time.time() + timeout
    last_size = -1
    stable_since = None
    while time.time() < deadline:
        if os.path.exists(path):
            sz = os.path.getsize(path)
            if sz > 0:
                if sz == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stable_seconds:
                        return True
                else:
                    last_size = sz
                    stable_since = None
        time.sleep(15)
    return False


# ─────────────────────────────────────────────
# 组装 debate_results.json（per_pid，含 data_benchmark）
# ─────────────────────────────────────────────
def assemble(scan: dict, workspace: str, data_benchmark: str) -> dict:
    ws = Path(workspace)
    verdicts = {}
    plan = build_spawn_plan(select_triggers(scan, load_debate_threshold()), workspace, data_benchmark)
    for item in plan["symbols"]:
        sym = item["symbol"]
        f = item["files"]
        try:
            p4z = json.load(open(f["p4_zhengzhen"], encoding="utf-8"))
            p4s = json.load(open(f["p4_zhensi"], encoding="utf-8"))
            p5j = json.load(open(f["p5_judge"], encoding="utf-8"))
            p5t = json.load(open(f["p5_trading_plan"], encoding="utf-8"))
            p5r = json.load(open(f["p5_risk_review"], encoding="utf-8"))
        except FileNotFoundError as e:
            print(f"  ⚠️ {sym} 缺文件: {e.filename}，跳过组装")
            continue

        jv = p5j.get("judge_verdict", p5j)
        verdicts[sym] = {
            "symbol": sym,
            "name": sym,
            "direction": str(jv.get("final_direction", p5j.get("direction", ""))).upper(),
            "verdict": str(jv.get("final_direction", p5j.get("direction", ""))).upper(),
            "confidence": jv.get("confidence", p5j.get("confidence")),
            "reasoning": jv.get("reasoning", p5j.get("reasoning")),
            "signal_type": scan_signal_type(scan, sym),
            "grade": item["grade"],
            "total_score": next((s.get("total") for s in scan.get("all_ranked", []) if s.get("symbol") == sym), None),
            "winner": jv.get("winner", p5j.get("winner", "")),
            "price": p5t.get("entry"),
            "atr": scan_atr(scan, sym),
            "adx": scan_adx(scan, sym),
            "rsi": scan_rsi(scan, sym),
            "cci": scan_cci(scan, sym),
            "chain": p5t.get("chain") or scan_chain(scan, sym),
            "entry_price": p5t.get("entry"),
            "target_price": p5t.get("target_1"),
            "stop_loss_price": p5t.get("stop_loss"),
            "position_size": p5t.get("position_pct"),
            "contract": p5t.get("contract"),
            "judge_verdict": {
                "final_direction": jv.get("final_direction"),
                "confidence": jv.get("confidence"),
                "reasoning": jv.get("reasoning"),
                "key_observation": jv.get("key_observation"),
                "score_breakdown": jv.get("score_breakdown"),
            },
            "bull_args": [f"{sym}-pro{i+1}: {a.get('claim', a.get('point', ''))}"
                         for i, a in enumerate(p4z.get("key_arguments", []))],
            "bear_args": [f"{sym}-con{i+1}: {a.get('claim', a.get('point', ''))}"
                         for i, a in enumerate(p4s.get("key_arguments", []))],
            "trading_plan": p5t,
            "risk_review": p5r,
        }

    out = {
        "round_id": f"FDT_{datetime.now().strftime('%Y%m%d')}_auto",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_benchmark": data_benchmark,
        "signal_source": scan.get("signal_source", ""),
        "scan_generated_at": scan.get("generated_at", scan.get("scan_generated_at", "")),
        "verdicts": verdicts,
    }
    out_path = ws / "debate_results.json"
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2, default=str)
    print(f"✅ 组装 debate_results.json: {out_path}（{len(verdicts)} 品种）")
    return out


def _scan_row(scan, sym):
    return next((s for s in scan.get("all_ranked", []) if s.get("symbol") == sym), {})


def scan_signal_type(scan, sym):
    return _scan_row(scan, sym).get("signal_type", "channel_breakout")


def scan_atr(scan, sym):
    return _scan_row(scan, sym).get("atr")


def scan_adx(scan, sym):
    return _scan_row(scan, sym).get("adx")


def scan_rsi(scan, sym):
    return _scan_row(scan, sym).get("rsi")


def scan_cci(scan, sym):
    return _scan_row(scan, sym).get("cci")


def scan_chain(scan, sym):
    return _scan_row(scan, sym).get("chain")


# ─────────────────────────────────────────────
# 萃取（D 项：批量 --from）
# ─────────────────────────────────────────────
def run_extract(workspace: str) -> int:
    dr = Path(workspace) / "debate_results.json"
    if not dr.exists():
        print(f"✗ 未找到 {dr}")
        return 1
    cmd = [sys.executable,
            str(FTA_SCRIPTS / "extract_knowledge.py"), "ingest_from",
            "--from", str(dr)]
    print(f"🔍 知识萃取（批量，conf<0.6 自动跳过）: {' '.join(cmd)}")
    return subprocess.call(cmd)


# ─────────────────────────────────────────────
# 报告（G 项：phase3 --debate，数据基准走 debate_results.data_benchmark）
# ─────────────────────────────────────────────
def run_report(workspace: str) -> int:
    ws = Path(workspace)
    cmd = [sys.executable,
            str(FTA_SCRIPTS / "phase3_generate_report.py"),
            "--debate", str(ws / "debate_results.json"),
            "--workspace", str(ws)]
    print(f"📊 生成辩论报告: {' '.join(cmd)}")
    return subprocess.call(cmd)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="FDT 辩论主动驱动层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="产出标准化 spawn 计划 JSON")
    p_plan.add_argument("--scan", required=True)
    p_plan.add_argument("--workspace", required=True)

    p_fin = sub.add_parser("finalize", help="组装+萃取+报告（spawn 后收口）")
    p_fin.add_argument("--scan", required=True)
    p_fin.add_argument("--workspace", required=True)

    p_asm = sub.add_parser("assemble", help="仅组装 debate_results.json")
    p_asm.add_argument("--scan", required=True)
    p_asm.add_argument("--workspace", required=True)

    p_ext = sub.add_parser("extract", help="仅批量萃取")
    p_ext.add_argument("--workspace", required=True)

    p_rep = sub.add_parser("report", help="仅生成报告")
    p_rep.add_argument("--workspace", required=True)

    args = ap.parse_args()

    scan = json.load(open(args.scan, encoding="utf-8"))
    threshold = load_debate_threshold()
    data_benchmark = derive_data_benchmark(scan)
    ws = Path(args.workspace)

    if args.cmd == "plan":
        triggers = select_triggers(scan, threshold)
        print(f"🔔 触发品种（|total|≥{threshold}）: {[t['symbol'] for t in triggers]}")
        plan = build_spawn_plan(triggers, str(ws), data_benchmark)
        out = ws / f"spawn_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"📋 spawn 计划: {out}")

    elif args.cmd == "assemble":
        assemble(scan, str(ws), data_benchmark)

    elif args.cmd == "extract":
        run_extract(str(ws))

    elif args.cmd == "report":
        run_report(str(ws))

    elif args.cmd == "finalize":
        assemble(scan, str(ws), data_benchmark)
        run_extract(str(ws))
        run_report(str(ws))


if __name__ == "__main__":
    main()
