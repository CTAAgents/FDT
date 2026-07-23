#!/usr/bin/env python3
"""
裁决验证器 — 用后续行情检验历史裁决方向正确性。

验证逻辑（非 T+1 K线逐根扫描）：
  - 获取裁决后最多 VALIDATION_BARS 根 K 线
  - 检查周期内 high/low 是否触及目标价/止损价
  - 统计目标价达标率、订单胜率、平均盈亏
  - 所有辩论结果均可验证（无 K 线时用兜底逻辑）

用法:
  python validate_verdicts.py [--report] [--force]

输出:
  - execution_followup.json (更新 validated=True + validation_results)
  - validation_stats.json (分组统计)
"""
from __future__ import annotations

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# 数据质量评估
try:
    from futures_data_core.core.data_quality import evaluate_symbol as _eval_dq
    _DQ_AVAILABLE = True
except ImportError:
    _DQ_AVAILABLE = False


# ─── 成本模型 ──────────────────────────────────────────
COST_BPS = 2.0           # 往返交易成本(基点)
DEFAULT_COST_BPS = 2.0
VALIDATION_BARS = 30     # 验证窗口：最多看裁决后 30 根 K 线
MIN_BARS_FOR_RANGE = 3   # 至少需要 3 根 K 线做价格范围判断


# ─── 数据获取 — 统一经由 quant-daily skill ─────────────

_ADAPTER = None
_ADAPTER_AVAILABLE = True


def _qdaily_scripts_dir() -> str:
    here = Path(__file__).resolve().parent
    candidate = here.parent / "skills" / "quant-daily" / "scripts"
    if candidate.exists():
        return str(candidate)
    return str(Path.home() / ".fdt" / "skills" / "quant-daily" / "scripts")


def _get_qdaily_adapter():
    global _ADAPTER, _ADAPTER_AVAILABLE
    if _ADAPTER is not None:
        return _ADAPTER
    if not _ADAPTER_AVAILABLE:
        return None
    try:
        scripts_dir = _qdaily_scripts_dir()
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        fdt_root = str(Path(scripts_dir).parent.parent.parent)
        if fdt_root not in sys.path:
            sys.path.insert(0, fdt_root)
        from data.multi_source_adapter import MultiSourceAdapter
        _ADAPTER = MultiSourceAdapter()
        return _ADAPTER
    except Exception as e:
        _ADAPTER_AVAILABLE = False
        return None


def _variety_from_symbol(symbol: str) -> str:
    return (symbol or "").split(".")[0].upper().strip()


def fetch_bars(symbol: str) -> list | None:
    """获取品种日 K 线序列"""
    adapter = _get_qdaily_adapter()
    if adapter is None:
        return None
    variety = _variety_from_symbol(symbol)
    try:
        res = adapter.get_kline(variety, days=VALIDATION_BARS, period="daily")
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
    except Exception:
        return None


# ─── 验证逻辑（单条裁决） ─────────────────────────────

