"""
事件日历 — 预排期货相关定期事件。

供给 event_driven 策略消费，注入 pipeline context["event_calendar"]。
所有日期按距离当前日期偏移表示（1=明天，-1=昨天，0=今天）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# ── 预排事件模板（品种 → 事件类型 → 触发条件） ──
EVENT_TEMPLATES: list[dict[str, Any]] = [
    # ── USDA ──
    {"symbol": "*", "name": "USDA WASDE月度供需报告", "source": "USDA",
     "day_offset": -3, "window": 2, "impact": "high",
     "affected": {"c", "m", "y", "a", "b", "p", "fb", "sr", "cf", "rs"}},
    {"symbol": "*", "name": "USDA出口销售周报", "source": "USDA",
     "day_offset": -1, "window": 1, "impact": "medium",
     "affected": {"c", "m", "y", "a", "b", "sr"}},
    # ── MPOB ──
    {"symbol": "*", "name": "MPOB棕榈油月度供需报告", "source": "MPOB",
     "day_offset": -2, "window": 2, "impact": "high",
     "affected": {"p", "y", "o", "m"}},
    # ── NBS/中国宏观 ──
    {"symbol": "*", "name": "中国PMI数据公布", "source": "NBS",
     "day_offset": -1, "window": 1, "impact": "high",
     "affected": {"rb", "hc", "i", "j", "jm", "c", "zn", "al", "cu"}},
    {"symbol": "*", "name": "中国CPI/PPI数据公布", "source": "NBS",
     "day_offset": -2, "window": 1, "impact": "medium",
     "affected": {"rb", "hc", "i", "j", "jm", "c", "zn", "al", "cu"}},
    # ── 美联储 ──
    {"symbol": "*", "name": "美联储利率决议", "source": "FED",
     "day_offset": -1, "window": 3, "impact": "high",
     "affected": {"au", "ag", "cu", "zn", "al", "c", "rb", "sc", "IF", "IH", "IC", "T"}},
    # ── EIA ──
    {"symbol": "*", "name": "EIA原油库存周报", "source": "EIA",
     "day_offset": -1, "window": 1, "impact": "high",
     "affected": {"sc", "fu", "lu", "bu", "l", "pp", "TA", "EG", "MA"}},
    # ── 行业周度库存 ──
    {"symbol": "*", "name": "Mysteel钢材库存周报", "source": "Mysteel",
     "day_offset": -1, "window": 1, "impact": "medium",
     "affected": {"rb", "hc", "wr"}},
    {"symbol": "*", "name": "隆众化工库存周报", "source": "隆众",
     "day_offset": -1, "window": 1, "impact": "medium",
     "affected": {"MA", "EG", "PP", "PE", "PVC", "TA"}},
    {"symbol": "*", "name": "钢谷网钢材库存", "source": "钢谷网",
     "day_offset": -1, "window": 1, "impact": "medium",
     "affected": {"rb", "hc"}},
    # ── 交割相关 ──
    {"symbol": "*", "name": "主力合约换月窗口", "source": "exchange",
     "day_offset": -5, "window": 5, "impact": "low",
     "affected": {"*"}},
    {"symbol": "*", "name": "最后交易日/交割日", "source": "exchange",
     "day_offset": -3, "window": 3, "impact": "medium",
     "affected": {"*"}},
]


def build_event_calendar() -> dict[str, list[dict]]:
    """根据当期日期计算各品种的近期事件。

    Returns:
        {sym: [event_dict, ...]} 每个事件包含 name/source/day_offset/window/impact
    """
    today = datetime.now()
    cal: dict[str, list[dict]] = {}
    for tmpl in EVENT_TEMPLATES:
        event_ts = today + timedelta(days=tmpl["day_offset"])
        event = {
            "name": tmpl["name"],
            "source": tmpl["source"],
            "date": event_ts.strftime("%Y-%m-%d"),
            "days_away": tmpl["day_offset"],
            "window": tmpl["window"],
            "impact": tmpl["impact"],
        }
        affected = tmpl["affected"]
        if "*" in affected:
            # 对所有品种广播
            cal.setdefault("*", []).append(event)
        else:
            for sym in affected:
                cal.setdefault(sym, []).append(event)
    return cal
