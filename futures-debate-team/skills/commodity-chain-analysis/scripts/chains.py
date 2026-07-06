# -*- coding: utf-8 -*-
"""产业链定义、聚类分析、龙头选择、跨链判断、反转映射缓存。

v2.14.0 优化内容：
- 新增 CROSS_CHAIN_VARIETIES 跨链品种清单和管理函数
- 新增 get_secondary_chain() / is_cross_chain_variety() / get_dominant_chain()
- cluster_chains() 输出含 cross_chain_info 字段
- 品种映射 100% 覆盖 futures-data-search 的 ALL_VARIETIES (66个品种)
- 保留 bc(国际铜) / pt(铂金) 作为额外品种
"""

from typing import Dict, List, Optional, Tuple

# ============================================================
# 产业链品种映射（主链）
# ============================================================
# 所有品种代码使用原始大小写（查询时用 .upper() 归一化）
# 66个品种完全覆盖 futures-data-search 的 ALL_VARIETIES
# 额外品种注明了来源
CHAIN_PRODUCTS: Dict[str, List[str]] = {
    "黑色系": ["i", "j", "jm", "rb", "hc", "SF", "SM"],
    "能源链": ["sc", "lu", "fu", "bu", "pg", "ec"],
    "聚酯链": ["PX", "TA", "PF", "PR"],
    "油化工": ["eg", "eb", "pp", "l", "PL", "bz"],
    "煤化工": ["MA", "SH", "v"],
    "有色": [
        "cu",
        "al",
        "zn",
        "pb",
        "ni",
        "sn",
        "ao",
        "SS",
        "ad",
        "bc",
    ],  # bc(国际铜) — 非 ALL_VARIETIES 标准品种，保留
    "新能源": ["ps", "si", "lc"],
    "贵金属": ["au", "ag", "pt"],  # pt(铂金) — 非 ALL_VARIETIES 标准品种，保留
    "油脂油料": ["a", "b", "m", "y", "p", "OI", "RM", "PK"],
    "谷物软商品": ["c", "cs", "SR", "CF", "CY", "jd", "lh", "AP", "CJ", "rr"],
    "建材": ["FG", "SA", "UR"],
    "橡胶": ["ru", "nr", "br"],
    "纸浆造纸": ["sp", "op"],
}

# ============================================================
# 跨链品种清单（v2.14 新增）
# ============================================================
# 这些品种在多个产业链中有交叉属性，需要根据市场状态判断主导链
# 格式：{品种: {'primary': 主链, 'secondary': [副链列表],
#              'judgment': '判断依据说明'}}
CROSS_CHAIN_VARIETIES: Dict[str, dict] = {
    "MA": {
        "primary": "煤化工",
        "secondary": ["能源链", "油化工"],
        "judgment": "看煤价与油价谁在边际定价；MTO开工率决定甲醇→烯烃路径活跃度",
    },
    "SA": {
        "primary": "建材",
        "secondary": ["新能源"],
        "judgment": "光伏玻璃占比持续抬升（现已>35%），平板玻璃→光伏并链分析",
    },
    "UR": {
        "primary": "建材",
        "secondary": ["煤化工", "谷物软商品"],
        "judgment": "看当期是工业需求(脲醛树脂/电厂脱硝)还是农业需求(化肥)为主",
    },
    "EG": {
        "primary": "聚酯链",
        "secondary": ["煤化工", "油化工"],
        "judgment": "看煤头(CTO)vs油头(石脑油裂解)产能利用率对比",
    },
    "LC": {
        "primary": "新能源",
        "secondary": ["有色"],
        "judgment": "定价权已从矿端移到中游正极厂；与有色共享部分矿端逻辑",
    },
    "SI": {
        "primary": "新能源",
        "secondary": ["有色"],
        "judgment": "光伏装机→多晶硅需求是主驱动；99%工业硅用于有机硅/铝合金",
    },
    "AL": {
        "primary": "有色",
        "secondary": ["能源链"],
        "judgment": "电解铝高耗能（吨铝耗电13500kWh），煤价→电价→铝价是隐藏传导链",
    },
}

