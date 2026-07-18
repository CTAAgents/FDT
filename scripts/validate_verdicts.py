#!/usr/bin/env python3
"""
裁决验证器 — 用后续行情检验历史裁决方向正确性。
在每次新辩论启动前运行，将验证结果反馈给闫判官。

用法:
  python validate_verdicts.py [--t1] [--t3] [--report]

  --t1     验证T+1日方向（默认）
  --t3     验证T+3日方向
  --report 仅生成汇总报告（不拉数据）

输出:
  - execution_followup.json (更新 validated=True + validation_results)
  - validation_report.html (可视化报告)
"""

import json
import sys
import os
import math
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


# ─── 成本模型（成本感知 PnL）───────────────────────────
# CLQT (arXiv:2606.29771) 核心教训: 回报≠能力, 不建模交易成本会系统性高估策略可交易性。
# 此处对每条裁决扣除往返交易成本(手续费+滑点), 计算净PnL, 暴露成本盲区。
# 默认 2 bps 往返(保守估计, 覆盖主流活跃品种); 可通过 --cost-bps 调整。
# 注: 成本对所有裁决为常量扣除, 不改变 Spearman 秩相关(D2 Acuity 不受影响),
#      但会改变 near-zero 输出的 correct 判定与均盈读数。
COST_BPS = 2.0           # 往返交易成本(基点)。1 bp = 0.01%
DEFAULT_COST_BPS = 2.0


# ─── 数据获取 — 统一经由 quant-daily skill ──────────────
# 规则铁律: 所有期货数据必须经由 quant-daily skill 获取（futures-debate-team 内置数据模块）。
# quant-daily 的 MultiSourceAdapter 内部已完成 tdx_local → tqsdk → 东方财富 三层降级，
# 因此本脚本只调用 quant-daily 单一数据源，不在外部重复直连。

_ADAPTER = None
_ADAPTER_AVAILABLE = True


def _qdaily_scripts_dir() -> str:
    """定位 quant-daily 的 scripts 目录（专家团内置；回退用户级 skill）"""
    here = Path(__file__).resolve().parent          # .../futures-debate-team/scripts
    candidate = here.parent / "skills" / "quant-daily" / "scripts"
    if candidate.exists():
        return str(candidate)
    return str(Path.home() / ".workbuddy" / "skills" / "quant-daily" / "scripts")


def _get_qdaily_adapter():
    """懒加载 quant-daily MultiSourceAdapter（单例）"""
    global _ADAPTER, _ADAPTER_AVAILABLE
    if _ADAPTER is not None:
        return _ADAPTER
    if not _ADAPTER_AVAILABLE:
        return None
    try:
        scripts_dir = _qdaily_scripts_dir()
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        # FDT 根目录优先，确保 futures_data_core 指向 FDT 内部副本
        fdt_root = str(Path(scripts_dir).parent.parent.parent)
        if fdt_root not in sys.path:
            sys.path.insert(0, fdt_root)
        from data.multi_source_adapter import MultiSourceAdapter
        _ADAPTER = MultiSourceAdapter()
        return _ADAPTER
    except Exception as e:
        print(f"[validate_verdicts] quant-daily adapter 加载失败: {e}")
        _ADAPTER_AVAILABLE = False
        return None


def _variety_from_symbol(symbol: str) -> str:
    """CU.SHF -> CU（quant-daily 用品种代码，不带交易所后缀；数据中小写亦转大写）"""
    return (symbol or "").split(".")[0].upper().strip()


