"""
真分层打分策略
=============
⚠️ 已废弃: 该策略的 --reverse 模式已验证存在因子方向矛盾
    (IC=-0.039, 胜率43%), 目前保持代码但不作为活跃策略。

注册为 "true_layered"

如需修复后重新启用:
  1. 修复 true_layered_scoring.py 中的因子加权逻辑
  2. 重跑回测验证 IC 方向正确
  3. 将 register_strategy() 的最后一个参数改为 True
"""

import sys, os
from typing import Optional

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
        执行真分层打分（已废弃 — 因子方向矛盾未修复）。
        
        此策略不再维护。请在 scan_all.py 中使用默认的 layered_l1l4 策略。
        如需重新启用，需先修复 true_layered_scoring.py 中的因子方向问题。
        """
        import warnings
        warnings.warn(
            "true_layered 策略已废弃（因子方向矛盾未修复）。"
            "请使用默认策略 layered_l1l4。",
            DeprecationWarning, stacklevel=2
        )
        print("\n⚠️  true_layered 策略已废弃。输出格式可能与下游 Agent 不兼容。")
        print("   请使用 --strategy layered_l1l4（默认）\n")
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
                adx=src_tech.get("ADX", 0),
                rsi=src_tech.get("RSI14", 0),
                cci=src_tech.get("CCI20", 0),
                ma_slope=src_tech.get("MA20_SLOPE", 0),
                stage="true_layered",
                _tdx_patched=src_tech.get("_tdx_patched", False),
                extra={
                    "_true_layered_net_rank": c.get("net_rank"),
                    "_true_layered_avg_rank": c.get("avg_rank"),
                },
            )
            results.append(result)

        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)

        return {
            "_meta": {
                "mode": "true_layered",
                "strategy": self.name,
                "total": len(results),
                "bull": len([r for r in results if r.direction == "bull"]),
                "bear": len([r for r in results if r.direction == "bear"]),
                **raw.get("meta", {}),
            },
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
            "true_layered_detail": raw,
        }


# 注册但不设为默认（已废弃）
register_strategy(TrueLayeredStrategy, is_default=False)
