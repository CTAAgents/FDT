"""
技术指标数据接口 v1.1
供观澜（技术面研究员）读取本 skill 的技术指标数据。
"""

import json
import os
from typing import Optional


def load_scan(path: str) -> list:
    """从技术指标 JSON 中加载全品种数据"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("all_ranked", [])


def load_scan_by_date(date_str: str, report_dir: str = None) -> list:
    """按日期加载扫描数据。"""
    if report_dir is None:
        report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    path = os.path.join(report_dir, f"full_scan_{date_str}.json")
    if os.path.exists(path):
        return load_scan(path)
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