def _norm_date(s: str) -> str:
    """将任意日期字符串归一为 YYYYMMDD（8位数字），用于K线入场对齐"""
    digits = "".join(ch for ch in (s or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


# ─── 数据获取 — 统一经由 quant-daily 的 MultiSourceAdapter ──

def fetch_bar_sequence_qdaily(symbol: str, count: int = 10) -> list | None:
    """通过 quant-daily MultiSourceAdapter 获取 K 线序列（统一数据源）

    quant-daily 内部已做 tdx_local → tqsdk → 东方财富 三层降级，
    返回最近 days 根日K线。此处返回全部已获取K线（按日期升序），
    由调用方按裁决日做入场对齐与窗口截取。
    """
    adapter = _get_qdaily_adapter()
    if adapter is None:
        return None
    variety = _variety_from_symbol(symbol)
    try:
        # days 覆盖最近 N 天；取缓冲天数确保裁决日之后有足够K线
        res = adapter.get_kline(variety, days=max(count + 5, 20), period="daily")
        if not res or not res.get("success"):
            return None
        data = res.get("data", [])
        if not data:
            return None
        bars = []
        for d in data:
            bars.append({
                "date": str(d.get("date", "")),
                "open": float(d.get("open", 0) or 0),
                "high": float(d.get("high", 0) or 0),
                "low": float(d.get("low", 0) or 0),
                "close": float(d.get("close", 0) or 0),
            })
        bars.sort(key=lambda b: b["date"])
        return bars
    except Exception as e:
        print(f"[validate_verdicts] quant-daily get_kline({symbol}) 失败: {e}")
        return None


def get_bar_sequence(symbol: str, count: int = 10) -> list:
    """获取品种 K 线序列（统一经由 quant-daily skill，内部已含三层降级）

    返回最近 count 根日K线（按日期升序），供 validate_round 做入场对齐。
    """
    bars = fetch_bar_sequence_qdaily(symbol, count)
    if bars:
        for b in bars:
            b["source"] = "quant-daily"
        return bars[-count:] if len(bars) >= count else bars
    return []


# ─── 验证逻辑 — 重构：用K线序列做stop/target触发检测 ──

def validate_verdict_intraday(verdict: dict, bars: list) -> dict:
    """用裁决后的K线序列验证真实实现盈亏（含跳空和止损触发）。

    P0修复: 替代原 validate_verdict() 的单点close判方向逻辑。
    用 bar.high/low 判断是否触及止损/目标价, 而非仅看收盘价方向。
    """
    direction = verdict["direction"]
    entry = verdict["entry_price"]
    stop = verdict["stop_loss"]
    target1 = verdict.get("target1", verdict.get("target_price", 0))
    target2 = verdict.get("target2", 0)

    if entry <= 0 or not bars:
        return {
            "correct": None, "realized_pnl_pct": 0, "reason": "价格数据缺失",
            "hit_stop": False, "hit_target1": False, "hit_target2": False,
            "gap_stop": False,
        }

    # 扫描所有K线, 检查stop/target触发
    hit_stop = False
    hit_target1 = False
    hit_target2 = False
    gap_stop = False
    first_bar = bars[0]

    # 场景1: 跳空扫损（夜盘跳空越过止损位）
    if direction == "bear":
        gap_open = first_bar["open"] - entry
        stop_dist = abs(stop - entry)
        if stop_dist > 0 and gap_open >= stop_dist * 0.8:
            gap_stop = True
            hit_stop = True
    else:  # bull
        gap_open = entry - first_bar["open"]
        stop_dist = abs(stop - entry)
        if stop_dist > 0 and gap_open >= stop_dist * 0.8:
            gap_stop = True
            hit_stop = True

    # 场景2: 逐K线检测stop/target触发（含gap已触发的情况）
    for bar in bars:
        if hit_stop and hit_target1:
            break  # 两个条件都已确定, 不需要再扫

        if direction == "bear":
            # 空单: 止损=上破high, 止盈=下破low
            if not hit_stop and bar["high"] >= stop:
                hit_stop = True
            if not hit_target1 and target1 > 0 and bar["low"] <= target1:
                hit_target1 = True
            if not hit_target2 and target2 > 0 and bar["low"] <= target2:
                hit_target2 = True
        else:  # bull
            # 多单: 止损=下破low, 止盈=上破high
            if not hit_stop and bar["low"] <= stop:
                hit_stop = True
            if not hit_target1 and target1 > 0 and bar["high"] >= target1:
                hit_target1 = True
            if not hit_target2 and target2 > 0 and bar["high"] >= target2:
                hit_target2 = True

    # 计算实现盈亏
    if hit_stop:
        # 被止损: 亏损 = 止损距
        realized = -abs(stop - entry) / entry
    elif hit_target2:
        # T2止盈: T1减仓30% + T2减仓50% (剩余趋势跟踪假设T2出)
        t1_pnl = abs(target1 - entry) / entry * 0.3 if target1 > 0 else 0
        t2_pnl = abs(target2 - entry) / entry * 0.5 if target2 > 0 else abs(target1 - entry) / entry * 0.5
        realized = t1_pnl + t2_pnl
    elif hit_target1:
        realized = abs(target1 - entry) / entry
    else:
        # 未触及任何边界: 用最后收盘价
        last_close = bars[-1]["close"]
        change = (last_close - entry) / entry
        realized = -change if direction == "bear" else change

    realized_pnl_pct = round(realized * 100, 2)

    # 成本感知: 扣除往返交易成本, 计算净PnL
    cost_pct = COST_BPS / 100.0            # COST_BPS(bp) → 百分比
    net_realized_pct = round(realized * 100 - cost_pct, 2)

    # correct     = 毛方向盈亏为正（方向判断正确性）
    # correct_net = 扣费后实际可交易盈亏为正（可交易性 / 成本敏感性）
    correct = realized > 0
    correct_net = (realized * 100 - cost_pct) > 0

    return {
        "correct": correct,
        "correct_net": correct_net,
        "realized_pnl_pct": realized_pnl_pct,
        "net_pnl_pct": net_realized_pct,
        "cost_bps": COST_BPS,
        "hit_stop": hit_stop,
        "hit_target1": hit_target1,
        "hit_target2": hit_target2,
        "gap_stop": gap_stop,
        "reason": _build_validation_reason(direction, entry, stop, target1,
                                            hit_stop, hit_target1, hit_target2, gap_stop),
    }


def _build_validation_reason(direction, entry, stop, target1,
                              hit_stop, hit_target1, hit_target2, gap_stop):
    parts = []
    if gap_stop:
        parts.append("⚠️跳空扫损")
    if hit_stop:
        parts.append(f"触止损@ {stop}")
    if hit_target1:
        parts.append(f"达T1@ {target1}")
    if hit_target2:
        parts.append(f"达T2(预)@{target1}")
    if not (hit_stop or hit_target1 or hit_target2):
        parts.append("边界未触")
    return " | ".join(parts) if parts else "无数据"


# ─── 验证逻辑 ───────────────────────────────────────────

# ─── 旧版验证保留为降级路径 ─────────────────────────────

def validate_verdict_fallback(verdict: dict, current_price: float) -> dict:
    """旧版验证: 单点close判方向（无止损检测）。仅当拉K线失败时使用。"""
    direction = verdict["direction"]
    entry = verdict["entry_price"]
    if entry <= 0 or current_price <= 0:
        return {"correct": None, "change_pct": 0, "reason": "价格数据缺失",
                "hit_stop": False, "hit_target1": False, "gap_stop": False,
                "realized_pnl_pct": 0}
    change_pct = round((current_price - entry) / entry * 100, 2)
    if direction == "bear":
        correct = current_price < entry
    elif direction == "bull":
        correct = current_price > entry
    else:
        correct = None
    pnl_pct = round(-change_pct if direction == "bear" else change_pct, 2)
    cost_pct = COST_BPS / 100.0
    net_pnl_pct = round(pnl_pct - cost_pct, 2)
    return {
        "correct": correct, "correct_net": net_pnl_pct > 0, "change_pct": change_pct,
        "realized_pnl_pct": pnl_pct,
        "net_pnl_pct": net_pnl_pct,
        "cost_bps": COST_BPS,
        "hit_stop": False, "hit_target1": False, "hit_target2": False,
        "gap_stop": False,
        "reason": "旧版验证(无止损检测)",
    }


def validate_round(record: dict, bar_cache: dict = None) -> dict:
    """验证一轮辩论的全部裁决 — 用K线序列检测stop/target触发"""
    if bar_cache is None:
        bar_cache = {}

    verdicts = record["verdicts"]
    results = []
    errors = []
    bar_count = 45  # 拉足够长窗口，覆盖裁决日之后，供入场对齐
    entry_date = _norm_date(record.get("generated_at", ""))  # 裁决日，用于入场对齐

    for v in verdicts:
        sym = v["symbol"]
        if sym not in bar_cache:
            bars = get_bar_sequence(sym, bar_count)
            # 入场日对齐: 仅保留 >= 裁决日的K线，避免用入场前历史误触止损
            if entry_date and bars:
                bars = [b for b in bars if _norm_date(b["date"]) >= entry_date]
            bar_cache[sym] = bars

        bars = bar_cache[sym]

        if not bars:
            errors.append(f"{sym}: 无法获取K线数据")
            results.append({
                "symbol": sym, "direction": v["direction"],
                "correct": None, "realized_pnl_pct": 0,
                "hit_stop": False, "hit_target1": False, "hit_target2": False,
                "gap_stop": False,
                "error": "无K线数据",
            })
        else:
            vr = validate_verdict_intraday(v, bars)
            vr["symbol"] = sym
            vr["data_source"] = bars[0].get("source", "未知")
            results.append(vr)

    total = len(results)
    correct = sum(1 for r in results if r["correct"] is True)
    wrong = sum(1 for r in results if r["correct"] is False)
    unknown = total - correct - wrong
    accuracy = round(correct / (correct + wrong) * 100, 1) if (correct + wrong) > 0 else 0
    validatable = (correct + wrong) > 0
    stop_hit = sum(1 for r in results if r.get("hit_stop"))
    target_hit = sum(1 for r in results if r.get("hit_target1"))
    gap_hit = sum(1 for r in results if r.get("gap_stop"))

    # 净指标（成本感知）
    net_correct = sum(1 for r in results if r.get("correct_net") is True)
    net_wrong = sum(1 for r in results if r.get("correct_net") is False)
    net_accuracy = round(net_correct / (net_correct + net_wrong) * 100, 1) if (net_correct + net_wrong) > 0 else 0
    net_vals = [r.get("net_pnl_pct", 0) for r in results if r.get("net_pnl_pct") is not None]
    net_avg_pnl = round(sum(net_vals) / max(len(net_vals), 1), 2)

    return {
        "validated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cost_bps": COST_BPS,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "accuracy": accuracy,
        "validatable": validatable,
        "net_correct": net_correct,
        "net_wrong": net_wrong,
        "net_accuracy": net_accuracy,
        "net_avg_pnl_pct": net_avg_pnl,
        "stop_hit_count": stop_hit,
        "target_hit_count": target_hit,
        "gap_stop_count": gap_hit,
        "avg_pnl_pct": round(
            sum(r["realized_pnl_pct"] for r in results if r["realized_pnl_pct"] != 0)
            / max(sum(1 for r in results if r["realized_pnl_pct"] != 0), 1), 2),
        "results": results,
        "errors": errors,
    }


# ─── 分组统计 ───────────────────────────────────────────

def save_feedback_entries(results: list, verdicts: list, followup_dir: str) -> None:
    """将验证结果写为 risk_engine.build_feedback_entry 格式。

    对接风险引擎的反馈闭环:
    - aggregate_feedback() 分析假破 vs 实破统计
    - 数据源: 验证层检测到的 stop/target 触发
    """
    entries = []
    for i, r in enumerate(results):
        if r.get("correct") is None:
            continue
        v = verdicts[i] if i < len(verdicts) else {}
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": r["symbol"],
            "anchor_price": v.get("stop_loss", 0),
            "anchor_source": "stop_loss_from_verdict",
            "stop_hit": r.get("hit_stop", False),
            "hit_scenario": _build_hit_scenario(r),
            "outcome": _build_outcome(r),
        }
        entries.append(entry)

    # 追加到 feedback_entries.json（留存的累计文件）
    feedback_path = os.path.join(followup_dir, "feedback_entries.json")
    existing = []
    if os.path.exists(feedback_path):
        try:
            with open(feedback_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = []
    existing.extend(entries)
    with open(feedback_path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"  反馈条目: {len(entries)} 条追加至 {feedback_path} (累计{len(existing)}条)")


def _build_hit_scenario(r: dict) -> str:
    """构建 hit_scenario 描述（匹配 risk_engine 格式）"""
    parts = []
    if r.get("gap_stop"):
        parts.append("跳空扫损")
    if r.get("hit_stop"):
        parts.append("price_stop_hit")
    if r.get("hit_target1"):
        parts.append("target1_hit")
    if r.get("hit_target2"):
        parts.append("target2_hit")
    if not parts:
        parts.append("无触发")
    return " | ".join(parts)


def _build_outcome(r: dict) -> str:
    """基于实现盈亏构建 outcome 标签"""
    pnl = r.get("realized_pnl_pct", 0)
    if r.get("hit_stop"):
        return "扫损出局" if pnl < 0 else ("扫损后反弹" if r.get("gap_stop") else "止损合理")
    if r.get("hit_target1"):
        return "达标止盈" if pnl > 0 else "扫损出局"
    return "持仓未触边界"

def compute_group_stats(all_records: list) -> dict:
    """对所有已验证记录做分组统计"""
    by_confidence = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0, "stop_hit": 0})
    by_direction = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0, "stop_hit": 0})
    by_chain = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0, "stop_hit": 0})
    by_adx_range = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0, "stop_hit": 0})

    for record in all_records:
        if not record.get("validated"):
            continue
        vr = record.get("validation_results", {})
        if not vr:
            continue

        verdicts = record["verdicts"]
        results = vr.get("results", [])

        for i, v in enumerate(verdicts):
            if i >= len(results):
                continue
            r = results[i]
            if r.get("correct") is None:
                continue

            conf = v.get("confidence", "中")
            direction = v.get("direction", "neutral")
            chain = v.get("chain", "其他")
            adx = v.get("adx", 0)

            by_confidence[conf]["total"] += 1
            by_direction[direction]["total"] += 1
            by_chain[chain]["total"] += 1

            if adx >= 70:
                adx_range = "ADX≥70"
            elif adx >= 50:
                adx_range = "50≤ADX<70"
            elif adx >= 30:
                adx_range = "30≤ADX<50"
            else:
                adx_range = "ADX<30"
            by_adx_range[adx_range]["total"] += 1

            if r["correct"]:
                by_confidence[conf]["correct"] += 1
                by_direction[direction]["correct"] += 1
                by_chain[chain]["correct"] += 1
                by_adx_range[adx_range]["correct"] += 1

            if r.get("hit_stop"):
                by_confidence[conf]["stop_hit"] += 1
                by_direction[direction]["stop_hit"] += 1
                by_chain[chain]["stop_hit"] += 1
                by_adx_range[adx_range]["stop_hit"] += 1

            by_confidence[conf]["pnl_sum"] += r.get("realized_pnl_pct", 0)
            by_direction[direction]["pnl_sum"] += r.get("realized_pnl_pct", 0)
            by_chain[chain]["pnl_sum"] += r.get("realized_pnl_pct", 0)
            by_adx_range[adx_range]["pnl_sum"] += r.get("realized_pnl_pct", 0)
            by_confidence[conf]["net_pnl_sum"] += r.get("net_pnl_pct", 0)
            by_direction[direction]["net_pnl_sum"] += r.get("net_pnl_pct", 0)
            by_chain[chain]["net_pnl_sum"] += r.get("net_pnl_pct", 0)
            by_adx_range[adx_range]["net_pnl_sum"] += r.get("net_pnl_pct", 0)

    def _format(stats):
        result = {}
        for key, s in stats.items():
            result[key] = {
                "total": s["total"],
                "correct": s["correct"],
                "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
                "avg_pnl": round(s["pnl_sum"] / s["total"], 2) if s["total"] > 0 else 0,
                "net_avg_pnl": round(s["net_pnl_sum"] / s["total"], 2) if s["total"] > 0 else 0,
                "stop_hit_rate": round(s["stop_hit"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
            }
        return result

    return {
        "by_confidence": _format(by_confidence),
        "by_direction": _format(by_direction),
        "by_chain": _format(by_chain),
        "by_adx_range": _format(by_adx_range),
    }


# ─── 主程序 ───────────────────────────────────────────

def main() -> None:
    global COST_BPS
    import argparse
    parser = argparse.ArgumentParser(description="裁决验证器（成本感知）")
    parser.add_argument("--t1", action="store_true", help="验证T+1日")
    parser.add_argument("--t3", action="store_true", help="验证T+3日")
    parser.add_argument("--report", action="store_true", help="仅生成汇总报告")
    parser.add_argument("--force", action="store_true", help="强制重验已验证记录（如数据源修复后）")
    parser.add_argument("--cost-bps", type=float, default=COST_BPS,
                        help=f"往返交易成本(基点), 默认 {DEFAULT_COST_BPS}bp")
    parser.add_argument("--followup", default=None, help="execution_followup.json路径")
    args = parser.parse_args()

    COST_BPS = args.cost_bps

    if args.followup is None:
        script_dir = Path(__file__).parent.parent
        args.followup = str(script_dir / "memory" / "execution_followup.json")

    with open(args.followup, 'r', encoding='utf-8') as f:
        followup = json.load(f)

    if not followup["records"]:
        print("⚠️ 无历史裁决记录，跳过验证")
        return

    updated_count = 0
    for record in followup["records"]:
        if record.get("validated") and not args.force:
            continue

        print(f"\n🔍 验证轮次: {record['round_id']} ({record['generated_at']})")
        print(f"   品种数: {record['total_verdicts']}")

        if not args.report:
            vr = validate_round(record)
            record["validated"] = True
            record["validation_results"] = vr
            updated_count += 1

            print(f"   准确率(毛): {vr['accuracy']}% ({vr['correct']}/{vr['total']}正确)")
            print(f"   准确率(净, {vr['cost_bps']}bp成本): {vr['net_accuracy']}% ({vr['net_correct']}/{vr['total']}正确)")
            print(f"   止损触发: {vr['stop_hit_count']}/{vr['total']} ({vr['gap_stop_count']}跳空扫损)")
            print(f"   止盈达标: {vr['target_hit_count']}/{vr['total']}")
            print(f"   均实现盈亏(毛): {vr['avg_pnl_pct']:+.2f}%  | (净): {vr['net_avg_pnl_pct']:+.2f}%")
            if vr["errors"]:
                print(f"   错误: {', '.join(vr['errors'])}")

            # 写反馈条目（对接 risk_engine 反馈闭环）
            followup_dir = str(Path(args.followup).parent)
            save_feedback_entries(vr.get("results", []),
                                  record.get("verdicts", []),
                                  followup_dir)

    if updated_count > 0:
        with open(args.followup, 'w', encoding='utf-8') as f:
            json.dump(followup, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已验证 {updated_count} 轮裁决，保存至 {args.followup}")

    # 汇总统计
    stats = compute_group_stats(followup["records"])
    print("\n" + "="*60)
    print("📊 汇总统计")
    print("="*60)

    for group_name, group_data in [
        ("按置信度", stats["by_confidence"]),
        ("按方向", stats["by_direction"]),
        ("按ADX区间", stats["by_adx_range"]),
    ]:
        print(f"\n{'─'*40}")
        print(f"  {group_name}:")
        for key, s in sorted(group_data.items()):
            print(f"    {key:12s}  准确率={s['accuracy']:5.1f}%  ({s['correct']}/{s['total']})  "
                  f"均盈(毛)={s['avg_pnl']:+.2f}%  (净)={s['net_avg_pnl']:+.2f}%  止损率={s['stop_hit_rate']:.1f}%")

    print(f"\n{'─'*40}")
    print(f"  按产业链:")
    for key, s in sorted(stats["by_chain"].items(), key=lambda x: -x[1]['accuracy']):
        print(f"    {key:8s}  准确率={s['accuracy']:5.1f}%  ({s['correct']}/{s['total']})  均盈={s['avg_pnl']:+.2f}%")

    # Save stats
    stats_path = str(Path(args.followup).parent / "validation_stats.json")
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n📊 统计数据已保存: {stats_path}")


if __name__ == "__main__":
    main()
