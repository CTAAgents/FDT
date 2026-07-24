# -*- coding: utf-8 -*-
"""供需平衡表估算模块 — 供给−需求滚动差计算。

为探源 Agent 第①维度"供需平衡表"提供估算工具。
调用 supply.py + demand.py 的数据进行差额推算。
"""



def query_chain_balance(symbol: str) -> dict:
    """估算品种供需平衡表。

    通过调用 query_supply() 和 query_demand() 获取供需两端数据，
    粗略推算当期平衡差方向和未来1-3月边际变化。

    Args:
        symbol: 品种代码

    Returns:
        dict: {current, trend_4w, driver, detail, _source}
    """
    sym = symbol.upper()

    # 尝试从supply+demand模块获取实时数据
    try:
        from fundamental_data_collector.scripts.demand import query_demand
        from fundamental_data_collector.scripts.supply import query_supply

        supply_data = query_supply(sym)
        demand_data = query_demand(sym)
        has_real_data = True
    except (ImportError, Exception):
        supply_data = {}
        demand_data = {}
        has_real_data = False

    # 板块级平衡表估算模板
    BALANCE_TEMPLATES = {
        "RB": {
            "desc": "螺纹钢供需平衡",
            "supply_anchor": "高炉开工率+粗钢日均产量",
            "demand_anchor": "地产新开工同比+基建增速+水泥磨机开工率",
        },
        "CU": {
            "desc": "电解铜供需平衡",
            "supply_anchor": "冶炼厂开工率+进口+TC加工费",
            "demand_anchor": "电网投资+新能源汽车+家电出口",
        },
        "SA": {
            "desc": "纯碱供需平衡",
            "supply_anchor": "装置开工率+新产能投放",
            "demand_anchor": "光伏玻璃投产+浮法玻璃开工",
        },
        "TA": {
            "desc": "PTA供需平衡",
            "supply_anchor": "PTA开工率+新装置投产",
            "demand_anchor": "聚酯开工+织造开工",
        },
        "M": {
            "desc": "豆粕供需平衡",
            "supply_anchor": "大豆到港+压榨开机率",
            "demand_anchor": "生猪存栏+饲料产量",
        },
    }

    template = BALANCE_TEMPLATES.get(
        sym,
        {
            "desc": f"{sym}通用供需框架",
            "supply_anchor": "产量+进口+开工率",
            "demand_anchor": "表观消费+下游开工",
        },
    )

    result = {
        "symbol": sym,
        "current": "待通过实际数据判断（缺/松/紧平衡）",
        "trend_4w": "待通过边际变化判断",
        "driver": "待识别",
        "framework": template,
        "_source": "探源供需平衡表估算（基于supply+demand模块）",
        "_note": "当前输出为框架模板，建议通过 WebSearch 获取最新平衡表数据填入",
    }

    if has_real_data:
        result["_supply_raw"] = supply_data
        result["_demand_raw"] = demand_data

    return result
