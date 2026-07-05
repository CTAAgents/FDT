# -*- coding: utf-8 -*-
"""事件日历mask — 宏观事件日自动降技术信号置信度。

功能：
- get_events_for_date(date): 查询某日是否有宏观事件
- check_event_impact(today, symbol): 返回置信度折扣系数
- 集成到 risk_engine.special_scenario_override()

事件数据库结构：
{"event_type": "FOMC", "date": "2026-07-29", "description": "美联储利率决议", "affected": ["all"]}
event_type 支持：FOMC/NFP/USDA/EIA/CPI/PBOC/交割日/主力换月日
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json, os, math


# ── 固定事件模板（每年更新一次） ──
# 格式：每月第几周的周几发生哪类事件
_RECURRING_EVENTS = {
    "FOMC": {"week": 3, "weekday": 2, "months": list(range(1, 13))},       # 每月第3周的周二
    "USDA_WASDE": {"week": 2, "weekday": 4, "months": list(range(1, 13))}, # 每月第2周的周四
    "EIA": {"week": 2, "weekday": 3, "months": list(range(1, 13))},        # 每周三
    "CPI_US": {"week": 2, "weekday": 4, "months": list(range(1, 13))},     # 每月第2周周四
    "NFP": {"week": 1, "weekday": 4, "months": list(range(1, 13))},        # 每月第1周周五
}

# ── 品种受影响映射 ──
_EVENT_AFFECTED_SYMBOLS = {
    "FOMC": "__ALL__",
    "NFP": "__ALL__",
    "CPI_US": "__ALL__",
    "USDA_WASDE": ["M", "RM", "P", "Y", "C", "CS"],
    "EIA": ["SC", "BU", "LU", "FU"],
    "PBOC": ["IF", "IH", "IC", "T", "TF"],
}

# ── 品种板块（用于跨品种联动） ──
SECTOR_MAP = {
    "黑色": ["RB", "HC", "I", "J", "JM", "SM", "SF"],
    "有色": ["CU", "AL", "ZN", "PB", "NI", "SN"],
    "贵金属": ["AU", "AG"],
    "化工": ["MA", "TA", "EG", "PF", "PR", "EB", "PP", "L", "V", "RU", "NR", "BU", "SC", "LU", "FU"],
    "农产品": ["M", "RM", "Y", "P", "OI", "C", "CS", "A", "B", "AP", "CJ", "PK", "LH", "JD"],
    "软商品": ["SR", "CF", "CY", "ZC"],
    "股指": ["IF", "IH", "IC"],
    "国债": ["T", "TF", "TS"],
}


def _get_nth_weekday(year: int, month: int, nth: int, weekday: int) -> Optional[str]:
    """获取某月第n个周x的日期。weekday: 0=周一, 6=周日, nth从1开始"""
    from calendar import monthcalendar
    import calendar
    cal = monthcalendar(year, month)
    # 找到该月所有指定weekday的日期
    days = [week[weekday] for week in cal if week[weekday] != 0]
    if len(days) >= nth:
        d = days[nth - 1]
        return f"{year:04d}-{month:02d}-{d:02d}"
    return None


def generate_event_dates(year: int) -> List[Dict]:
    """根据固定模板生成全年事件日期。"""
    events = []
    for etype, cfg in _RECURRING_EVENTS.items():
        for m in cfg["months"]:
            d = _get_nth_weekday(year, m, cfg["week"], cfg["weekday"])
            if d:
                events.append({"event_type": etype, "date": d, "affected": _EVENT_AFFECTED_SYMBOLS.get(etype, [])})
    # EIA是每周三，特殊处理
    import calendar
    for m in range(1, 13):
        for w in calendar.monthcalendar(year, m):
            if w[2] != 0:  # 周三
                d = f"{year:04d}-{m:02d}-{w[2]:02d}"
                events.append({"event_type": "EIA", "date": d, "affected": _EVENT_AFFECTED_SYMBOLS.get("EIA", [])})
    return events


def get_events_for_date(date_str: str, events_cache: Optional[List[Dict]] = None) -> List[Dict]:
    """查询某日的事件列表。

    Args:
        date_str: "2026-07-29"
        events_cache: 可选，预生成的事件列表

    Returns:
        [{"event_type": str, "affected": list}, ...]
    """
    if events_cache is None:
        year = int(date_str[:4])
        events_cache = generate_event_dates(year)
    return [e for e in events_cache if e["date"] == date_str]


def check_event_impact(
    date_str: str,
    symbol: str,
    events_cache: Optional[List[Dict]] = None,
) -> Dict:
    """检查事件日对某品种的技术置信度影响。

    Args:
        date_str: 日期字符串
        symbol: 品种代码
        events_cache: 预生成事件列表

    Returns:
        {"has_event": bool, "events": [str],
         "confidence_discount": float,  # 0.5 = 打折50%
         "suggested_position_pct": float}  # 0.3 = 建议30%仓位
    """
    events = get_events_for_date(date_str, events_cache)
    if not events:
        return {"has_event": False, "events": [], "confidence_discount": 1.0, "suggested_position_pct": 1.0}

    applicable = []
    for e in events:
        affected = e.get("affected", [])
        if affected == "__ALL__" or symbol in affected:
            applicable.append(e["event_type"])

    if not applicable:
        return {"has_event": True, "events": events, "confidence_discount": 1.0, "suggested_position_pct": 1.0}

    # 每个事件折扣0.5，多个事件叠加
    discount = 0.5 ** len(applicable)
    position_pct = max(0.3, discount)  # 仓位最低30%

    return {
        "has_event": True,
        "events": applicable,
        "confidence_discount": round(discount, 2),
        "suggested_position_pct": round(position_pct, 2),
    }


EVENT_CACHE = generate_event_dates(datetime.now().year)


def get_upcoming_events(symbol: str, days: int = 7) -> List[Dict]:
    """获取未来N天内影响某品种的事件列表。

    供闫判官/风控明做辩论时间窗决策：
    - USDA报告前48h适合等待数据后再辩
    - FOMC前后降杠杆

    Args:
        symbol: 品种代码
        days: 前瞻天数

    Returns:
        [{"event_type": str, "date": str, "days_until": int, "impact": str}, ...]
    """
    from datetime import date, timedelta
    today = date.today()
    end_date = today + timedelta(days=days)

    events = []
    for e in EVENT_CACHE:
        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if today <= d <= end_date:
            affected = e.get("affected", [])
            if affected == "__ALL__" or symbol.upper() in [s.upper() for s in affected]:
                impact = check_event_impact(e["date"], symbol)
                events.append({
                    "event_type": e["event_type"],
                    "date": e["date"],
                    "days_until": (d - today).days,
                    "confidence_discount": impact.get("confidence_discount", 1.0),
                    "suggested_position_pct": impact.get("suggested_position_pct", 1.0),
                })

    events.sort(key=lambda x: x["days_until"])
    return events
