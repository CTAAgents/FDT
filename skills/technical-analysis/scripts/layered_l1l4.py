"""
L1-L4 分层累加打分 — technical-analysis 子 Agent（观澜）自有模块
===============================================================
从 quant-daily 的 strategies/layered_l1l4.py 迁移而来（2026-07-14 §2/§3 重构）。
去掉 BaseStrategy / registry 注册框架，改为独立可调用类；L1-L4 打分逻辑
来自同目录 l1l4_scoring.py（自包含，assess_trend_maturity 走 FDC）。

供观澜产出 full_scan_l1l4_{date}.json，由其 data_interface.load_l1l4_scan 读取。
"""

import os
import sys
import pandas as pd
from statistics import mean, stdev

# ── 路径自举：确保本目录在 sys.path（便于 `from l1l4_scoring import ...`）──
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from l1l4_scoring import calculate_composite_score


class LayeredL1L4Scorer:
    """L1-L4 分层累加打分（观澜技术分析工具）。

    输出结构对齐原 quant-daily SignalResult.to_dict()：
    {symbol, name, price, change_pct, volume, total, abs, direction, grade,
     adx, rsi, cci, ma_slope, macd_cross, dc20_break, ma_align, z_score,
     stage, _tdx_patched, veto, cons, atr, l1, l2, l3, l4}
    """

    @property
    def name(self) -> str:
        return "layered_l1l4"

    @property
    def display_name(self) -> str:
        return "L1-L4分层累加打分"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: dict = None,
        df_map: dict = None,
        **kwargs,
    ) -> dict:
        """执行 L1-L4 分层打分。

        需要 tech_list 中每个 dict 包含:
            - symbol, name, last_price, open_interest
            - ADX, RSI14, CCI20, MA20_SLOPE, macd_cross, dc20_break, ma_align, ATR
            - 以及 l1l4_scoring.calculate_composite_score 所需全部指标字段
        """
        results = []

        for tech in tech_list:
            sym = tech.get("symbol", "")
            name = tech.get("name", sym)
            price = tech.get("last_price", tech.get("price", 0))

            sym_scoring = {
                "last_price": price,
                "open_interest": tech.get("open_interest", 0),
            }

            # 从 df_map 或 tech 中获取收盘价序列
            closes = None
            if df_map and sym in df_map:
                closes = df_map[sym]["close"].tolist()
            elif "closes" in tech:
                closes = tech["closes"]

            sc = calculate_composite_score(tech, sym_scoring, 0, closes, None)

            direction = "bull" if sc["direction"] == "BUY" else ("bear" if sc["direction"] == "SELL" else "neutral")
            s = 1 if direction == "bull" else (-1 if direction == "bear" else 0)
            stage = sc["maturity"]["stage"]

            total = sc["total"] * s
            result = {
                "symbol": sym,
                "name": name,
                "price": round(price, 1),
                "change_pct": round(tech.get("change_pct", 0), 2),
                "volume": int(round(float(tech.get("volume", 0)))),
                "total": round(total),
                "abs": round(sc["total"]),
                "direction": direction,
                "grade": sc["grade"],
                "adx": round(tech.get("ADX", 0), 1),
                "rsi": round(tech.get("RSI14", 0), 1),
                "cci": round(tech.get("CCI20", 0), 1),
                "ma_slope": round(tech.get("MA20_SLOPE", 0), 2),
                "macd_cross": tech.get("macd_cross", "none"),
                "dc20_break": tech.get("dc20_break", "none"),
                "ma_align": tech.get("ma_align", "mixed"),
                "z_score": 0.0,
                "stage": stage,
                "_tdx_patched": tech.get("_tdx_patched", False),
                "veto": sc["veto_score"],
                "cons": 0,
                "atr": round(float(tech.get("ATR", tech.get("ATR14", tech.get("atr", 0)))), 1),
                "l1": round(sc["L1_score"] * s),
                "l2": round(sc["L2_score"] * s),
                "l3": round(sc["L3_score"] * s),
                "l4": round(sc["L4_score"] * s),
            }
            results.append(result)

        # ── 一致性计算 + Z-score ──
        self._enrich(results)

        # ── 排序 ──
        all_ranked = sorted(results, key=lambda r: r["abs"], reverse=True)

        # ── 构建输出 ──
        totals = [r["total"] for r in results]
        mu = mean(totals) if totals else 0
        sigma = stdev(totals) if len(totals) > 1 else 1

        bear_totals = [r["total"] for r in results if r["total"] < 0]
        bull_totals = [r["total"] for r in results if r["total"] > 0]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        summary = {
            "_meta": {
                "mode": "layered",
                "strategy": self.name,
                "total": len(results),
                "bull": len([r for r in results if r["direction"] == "bull"]),
                "bear": len([r for r in results if r["direction"] == "bear"]),
                "z_mu": round(mu, 1),
                "z_sigma": round(sigma, 1),
                "z_mu_bear": round(mu_bear, 1) if mu_bear is not None else None,
                "z_sigma_bear": round(sigma_bear, 1) if sigma_bear is not None else None,
                "z_mu_bull": round(mu_bull, 1) if mu_bull is not None else None,
                "z_sigma_bull": round(sigma_bull, 1) if sigma_bull is not None else None,
            },
            "all_ranked": all_ranked,
            "bull_signals": [r for r in all_ranked if r["direction"] == "bull"],
            "bear_signals": [r for r in all_ranked if r["direction"] == "bear"],
        }
        return summary

    def _enrich(self, results: list[dict]):
        """计算 Z-score 和子层一致性"""
        bear_totals = [r["total"] for r in results if r["direction"] == "bear"]
        bull_totals = [r["total"] for r in results if r["direction"] == "bull"]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        for r in results:
            # Z-score (方向感知)
            if r["direction"] == "bear" and sigma_bear and sigma_bear > 0:
                r["z_score"] = round((r["total"] - mu_bear) / sigma_bear, 2)
            elif r["direction"] == "bull" and sigma_bull and sigma_bull > 0:
                r["z_score"] = round((r["total"] - mu_bull) / sigma_bull, 2)
            else:
                r["z_score"] = 0.0

            # 子层一致性
            layers = [r.get(k, 0) for k in ("l1", "l2", "l3", "l4")]
            r["cons"] = sum(1 for l in layers if (l > 0 and r["total"] > 0) or (l < 0 and r["total"] < 0))


if __name__ == "__main__":
    # 直接运行等价于 run_l1l4_scan.py（便于测试）
    from run_l1l4_scan import main

    main()
