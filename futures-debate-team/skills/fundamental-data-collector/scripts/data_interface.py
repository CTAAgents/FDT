"""
因子择时数据接口 v1.0
供探源（基本面研究员）从quant-daily的scan_all.py输出中读取factor_timing因子数据。
替代直接import quant-daily。

通过此接口，探源可获取：
- 因子投票（vote_net/vote_confidence）
- 期限结构（ts_type/ts_slope）
- 共振因子（resonance）
- 市场状态（market_state）
- 十分组（g_group）
"""

import json, os
from typing import Optional


def load_factor_timing_scan(path: str) -> list:
    """从 scan_all.py 输出的因子择时JSON中加载全品种因子数据"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("all_ranked", [])


def load_factor_by_date(date_str: str, report_dir: str = None) -> list:
    """按日期加载因子择时数据"""
    if report_dir is None:
        report_dir = os.path.expanduser("~/.workbuddy/skills/quant-daily/data")
    path = os.path.join(report_dir, f"full_scan_factor_timing_{date_str}.json")
    if os.path.exists(path):
        return load_factor_timing_scan(path)
    return []


def get_symbol_factors(scan_data: list, symbol: str) -> Optional[dict]:
    """从全量因子数据中获取单个品种的因子"""
    for item in scan_data:
        if item.get("symbol", "").lower() == symbol.lower():
            return item
    return None


def get_factor_meta(scan_data: list) -> dict:
    """获取因子数据元数据"""
    if not scan_data:
        return {}
    return {
        "total_symbols": len(scan_data),
        "method": "十分组投票系统v2.3.1",
        "factors": ["展期收益率", "动量", "反向仓单", "偏度", "量价相关性"],
    }
