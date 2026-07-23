#!/usr/bin/env python3
"""
多源数据适配器 v4.0.0 — FDC 瘦包装器 [DEPRECATED]
===================================================

2026-07-13: 已被 futures_data_core (FDC) 统一数据引擎取代。
保留本文件作为**向后兼容层**，所有方法委托给 FDC 处理。
新代码请直接 ``from futures_data_core import get_kline, get_quote`` 等。

接口兼容：
  - MultiSourceAdapter.get_kline(variety, days, period, contract)
     → {"success": bool, "data": [...], "data_source": "fdc/tqsdk/tdx", ...}
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

# ── 确保 FDC 可导入 ──
_FDT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # skills/ ↑↑↑ → FDT 根
if str(_FDT_ROOT) not in sys.path:
    sys.path.insert(0, str(_FDT_ROOT))

from futures_data_core import get_kline as _fdc_get_kline


def _fdc_sync(variety: str, days: int = 120, period: str = "daily") -> dict:
    """同步包装 FDC get_kline，返回 dict 兼容旧接口。"""
    try:
        payload = asyncio.run(_fdc_get_kline(variety, period=period, days=days))
        meta = payload.meta
        grade = meta.get("data_grade_label", "")
        # 先计算数据源标签（穿透到 FDC 的真实底层源）
        _sources_list = meta.get("sources", ["fdc"])
        _source_label = _sources_list[0] if isinstance(_sources_list, list) else str(_sources_list)
        if grade in ("UNAVAILABLE", "STALE"):
            return {"success": False, "data": [], "data_source": grade,
                    "error": f"FDC grade={grade}"}
        bars_raw = payload.data.get("bars", [])
        if not bars_raw:
            return {"success": False, "data": [], "data_source": _source_label,
                    "error": "FDC 返回空 K 线"}
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
                "data_source": _source_label,
                "confidence": 1.0,
            })
        return {"success": True, "data": records, "data_source": _source_label, "confidence": 1.0}
    except Exception as e:
        return {"success": False, "data": [], "data_source": "fdc_error", "error": str(e)}


class MultiSourceAdapter:
    """Deprecated: FDC 瘦包装器。

    所有数据请求委托给 ``futures_data_core``（QMT/TDX/TqSDK 统一降级链）。
    新代码请直接导入 FDC 对应 API。
    """

    def __init__(self, *args, **kwargs):
        self._warned = False

    def _deprecated(self, method: str = "") -> None:
        if not self._warned:
            self._warned = True
            warnings.warn(
                f"[DEPRECATED] MultiSourceAdapter.{method} — 请改用 "
                f"``from futures_data_core import {method.replace('get_', '')}``",
                DeprecationWarning, stacklevel=3,
            )

    def get_kline(self, variety: str, days: int = 120,
                  period: str = "daily", **kwargs) -> dict:
        """获取 K 线数据。委托 FDC。兼容 old callers.

        Args:
            variety: 品种代码，如 "CU"
            days: 历史天数
            period: "daily" | "60m" | "120m" | "240m" 等
            **kwargs: 旧接口中的 contract/start_date/end_date 等（已忽略）

        Returns:
            {"success": bool, "data": [...], "data_source": str}
        """
        self._deprecated("get_kline")
        return _fdc_sync(variety, days=days, period=period)

    def get_indicators(self, symbol: str) -> dict:
        """获取技术指标。委托 FDC。"""
        self._deprecated("get_indicators")
        try:
            from futures_data_core.indicators.core import compute_indicators
            import numpy as np

            result = compute_indicators(symbol)
            if result:
                return {"success": True, **result}
        except Exception as e:
            pass
        return {"success": False, "error": f"FDC indicators unavailable: {e}" if 'e' in dir() else "unknown"}

    def get_term_structure(self, variety: str) -> dict:
        """获取期限结构。委托 FDC。"""
        self._deprecated("get_term_structure")
        try:
            payload = asyncio.run(
                __import__("futures_data_core", fromlist=["get_term_structure"]).get_term_structure(variety)
            )
            if payload and payload.data:
                ts = payload.data
                sources = payload.meta.get("sources", ["fdc"])
                return {"success": True, "data_source": sources[0], **ts}
        except Exception:
            pass
        return {"success": False, "error": f"term_structure {variety} 不可用"}

    def get_quote(self, symbol: str, *args, **kwargs) -> Optional[dict]:
        """获取行情快照。委托 FDC。"""
        self._deprecated("get_quote")
        try:
            payload = asyncio.run(
                __import__("futures_data_core", fromlist=["get_quote"]).get_quote(symbol)
            )
            if payload:
                return payload.data
        except Exception:
            pass
        return None
