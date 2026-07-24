# -*- coding: utf-8 -*-
"""联网搜索统一路由 — 通过 WebSearch/WebFetch 采集基本面数据。

当内置缓存数据不足或过时时，此模块提供联网采集框架。
"""



def query_web(keywords: str) -> str:
    """联网搜索基本面信息，返回关键信息摘要。

    由Agent在调用时通过 WebSearch/WebFetch 实际执行。
    此函数返回搜索提示模板。

    Args:
        keywords: 搜索关键词（建议包含时间限定词）

    Returns:
        str: 搜索提示，列出推荐的搜索查询
    """
    hints = [
        f"建议搜索: {keywords}",
        "请使用 WebSearch 工具执行以下查询（已内置时间限定）:",
    ]

    # 根据关键词自动补充分类搜索建议
    if any(kw in keywords for kw in ["库存", "库存", "inventory"]):
        hints.append(f'  - "{keywords} 周度 最新"')
        hints.append(f'  - "{keywords} 同比 环比 分位数"')
    elif any(kw in keywords for kw in ["开工", "产量", "supply", "产能"]):
        hints.append(f'  - "{keywords} 开工率 最新 周度"')
        hints.append(f'  - "{keywords} 产量 月度"')
    elif any(kw in keywords for kw in ["利润", "margin", "加工"]):
        hints.append(f'  - "{keywords} 利润 成本 最新"')
    elif any(kw in keywords for kw in ["需求", "demand", "订单"]):
        hints.append(f'  - "{keywords} 需求 下游 开工"')
    else:
        hints.append(f'  - "{keywords} 2026年7月 最新"')

    hints.append("\n⚠️ 请在搜索结果中标注数据时间和来源")
    return "\n".join(hints)
