"""
L1-L4 分层累加打分策略
====================
从 scan_all.py 提取的独立策略模块。
L1=趋势动量+持仓(35%), L2=量价配合(35%), L3=价格结构(20%), L4=确认信号(10%)

依赖:
    - signals.scoring_system.calculate_composite_score
    - indicators.core.assess_trend_maturity

注册为 "layered_l1l4" (默认)
"""

import sys, os
import pandas as pd
from statistics import mean, stdev
from typing import Optional

# ── 路径自举 ──
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy
from signals.scoring_system import calculate_composite_score


class LayeredL1L4Strategy(BaseStrategy):
    """L1-L4 分层累加打分"""

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
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        执行 L1-L4 分层打分。

        需要 tech_list 中每个 dict 包含:
            - symbol, name, last_price, open_interest
            - ADX, RSI14, CCI20, MA20_SLOPE, macd_cross, dc20_break, ma_align
        df_map 用于获取 kline_closes（计算 L4 等指标）。如不传则
        尝试从 tech_list 的 'closes' 字段读取。
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
            result = SignalResult(
                symbol=sym,
                name=name,
                total=total,
                abs_score=sc["total"],
                direction=direction,
                grade=sc["grade"],
                sub_scores={
                    "l1": sc["L1_score"] * s,
                    "l2": sc["L2_score"] * s,
                    "l3": sc["L3_score"] * s,
                    "l4": sc["L4_score"] * s,
                },
                veto=sc["veto_score"],
                price=price,
                change_pct=round(tech.get("change_pct", 0), 2),
                volume=int(round(float(tech.get("volume", 0)))),
                adx=tech.get("ADX", 0),
                rsi=tech.get("RSI14", 0),
                cci=tech.get("CCI20", 0),
                ma_slope=tech.get("MA20_SLOPE", 0),
                macd_cross=tech.get("macd_cross", "none"),
                dc20_break=tech.get("dc20_break", "none"),
                ma_align=tech.get("ma_align", "mixed"),
                stage=stage,
                atr=float(tech.get("ATR", tech.get("ATR14", tech.get("atr", 0)))),
                _tdx_patched=tech.get("_tdx_patched", False),
            )
            results.append(result)

        # ── 一致性计算 + Z-score ──
        self._enrich(results)

        # ── 排序 ──
        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)

        # ── 构建输出 ──
        totals = [r.total for r in results]
        mu = mean(totals) if totals else 0
        sigma = stdev(totals) if len(totals) > 1 else 1

        bear_totals = [r.total for r in results if r.total < 0]
        bull_totals = [r.total for r in results if r.total > 0]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        summary = {
            "_meta": {
                "mode": "layered",
                "strategy": self.name,
                "total": len(results),
                "bull": len([r for r in results if r.direction == "bull"]),
                "bear": len([r for r in results if r.direction == "bear"]),
                "z_mu": round(mu, 1),
                "z_sigma": round(sigma, 1),
                "z_mu_bear": round(mu_bear, 1) if mu_bear is not None else None,
                "z_sigma_bear": round(sigma_bear, 1) if sigma_bear is not None else None,
                "z_mu_bull": round(mu_bull, 1) if mu_bull is not None else None,
                "z_sigma_bull": round(sigma_bull, 1) if sigma_bull is not None else None,
            },
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
        }
        return summary

    def _enrich(self, results: list[SignalResult]):
        """计算 Z-score 和子层一致性"""
        bear_totals = [r.total for r in results if r.direction == "bear"]
        bull_totals = [r.total for r in results if r.direction == "bull"]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        for r in results:
            # Z-score (方向感知)
            if r.direction == "bear" and sigma_bear and sigma_bear > 0:
                r.z_score = round((r.total - mu_bear) / sigma_bear, 2)
            elif r.direction == "bull" and sigma_bull and sigma_bull > 0:
                r.z_score = round((r.total - mu_bull) / sigma_bull, 2)
            else:
                r.z_score = 0.0

            # 子层一致性
            layers = [r.sub_scores.get(k, 0) for k in ("l1", "l2", "l3", "l4")]
            r.consistency = sum(1 for l in layers if (l > 0 and r.total > 0) or (l < 0 and r.total < 0))


# ── 自动注册 ──
register_strategy(LayeredL1L4Strategy)
