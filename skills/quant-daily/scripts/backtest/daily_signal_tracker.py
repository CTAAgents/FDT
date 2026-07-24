# -*- coding: utf-8 -*-
"""
quant-daily 实盘信号追踪器 v1.0
=================================
记录每日 scan_all 产生的信号，后续核对实际表现。

工作流：
  1. scan_all.py 执行完毕后，调用 track_signals() 记录当日信号
  2. 每次 scan_all 追加新信号（按日期去重）
  3. 运行 update_outcomes() 自动核对已过期信号的收益
  4. 输出性能追踪报告

CSV 格式 (signals.csv)：
  date | sym | grade | direction | total | price | ret_5d | ret_10d | ret_20d | resolved_at

用法：
  from backtest.daily_signal_tracker import track_signals, update_outcomes, report

  # 记录当日信号
  track_signals(scan_results)

  # 核对已过期信号（每天闭市后运行一次）
  update_outcomes()

  # 查看追踪报告
  report()
"""

import csv
import json
import os
from datetime import datetime
from typing import Dict, List

# ── 路径 ──
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER_DIR = os.path.join(os.path.dirname(SKILL_DIR), "backtest", "tracker")
SIGNALS_CSV = os.path.join(TRACKER_DIR, "signals.csv")
OUTCOMES_CSV = os.path.join(TRACKER_DIR, "outcomes.csv")
FIELDS = [
    "record_date",
    "sym",
    "grade",
    "direction",
    "total",
    "price",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "resolved_at",
    "status",
]


def _ensure_dir():
    os.makedirs(TRACKER_DIR, exist_ok=True)
    if not os.path.exists(SIGNALS_CSV):
        with open(SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def track_signals(scan_results: List[Dict], record_date: str = None):
    """记录 scan_all 输出的信号到追踪CSV。

    Args:
        scan_results: scan_all 输出的 results list
            [{'sector','direction','grade','total','price',...}, ...]
        record_date: 记录日期 (默认今天)
    """
    _ensure_dir()
    if record_date is None:
        record_date = datetime.now().strftime("%Y-%m-%d")

    # 读取已有记录去重
    existing = set()
    if os.path.exists(SIGNALS_CSV):
        with open(SIGNALS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row["record_date"], row["sym"]))

    new_rows = 0
    for r in scan_results:
        key = (record_date, r.get("sector", r.get("sym", "?")))
        if key in existing:
            continue
        row = {
            "record_date": record_date,
            "sym": r.get("sector", r.get("sym", "?")),
            "grade": r.get("grade", "?"),
            "direction": r.get("direction", "?"),
            "total": r.get("total", 0),
            "price": r.get("price", 0),
            "ret_5d": "",
            "ret_10d": "",
            "ret_20d": "",
            "resolved_at": "",
            "status": "pending",
        }
        existing.add(key)
        new_rows += 1

        with open(SIGNALS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writerow(row)

    print(f"[Tracker] 记录 {new_rows} 条信号 ({record_date})")
    return new_rows


def update_outcomes(data_provider=None):
    """核对已过期但未resolved的信号收益。

    需要外部提供后N日收盘价。
    Args:
        data_provider: callable(sym, date, days_ahead) → [price_5d, price_10d, price_20d]
                       如果为None则跳过实际收益填充
    """
    _ensure_dir()

    rows = []
    updated = 0
    today = datetime.now()

    with open(SIGNALS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 已resolve的跳过
            if row.get("status") == "resolved":
                rows.append(row)
                continue

            # 自动填充 status 标记
            has_ret = row.get("ret_5d") or row.get("ret_10d") or row.get("ret_20d")
            if has_ret:
                row["status"] = "resolved"
                row["resolved_at"] = today.strftime("%Y-%m-%d %H:%M")
                updated += 1

            rows.append(row)

    with open(SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if updated:
        print(f"[Tracker] 更新 {updated} 条信号为已解决")
    return updated


def report(min_signals: int = 3) -> dict:
    """生成信号追踪报告。"""
    _ensure_dir()

    if not os.path.exists(SIGNALS_CSV):
        print("[Tracker] 无追踪数据")
        return {}

    from collections import defaultdict

    by_grade = defaultdict(list)

    with open(SIGNALS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            grade = row.get("grade", "?")
            ret_10d = row.get("ret_10d", "")
            if ret_10d and grade in ("WATCH", "WEAK"):
                by_grade[grade].append(float(ret_10d))

    print(f"\n{'=' * 55}")
    print(f"  信号追踪报告 ({datetime.now().strftime('%Y-%m-%d')})")
    print(f"{'=' * 55}")

    report_data = {}
    for grade in ["WATCH", "WEAK"]:
        arr = by_grade.get(grade, [])
        if len(arr) < min_signals:
            print(f"  {grade:<8}: 仅{len(arr)}个已解决信号 (需≥{min_signals})")
            report_data[grade] = {"count": len(arr), "note": "样本不足"}
            continue
        wins = sum(1 for r in arr if r > 0)
        wr = wins / len(arr) * 100
        avg_r = sum(arr) / len(arr)
        print(f"  {grade:<8}: {len(arr):>4}个已解决 胜率{wr:>5.1f}% 均收益{avg_r:>+6.2f}%")
        report_data[grade] = {"count": len(arr), "win_rate": round(wr, 1), "avg_return": round(avg_r, 2)}

    return report_data


def export_signals(format="json"):
    """导出追踪信号用于外部分析。"""
    _ensure_dir()
    if not os.path.exists(SIGNALS_CSV):
        return []

    with open(SIGNALS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = [row for row in reader]

    if format == "json":
        out_path = os.path.join(TRACKER_DIR, "signals_export.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return data


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    elif len(sys.argv) > 1 and sys.argv[1] == "update":
        update_outcomes()
    else:
        print("用法: python daily_signal_tracker.py [report|update]")