def validate_single(verdict: dict, entry_date: str = "") -> dict:
    """用后续 K 线验证单条裁决。

    不依赖 T+1 对齐，而是取裁决后全部可用 K 线，
    检查周期内是否达到目标价/止损价，计算可实现盈亏。
    K 线不可用时用兜底逻辑。
    """
    direction = verdict["direction"]
    entry = verdict.get("entry_price", verdict.get("entry_plan", 0))
    stop = verdict.get("stop_loss", 0)
    target1 = verdict.get("target1", verdict.get("target_price", 0))
    target2 = verdict.get("target2", 0)
    sym = verdict.get("symbol", "")

    # ── 获取价格数据 ──
    bars = fetch_bars(sym) if sym else None

    # 按裁决日对齐（如果有 entry_date）
    if entry_date and bars:
        bars = [b for b in bars if _norm_date(b["date"]) >= entry_date]
    if bars:
        for b in bars:
            b["source"] = "quant-daily"

    # ── 计算范围指标 ──
    enough_bars = bars and len(bars) >= MIN_BARS_FOR_RANGE
    period_high = max(b["high"] for b in bars) if enough_bars else 0
    period_low = min(b["low"] for b in bars) if enough_bars else 0
    last_close = bars[-1]["close"] if enough_bars else 0

    # ── 判断目标价/止损是否达到 ──
    hit_stop = False
    hit_target1 = False
    hit_target2 = False
    entry_pnl_pct = 0.0  # 纯方向盈亏 (entry → last_close)
    realizable_pnl_pct = 0.0  # 可实现的带止损/止盈的盈亏

    if enough_bars and entry > 0:
        if direction == "bear":
            # 空单：止损=上破high, 止盈=下破low
            hit_stop = stop > 0 and period_high >= stop
            hit_target1 = target1 > 0 and period_low <= target1
            hit_target2 = target2 > 0 and period_low <= target2
            entry_pnl_pct = (entry - last_close) / entry * 100
        else:
            # 多单：止损=下破low, 止盈=上破high
            hit_stop = stop > 0 and period_low <= stop
            hit_target1 = target1 > 0 and period_high >= target1
            hit_target2 = target2 > 0 and period_high >= target2
            entry_pnl_pct = (last_close - entry) / entry * 100

        # 计算可实现盈亏（按优先顺序：止损→T2→T1→持仓）
        if hit_stop:
            realizable_pnl_pct = -abs(stop - entry) / entry * 100
        elif hit_target2 and target2 > 0:
            t1_part = abs(target1 - entry) / entry * 0.3 if target1 > 0 else 0
            t2_part = abs(target2 - entry) / entry * 0.5
            realizable_pnl_pct = (t1_part + t2_part) * 100
        elif hit_target1:
            realizable_pnl_pct = abs(target1 - entry) / entry * 100
        else:
            realizable_pnl_pct = entry_pnl_pct  # 未触及边界，用方向盈亏
    else:
        # 兜底：K 线不可用，用纯方向盈亏 = 0（无法判定）
        entry_pnl_pct = 0.0
        realizable_pnl_pct = 0.0

    # 成本感知
    cost_pct = COST_BPS / 100.0
    net_pnl_pct = round(realizable_pnl_pct - cost_pct, 2)
    correct = realizable_pnl_pct > 0
    correct_net = net_pnl_pct > 0

    # 目标价达标率 = 达到 target1 或 target2 的占比
    target_hit = hit_target1 or hit_target2

    # 推理说明
    if not enough_bars:
        reason = "K线数据不足，跳过价格判定"
    elif hit_stop:
        reason = f"触发止损@{stop}，亏{abs(realizable_pnl_pct):.1f}%"
    elif hit_target2:
        reason = f"达T2(预)@{target1}(+{abs(realizable_pnl_pct):.1f}%)"
    elif hit_target1:
        reason = f"达T1@{target1}(+{abs(realizable_pnl_pct):.1f}%)"
    else:
        reason = f"边界未触，收于{last_close}，盈{realizable_pnl_pct:+.1f}%"

    # ── 数据质量评估（Data Governance Phase 1） ──
    dq = _eval_dq(sym, bars, bars[0].get("source", "unknown") if enough_bars else "unknown") if _DQ_AVAILABLE else {
        "available": enough_bars, "confidence": "FRESH" if enough_bars else "STALE",
        "overall": "A" if enough_bars else "D", "issues": [] if enough_bars else ["无数据"]
    }

    return {
        "symbol": sym,
        "direction": direction,
        "correct": correct,
        "correct_net": correct_net,
        "realized_pnl_pct": round(realizable_pnl_pct, 2),
        "entry_pnl_pct": round(entry_pnl_pct, 2),
        "net_pnl_pct": net_pnl_pct,
        "cost_bps": COST_BPS,
        "hit_stop": hit_stop,
        "hit_target1": hit_target1,
        "hit_target2": hit_target2,
        "target_hit": target_hit,
        "reason": reason,
        "data_source": bars[0].get("source", "none") if enough_bars else "none",
        "n_bars": len(bars) if bars else 0,
        "data_quality": dq,  # 数据质量元数据
    }


