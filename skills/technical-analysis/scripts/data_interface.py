"""
L1-L4原始指标数据接口 v1.0
供观澜（技术面研究员）从quant-daily的scan_all.py输出中读取L1-L4原始指标。
替代直接import quant-daily。

通过此接口，观澜可获取：
- 全品种K线数据（OHLCV）
- 技术指标（ADX/RSI/CCI/MA/MACD/Bollinger等）
- 趋势阶段（launch/trending/exhausted/reversal）
- 四层评分明细（l1/l2/l3/l4/cons/veto）
"""

import json, os
from typing import Optional


def load_l1l4_scan(path: str) -> list:
    """从 scan_all.py 输出的L1-L4 JSON中加载全品种指标数据"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("all_ranked", [])


def load_l1l4_scan_by_date(date_str: str, report_dir: str = None) -> list:
    """按日期加载L1-L4扫描数据"""
    if report_dir is None:
        report_dir = os.path.expanduser("~/.workbuddy/skills/quant-daily/data")
    path = os.path.join(report_dir, f"full_scan_l1l4_{date_str}.json")
    if os.path.exists(path):
        return load_l1l4_scan(path)
    return []


def get_symbol_indicators(scan_data: list, symbol: str) -> Optional[dict]:
    """从全量扫描数据中获取单个品种的指标"""
    for item in scan_data:
        if item.get("symbol", "").lower() == symbol.lower():
            return item
    return None


def get_scan_meta(scan_data: list) -> dict:
    """获取扫描元数据"""
    if not scan_data:
        return {}
    sample = scan_data[0]
    return {
        "total_symbols": len(scan_data),
        "data_source": "通达信TQ-Local",
        "method": "numpy向量化(通达信公式对齐)",
    }
