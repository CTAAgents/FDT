#!/usr/bin/env python3
"""
辩手工具 — 证真（正方）and 慎思（反方）的数据查询工具箱
========================================================
供正反方辩手在辩论中直接查询7因子分解、产业链上下文、价格走势。

v2.2.0 优化:
- 修复硬编码绝对路径 → __file__ 动态定位
- 链映射改用 commodity-chain-analysis 的 CHAIN_PRODUCTS（唯一来源）
- 不包含任何分析逻辑 —— 仅返回原始数据，让Agent自行论证
"""

import json
import os
from typing import Dict, Optional
from datetime import datetime


def _get_skill_dir() -> str:
    """动态获取本 skill 的根目录。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_recent(base_dir: str, prefix: str, suffix: str = ".json") -> Optional[str]:
    """在目录中查找最新的匹配前缀的文件。"""
    if not os.path.isdir(base_dir):
        return None
    candidates = [f for f in os.listdir(base_dir) if f.startswith(prefix) and f.endswith(suffix)]
    if not candidates:
        return None
    candidates.sort(reverse=True)  # 最新的在前
    return os.path.join(base_dir, candidates[0])


def _find_report(filename: str) -> Optional[str]:
    """在多个候选路径中查找数据报告文件，无精确匹配时搜索最新文件。"""
    skill_dir = _get_skill_dir()
    base_candidates = [
        os.path.join(os.path.expanduser("~"), "Documents", "Signal", "reports"),
        os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "quant-daily", "reports"),
        os.path.join(skill_dir, "reports"),
    ]

    # 1. 精确路径匹配
    for base in base_candidates:
        path = os.path.join(base, filename)
        if os.path.exists(path):
            return path

    # 2. 按前缀搜索最新文件
    prefix = filename.split("_2026")[0] if "_2026" in filename else filename.split(".")[0]
    for base in base_candidates:
        found = _find_recent(base, prefix)
        if found:
            return found

    return None


def _load_data() -> dict:
    """加载信号数据和全品种排名（动态查找最新报告）。"""
    result = {"ranked": [], "signals": {}}

    tl_path = _find_report("true_layered_20260704.json")
    if tl_path:
        try:
            with open(tl_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'ranked' in data:
                result["ranked"] = data['ranked']
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    sig_path = _find_report("signals_20260704.json")
    if sig_path:
        try:
            with open(sig_path, 'r', encoding='utf-8') as f:
                result["signals"] = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    return result


def get_factor_decomp(symbol: str) -> dict:
    """获取品种的7因子分解数据和溯源信息。

    返回因子排名百分位(0-100)，越高=做空越拥挤。
    不可用于直接判定多空方向（那是量析师的事）。
    """
    data = _load_data()
    for entry in data.get("ranked", []):
        if entry.get('symbol', '').upper() == symbol.upper():
            return {
                "symbol": symbol,
                "adjusted_rank": entry.get("adjusted_rank", 0),
                "net_rank": entry.get("net_rank", 0),
                "veto_penalty": entry.get("veto_penalty", 1.0),
                "maturity_stage": entry.get("maturity_stage", ""),
                "dimensions": entry.get("dims", {}),
                "active_dims": entry.get("active_dims", 0),
                "provenance": entry.get("_provenance", {}),
            }
    return {"symbol": symbol, "error": "未找到该品种的因子分解数据"}


def get_chain_context(symbol: str) -> dict:
    """获取品种所在产业链的上下文信息。

    优先尝试从 commodity-chain-analysis 动态导入 CHAIN_PRODUCTS，
    失败时使用内置备用映射。
    """
    chain_name = None

    # 尝试动态导入 commodity-chain-analysis 的 CHAIN_PRODUCTS
    try:
        sys_path_backup = __import__('sys').path[:]
        ccc_path = os.path.join(os.path.expanduser("~"), ".workbuddy",
                                 "plugins", "marketplaces", "my-experts",
                                 "plugins", "futures-debate-team",
                                 "skills", "commodity-chain-analysis")
        if os.path.exists(ccc_path):
            import sys
            sys.path.insert(0, ccc_path)
            from scripts.chains import get_chain_for_symbol, CHAIN_PRODUCTS
            chain_name = get_chain_for_symbol(symbol)
            sys.path = sys_path_backup
    except (ImportError, Exception):
        pass

    # fallback: 内置备用映射
    if not chain_name:
        chain_name = _FALLBACK_CHAIN_MAP.get(symbol.upper(), "未分类")

    return {
        "symbol": symbol,
        "chain": chain_name,
        "note": "产业链分类源自 commodity-chain-analysis" if chain_name != "未分类" else "链分类未找到",
    }


# 备用产业链映射（仅在 commodity-chain-analysis 不可用时使用）
_FALLBACK_CHAIN_MAP = {
    "I": "黑色系", "J": "黑色系", "JM": "黑色系", "RB": "黑色系", "HC": "黑色系",
    "SF": "黑色系", "SM": "黑色系",
    "SC": "能源链", "LU": "能源链", "FU": "能源链", "BU": "能源链", "PG": "能源链",
    "PX": "聚酯链", "TA": "聚酯链", "PF": "聚酯链", "PR": "聚酯链",
    "EG": "聚酯链", "EB": "油化工", "PP": "油化工", "L": "油化工",
    "MA": "煤化工", "SH": "煤化工", "V": "煤化工",
    "CU": "有色", "AL": "有色", "ZN": "有色", "PB": "有色",
    "NI": "有色", "SN": "有色", "AO": "有色", "SS": "有色",
    "AU": "贵金属", "AG": "贵金属",
    "PK": "油脂油料", "A": "油脂油料", "B": "油脂油料", "M": "油脂油料",
    "Y": "油脂油料", "P": "油脂油料", "OI": "油脂油料", "RM": "油脂油料",
    "C": "谷物软商品", "CS": "谷物软商品", "SR": "谷物软商品",
    "CF": "谷物软商品", "JD": "谷物软商品", "LH": "谷物软商品",
    "FG": "建材", "SA": "建材", "UR": "建材",
    "RU": "橡胶", "NR": "橡胶", "BR": "橡胶",
    "SP": "纸浆造纸", "OP": "纸浆造纸",
    "LC": "新能源", "SI": "新能源", "PS": "新能源",
    "EC": "能源链", "RR": "谷物软商品", "AD": "有色",
    "CY": "谷物软商品", "PL": "油化工", "BZ": "油化工",
}


def get_price_action(symbol: str, days: int = 20) -> dict:
    """获取品种近期价格走势摘要。

    返回因子排名、方向、信号强度等信息。因子排名为百分位(0-100)，
    越高表示做空越拥挤（反向信号时）。
    """
    data = _load_data()
    for entry in data.get("ranked", []):
        s = entry.get('symbol', '').upper()
        if s == symbol.upper():
            dims = entry.get("dims", {})
            return {
                "symbol": symbol,
                "adjusted_rank": entry.get("adjusted_rank", 0),
                "direction": entry.get("direction", "N/A"),
                "grid": entry.get("grid", ""),
                "side": entry.get("side", ""),
                "reg_score": entry.get("reg_score", 0),
                "trend_score": entry.get("trend_score", 0),
                "signal_type": entry.get("signal_type", ""),
                "active_dimensions": entry.get("active_dims", 0),
                "factor_detail": {
                    k: v for k, v in dims.items()
                    if k.startswith("D")
                },
                "note": "数据来自TDX TQ-Local; 排名百分位(0-100), 方向=BUY/SELL, grid=九宫格分类"
            }
    return {"symbol": symbol, "error": "未找到价格数据"}
