"""
因子择时打分 — fundamental-data-collector（探源）自有模块
========================================================
从 quant-daily 的 strategies/factor_timing.py 迁移而来（2026-07-14 §2/§3 重构）。
去掉 BaseStrategy / registry 注册框架，改为独立可调用类；数据依赖改为本 skill 自有
数据模块（term_basis / inventory）+ FDC 行情，不再依赖 quant-daily 的
MultiSourceAdapter / DuckDBStore。

五因子（截面标准化 → 十分组投票 → 复合方向）：
  - 展期收益率(carry)   : term_basis.query_term(symbol)["spread"] / near
  - 动量(momentum)      : FDC K线 N日收益率
  - 反向仓单(inv)        : inventory.query_inventory(symbol) 季节性分位数（高分位=高库存=偏空→反向）
  - 偏度(skew)          : FDC K线日收益分布偏度
  - 量价相关性(corr)     : FDC K线 ΔP 与 ΔVolume 的 N日相关性

供探源产出 full_scan_factor_timing_{date}.json，由其 data_interface.load_factor_timing_scan 读取。
"""

import os
import sys
import numpy as np
import pandas as pd
from statistics import mean, stdev
from typing import Optional

# ── 路径自举 ──
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
# FDT 根（含 futures_data_core/ 包）：scripts → fundamental-data-collector → skills → futures-debate-team
_FD_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPTS_DIR))))
if _FD_ROOT not in sys.path:
    sys.path.insert(0, _FD_ROOT)

from term_basis import query_term
from inventory import query_inventory


# 五因子 → 层映射（沿用原 factor_timing factor_layer_map 语义）
FACTOR_LAYER_MAP = {
    "carry": 1,     # 展期收益率 → L1 资金结构
    "momentum": 2,  # 动量 → L2 量价
    "inventory": 3, # 反向仓单 → L3 结构
    "skew": 4,      # 偏度 → L4 确认
    "corr": 2,      # 量价相关性 → L2 量价
}

# 因子方向语义：值为正时代表什么方向？
#   carry: 正值=back结构（近月升水）=偏多
#   momentum: 正值=上涨=偏多
#   inventory: 原始分位数越高=库存越高=偏空 → 反向因子，取负
#   skew: 正偏度=右尾=急涨后回落风险 → 这里按原策略：正偏度视为偏多信号（追涨）
#   corr: 量价正相关（放量上涨）=偏多
_FACTOR_SIGNAL_POLARITY = {
    "carry": 1.0,
    "momentum": 1.0,
    "inventory": -1.0,   # 反向仓单
    "skew": 1.0,
    "corr": 1.0,
}


def _zscore(values: np.ndarray) -> np.ndarray:
    """截面 Z-score；样本<2 时返回全 0。"""
    vals = np.asarray(values, dtype=float)
    mu = np.nanmean(vals)
    sigma = np.nanstd(vals)
    if sigma == 0 or not np.isfinite(sigma):
        return np.zeros_like(vals)
    return (vals - mu) / sigma


def _decile_groups(series: pd.Series) -> dict:
    """对单因子做十分组（g1 最小 … g10 最大），返回 {symbol: 'gN'}。"""
    valid = series.dropna()
    if len(valid) < 2:
        return {sym: "g5" for sym in series.index}
    # rank pct → 1..10
    ranks = valid.rank(pct=True)
    out = {}
    for sym, rp in ranks.items():
        g = int(np.clip(round(rp * 10), 1, 10))
        out[sym] = f"g{g}"
    # 缺失值归中组
    for sym in series.index:
        if sym not in out:
            out[sym] = "g5"
    return out


