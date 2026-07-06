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


# ─── 数据获取 — 重构：拉K线序列而非单点价格 ──────────────

def fetch_bar_sequence_tdx(symbol: str, count: int = 10) -> list | None:
    """通过通达信TQ-Local获取品种最近N根日K线"""
    try:
        import requests
        url = f"http://localhost:7709/tq?symbol={symbol}&type=kline&period=day&count={count}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 and data.get("data"):
                bars = data["data"]
                if isinstance(bars, list) and len(bars) > 0:
                    result = []
                    for b in bars:
                        result.append({
                            "date": b.get("date", ""),
                            "open": float(b.get("open", 0)),
                            "high": float(b.get("high", 0)),
                            "low": float(b.get("low", 0)),
                            "close": float(b.get("close", 0)),
                        })
                    return result
    except Exception:
        pass
    return None


def fetch_bar_sequence_em(symbol: str, count: int = 10) -> list | None:
    """东方财富备用数据源 — 拉K线序列"""
    try:
        import requests
        market_code = _get_em_market_code(symbol)
        if not market_code:
            return None
        url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
               f"secid={market_code}&fields1=f1,f2,f3,f4,f5,f6&"
               f"fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&end=20500101&lmt={count}")
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data") and data["data"].get("klines"):
                klines = data["data"]["klines"]
                result = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) >= 6:
                        result.append({
                            "date": parts[0],
                            "open": float(parts[1]),
                            "close": float(parts[2]),
                            "high": float(parts[3]),
                            "low": float(parts[4]),
                        })
                return result if result else None
    except Exception:
        pass
    return None


def _get_em_market_code(symbol: str) -> str | None:
    """将期货代码转为东方财富market code（大小写不敏感）"""
    sym_upper = symbol.upper()
    mapping = {
        # 上海期货交易所
        "CU": "113", "AL": "113", "ZN": "113", "PB": "113", "NI": "113",
        "SN": "113", "AU": "113", "AG": "113", "RB": "113", "HC": "113",
        "SS": "113", "BU": "113", "RU": "113", "NR": "113", "SP": "113",
        "BR": "113",
        # 上海国际能源交易中心
        "SC": "114", "LU": "114", "FU": "114",
        "EC": "114",
        # 大连商品交易所
        "C": "114", "CS": "114", "A": "114", "B": "114", "M": "114",
        "Y": "114", "P": "114", "L": "114", "V": "114", "PP": "114",
        "J": "114", "JM": "114", "I": "114", "EG": "114", "EB": "114",
        "PG": "114", "RR": "114", "JD": "114", "LH": "114",
        # 郑州商品交易所
        "CF": "113", "SR": "113", "TA": "113", "MA": "113", "FG": "113",
        "SA": "113", "UR": "113", "PF": "113", "PK": "113", "CJ": "113",
        "AP": "113", "RM": "113", "OI": "113", "SM": "113", "SF": "113",
        "PR": "113", "PX": "113", "SH": "113",
        # 广州期货交易所
        "AO": "117", "SI": "117", "PS": "117",
    }
    exchange = mapping.get(sym_upper, "")
    if not exchange:
        return None
    return f"{exchange}.{symbol}"


def get_bar_sequence(symbol: str, count: int = 10) -> list:
    """获取品种K线序列（多源降级）"""
    bars = fetch_bar_sequence_tdx(symbol, count)
    if bars:
        for b in bars:
            b["source"] = "通达信TQ-Local"
        return bars
    bars = fetch_bar_sequence_em(symbol, count)
    if bars:
        for b in bars:
            b["source"] = "东方财富"
        return bars
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

    # correct = 实现盈亏为正
    correct = realized > 0

    return {
        "correct": correct,
        "realized_pnl_pct": realized_pnl_pct,
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
    return {
        "correct": correct, "change_pct": change_pct,
        "realized_pnl_pct": pnl_pct,
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
    bar_count = 8  # 拉8根日K线, 确保裁决日之后有足够数据

    for v in verdicts:
        sym = v["symbol"]
        if sym not in bar_cache:
            bars = get_bar_sequence(sym, bar_count)
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

    return {
        "validated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "accuracy": accuracy,
        "validatable": validatable,
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

def save_feedback_entries(results: list, verdicts: list, followup_dir: str):
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
    by_confidence = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "stop_hit": 0})
    by_direction = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "stop_hit": 0})
    by_chain = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "stop_hit": 0})
    by_adx_range = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0, "stop_hit": 0})

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

    def _format(stats):
        result = {}
        for key, s in stats.items():
            result[key] = {
                "total": s["total"],
                "correct": s["correct"],
                "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
                "avg_pnl": round(s["pnl_sum"] / s["total"], 2) if s["total"] > 0 else 0,
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

def main():
    import argparse
    parser = argparse.ArgumentParser(description="裁决验证器")
    parser.add_argument("--t1", action="store_true", help="验证T+1日")
    parser.add_argument("--t3", action="store_true", help="验证T+3日")
    parser.add_argument("--report", action="store_true", help="仅生成汇总报告")
    parser.add_argument("--followup", default=None, help="execution_followup.json路径")
    args = parser.parse_args()

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
        if record.get("validated"):
            continue

        print(f"\n🔍 验证轮次: {record['round_id']} ({record['generated_at']})")
        print(f"   品种数: {record['total_verdicts']}")

        if not args.report:
            vr = validate_round(record)
            record["validated"] = True
            record["validation_results"] = vr
            updated_count += 1

            print(f"   准确率: {vr['accuracy']}% ({vr['correct']}/{vr['total']}正确)")
            print(f"   止损触发: {vr['stop_hit_count']}/{vr['total']} ({vr['gap_stop_count']}跳空扫损)")
            print(f"   止盈达标: {vr['target_hit_count']}/{vr['total']}")
            print(f"   均实现盈亏: {vr['avg_pnl_pct']:+.2f}%")
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
                  f"均盈={s['avg_pnl']:+.2f}%  止损率={s['stop_hit_rate']:.1f}%")

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