# ============================================================
# 缓存加速
# ============================================================
_PRODUCT_TO_CHAIN: Dict[str, str] = {}
_PRODUCT_TO_CROSS_CHAIN: Dict[str, dict] = {}


def _build_reverse_map():
    """构建品种→产业链的反向映射表（仅构建一次）"""
    global _PRODUCT_TO_CHAIN, _PRODUCT_TO_CROSS_CHAIN
    if not _PRODUCT_TO_CHAIN:
        for chain_name, products in CHAIN_PRODUCTS.items():
            for pid in products:
                _PRODUCT_TO_CHAIN[pid] = chain_name
    if not _PRODUCT_TO_CROSS_CHAIN:
        for pid, info in CROSS_CHAIN_VARIETIES.items():
            _PRODUCT_TO_CROSS_CHAIN[pid.upper()] = info


def get_all_products() -> List[str]:
    """获取所有品种代码列表（原始大小写）"""
    _build_reverse_map()
    return list(_PRODUCT_TO_CHAIN.keys())


def get_chain_for_symbol(product_id: str) -> Optional[str]:
    """O(1)查找品种所属产业链（默认主链，大小写不敏感）"""
    _build_reverse_map()
    pid_upper = product_id.upper()
    # 先检查主链映射
    for chain_name, products in CHAIN_PRODUCTS.items():
        if pid_upper in [p.upper() for p in products]:
            return chain_name
    return None


def is_cross_chain_variety(product_id: str) -> bool:
    """判断品种是否为跨链品种"""
    _build_reverse_map()
    return product_id.upper() in _PRODUCT_TO_CROSS_CHAIN


def get_cross_chain_info(product_id: str) -> Optional[dict]:
    """获取跨链品种的详细信息"""
    _build_reverse_map()
    return _PRODUCT_TO_CROSS_CHAIN.get(product_id.upper())


def get_secondary_chain(product_id: str) -> List[str]:
    """获取跨链品种的副链列表"""
    info = get_cross_chain_info(product_id)
    return info["secondary"] if info else []


def get_all_chains_for_symbol(product_id: str) -> List[str]:
    """获取品种所属的所有产业链（主链 + 副链，跨链品种专用）"""
    _build_reverse_map()
    pid_upper = product_id.upper()
    chains = []
    for chain_name, products in CHAIN_PRODUCTS.items():
        if pid_upper in [p.upper() for p in products]:
            chains.append(chain_name)
    # 补充跨链品种的副链（可能不在 CHAIN_PRODUCTS 中）
    if pid_upper in _PRODUCT_TO_CROSS_CHAIN:
        info = _PRODUCT_TO_CROSS_CHAIN[pid_upper]
        for sec in info["secondary"]:
            if sec not in chains:
                chains.append(sec)
    return chains


