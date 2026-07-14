#!/usr/bin/env python3
"""
L1-L4 扫描入口 — technical-analysis 子 Agent（观澜）自有计算模块
================================================================
产出 full_scan_l1l4_{date}.json，供观澜 data_interface.load_l1l4_scan 读取。
依赖：FDC（futures_data_core）采 K线 + 算指标（§1 已收编 indicators）。

用法：
  python run_l1l4_scan.py --symbols RB,IF,CU
  python run_l1l4_scan.py --all
  python run_l1l4_scan.py --symbols RB --output-dir /path/to/reports
"""
import sys
import os
import json
import asyncio
import argparse
from datetime import date
from typing import Optional

# ── 路径自举 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
# FDT 根（含 futures_data_core/ 包），插到 sys.path[0] 以覆盖其他版本
FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
if FDT_ROOT not in sys.path:
    sys.path.insert(0, FDT_ROOT)

import pandas as pd
from futures_data_core import get_kline as _fdc_get_kline
from futures_data_core.indicators.legacy_numpy import _compute_indicators_numpy
from futures_data_core._a2a import DATA_GRADE_NAME
from layered_l1l4 import LayeredL1L4Scorer


def _fdc_get_kline_sync(variety: str, days: int = 120, period: str = "daily") -> dict:
    """同步包装 FDC get_kline（复刻 scan_all._fdc_get_kline_sync）。"""
    try:
        payload = asyncio.run(_fdc_get_kline(variety, period=period, days=days))
        meta = payload.meta
        grade = meta.get("data_grade_label", "")
        grade_name = DATA_GRADE_NAME.get(grade, str(grade))
        if grade_name == "UNAVAILABLE":
            return {"success": False, "data": [], "data_source": grade_name, "error": f"FDC grade={grade_name}"}
        bars_raw = payload.data.get("bars", [])
        if not bars_raw:
            return {"success": False, "data": [], "data_source": meta.get("source", "fdc"), "error": "FDC 返回空 K 线"}
        records = []
        for b in bars_raw:
            records.append({
                "date": b.get("date", ""),
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "volume": int(b.get("volume", 0)),
                "oi": int(b.get("oi", 0) if b.get("oi") else 0),
                "settle": float(b.get("settle", 0) if b.get("settle") else 0),
                "data_source": meta.get("source", "fdc"),
                "confidence": 1.0,
            })
        sources = meta.get("sources", ["fdc"])
        source_label = sources[0] if isinstance(sources, list) else str(sources)
        return {"success": True, "data": records, "data_source": source_label, "confidence": 1.0}
    except Exception as e:
        return {"success": False, "data": [], "data_source": "fdc_error", "error": str(e)}


def _atomic_write(path: str, content):
    """原子写入：写 .tmp → rename，防止写半截文件"""
    tmp = path + ".tmp_" + str(os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# 默认品种列表（辩论常用；--all 可扩展）
DEFAULT_SYMBOLS = ["RB", "IF", "CU", "TA", "MA", "AU", "AG", "I", "J", "JM"]


def main():
    parser = argparse.ArgumentParser(description="L1-L4 分层扫描（观澜技术分析）")
    parser.add_argument("--symbols", type=str, default=None, help="品种逗号分隔，如 RB,IF")
    parser.add_argument("--all", action="store_true", help="扫描默认品种列表")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--period", type=str, default="daily")
    parser.add_argument("--output-dir", type=str, default=None, help="JSON 输出目录")
    args = parser.parse_args()

    if args.symbols:
        symbols = [(s.strip().upper(), s.strip().upper()) for s in args.symbols.split(",") if s.strip()]
    elif args.all:
        symbols = [(s, s) for s in DEFAULT_SYMBOLS]
    else:
        symbols = [(s, s) for s in DEFAULT_SYMBOLS]

    output_dir = args.output_dir or os.path.join(SCRIPT_DIR, "reports")
    os.makedirs(output_dir, exist_ok=True)

    today_str = date.today().strftime("%Y%m%d")
    print(f"[L1-L4] 采集 {len(symbols)} 品种 K线 (FDC)...")

    tech_list = []
    kline_data = {}
    for sym, name in symbols:
        r = _fdc_get_kline_sync(sym, days=args.days, period=args.period)
        if not r["success"]:
            print(f"  ⚠ {sym}: FDC 失败 {r.get('error', '')}")
            continue
        dlist = r["data"]
        if len(dlist) < 60:
            print(f"  ⚠ {sym}: K线不足 {len(dlist)} (<60)")
            continue
        try:
            df = pd.DataFrame({k: [float(b[k]) for b in dlist] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(b.get("volume", 0)) for b in dlist]
            if "oi" in dlist[0]:
                df["open_interest"] = [float(b.get("oi", 0)) for b in dlist]
            tech = _compute_indicators_numpy(df, sym, period=args.period)
            tech["price"] = tech.get("last_price", float(df["close"].iloc[-1]))
            tech["change_pct"] = (
                round((float(df["close"].iloc[-1]) / float(df["close"].iloc[-2]) - 1) * 100, 2)
                if len(df) >= 2 and float(df["close"].iloc[-2]) > 0 else 0.0
            )
            tech["symbol"] = sym
            tech["name"] = name
            tech["volume"] = int(round(float(df["volume"].iloc[-1]))) if not df["volume"].empty else 0
            tech_list.append(tech)
            kline_data[sym] = df
        except Exception as e:
            print(f"  ⚠ {sym}: 指标计算失败 {e}")

    print(f"[L1-L4] 计算 {len(tech_list)} 品种打分...")
    scorer = LayeredL1L4Scorer()
    df_map = {sym: kline_data[sym] for sym in kline_data}
    summary = scorer.score(tech_list, mode="full", df_map=df_map, period=args.period)

    out_path = os.path.join(output_dir, f"full_scan_l1l4_{today_str}.json")
    _atomic_write(out_path, summary)
    print(f"[L1-L4] 产出: {out_path} ({len(summary['all_ranked'])} 品种)")


if __name__ == "__main__":
    main()
