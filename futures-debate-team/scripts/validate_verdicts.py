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


# ─── 数据获取 ───────────────────────────────────────────

def fetch_latest_price_tdx(symbol: str) -> dict | None:
    """通过通达信TQ-Local获取品种最新收盘价"""
    try:
        import requests
        url = f"http://localhost:7709/tq?symbol={symbol}&type=kline&period=day&count=5"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 and data.get("data"):
                # 取最新一根K线的收盘价
                bars = data["data"]
                if isinstance(bars, list) and len(bars) > 0:
                    latest = bars[-1]
                    return {
                        "price": float(latest.get("close", 0)),
                        "date": latest.get("date", ""),
                        "high": float(latest.get("high", 0)),
                        "low": float(latest.get("low", 0)),
                        "source": "通达信TQ-Local"
                    }
    except Exception as e:
        pass
    return None


def fetch_latest_price_fallback(symbol: str) -> dict | None:
    """东方财富备用数据源"""
    try:
        import requests
        # 东方财富期货行情
        market_code = _get_em_market_code(symbol)
        if not market_code:
            return None
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market_code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&end=20500101&lmt=5"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data") and data["data"].get("klines"):
                klines = data["data"]["klines"]
                if klines:
                    last = klines[-1].split(",")
                    return {
                        "price": float(last[2]),
                        "date": last[0],
                        "high": float(last[3]),
                        "low": float(last[4]),
                        "source": "东方财富"
                    }
    except:
        pass
    return None


def _get_em_market_code(symbol: str) -> str | None:
    """将期货代码转为东方财富market code"""
    # 常见期货品种映射
    mapping = {
        # 上海期货交易所
        "cu": "113", "al": "113", "zn": "113", "pb": "113", "ni": "113",
        "sn": "113", "au": "113", "ag": "113", "rb": "113", "hc": "113",
        "ss": "113", "bu": "113", "ru": "113", "nr": "113", "sp": "113",
        "sc": "114", "lu": "114", "fu": "114", "ao": "117",
        "br": "113",
        # 大连商品交易所
        "c": "114", "cs": "114", "a": "114", "b": "114", "m": "114",
        "y": "114", "p": "114", "l": "114", "v": "114", "pp": "114",
        "j": "114", "jm": "114", "i": "114", "eg": "114", "eb": "114",
        "pg": "114", "rr": "114", "jd": "114", "lh": "114",
        # 郑州商品交易所
        "CF": "113", "SR": "113", "TA": "113", "MA": "113", "FG": "113",
        "SA": "113", "UR": "113", "PF": "113", "PK": "113", "CJ": "113",
        "AP": "113", "RM": "113", "OI": "113", "SM": "113", "SF": "113",
        "PR": "113", "PX": "113", "SH": "113",
        # 上海国际能源交易中心
        "ec": "114", "si": "117", "ps": "117",
    }
    exchange = mapping.get(symbol, "")
    if not exchange:
        return None
    return f"{exchange}.{symbol}"


def get_current_price(symbol: str) -> dict:
    """获取品种当前最新价格（多源降级）"""
    result = fetch_latest_price_tdx(symbol)
    if result and result["price"] > 0:
        return result
    result = fetch_latest_price_fallback(symbol)
    if result and result["price"] > 0:
        return result
    return {"price": 0, "date": "", "source": "无数据"}


# ─── 验证逻辑 ───────────────────────────────────────────

def validate_verdict(verdict: dict, current_price: float) -> dict:
    """验证单条裁决的方向正确性"""
    direction = verdict["direction"]
    entry = verdict["entry_price"]

    if entry <= 0 or current_price <= 0:
        return {"correct": None, "change_pct": 0, "reason": "价格数据缺失"}

    change_pct = round((current_price - entry) / entry * 100, 2)

    if direction == "bear":
        correct = current_price < entry
    elif direction == "bull":
        correct = current_price > entry
    else:
        correct = None

    # 计算盈亏（以1标准手计算）
    pnl_pct = round(-change_pct if direction == "bear" else change_pct, 2)

    return {
        "correct": correct,
        "entry_price": entry,
        "current_price": current_price,
        "change_pct": change_pct,
        "pnl_pct": pnl_pct,
        "hit_stop": False,  # 需要日内数据才能精确计算
    }


def validate_round(record: dict, price_cache: dict = None) -> dict:
    """验证一轮辩论的全部裁决"""
    if price_cache is None:
        price_cache = {}

    verdicts = record["verdicts"]
    results = []
    errors = []

    for v in verdicts:
        sym = v["symbol"]
        if sym not in price_cache:
            price_data = get_current_price(sym)
            price_cache[sym] = price_data

        price_data = price_cache[sym]
        current_price = price_data.get("price", 0)

        if current_price <= 0:
            errors.append(f"{sym}: 无法获取当前价格")
            results.append({
                "symbol": sym,
                "direction": v["direction"],
                "correct": None,
                "change_pct": 0,
                "pnl_pct": 0,
                "error": "无价格数据",
            })
        else:
            vr = validate_verdict(v, current_price)
            vr["symbol"] = sym
            results.append(vr)

    total = len(results)
    correct = sum(1 for r in results if r["correct"] is True)
    wrong = sum(1 for r in results if r["correct"] is False)
    unknown = total - correct - wrong
    accuracy = round(correct / (correct + wrong) * 100, 1) if (correct + wrong) > 0 else 0
    validatable = (correct + wrong) > 0

    return {
        "validated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "accuracy": accuracy,
        "validatable": validatable,
        "avg_pnl_pct": round(sum(r["pnl_pct"] for r in results if r["pnl_pct"] != 0) / max(total, 1), 2),
        "results": results,
        "errors": errors,
    }


# ─── 分组统计 ───────────────────────────────────────────

def compute_group_stats(all_records: list) -> dict:
    """对所有已验证记录做分组统计"""
    by_confidence = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0})
    by_direction = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0})
    by_chain = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0})
    by_adx_range = defaultdict(lambda: {"total": 0, "correct": 0, "pnl_sum": 0})

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

            by_confidence[conf]["pnl_sum"] += r.get("pnl_pct", 0)
            by_direction[direction]["pnl_sum"] += r.get("pnl_pct", 0)
            by_chain[chain]["pnl_sum"] += r.get("pnl_pct", 0)
            by_adx_range[adx_range]["pnl_sum"] += r.get("pnl_pct", 0)

    def _format(stats):
        result = {}
        for key, s in stats.items():
            result[key] = {
                "total": s["total"],
                "correct": s["correct"],
                "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
                "avg_pnl": round(s["pnl_sum"] / s["total"], 2) if s["total"] > 0 else 0,
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
            if vr["errors"]:
                print(f"   错误: {', '.join(vr['errors'])}")

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
            print(f"    {key:12s}  准确率={s['accuracy']:5.1f}%  ({s['correct']}/{s['total']})  均盈={s['avg_pnl']:+.2f}%")

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