def get_dominant_chain(product_id: str, market_state: str = "default") -> str:
    """根据市场状态判断跨链品种的当前主导链。

    market_state 可选值：
    - 'default': 返回默认主链
    - 'cost_push': 成本推动型（上游定价）
    - 'demand_pull': 需求拉动型（下游定价）
    - 'policy_shift': 政策/新变量打断

    返回：(主导链名称, 判断理由)
    """
    pid_upper = product_id.upper()
    primary = get_chain_for_symbol(product_id)

    if pid_upper not in _PRODUCT_TO_CROSS_CHAIN:
        return primary, "非跨链品种，默认主链"

    info = _PRODUCT_TO_CROSS_CHAIN[pid_upper]

    # — 市场状态主导链切换 —
    if product_id.upper() == "MA":
        if market_state == "cost_push":
            return "煤化工", "煤价上行主导（成本推动型），甲醇跟煤走"
        elif market_state == "demand_pull":
            return "油化工", "下游烯烃需求主导（需求拉动型），甲醇跟下游走"
        return info["primary"], info["judgment"]

    elif product_id.upper() == "SA":
        if market_state == "policy_shift":
            return "新能源", "光伏装机政策驱动+玻璃产能置换，光伏占比已>35%"
        elif market_state == "demand_pull":
            return "新能源", "光伏组件需求拉动，纯碱→光伏玻璃链活跃"
        return info["primary"], info["judgment"]

    elif product_id.upper() == "UR":
        if market_state == "cost_push":
            return "煤化工", "煤价上涨，尿素生产成本驱动"
        elif market_state == "demand_pull":
            return "谷物软商品", "农业需求旺季，尿素→化肥→农产品传导"
        return info["primary"], info["judgment"]

    elif product_id.upper() == "EG":
        if market_state == "cost_push":
            return "油化工", "石脑油裂解路线主导，油价→EG传导"
        elif market_state == "policy_shift":
            return "煤化工", "煤制EG产能释放，煤头路线成本优势"
        return info["primary"], info["judgment"]

    elif product_id.upper() == "AL":
        if market_state == "cost_push":
            return "能源链", "电力成本（煤→电→铝）主导，铝厂成本承压"
        return info["primary"], info["judgment"]

    return info["primary"], info["judgment"]


# ============================================================
# 辩论单元
# ============================================================
DEBATE_UNITS: Dict[str, dict] = {
    "黑色系": {"unit": ["i", "j", "rb"], "focus": "成本推涨vs需求拉动？利润在上游还是下游？"},
    "能源链": {"unit": ["sc", "lu", "bu"], "focus": "裂解价差？原油-成品油传导效率？"},
    "聚酯链": {"unit": ["PX", "TA", "PF"], "focus": "聚酯利润？PX-PTA价差？"},
    "油化工": {"unit": ["eg", "pp", "l"], "focus": "烯烃利润？原油-化工品传导？"},
    "煤化工": {"unit": ["MA", "SH", "v"], "focus": "MTO/MTP价差？煤-甲醇传导？电石法vs乙烯法PVC成本？"},
    "有色": {"unit": ["ao", "al", "ni"], "focus": "氧化铝→铝的成本传导？镍→不锈钢？"},
    "新能源": {"unit": ["ps", "si", "lc"], "focus": "多晶硅→光伏产业链？工业硅→有机硅？碳酸锂→新能源汽车需求？"},
    "贵金属": {"unit": ["au", "ag"], "focus": "黄金-白银比价，避险情绪传导"},
    "油脂油料": {"unit": ["m", "y", "p"], "focus": "压榨利润？油脂间替代关系？"},
    "谷物软商品": {"unit": ["c", "CF", "lh"], "focus": "农产品供需周期？养殖利润？"},
    "建材": {"unit": ["FG", "SA", "UR"], "focus": "纯碱→玻璃成本传导？"},
    "橡胶": {"unit": ["ru", "nr", "br"], "focus": "天然vs合成橡胶价差？"},
    "纸浆造纸": {"unit": ["sp", "op"], "focus": "纸浆-双胶纸价差？sp为上游（纸浆），op为下游（双胶纸）"},
}

# ============================================================
# 产业链相关性矩阵
# ============================================================
# 范围 0.0~1.0，表示跨链联动强度
CHAIN_CORRELATION_MATRIX: Dict[str, Dict[str, float]] = {
    "黑色系": {"能源链": 0.3, "有色": 0.4, "建材": 0.6},
    "能源链": {"黑色系": 0.3, "聚酯链": 0.7, "油化工": 0.8},
    "聚酯链": {"能源链": 0.7, "油化工": 0.6},
    "油化工": {"能源链": 0.8, "聚酯链": 0.6, "煤化工": 0.5},
    "煤化工": {"油化工": 0.6, "能源链": 0.4, "建材": 0.5},
    "有色": {"黑色系": 0.4, "贵金属": 0.3, "新能源": 0.5},
    "新能源": {"有色": 0.5},
    "贵金属": {"有色": 0.3},
    "油脂油料": {"谷物软商品": 0.5},
    "谷物软商品": {"油脂油料": 0.5},
    "建材": {"黑色系": 0.6, "煤化工": 0.5},
    "橡胶": {"能源链": 0.4},
    "纸浆造纸": {},
}