class FactorTimingScorer:
    """五因子截面择时打分（探源基本面工具）。

    输入 raw_list: 每个 dict 含
        symbol, name,
        carry (float|None), momentum (float|None),
        inventory_pct (float|None, 0-100), skew (float|None), corr (float|None)
    """

    @property
    def name(self) -> str:
        return "factor_timing"

    @property
    def display_name(self) -> str:
        return "五因子截面择时"

    def score(self, raw_list: list[dict], mode: str = "full", **kwargs) -> dict:
        if not raw_list:
            return {"_meta": {"mode": "factor", "strategy": self.name, "total": 0},
                    "all_ranked": [], "bull_signals": [], "bear_signals": []}

        syms = [r.get("symbol", "") for r in raw_list]
        names = {r.get("symbol", ""): r.get("name", r.get("symbol", "")) for r in raw_list}

        raw = pd.DataFrame({
            "carry": [r.get("carry") for r in raw_list],
            "momentum": [r.get("momentum") for r in raw_list],
            "inventory": [r.get("inventory_pct") for r in raw_list],
            "skew": [r.get("skew") for r in raw_list],
            "corr": [r.get("corr") for r in raw_list],
        }, index=syms)

        # 反向仓单：库存分位数取负（高分位=高库存=偏空）
        inv_signed = raw["inventory"] * _FACTOR_SIGNAL_POLARITY["inventory"]

        # 截面 Z-score（按因子方向极性调整符号，使正向 Z = 偏多）
        z = pd.DataFrame(index=syms)
        z["carry"] = _zscore(raw["carry"].values) * _FACTOR_SIGNAL_POLARITY["carry"]
        z["momentum"] = _zscore(raw["momentum"].values) * _FACTOR_SIGNAL_POLARITY["momentum"]
        z["inventory"] = _zscore(inv_signed.values)   # 已取负
        z["skew"] = _zscore(raw["skew"].values) * _FACTOR_SIGNAL_POLARITY["skew"]
        z["corr"] = _zscore(raw["corr"].values) * _FACTOR_SIGNAL_POLARITY["corr"]

        # 十分组（按原始极性方向分组，g10=最偏多）
        deciles = {f: _decile_groups(raw[f] * _FACTOR_SIGNAL_POLARITY[f]) for f in raw.columns}

        results = []
        for sym in syms:
            zrow = z.loc[sym]
            zvals = zrow.values.astype(float)
            finite_mask = np.isfinite(zvals)
            if finite_mask.sum() == 0:
                total = 0.0
                direction = "neutral"
            else:
                # 复合分 = 各因子 Z 的等权均值（仅有限因子参与）
                total = float(np.mean(zvals[finite_mask]))
                direction = "bull" if total > 0.15 else ("bear" if total < -0.15 else "neutral")

            s = 1 if direction == "bull" else (-1 if direction == "bear" else 0)
            # 一致性：因子符号与复合方向一致的数量
            cons = int(np.sum((np.sign(zvals) * s) > 0)) if s != 0 else 0

            # 主驱动组（复合方向最极端的因子组）
            g_groups = [deciles[f].get(sym, "g5") for f in raw.columns]
            g10 = sum(1 for g in g_groups if g.startswith("g10"))
            g1 = sum(1 for g in g_groups if g.startswith("g1"))

            results.append({
                "symbol": sym,
                "name": names.get(sym, sym),
                "carry": None if pd.isna(raw.loc[sym, "carry"]) else round(float(raw.loc[sym, "carry"]), 4),
                "momentum": None if pd.isna(raw.loc[sym, "momentum"]) else round(float(raw.loc[sym, "momentum"]), 2),
                "inventory_pct": None if pd.isna(raw.loc[sym, "inventory"]) else round(float(raw.loc[sym, "inventory"]), 1),
                "skew": None if pd.isna(raw.loc[sym, "skew"]) else round(float(raw.loc[sym, "skew"]), 3),
                "corr": None if pd.isna(raw.loc[sym, "corr"]) else round(float(raw.loc[sym, "corr"]), 3),
                "z_carry": round(float(z.loc[sym, "carry"]), 2),
                "z_momentum": round(float(z.loc[sym, "momentum"]), 2),
                "z_inventory": round(float(z.loc[sym, "inventory"]), 2),
                "z_skew": round(float(z.loc[sym, "skew"]), 2),
                "z_corr": round(float(z.loc[sym, "corr"]), 2),
                "total": round(total, 2),
                "abs": round(abs(total), 2),
                "direction": direction,
                "cons": cons,
                "g_group": f"g10×{g10}" if g10 else (f"g1×{g1}" if g1 else "mid"),
                "n_factors": int(finite_mask.sum()),
            })

        all_ranked = sorted(results, key=lambda r: r["abs"], reverse=True)
        totals = [r["total"] for r in results]
        mu = mean(totals) if totals else 0
        sigma = stdev(totals) if len(totals) > 1 else 1

        summary = {
            "_meta": {
                "mode": "factor",
                "strategy": self.name,
                "total": len(results),
                "bull": len([r for r in results if r["direction"] == "bull"]),
                "bear": len([r for r in results if r["direction"] == "bear"]),
                "neutral": len([r for r in results if r["direction"] == "neutral"]),
                "z_mu": round(mu, 2),
                "z_sigma": round(sigma, 2),
                "factors": ["展期收益率", "动量", "反向仓单", "偏度", "量价相关性"],
            },
            "all_ranked": all_ranked,
            "bull_signals": [r for r in all_ranked if r["direction"] == "bull"],
            "bear_signals": [r for r in all_ranked if r["direction"] == "bear"],
        }
        return summary


if __name__ == "__main__":
    from run_factor_timing_scan import main
    main()
