"""
宏观制度策略 — 基于宏观锚的板块多空配置。

数据来自 fundamental-data-collector/scripts/macro_link.py（静态映射表）。
策略标记宏观制度（risk-on/risk-off/neutral），
对板块内品种做方向性提示。
"""

from __future__ import annotations

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal, format_reason


# ── 宏观制度映射（matching macro_link.py 结构） ──
# sector → {anchor: (bull_condition, bear_condition)}
MACRO_ANCHORS: dict[str, dict[str, str]] = {
    "黑色": {"房地产政策": "bull", "基建投资": "bull", "环保限产": "neutral"},
    "有色": {"美元指数": "bear", "全球PMI": "bull", "新能源需求": "bull"},
    "能化": {"原油价格": "bull", "OPEC+": "bull", "北美寒潮": "bull"},
    "农产品": {"USDA报告": "neutral", "天气升水": "bull", "关税政策": "neutral"},
    "贵金属": {"美联储利率": "bear", "地缘风险": "bull", "通胀预期": "bull"},
}

SECTOR_SYMBOLS: dict[str, list[str]] = {
    "黑色": ["RB", "HC", "I", "J", "JM", "SM", "SF"],
    "有色": ["CU", "AL", "ZN", "PB", "NI", "SN", "SI"],
    "能化": ["SC", "FU", "LU", "BU", "L", "PP", "V", "TA", "EG", "MA", "SA", "FG", "UR", "PG", "EB"],
    "农产品": ["M", "RM", "Y", "OI", "P", "C", "CF", "SR", "JD", "LH", "AP", "CJ", "PK"],
    "贵金属": ["AU", "AG"],
}


class MacroRegimeStrategy(BaseStrategyV2):
    """宏观制度：板块多空配置。"""

    @property
    def name(self) -> str:
        return "macro_regime"

    @property
    def display_name(self) -> str:
        return "宏观制度(板块轮动)"

    @property
    def signal_type(self) -> str:
        return "macro_regime"

    @property
    def validators(self) -> list[str]:
        return []  # 宏观信号不经技术面验证器过滤

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        ctx = context or {}
        # 从 context 获取宏观信号（在 pipeline 中存放于 ctx["extra"]["macro_signal"]，
        # 同时兼容上层直接传 ctx["macro_signal"] 的旧路径）
        macro_signal = (
            ctx.get("extra", {}).get("macro_signal")
            or ctx.get("macro_signal")
            or "neutral"
        )
        if macro_signal not in ("bull", "bear"):
            return signals

        sym_in_tech = {t.get("symbol", "").upper() for t in tech_list}
        for sector, symbols in SECTOR_SYMBOLS.items():
            for sym in symbols:
                if sym not in sym_in_tech:
                    continue
                raw_score = 0.3 if macro_signal == "bull" else 0.3
                direction = macro_signal
                signals.append(RawSignal(
                    symbol=sym,
                    direction=direction,
                    signal_type=f"{self.signal_type}.{sector}",
                    raw_score=raw_score,
                    strategy_name=self.name,
                    meta={
                        "sector": sector,
                        "macro_signal": macro_signal,
                        "anchors": list(MACRO_ANCHORS.get(sector, {}).keys()),
                    },
                ))
        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=30 if s.direction == "bull" else -30,
                abs_score=30,
                grade="WEAK",
                weight=0.4,  # 宏观信号权重低于技术信号
            )
            # reason：子信号身份 + 关键条件，供辩论环节识别"为什么选这个信号"
            _m = s.meta
            _metrics = {}
            if _m.get("sector"):
                _metrics["sector"] = _m["sector"]
            if _m.get("macro_signal"):
                _metrics["regime"] = _m["macro_signal"]
            ss.reason = format_reason(
                s.signal_type, s.direction, "WEAK",
                metrics=_metrics or None, strength=abs(s.raw_score))
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
