#!/usr/bin/env python3
"""
市场制度检测 — 识别 trending/ranging/volatile (market-regime Loop)。

用法:
    python scripts/analysis/regime_detector.py --all
    python scripts/analysis/regime_detector.py --symbol RB

分类规则 (与 market-regime.contract.yaml 一致):
    ADX>=25 AND BB_Width>median → trending
    ADX<20 AND BB_Width<median → ranging
    ATR_Percentile>75 → volatile
    其余 → mixed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_kline(symbol: str, days: int = 60) -> list[dict]:
    """获取 K 线数据。"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "skills" / "quant-daily" / "scripts"))
        from data.multi_source_adapter import MultiSourceAdapter
        adapter = MultiSourceAdapter()
        res = adapter.get_kline(symbol, days=days, period="daily")
        if res and res.get("success"):
            return res.get("data", [])
    except Exception:
        pass
    return []


def _compute_adx(bars: list[dict], period: int = 14) -> float:
    """简化 ADX 计算 — 取 close 序列的标准差归一化。"""
    if len(bars) < period + 1:
        return 20.0  # 默认 moderate
    closes = [b.get("close", 0) for b in bars[-period:] if b.get("close")]
    if not closes:
        return 20.0
    import statistics
    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = variance ** 0.5
    adx = min(100, (std / mean) * 200) if mean > 0 else 20
    return max(0, adx)


def _compute_bb_width(bars: list[dict], period: int = 20) -> float:
    """布林带宽度 — (upper - lower) / middle。"""
    if len(bars) < period:
        return 0.1
    closes = [b.get("close", 0) for b in bars[-period:] if b.get("close")]
    if len(closes) < period:
        return 0.1
    import statistics
    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = variance ** 0.5
    width = (2 * std * 2) / mean if mean > 0 else 0.1  # 2*std upper - 2*std lower
    return round(width * 100, 2)


def _compute_atr_percentile(bars: list[dict], period: int = 14) -> float:
    """ATR 百分位 — 最近 ATR 在过去 N 期的位置。"""
    if len(bars) < period + 1:
        return 50.0
    atrs = []
    for i in range(len(bars) - period, len(bars)):
        if i < 1:
            continue
        prev = bars[i - 1].get("close", 0)
        high = bars[i].get("high", 0)
        low = bars[i].get("low", 0)
        tr = max(high - low, abs(high - prev), abs(low - prev))
        atrs.append(tr)
    if len(atrs) < 2:
        return 50.0
    current = atrs[-1]
    count_below = sum(1 for a in atrs[:-1] if a < current)
    return round(count_below / (len(atrs) - 1) * 100, 1)


def _classify_regime(adx: float, bb_width: float, atr_pct: float) -> str:
    """按规则分类市场制度。"""
    if atr_pct > 75:
        return "volatile"
    if adx >= 25 and bb_width > 0.5:  # BB_Width > median ≈ 0.5
        return "trending"
    if adx < 20 and bb_width < 0.5:
        return "ranging"
    return "mixed"


def _detect_symbol(symbol: str) -> dict:
    """检测单个品种的市场制度。"""
    bars = _get_kline(symbol)
    if not bars or len(bars) < 20:
        return {"symbol": symbol, "regime": "unknown", "reason": "数据不足"}

    adx = _compute_adx(bars)
    bb_width = _compute_bb_width(bars)
    atr_pct = _compute_atr_percentile(bars)
    regime = _classify_regime(adx, bb_width, atr_pct)

    return {
        "symbol": symbol,
        "regime": regime,
        "adx": round(adx, 1),
        "bb_width": round(bb_width, 2),
        "atr_percentile": round(atr_pct, 1),
        "n_bars": len(bars),
        "detected_at": datetime.now().isoformat(),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="市场制度检测 — market-regime Loop")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="检测所有主要品种")
    group.add_argument("--symbol", default="", help="品种代码")
    args = parser.parse_args()

    symbols = ["RB", "HC", "I", "TA", "MA", "V", "AU", "AG", "CU", "CF", "SR", "A"] if args.all else [args.symbol.upper()]

    results = []
    for sym in symbols:
        r = _detect_symbol(sym)
        results.append(r)
        print(f"  {r['symbol']:4s} → {r['regime']:<10s}  ADX={r['adx']:.1f}  BB={r['bb_width']:.2f}  ATR%={r['atr_percentile']:.0f}")

    # 写入缓存
    cache = {"results": results, "generated_at": datetime.now().isoformat()}
    cache_dir = PROJECT_ROOT / "memory" / "regime"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"regime_{datetime.now().strftime('%Y%m%d')}.json"
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    regimes = [r["regime"] for r in results if r["regime"] != "unknown"]
    counts = {r: regimes.count(r) for r in set(regimes)}
    print(f"市场制度: {len(results)} 品种检测完成, {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