def _norm_date(s: str) -> str:
    digits = "".join(ch for ch in (s or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


# ─── 一轮验证 ─────────────────────────────────────────

def validate_round(record: dict) -> dict:
    """验证一轮辩论的全部裁决"""
    verdicts = record.get("verdicts", [])
    if not verdicts:
        return {"total": 0, "correct": 0, "wrong": 0, "results": [], "errors": ["无裁决"]}

    entry_date = _norm_date(record.get("generated_at", ""))
    results = []

    for v in verdicts:
        vr = validate_single(v, entry_date)
        results.append(vr)

    total = len(results)
    correct = sum(1 for r in results if r["correct"] is True)
    wrong = sum(1 for r in results if r["correct"] is False)
    unknown = total - correct - wrong
    accuracy = round(correct / (correct + wrong) * 100, 1) if (correct + wrong) > 0 else 0
    validatable = (correct + wrong) > 0

    net_correct = sum(1 for r in results if r["correct_net"] is True)
    net_wrong = sum(1 for r in results if r["correct_net"] is False)
    net_accuracy = round(net_correct / (net_correct + net_wrong) * 100, 1) if (net_correct + net_wrong) > 0 else 0

    pnl_vals = [r["realized_pnl_pct"] for r in results if r["realized_pnl_pct"] != 0]
    avg_pnl = round(sum(pnl_vals) / max(len(pnl_vals), 1), 2) if pnl_vals else 0
    net_pnl_vals = [r["net_pnl_pct"] for r in results if r["net_pnl_pct"] is not None]
    net_avg_pnl = round(sum(net_pnl_vals) / max(len(net_pnl_vals), 1), 2)

    # 新指标
    target_hit_count = sum(1 for r in results if r["target_hit"])
    stop_hit_count = sum(1 for r in results if r["hit_stop"])
    profit_count = sum(1 for r in results if r["realized_pnl_pct"] > 0)
    loss_count = sum(1 for r in results if r["realized_pnl_pct"] < 0)
    profit_ratio = round(profit_count / max(profit_count + loss_count, 1) * 100, 1)
    target_hit_ratio = round(target_hit_count / total * 100, 1) if total > 0 else 0

    # 盈亏比
    total_profit = sum(r["realized_pnl_pct"] for r in results if r["realized_pnl_pct"] > 0)
    total_loss = abs(sum(r["realized_pnl_pct"] for r in results if r["realized_pnl_pct"] < 0))
    profit_loss_ratio = round(total_profit / max(total_loss, 0.01), 2) if total_loss > 0 else 0

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
        "avg_pnl_pct": avg_pnl,
        "net_avg_pnl_pct": net_avg_pnl,
        "stop_hit_count": stop_hit_count,
        "target_hit_count": target_hit_count,
        "target_hit_ratio": target_hit_ratio,
        "profit_count": profit_count,
        "loss_count": loss_count,
        "profit_ratio": profit_ratio,
        "profit_loss_ratio": profit_loss_ratio,
        "results": results,
        "errors": [],
    }


# ─── 分组统计 ───────────────────────────────────────────

def save_feedback_entries(results: list, verdicts: list, followup_dir: str) -> None:
    entries = []
    for i, r in enumerate(results):
        if r.get("correct") is None:
            continue
        v = verdicts[i] if i < len(verdicts) else {}
        entries.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": r.get("symbol", ""),
            "anchor_price": v.get("stop_loss", 0),
            "anchor_source": "stop_loss_from_verdict",
            "stop_hit": r.get("hit_stop", False),
            "target_hit": r.get("target_hit", False),
            "pnl_pct": r.get("realized_pnl_pct", 0),
            "correct": r.get("correct"),
            "reason": r.get("reason", ""),
        })
    if not entries:
        return
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


