"""
因子择时数据接口 v1.1
供探源（基本面研究员）从多个数据源读取基本面数据。

数据源：
1. quant-daily scan_all.py 因子择时输出
2. 徽商智汇(恒生数据中心) DuckDB 本地缓存 → huishang_adapter
"""

import json, os
from typing import Optional, List, Dict

# ── 因子择时数据（scan_all.py 输出） ──


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


# ── 恒生期货数据中心(徽商智汇)数据 v1.0 ──

# 品种中文名映射表（用于搜索恒生数据）
VARIETY_CN_MAP = {
    "RB": "螺纹钢", "HC": "热卷", "I": "铁矿石", "J": "焦炭", "JM": "焦煤",
    "FG": "玻璃", "SA": "纯碱", "SM": "锰硅", "SF": "硅铁",
    "CU": "铜", "AL": "铝", "ZN": "锌", "PB": "铅", "NI": "镍", "SN": "锡",
    "AU": "黄金", "AG": "白银",
    "SC": "原油", "BU": "沥青", "FU": "燃料油", "LU": "低硫燃料油", "PG": "液化气",
    "TA": "PTA", "PX": "对二甲苯", "PF": "短纤", "EG": "乙二醇", "PR": "聚丙烯",
    "MA": "甲醇", "V": "PVC", "L": "聚乙烯", "PP": "聚丙烯",
    "RU": "橡胶", "NR": "20号胶", "BR": "丁二烯橡胶",
    "P": "棕榈油", "Y": "豆油", "OI": "菜油",
    "M": "豆粕", "RM": "菜粕",
    "A": "豆一", "B": "豆二",
    "C": "玉米", "CS": "玉米淀粉",
    "CF": "棉花", "SR": "白糖", "AP": "苹果", "CJ": "红枣",
    "JD": "鸡蛋", "LH": "生猪",
    "UR": "尿素", "PF": "短纤",
    "SI": "工业硅", "LC": "碳酸锂",
    "EC": "集运欧线", "TS": "两年国债", "TF": "五年国债", "T": "十年国债",
}


def huishang_search(variety_cn: str) -> List[Dict]:
    """从本地 DuckDB 搜索品种基本面数据

    Args:
        variety_cn: 品种中文名（如"螺纹钢""纯碱"）

    Returns:
        [{id, name, source, query_ids, charts_type, ...}]
    """
    try:
        import duckdb
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "futures_data.duckdb")
        # Fallback to the Documents path
        alt_path = r"C:\Users\yangd\Documents\WorkBuddy\futures_data.duckdb"
        target = db_path if os.path.exists(db_path) else alt_path
        if not os.path.exists(target):
            return []

        con = duckdb.connect(target, read_only=True)
        rows = con.execute(
            "SELECT id, name, query_ids, charts_type, source, lib_name, lib_id "
            "FROM huishang_topics WHERE name LIKE ? ORDER BY id",
            [f"%{variety_cn}%"]
        ).fetchall()
        con.close()
        return [
            {"id": r[0], "name": r[1], "query_ids": r[2],
             "charts_type": r[3], "source": r[4], "lib_name": r[5], "lib_id": r[6]}
            for r in rows
        ]
    except Exception:
        return []


def huishang_data_points(topic_id: int) -> List[Dict]:
    """获取某主题的数据点序列

    Args:
        topic_id: 主题ID

    Returns:
        [{series_name, date_label, value}, ...]
    """
    try:
        import duckdb
        target = r"C:\Users\yangd\Documents\WorkBuddy\futures_data.duckdb"
        if not os.path.exists(target):
            return []
        con = duckdb.connect(target, read_only=True)
        rows = con.execute(
            "SELECT series_name, date_label, value FROM huishang_data_points WHERE topic_id = ? ORDER BY series_name, date_label",
            [topic_id]
        ).fetchall()
        con.close()
        return [{"series_name": r[0], "date_label": r[1], "value": r[2]} for r in rows]
    except Exception:
        return []


def get_fundamentals(symbol: str) -> Dict:
    """获取某品种的完整基本面数据（整合恒生 + 其他数据源）

    Args:
        symbol: 品种代码（如 "RB", "SA", "MA"）

    Returns:
        {
            "symbol": "...",
            "name": "...",
            "huishang_topics": [...],
            "summary": "...",
        }
    """
    cn_name = VARIETY_CN_MAP.get(symbol.upper(), symbol)
    topics = huishang_search(cn_name)

    # 提取关键数据摘要
    categories = {"库存": [], "产量": [], "开工率": [], "价格": [], "利润": []}
    for t in topics:
        for cat in categories:
            if cat in t["name"]:
                categories[cat].append(t["name"])

    summary_parts = [f"{cn_name}在恒生数据中心有{len(topics)}个数据主题"]
    for cat, items in categories.items():
        if items:
            summary_parts.append(f"{cat}:{len(items)}项")

    return {
        "symbol": symbol,
        "name": cn_name,
        "huishang_topics": topics,
        "huishang_count": len(topics),
        "categories": {k: v for k, v in categories.items() if v},
        "data_available": len(topics) > 0,
        "data_source": "徽商智汇(恒生期货数据中心)",
        "summary": " | ".join(summary_parts),
    }
