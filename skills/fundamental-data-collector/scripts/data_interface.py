"""
基本面数据接口 v1.2
供探源（基本面研究员）从多个数据源读取基本面数据。

数据源：
1. 徽商智汇(恒生数据中心) DuckDB 本地缓存 → huishang_adapter
"""

import os
from typing import Dict, List

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


def _get_db_path() -> str:
    """获取DuckDB路径: 全局优先,工作空间备选"""
    home = os.path.expanduser("~/.skills/futures_data.duckdb")
    if os.path.exists(home):
        return home
    ws = r"C:\Users\yangd\logs\futures_data.duckdb"
    return ws if os.path.exists(ws) else home


def huishang_search(variety_cn: str) -> List[Dict]:
    """从本地 DuckDB 搜索品种基本面数据"""
    try:
        import duckdb
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "futures_data.duckdb")
        target = _get_db_path()
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
    """获取某主题的数据点序列"""
    try:
        import duckdb
        target = _get_db_path()
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
    """获取某品种的完整基本面数据"""
    cn_name = VARIETY_CN_MAP.get(symbol.upper(), symbol)
    topics = huishang_search(cn_name)

    categories = {"库存": [], "产量": [], "开工率": [], "价格": [], "利润": []}
    for t in topics:
        for cat in categories:
            if cat in t["name"]:
                categories[cat].append(t["name"])

    summary_parts = [f"{cn_name}在徽商数据中心有{len(topics)}个数据主题"]
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
        "data_source": "徽商智汇(徽商期货数据中心)",
        "summary": " | ".join(summary_parts),
    }


def format_fundamentals_summary(symbol: str) -> str:
    """生成面向辩论的结构化基本面摘要"""
    info = get_fundamentals(symbol)
    cn = info["name"]
    if not info["data_available"]:
        return f"【{cn}】徽商数据中心暂无相关数据，建议使用 WebSearch 补充。"

    lines = [
        f"╔══ {cn} 基本面概况 ══╗",
        f"  数据源: {info['data_source']}",
        f"  数据主题: {info['huishang_count']} 个",
    ]
    for cat, items in info["categories"].items():
        names = "、".join(t[:25] for t in items[:3])
        suffix = f"...等{len(items)}项" if len(items) > 3 else ""
        lines.append(f"  {cat}: {names}{suffix}")
    lines.append("")
    lines.append("  可用主题:")
    for t in info["huishang_topics"][:10]:
        lines.append(f"    · {t['name']} (来源:{t.get('source','?')})")
    if info["huishang_count"] > 10:
        lines.append(f"    · ... 还有 {info['huishang_count'] - 10} 个主题")
    lines.append(f"╚{'═'*30}╝")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  DuckDB-first 查询（Phase 3.2）
# ═══════════════════════════════════════════════════════════════

# 数据类型到 category 关键词的映射
_DATA_TYPE_CATEGORY = {
    "inventory": {"库存", "仓单", "社库", "厂库", "港口"},
    "supply": {"产量", "开工率", "进口", "到港", "产能"},
    "demand": {"需求", "消费", "订单", "提货", "出口"},
    "margin": {"利润", "加工费", "毛利", "亏损"},
}


def query_duckdb_first(
    symbol: str,
    data_type: str,
    max_results: int = 5,
) -> tuple[Optional[list], Optional[str]]:
    """DuckDB 优先查询 — 按数据类型搜索主题，获取最新数据点。

    Args:
        symbol: 品种代码（如 "RB"）。
        data_type: 数据类型（"supply" / "demand" / "inventory" / "margin"）。
        max_results: 最大返回主题数。

    Returns:
        (data_points_list, summary_text) — DuckDB 有数据时返回列表 + 摘要，
        无数据时返回 (None, None) 供 caller fallback。
    """
    cn_name = VARIETY_CN_MAP.get(symbol.upper())
    if not cn_name:
        return None, None

    keywords = _DATA_TYPE_CATEGORY.get(data_type, set())
    if not keywords:
        return None, None

    topics = huishang_search(cn_name)
    if not topics:
        return None, None

    # 筛选匹配数据类型关键词的主题
    matched = []
    for t in topics:
        name = t.get("name", "")
        for kw in keywords:
            if kw in name:
                matched.append(t)
                break

    if not matched:
        return None, None

    # 获取最新数据点
    all_points = []
    for t in matched[:max_results]:
        points = huishang_data_points(t["id"])
        if points:
            # 只保留最新一条
            latest = max(points, key=lambda p: str(p.get("date_label", "")))
            latest["topic_name"] = t["name"]
            latest["source"] = t.get("source", "huishang")
            all_points.append(latest)

    if not all_points:
        return None, None

    summary_parts = [f"{cn_name}-{data_type}: {len(matched)} 个数据主题"]
    for p in all_points[:3]:
        summary_parts.append(f"{p.get('topic_name','?')}={p.get('value','?')}")
    summary = " | ".join(summary_parts)

    return all_points, summary
