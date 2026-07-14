#!/usr/bin/env python3
"""
因子择时扫描入口 — fundamental-data-collector（探源）自有计算模块
================================================================
产出 full_scan_factor_timing_{date}.json，供探源 data_interface.load_factor_timing_scan 读取。
数据来源：
  - 展期收益率 : 本 skill term_basis.query_term（自研期限库）
  - 反向仓单   : 本 skill inventory.query_inventory（季节性分位数）
  - 动量/偏度/量价相关性 : FDC K线（futures_data_core.get_kline）

用法：
  python run_factor_timing_scan.py --symbols RB,MA,SA
  python run_factor_timing_scan.py --all
"""
import sys
import os
import re
import json
import asyncio
import argparse
from datetime import date
from typing import Optional

# ── 路径自举 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
# FDT 根（含 futures_data_core/ 包）
FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR))))
if FDT_ROOT not in sys.path:
    sys.path.insert(0, FDT_ROOT)

import numpy as np
import pandas as pd
from futures_data_core import get_kline as _fdc_get_kline
from futures_data_core._a2a import DATA_GRADE_NAME
from factor_timing import FactorTimingScorer
from term_basis import query_term
from inventory import query_inventory


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
            })
        sources = meta.get("sources", ["fdc"])
        source_label = sources[0] if isinstance(sources, list) else str(sources)
        return {"success": True, "data": records, "data_source": source_label, "confidence": 1.0}
    except Exception as e:
        return {"success": False, "data": [], "data_source": "fdc_error", "error": str(e)}


def _sample_skew(returns: np.ndarray) -> float:
    """样本偏度（无 scipy 依赖）。"""
    n = len(returns)
    if n < 3:
        return 0.0
    mu = float(np.mean(returns))
    sd = float(np.std(returns, ddof=1))
    if sd == 0:
        return 0.0
    m3 = float(np.mean((returns - mu) ** 3))
    return m3 / (sd ** 3)


def _compute_kline_factors(records: list) -> dict:
    """从 K线记录计算 动量 / 偏度 / 量价相关性。"""
    closes = np.array([b["close"] for b in records], dtype=float)
    vols = np.array([b["volume"] for b in records], dtype=float)
    if len(closes) < 60:
        return {"momentum": None, "skew": None, "corr": None}
    # 动量：60 日收益率
    momentum = (closes[-1] / closes[-60] - 1.0) * 100.0
    # 偏度：日收益分布（近 60 根）
    rets = np.diff(closes[-60:]) / closes[-61:-1]
    skew = _sample_skew(rets)
    # 量价相关性：ΔP 与 ΔV 的 20 日相关性
    dprice = np.diff(closes[-21:]) / closes[-22:-1]
    dvol = np.diff(vols[-21:]).astype(float)
    if len(dprice) > 2 and np.std(dprice) > 0 and np.std(dvol) > 0:
        corr = float(np.corrcoef(dprice, dvol)[0, 1])
    else:
        corr = None
    return {"momentum": float(momentum), "skew": float(skew), "corr": corr}


def _carry_factor(sym: str) -> Optional[float]:
    """展期收益率：spread / near（back结构为正）。无数据返回 None。"""
    t = query_term(sym)
    spread = t.get("spread")
    near = t.get("near")
    if spread is None or near in (None, 0):
        return None
    try:
        return float(spread) / float(near)
    except (TypeError, ValueError):
        return None


def _inventory_pct(sym: str) -> Optional[float]:
    """库存季节性分位数（0-100），高分位=高库存。无数据返回 None。"""
    inv = query_inventory(sym)
    if "seasonal" not in inv:
        return None
    pct_str = inv["seasonal"].get("分位数", "")
    m = re.search(r"(\d+)", pct_str)
    if not m:
        return None
    return float(m.group(1))


def _atomic_write(path: str, content):
    tmp = path + ".tmp_" + str(os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


DEFAULT_SYMBOLS = ["RB", "I", "J", "JM", "SA", "MA", "TA", "CU", "AL", "AG", "AU", "SC", "BU", "FU", "LU", "PG", "EG", "UR"]


def main():
    parser = argparse.ArgumentParser(description="因子择时扫描（探源基本面）")
    parser.add_argument("--symbols", type=str, default=None, help="品种逗号分隔，如 RB,MA")
    parser.add_argument("--all", action="store_true", help="扫描默认品种列表")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--period", type=str, default="daily")
    parser.add_argument("--output-dir", type=str, default=None, help="JSON 输出目录")
    args = parser.parse_args()

    if args.symbols:
        symbols = [(s.strip().upper(), s.strip().upper()) for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = [(s, s) for s in DEFAULT_SYMBOLS]

    output_dir = args.output_dir or os.path.join(SCRIPT_DIR, "reports")
    os.makedirs(output_dir, exist_ok=True)

    today_str = date.today().strftime("%Y%m%d")
    print(f"[因子择时] 采集 {len(symbols)} 品种（term_basis + inventory + FDC K线）...")

    raw_list = []
    for sym, name in symbols:
        kf = {"momentum": None, "skew": None, "corr": None}
        r = _fdc_get_kline_sync(sym, days=args.days, period=args.period)
        if r["success"]:
            kf = _compute_kline_factors(r["data"])
        else:
            print(f"  ⚠ {sym}: FDC K线失败 {r.get('error', '')}")
        carry = _carry_factor(sym)
        inv_pct = _inventory_pct(sym)
        raw_list.append({
            "symbol": sym,
            "name": name,
            "carry": carry,
            "momentum": kf["momentum"],
            "inventory_pct": inv_pct,
            "skew": kf["skew"],
            "corr": kf["corr"],
        })
        print(f"  · {sym}: carry={carry} mom={kf['momentum']} inv%={inv_pct} skew={kf['skew']} corr={kf['corr']}")

    print(f"[因子择时] 计算 {len(raw_list)} 品种截面打分...")
    scorer = FactorTimingScorer()
    summary = scorer.score(raw_list, mode="full")

    out_path = os.path.join(output_dir, f"full_scan_factor_timing_{today_str}.json")
    _atomic_write(out_path, summary)
    print(f"[因子择时] 产出: {out_path} ({len(summary['all_ranked'])} 品种)")


if __name__ == "__main__":
    main()