# ============================================================
# 同链冗余检测 — 动态规则（v2.15+ 废弃硬编码）
# ============================================================
# 【重要变更 v2.15】同链高相关性不再使用硬编码配对。
# analyze_chain.py Step 4 已改为基于60日滚动相关系数的动态检测。
# 相关系数 > 0.80 的品种自动标记为冗余，由闫判官做取舍。
#
# 仍保留 WITHIN_CHAIN_INDEPENDENT 用于特殊场景：
# 同产业链内驱动因素明确独立，即使统计相关高也不应视为冗余。
WITHIN_CHAIN_HIGH_CORRELATION: Dict[str, List[tuple]] = {}  # 已废弃（保留为空兼容导入）

# 品种级独立声明（同产业链内驱动因素独立，永不视为冗余）
WITHIN_CHAIN_INDEPENDENT: Dict[str, List[str]] = {
    "黑色系": ["SM", "SF"],  # 锰硅/硅铁受独立供需+锰矿进口影响，与RB/HC相关性弱
}


def classify_chain(avg_score: float, direction_counts: dict = None) -> str:
    """根据平均得分和方向分布判断产业链整体趋势。

    v2.14修正：score代表信号强度（绝对值），方向由direction字段决定。
    - 如果多数品种是SELL，即使avg_score>0，也是空头趋势
    - 如果多数品种是BUY，即使avg_score<0，也是多头趋势
    """
    if direction_counts:
        buy_count = direction_counts.get("BUY", 0)
        sell_count = direction_counts.get("SELL", 0)
        total = buy_count + sell_count

        if total > 0:
            buy_ratio = buy_count / total
            sell_ratio = sell_count / total

            # 多数品种方向决定产业链趋势
            if sell_ratio >= 0.7:  # 70%以上是SELL
                if avg_score >= 40:
                    return "强势空头"
                elif avg_score >= 25:
                    return "空头趋势"
                else:
                    return "偏空震荡"
            elif buy_ratio >= 0.7:  # 70%以上是BUY
                if avg_score >= 40:
                    return "强势多头"
                elif avg_score >= 25:
                    return "多头趋势"
                else:
                    return "偏多震荡"
            else:
                # 方向不统一，震荡市
                if avg_score >= 40:
                    return "高波动震荡"
                elif avg_score >= 25:
                    return "震荡偏弱"
                else:
                    return "震荡"

    # fallback: 旧逻辑（基于score正负）
    if avg_score >= 20:
        return "多头趋势"
    elif avg_score >= 5:
        return "偏多震荡"
    elif avg_score <= -20:
        return "空头趋势"
    elif avg_score <= -5:
        return "偏空震荡"
    return "震荡"


def _get_score(s):
    """获取品种趋势评分（兼容trend.score和tech.score两种格式）。"""
    return s.get("trend", {}).get("score") or s.get("tech", {}).get("score", 0)


