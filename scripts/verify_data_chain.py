"""端到端数据链路验证脚本 [INDEPENDENT]。

验证 FDT 数据源改造后，以下链路是否正常工作：
  1. K 线数据 (get_kline)
  2. 技术指标 (compute_indicators)
  3. F10 衍生品数据 (term_structure / spread / basis / warrant / fundamental)
  4. F10 综合报告 (get_f10)

输出每个调用的：
  - 数据来源 (datacore / TDX / QMT / 缓存 / UNAVAILABLE)
  - 数据等级 (FRESH / ACCEPTABLE / STALE / UNAVAILABLE)
  - 数据规模（K 线根数、字段数等）
  - 是否成功
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

# 启用 DEBUG 日志，观察降级链每一步
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

# 使用 FDT 包内接口（不走 data_source_adapter，直接验证 futures_data_core 本身）
import futures_data_core as fdc


def _safe_getattr(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for part in path.split("."):
        try:
            cur = getattr(cur, part)
        except AttributeError:
            try:
                cur = cur.get(part) if hasattr(cur, "get") else default
            except Exception:
                return default
    return cur


def _summarize_kline(payload: Any) -> dict[str, Any]:
    """总结 K 线 A2APayload。"""
    data = payload.data if hasattr(payload, "data") else None
    if not data:
        return {"success": False, "reason": "data 为空"}
    if isinstance(data, list):
        bars = data
    elif isinstance(data, dict):
        bars = data.get("bars") or data.get("klines") or []
        if not bars and any(k in data for k in ("close", "high", "low")):
            bars = [data]
    else:
        bars = []
    return {
        "success": len(bars) > 0,
        "bars_count": len(bars),
        "sources": getattr(payload, "meta", {}).get("sources", []) if hasattr(payload, "meta") else [],
        "data_grade": getattr(payload, "meta", {}).get("data_grade_label", "?") if hasattr(payload, "meta") else "?",
        "summary": getattr(payload, "summary", "") if hasattr(payload, "summary") else "",
    }


def _summarize_f10(payload: Any, name: str) -> dict[str, Any]:
    """总结 F10 子块。"""
    data = payload.data if hasattr(payload, "data") else None
    meta = getattr(payload, "meta", {}) if hasattr(payload, "meta") else {}
    info = {
        "name": name,
        "success": data is not None and data != {} and data != [],
        "sources": meta.get("sources", []),
        "data_grade": meta.get("data_grade_label", "?"),
        "data_keys": list(data.keys()) if isinstance(data, dict) else f"<{type(data).__name__}>",
    }
    if isinstance(data, dict):
        # 检查 data 字段
        nested = data.get("data")
        if nested is None or nested == {} or nested == []:
            info["warning"] = "data.data 为空"
    return info


async def main(symbol: str = "RB") -> int:
    print(f"\n=== FDT 数据链路验证 — 品种: {symbol} ===\n")

    # ── 1. K 线 ──────────────────────────────────────
    print("[1/4] K 线数据 (get_kline, days=30)")
    try:
        kl = await fdc.get_kline(symbol, period="daily", days=30)
        info = _summarize_kline(kl)
        print(f"  → {info}")
        if not info["success"]:
            print("  [FAIL] K 线为空，下游技术指标将无法计算")
            return 1
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return 1

    # ── 2. compute_indicators ───────────────────────
    print("\n[2/4] 技术指标 (compute_indicators)")
    try:
        # kl.data 是 KlineData.to_dict() 的结果: {symbol, bars: [{date,open,high,low,close,volume,...}]}
        raw = kl.data
        if isinstance(raw, dict) and "bars" in raw:
            bars_list = raw["bars"]
        elif isinstance(raw, list):
            bars_list = raw
        else:
            bars_list = [raw]
        # compute_indicators 期望 dict of arrays: {"close": [...], "high": [...], ...}
        if bars_list and isinstance(bars_list[0], dict):
            df_dict = {
                "date": [b.get("date") for b in bars_list],
                "open": [b.get("open") for b in bars_list],
                "high": [b.get("high") for b in bars_list],
                "low": [b.get("low") for b in bars_list],
                "close": [b.get("close") for b in bars_list],
                "volume": [b.get("volume") for b in bars_list],
            }
        elif bars_list and hasattr(bars_list[0], "close"):
            # KlineBar 对象列表
            df_dict = {
                "date": [b.date for b in bars_list],
                "open": [b.open for b in bars_list],
                "high": [b.high for b in bars_list],
                "low": [b.low for b in bars_list],
                "close": [b.close for b in bars_list],
                "volume": [b.volume for b in bars_list],
            }
        else:
            df_dict = bars_list
        indicators = fdc.compute_indicators(df_dict, "all")
        keys = list(indicators.keys())
        expected = {"MA", "EMA", "RSI", "MACD", "BOLL", "KDJ", "ATR", "CCI",
                    "WILLIAMS_R", "OBV", "ADX", "BIAS", "ROC", "MOM", "STDDEV", "VOL_MA"}
        missing = expected - set(keys)
        # 检查类型：MA 应该是 ndarray，BOLL 应该是 tuple
        ma_type = type(indicators.get("MA")).__name__
        boll_type = type(indicators.get("BOLL")).__name__
        print(f"  → 指标数: {len(keys)}, 缺失: {missing or '无'}")
        print(f"  → MA 类型: {ma_type}, BOLL 类型: {boll_type}")
        if missing:
            print(f"  [FAIL] 缺失指标: {missing}")
            return 1
        if ma_type != "ndarray":
            print(f"  [FAIL] MA 类型应为 ndarray，实际 {ma_type}")
            return 1
        if boll_type != "tuple":
            print(f"  [FAIL] BOLL 类型应为 tuple，实际 {boll_type}")
            return 1
        print("  [OK] 指标键名和类型正确")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return 1

    # ── 3. F10 子块 ──────────────────────────────────
    print("\n[3/4] F10 衍生品数据")
    f10_results: list[dict[str, Any]] = []

    try:
        ts = await fdc.get_term_structure(symbol)
        f10_results.append(_summarize_f10(ts, "term_structure"))
    except Exception as e:
        f10_results.append({"name": "term_structure", "error": f"{type(e).__name__}: {e}"})

    try:
        sp = await fdc.get_spread(symbol)
        f10_results.append(_summarize_f10(sp, "spread"))
    except Exception as e:
        f10_results.append({"name": "spread", "error": f"{type(e).__name__}: {e}"})

    try:
        bs = await fdc.get_basis(symbol)
        f10_results.append(_summarize_f10(bs, "basis"))
    except Exception as e:
        f10_results.append({"name": "basis", "error": f"{type(e).__name__}: {e}"})

    try:
        wt = await fdc.get_warrant(symbol)
        f10_results.append(_summarize_f10(wt, "warrant"))
    except Exception as e:
        f10_results.append({"name": "warrant", "error": f"{type(e).__name__}: {e}"})

    try:
        fm = await fdc.get_fundamental(symbol, use_llm=False)
        f10_results.append(_summarize_f10(fm, "fundamental"))
    except Exception as e:
        f10_results.append({"name": "fundamental", "error": f"{type(e).__name__}: {e}"})

    for r in f10_results:
        print(f"  → {r}")

    # ── 4. F10 综合 ──────────────────────────────────
    print("\n[4/4] F10 综合报告 (get_f10)")
    try:
        f10 = await fdc.get_f10(symbol)
        data = f10.data
        if isinstance(data, dict):
            sub_keys = list(data.keys())
            print(f"  → 子块: {sub_keys}")
            print(f"  → sources: {f10.meta.get('sources', [])}")
            print(f"  → data_grade: {f10.meta.get('data_grade_label', '?')}")
            # 检查每个子块
            for k in ("term_structure", "spread", "basis", "warrant", "fundamental"):
                v = data.get(k)
                if v is None or v == {} or v == []:
                    print(f"  [WARN] {k} 为空")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return 1

    print("\n=== 验证完成 ===\n")
    return 0


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "RB"
    sys.exit(asyncio.run(main(sym)))