def compute_group_stats(all_records: list) -> dict:
    """对所有已验证记录做分组统计"""
    by_confidence = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                          "stop_hit": 0, "target_hit": 0, "profit": 0})
    by_direction = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                         "stop_hit": 0, "target_hit": 0, "profit": 0})
    by_chain = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                     "stop_hit": 0, "target_hit": 0, "profit": 0})
    by_adx_range = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                         "stop_hit": 0, "target_hit": 0, "profit": 0})
    by_data_quality = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                            "stop_hit": 0, "target_hit": 0, "profit": 0})
    by_source = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "net_pnl_sum": 0,
                                      "stop_hit": 0, "target_hit": 0, "profit": 0})

    for record in all_records:
        if not record.get("validated"):
            continue
        vr = record.get("validation_results", {})
        if not vr:
            continue
        verdicts = record.get("verdicts", [])
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

            for stats_map in [by_confidence, by_direction, by_chain]:
                pass  # will assign per key below

            by_confidence[conf]["total"] += 1
            by_direction[direction]["total"] += 1
            by_chain[chain]["total"] += 1

            if adx >= 70:
                adx_range = "ADX>=70"
            elif adx >= 50:
                adx_range = "50<=ADX<70"
            elif adx >= 30:
                adx_range = "30<=ADX<50"
            else:
                adx_range = "ADX<30"
            by_adx_range[adx_range]["total"] += 1

            if r["correct"]:
                for stats in [by_confidence[conf], by_direction[direction],
                              by_chain[chain], by_adx_range[adx_range]]:
                    stats["correct"] += 1

            if r.get("hit_stop"):
                for stats in [by_confidence[conf], by_direction[direction],
                              by_chain[chain], by_adx_range[adx_range]]:
                    stats["stop_hit"] += 1

            if r.get("target_hit"):
                for stats in [by_confidence[conf], by_direction[direction],
                              by_chain[chain], by_adx_range[adx_range]]:
                    stats["target_hit"] += 1

            if r.get("realized_pnl_pct", 0) > 0:
                for stats in [by_confidence[conf], by_direction[direction],
                              by_chain[chain], by_adx_range[adx_range]]:
                    stats["profit"] += 1

            pnl = r.get("realized_pnl_pct", 0)
            net = r.get("net_pnl_pct", 0)
            for stats in [by_confidence[conf], by_direction[direction],
                          by_chain[chain], by_adx_range[adx_range]]:
                stats["pnl_sum"] += pnl
                stats["net_pnl_sum"] += net

            # 数据质量分组
            dq = r.get("data_quality", {})
            dq_grade = dq.get("overall", "N/A")
            dq_source = dq.get("source", r.get("data_source", "unknown"))
            by_data_quality[dq_grade]["total"] += 1
            by_source[dq_source]["total"] += 1
            if r["correct"]:
                by_data_quality[dq_grade]["correct"] += 1
                by_source[dq_source]["correct"] += 1
            if r.get("hit_stop"):
                by_data_quality[dq_grade]["stop_hit"] += 1
                by_source[dq_source]["stop_hit"] += 1
            if r.get("target_hit"):
                by_data_quality[dq_grade]["target_hit"] += 1
                by_source[dq_source]["target_hit"] += 1
            if r.get("realized_pnl_pct", 0) > 0:
                by_data_quality[dq_grade]["profit"] += 1
                by_source[dq_source]["profit"] += 1
            by_data_quality[dq_grade]["pnl_sum"] += pnl
            by_data_quality[dq_grade]["net_pnl_sum"] += net
            by_source[dq_source]["pnl_sum"] += pnl
            by_source[dq_source]["net_pnl_sum"] += net

    def _format(stats):
        result = {}
        for key, s in stats.items():
            total = s["total"]
            tc = s["correct"]
            tp = s["profit"]
            result[key] = {
                "total": total,
                "correct": tc,
                "accuracy": round(tc / total * 100, 1) if total > 0 else 0,
                "profit_ratio": round(tp / total * 100, 1) if total > 0 else 0,
                "target_hit_ratio": round(s["target_hit"] / total * 100, 1) if total > 0 else 0,
                "stop_hit_rate": round(s["stop_hit"] / total * 100, 1) if total > 0 else 0,
                "avg_pnl": round(s["pnl_sum"] / total, 2) if total > 0 else 0,
                "net_avg_pnl": round(s["net_pnl_sum"] / total, 2) if total > 0 else 0,
            }
        return result

    return {
        "by_confidence": _format(by_confidence),
        "by_direction": _format(by_direction),
        "by_chain": _format(by_chain),
        "by_adx_range": _format(by_adx_range),
        "by_data_quality": _format(by_data_quality),
        "by_source": _format(by_source),
    }


# ─── 主程序 ───────────────────────────────────────────

