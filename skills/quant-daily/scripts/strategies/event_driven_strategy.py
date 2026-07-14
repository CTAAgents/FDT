"""
事件驱动策略 — 日历事件前后价格偏差捕获。

内置事件日历（USDA/MPOB/PBoC/Mysteel 等）。
当事件公布后价格反应方向与预期方向相反时
（利空出尽/利多出尽），产出反转信号。
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


# ── 内置事件日历 ──
# date_str: "MM-DD"（每年周期性）
# expected_impact: "bull" / "bear" 对价格的理论方向
# affected_symbols: 影响品种列表
EVENT_CALENDAR: list[dict[str, Any]] = [
    # USDA WASDE 报告 (月度, 约8-12日)
    {"date": "01-12", "name": "USDA月度供需报告", "expected": "neutral",
     "symbols": ["M", "RM", "Y", "OI", "P", "C", "SR", "CF"]},
    {"date": "02-09", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI", "P", "C"]},
    {"date": "03-09", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "04-11", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "05-10", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "06-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "07-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "08-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "09-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "10-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "11-09", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    {"date": "12-12", "name": "USDA月度供需报告", "expected": "neutral", "symbols": ["M", "RM", "Y", "OI"]},
    # USDA种植面积报告 (3月末/6月末)
    {"date": "03-31", "name": "USDA种植意向报告", "expected": "neutral", "symbols": ["M", "RM", "C", "CF"]},
    {"date": "06-30", "name": "USDA实际种植面积", "expected": "neutral", "symbols": ["M", "RM", "C", "CF"]},
    # MPOB 月度报告 (约10日)
    {"date": "01-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "02-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "03-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "04-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "05-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "06-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "07-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "08-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "09-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "10-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "11-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    {"date": "12-10", "name": "MPOB棕榈油报告", "expected": "neutral", "symbols": ["P", "Y", "OI"]},
    # 美联储利率决议 (约8次/年)
    {"date": "01-29", "name": "美联储利率决议", "expected": "bear" if True else "bull",
     "symbols": ["AU", "AG", "CU", "RB", "SC"]},
    {"date": "03-19", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "05-07", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "06-18", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "07-30", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "09-17", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "11-05", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
    {"date": "12-17", "name": "美联储利率决议", "expected": "bear", "symbols": ["AU", "AG", "CU"]},
]

EVENT_LOOKBACK_DAYS = 2  # 事件后多少天内检查价格反应


def _get_today_mmdd() -> str:
    return datetime.now().strftime("%m-%d")


def _find_recent_events() -> list[dict]:
    """找到今天附近 N 天内的已发生事件。"""
    today = datetime.now()
    recent: list[dict] = []
    for ev in EVENT_CALENDAR:
        ev_date = datetime.strptime(ev["date"] + f"-{today.year}", "%m-%d-%Y")
        diff = (today - ev_date).days
        if 0 <= diff <= EVENT_LOOKBACK_DAYS:
            recent.append({**ev, "event_date": ev_date.strftime("%Y-%m-%d")})
    return recent


# ════════════════════════════════════════════════════════════

class EventDrivenStrategy(BaseStrategyV2):
    """事件驱动：事件后价格偏差捕获。"""

    @property
    def name(self) -> str:
        return "event_driven"

    @property
    def display_name(self) -> str:
        return "事件驱动(日历偏差)"

    @property
    def signal_type(self) -> str:
        return "event_driven"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        events = _find_recent_events()
        if not events:
            return []

        signals: list[RawSignal] = []
        sym_map = {t.get("symbol", "").upper(): t for t in tech_list}
        price_change = {t.get("symbol", "").upper(): t.get("change_pct", 0) for t in tech_list}

        for ev in events:
            affected = [s.upper() for s in ev["symbols"] if s.upper() in sym_map]
            for sym in affected:
                chg = price_change.get(sym, 0)
                expected = ev.get("expected", "neutral")
                # 事件后价格与预期方向相反 → 利空出尽变利多 / 利多出尽变利空
                if expected == "bear" and abs(chg) > 1.0:
                    # 预期利空但价格上涨 → 利空出尽
                    direction = "bull" if chg > 0 else "bear"
                    signals.append(RawSignal(
                        symbol=sym,
                        direction=direction,
                        signal_type=f"{self.signal_type}.contrary",
                        raw_score=abs(chg) / 10.0,
                        strategy_name=self.name,
                        meta={
                            "event": ev["name"],
                            "event_date": ev["event_date"],
                            "expected": expected,
                            "price_change_pct": chg,
                            "type": "event_contrary",
                        },
                    ))
                elif expected == "bull" and abs(chg) > 1.0:
                    direction = "bear" if chg < 0 else "bull"
                    signals.append(RawSignal(
                        symbol=sym,
                        direction=direction,
                        signal_type=f"{self.signal_type}.confirm",
                        raw_score=abs(chg) / 10.0,
                        strategy_name=self.name,
                        meta={
                            "event": ev["name"],
                            "event_date": ev["event_date"],
                            "expected": expected,
                            "price_change_pct": chg,
                            "type": "event_confirm",
                        },
                    ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade="WEAK",
                weight=0.5,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
