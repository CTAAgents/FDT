"""
期现基差 OU 均值回归策略 — Basis Reversion（G35 Phase 2 续）。

消费 ``ctx["basis_history"]``（scan_all 每日 100ppi 抓取 + JSONL 持久化 → provider 读取），
对每品种基差序列做 OU 拟合 + 滚动 Z-score → 信号。

数据通路：
  - get_basis_batch() 日调用 → 写入 memory/basis_history.jsonl（append-only）
  - fetch_basis_history() 读取最近 N 天 → 构建 basis_history dict
  - 策略 compute 仅消费 ctx["basis_history"]，离线为空时无操作
  零新外部数据源（复用 basis.py 已有 100ppi 抓取 + xtquant 期货价）。
"""

from __future__ import annotations
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal
from .spread_reversion_strategy import _fit_ou_half_life, kalman_filter_ou


# ── 阈值配置 ──
Z_ENTRY = 2.0
MIN_BARS = 60
HALF_LIFE_MAX = 120.0
HALF_LIFE_MIN = 2.0

# ── JSONL 持久化路径（相对 FDT_ROOT）──
_BASIS_LOG_RELPATH = "memory/basis_history.jsonl"


def _repo_root() -> Path:
    """向上导航至 FDT 仓库根目录（from strategies/ → skills/quant-daily/scripts/ → ... → 根）。"""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _basis_log_path() -> str:
    return str(_repo_root() / _BASIS_LOG_RELPATH)


# ════════════════════════════════════════════════════════════
# 存储层
# ════════════════════════════════════════════════════════════

def store_basis_snapshot(items: dict, data_date: Optional[str] = None) -> None:
    """将 get_basis_batch 返回的 items 追加到 JSONL 日志。

    每日调用一次（scan_all 受保护段落中），逐品种记录现货/期货/基差。
    """
    if not items:
        return
    record = {
        "date": data_date or date.today().strftime("%Y-%m-%d"),
        "ts": datetime.now().isoformat(),
        "items": {},
    }
    for sym_lower, item in items.items():
        record["items"][sym_lower] = {
            "spot": item.get("spot_price"),
            "futures": item.get("futures_price"),
            "basis": item.get("basis"),
            "basis_pct": item.get("basis_pct"),
        }
    path = _basis_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ════════════════════════════════════════════════════════════
# Provider：读取历史的基差序列
# ════════════════════════════════════════════════════════════

def fetch_basis_history(symbol: str, days: int = 120) -> Optional[dict]:
    """从 JSONL 日志读取某品种最近 N 天的基差序列。

    Returns:
        ``{"spot": [float], "futures": [float], "basis": [float],
        "basis_pct": [float], "dates": [str]}``
        或 None（无数据/解析失败）。
    """
    path = _basis_log_path()
    if not os.path.isfile(path):
        return None

    sym = symbol.lower()
    records: list[dict] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            item = rec.get("items", {}).get(sym)
            if item is None:
                continue
            if item.get("basis") is not None:
                records.append({
                    "date": rec.get("date", ""),
                    "spot": item["spot"],
                    "futures": item["futures"],
                    "basis": item["basis"],
                    "basis_pct": item["basis_pct"],
                })

    if len(records) < MIN_BARS:
        return None
    recent = records[-days:]
    return {
        "variety": symbol.upper(),
        "dates": [r["date"] for r in recent],
        "spot": [float(r["spot"]) for r in recent],
        "futures": [float(r["futures"]) for r in recent],
        "basis": [float(r["basis"]) for r in recent],
        "basis_pct": [float(r["basis_pct"]) if r["basis_pct"] is not None else 0.0
                      for r in recent],
    }


# ════════════════════════════════════════════════════════════
# 策略类
# ════════════════════════════════════════════════════════════

class BasisReversionStrategy(BaseStrategyV2):
    """期现基差 OU 均值回归：基差大幅偏离历史均值时回归交易。"""

    @property
    def name(self) -> str:
        return "basis_reversion"

    @property
    def display_name(self) -> str:
        return "期现基差OU均值回归(做空回归)"

    @property
    def signal_type(self) -> str:
        return "basis_reversion"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing", "stability"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        ctx = context or {}
        bh = ctx.get("basis_history") or {}
        if not bh:
            return signals

        for sym, info in bh.items():
            basis_raw = info.get("basis")
            if not basis_raw or len(basis_raw) < MIN_BARS:
                continue
            basis = np.asarray(basis_raw, dtype=float)

            # OU 半衰期门禁
            hl = _fit_ou_half_life(basis)
            if not np.isfinite(hl) or hl > HALF_LIFE_MAX or hl < HALF_LIFE_MIN:
                continue

            # KF 自适应 z
            kf = kalman_filter_ou(basis)
            z = kf["z_score"]
            if abs(z) < Z_ENTRY:
                continue

            direction = "bull" if z < 0 else "bear"
            raw = min(1.0, abs(z) / 3.0)
            basis_pct = info.get("basis_pct", [0.0])
            meta = {
                "variety": str(sym),
                "basis": round(float(basis[-1]), 2),
                "basis_pct": round(float(basis_pct[-1]), 4) if basis_pct else None,
                "z_score": round(z, 2),
                "half_life": round(hl, 1),
                "type": "basis_reversion",
                "kf_state_sigma": round(float(kf["state_sigma"][-1]), 4),
                "kf_innov_var": round(kf["last_innovation_var"], 4),
            }
            signals.append(RawSignal(
                symbol=str(sym), direction=direction,
                signal_type=f"{self.signal_type}.{str(sym).lower()}",
                raw_score=raw, strategy_name=self.name, meta=meta,
            ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100
            grade = "WATCH" if raw > 0.8 else "WEAK" if raw > 0.4 else "NOISE"
            ss = ScoredSignal(
                symbol=s.symbol, direction=s.direction,
                signal_type=s.signal_type, strategy_name=self.name,
                total=round(total, 1), abs_score=round(raw * 100, 1),
                grade=grade, weight=0.7,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