def main() -> None:
    global COST_BPS
    import argparse
    parser = argparse.ArgumentParser(description="裁决验证器（目标价达标+订单胜率）")
    parser.add_argument("--report", action="store_true", help="仅生成汇总报告")
    parser.add_argument("--force", action="store_true", help="强制重验已验证记录")
    parser.add_argument("--cost-bps", type=float, default=COST_BPS,
                        help=f"往返交易成本(基点), 默认 {DEFAULT_COST_BPS}bp")
    parser.add_argument("--followup", default=None, help="execution_followup.json路径")
    args = parser.parse_args()
    COST_BPS = args.cost_bps

    if args.followup is None:
        followup_path = Path(__file__).parent.parent / "memory" / "execution_followup.json"
    else:
        followup_path = Path(args.followup)

    with open(followup_path, 'r', encoding='utf-8') as f:
        followup = json.load(f)

    if not followup["records"]:
        print("⚠️ 无历史裁决记录，跳过验证")
        return

    updated_count = 0
    for record in followup["records"]:
        if record.get("validated") and not args.force:
            continue

        # 兼容新旧格式
        is_new = "verdicts" not in record and "decision" in record
        if is_new:
            record["total_verdicts"] = 1
            v = dict(record)
            v["entry_price"] = v.get("entry_plan", 0)
            v["target_price"] = v.get("target1", 0)
            record["verdicts"] = [v]
            record["data_source"] = record.get("source_path", "未知")

        if record.get("total_verdicts", 0) == 0 or not record.get("verdicts"):
            print(f"  ⏭ {record['round_id']}: 无裁决")
            continue

        print(f"\n🔍 {record['round_id']} ({record.get('generated_at', '')})")
        print(f"   品种数: {len(record['verdicts'])}")

        if not args.report:
            vr = validate_round(record)
            record["validated"] = True
            record["validation_results"] = vr
            updated_count += 1

            print(f"   准: {vr['accuracy']}% ({vr['correct']}/{vr['total']})  "
                  f"盈: {vr['profit_ratio']}% ({vr['profit_count']}/{vr['profit_count']+vr['loss_count']})  "
                  f"目标达标: {vr['target_hit_ratio']}%  "
                  f"均盈: {vr['avg_pnl_pct']:+.2f}%")
            if vr["target_hit_count"] > 0:
                print(f"   止盈: {vr['target_hit_count']} 止损: {vr['stop_hit_count']}  "
                      f"盈亏比: {vr['profit_loss_ratio']}")

            followup_dir = str(followup_path.parent)
            save_feedback_entries(vr["results"], record["verdicts"], followup_dir)

    if updated_count > 0:
        with open(followup_path, 'w', encoding='utf-8') as f:
            json.dump(followup, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已验证 {updated_count} 轮，保存至 {followup_path}")

    # 汇总统计
    stats = compute_group_stats(followup["records"])
    print("\n" + "=" * 70)
    print("📊 验证汇总")
    print("=" * 70)

    for group_name, group_data in [
        ("按置信度", stats["by_confidence"]),
        ("按方向", stats["by_direction"]),
        ("按ADX区间", stats["by_adx_range"]),
    ]:
        print(f"\n{'─'*50}")
        print(f"  {group_name}:")
        print(f"  {'维度':12s} {'准确率':>8s} {'胜率':>6s} {'目标达标':>8s} {'止损率':>6s} {'均盈':>8s}")
        for key, s in sorted(group_data.items()):
            print(f"  {key:12s} {s['accuracy']:6.1f}%  {s['profit_ratio']:5.1f}%  "
                  f"{s['target_hit_ratio']:6.1f}%  {s['stop_hit_rate']:5.1f}%  {s['avg_pnl']:+.2f}%")

    print(f"\n{'─'*50}")
    print(f"  按产业链:")
    print(f"  {'产业链':10s} {'准确率':>8s} {'胜率':>6s} {'均盈':>8s}")
    for key, s in sorted(stats["by_chain"].items(), key=lambda x: -x[1]['accuracy']):
        print(f"  {key:10s} {s['accuracy']:6.1f}%  {s['profit_ratio']:5.1f}%  {s['avg_pnl']:+.2f}%")

    # 数据质量分组输出
    print(f"\n{'─'*50}")
    print(f"  按数据质量等级:")
    print(f"  {'等级':6s} {'数量':>4s} {'准确率':>8s} {'胜率':>6s} {'均盈':>8s}")
    for grade in ["A", "B", "C", "D", "N/A"]:
        s = stats["by_data_quality"].get(grade)
        if s and s["total"] > 0:
            print(f"  {grade:6s} {s['total']:4d} {s['accuracy']:6.1f}%  "
                  f"{s['profit_ratio']:5.1f}%  {s['avg_pnl']:+.2f}%")

    print(f"\n{'─'*50}")
    print(f"  按数据源:")
    print(f"  {'数据源':12s} {'数量':>4s} {'准确率':>8s} {'均盈':>8s}")
    for key, s in sorted(stats["by_source"].items(), key=lambda x: -x[1]['total']):
        if s["total"] > 0:
            print(f"  {key:12s} {s['total']:4d} {s['accuracy']:6.1f}%  {s['avg_pnl']:+.2f}%")

    stats_path = followup_path.parent / "validation_stats.json"
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n📊 统计已保存: {stats_path}")


if __name__ == "__main__":
    main()