def select_leader(chain_symbols: list, overall_trend: str):
    """按趋势方向选择龙头品种。

    v2.14修正：根据direction字段选择龙头，而不是根据score正负。
    - 多头趋势：选BUY方向中score最高的（信号最强的多头）
    - 空头趋势：选SELL方向中score最高的（信号最强的空头）
    - 震荡市：选波动率最高的
    """
    if overall_trend in ("强势多头", "多头趋势", "偏多震荡"):
        # 多头趋势：选BUY方向中score最高的
        buy_symbols = [s for s in chain_symbols if s.get("direction") == "BUY"]
        if buy_symbols:
            leader = max(buy_symbols, key=lambda x: _get_score(x))
            reason = "多头信号最强（领涨）"
        else:
            # 没有BUY品种，选score最低的（最抗跌的）
            leader = min(chain_symbols, key=lambda x: _get_score(x))
            reason = "最抗跌（跌幅最小）"
    elif overall_trend in ("强势空头", "空头趋势", "偏空震荡"):
        # 空头趋势：选SELL方向中score最高的（信号最强的空头）
        sell_symbols = [s for s in chain_symbols if s.get("direction") == "SELL"]
        if sell_symbols:
            leader = max(sell_symbols, key=lambda x: _get_score(x))
            reason = "空头信号最强（领跌）"
        else:
            # 没有SELL品种，选score最高的（最抗涨的）
            leader = max(chain_symbols, key=lambda x: _get_score(x))
            reason = "最抗涨（涨幅最小）"
    else:
        # 震荡市：选波动率最高的
        leader = max(chain_symbols, key=lambda x: x.get("tech", {}).get("ATR14", 0) or 0)
        reason = "波动率最高（ATR最大，弹性最好）"
    return leader, reason


def cluster_chains(symbols: list, market_state: str = "default") -> dict:
    """将品种数据按产业链聚类，v2.14 新增 cross_chain_info 字段。

    Args:
        symbols: 品种数据列表，每项含 product_id, direction, last_price, open_interest 等
        market_state: 市场状态（用于跨链品种的主导链判断）
            - 'default' | 'cost_push' | 'demand_pull' | 'policy_shift'

    Returns:
        dict: {链名: {count, leader, overall_trend, members, cross_chain_info, ...}}
    """
    chain_results = {}
    # 构建大小写不敏感的产品映射
    products_upper = {chain_name: [p.upper() for p in products] for chain_name, products in CHAIN_PRODUCTS.items()}
    for chain_name, products in CHAIN_PRODUCTS.items():
        chain_symbols = [s for s in symbols if s.get("product_id", "").upper() in products_upper[chain_name]]
        if not chain_symbols:
            continue

        # 统计方向分布
        direction_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for s in chain_symbols:
            direction = s.get("direction", "HOLD")
            direction_counts[direction] = direction_counts.get(direction, 0) + 1

        total_score = sum(
            s.get("trend", {}).get("score", 0) or s.get("tech", {}).get("score", 0) for s in chain_symbols
        )
        avg_score = total_score / len(chain_symbols) if chain_symbols else 0
        overall_trend = classify_chain(avg_score, direction_counts)
        leader, leader_reason = select_leader(chain_symbols, overall_trend)

        # 标记本链中的跨链品种
        cross_chain_in_chain = []
        for s in chain_symbols:
            pid = s.get("product_id", "")
            if is_cross_chain_variety(pid):
                dominant, reason = get_dominant_chain(pid, market_state)
                cross_chain_in_chain.append(
                    {
                        "pid": pid,
                        "cross_type": "主链" if dominant == chain_name else "副链",
                        "dominant_chain": dominant,
                        "dominant_reason": reason,
                    }
                )

        result = {
            "count": len(chain_symbols),
            "leader": leader.get("product_id"),
            "leader_price": leader.get("last_price"),
            "leader_reason": leader_reason,
            "overall_trend": overall_trend,
            "avg_score": round(avg_score, 1),
            "debate_unit": DEBATE_UNITS.get(chain_name, {}),
            "cross_chain_info": cross_chain_in_chain if cross_chain_in_chain else None,
            "members": [
                {
                    "pid": s["product_id"],
                    "name": s.get("product_name", s["product_id"]),
                    "price": s["last_price"],
                    "score": _get_score(s),
                    "trend": s.get("trend", {}).get("trend", s.get("tech", {}).get("trend", "N/A")),
                    "oi": s["open_interest"],
                }
                for s in chain_symbols
            ],
        }
        chain_results[chain_name] = result
    return chain_results
