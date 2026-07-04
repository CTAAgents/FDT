"""
真分层打分策略
=============
IC=-0.039（20日持有期），因子方向偏负 → 信号解读需注意反向。
默认使用截面排序→秩变换→等权汇总方法论。

注册为 "true_layered"（非默认，需通过 --strategy true_layered 显式指定）

⚠️ 注意：该策略的因子方向与 layered_l1l4 可能相反，
   下游 Agent 消费信号时需根据 _meta.strategy 字段区分解读策略。
"""

import sys, os
from typing import Optional
from statistics import mean, stdev

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy
from signals.true_layered_scoring import compute_true_layered_score


class TrueLayeredStrategy(BaseStrategy):
    """真分层打分 (截面排序→秩变换→等权汇总)"""

    @property
    def name(self) -> str:
        return "true_layered"

    @property
    def display_name(self) -> str:
        return "真分层打分(portfolio sort)"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
    ) -> dict:
        """
        执行真分层打分（截面排序→秩变换→等权汇总）。

        注意：IC偏负，方向解读与 layered_l1l4 可能相反。
        下游Agent通过 _meta.strategy 区分。
        """
        raw = compute_true_layered_score(tech_list)
        ranked = raw.get("ranked", [])

        results = []
        for c in ranked:
            net = c.get("net_rank", 0)
            direction = "bull" if net > 0 else ("bear" if net < 0 else "neutral")
            grade = (
                "STRONG"
                if abs(net) >= 25
                else ("WATCH" if abs(net) >= 15 else ("WEAK" if abs(net) >= 5 else "NOISE"))
            )
            src_tech = next((t for t in tech_list if t.get("symbol") == c["symbol"]), {})

            dims = c.get("dimensions", {})
            dim_keys = list(dims.keys())
            sub_scores = {}
            for i, k in enumerate(dim_keys):
                sub_scores[f"d{i+1}"] = dims[k]

            result = SignalResult(
                symbol=c["symbol"],
                name=src_tech.get("name", c["symbol"]),
                total=round(net * 2),
                abs_score=round(abs(net)),
                direction=direction,
                grade=grade,
                sub_scores=sub_scores,
                price=src_tech.get("last_price", 0),
                change_pct=round(src_tech.get("change_pct", 0), 2),
                volume=int(round(float(src_tech.get("volume", 0)))),
                adx=src_tech.get("ADX", 0),
                rsi=src_tech.get("RSI14", 0),
                cci=src_tech.get("CCI20", 0),
                ma_slope=src_tech.get("MA20_SLOPE", 0),
                macd_cross=src_tech.get("macd_cross", "none"),
                dc20_break=src_tech.get("dc20_break", "none"),
                ma_align=src_tech.get("ma_align", "mixed"),
                stage=src_tech.get("stage", src_tech.get("maturity_stage", "true_layered")),
                _tdx_patched=src_tech.get("_tdx_patched", False),
                extra={
                    "_true_layered_net_rank": c.get("net_rank"),
                    "_true_layered_avg_rank": c.get("avg_rank"),
                },
            )
            results.append(result)

        # ── 一致性计算 + Z-score（与 layered_l1l4 对齐） ──
        self._enrich(results)

        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)

        # ── 统计量（与 layered_l1l4 对齐） ──
        totals = [r.total for r in results]
        mu = mean(totals) if totals else 0
        sigma = stdev(totals) if len(totals) > 1 else 1
        bear_totals = [r.total for r in results if r.total < 0]
        bull_totals = [r.total for r in results if r.total > 0]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        return {
            "_meta": {
                "mode": "true_layered",
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
                **raw.get("meta", {}),
            },
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
            "true_layered_detail": raw,
        }

    def _enrich(self, results: list[SignalResult]):
        """计算 Z-score 和子层一致性（与 layered_l1l4 对齐）"""
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

            # 子层一致性（方向与总分一致则+1）
            layers = list(r.sub_scores.values())
            r.consistency = sum(
                1 for l in layers
                if (l > 0 and r.total > 0) or (l < 0 and r.total < 0)
            )
