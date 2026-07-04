#!/usr/bin/env python3
"""
辩手工具 — 证真（正方）and 慎思（反方）的数据查询工具箱
========================================================
供正反方辩手在辩论中直接查询7因子分解、产业链上下文、价格走势。

不包含任何分析逻辑 —— 仅返回原始数据，让Agent自行论证。
"""

import json, os


def _load_data() -> dict:
    """加载信号数据和全品种排名。"""
    tl_path = r"C:\Users\yangd\Documents\Signal\reports\true_layered_20260704.json"
    sig_path = r"C:\Users\yangd\Documents\Signal\reports\signals_20260704.json"
    result = {"ranked": [], "signals": {}}
    try:
        with open(tl_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'ranked' in data:
            result["ranked"] = data['ranked']
    except: pass
    try:
        with open(sig_path, 'r', encoding='utf-8') as f:
            result["signals"] = json.load(f)
    except: pass
    return result


def get_factor_decomp(symbol: str) -> dict:
    """获取品种的7因子分解数据和溯源信息。"""
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
    """获取品种所在产业链的上下文信息。"""
    chain_map = {
        "PK": "油脂油料链（花生/豆油/棕榈油/菜油）",
        "jd": "养殖链（鸡蛋/豆粕/玉米）",
        "ec": "航运链（集运欧线指数）",
        "sn": "有色链（锡/铜/铝/锌/铅/镍）",
        "SF": "黑色链（硅铁/锰硅/螺纹/热卷/铁矿/焦炭/焦煤）",
        "ni": "有色链（镍/铜/铝/锌/铅/锡）",
        "CF": "纺织链（棉花/棉纱/PTA/PF）",
        "c": "谷物链（玉米/淀粉/大豆/豆粕）",
        "UR": "化工链（尿素/甲醇/纯碱/PVC/苯乙烯）",
        "sc": "能源链（原油/燃料油/低硫油/沥青/LPG）",
        "v": "化工链（PVC/纯碱/甲醇/尿素/苯乙烯）",
        "SA": "化工链（纯碱/玻璃/PVC/甲醇/尿素）",
        "eb": "化工链（苯乙烯/原油/PVC/纯碱）",
        "AP": "果蔬链（苹果/红枣/鲜鸡蛋）",
        "a": "油脂油料链（豆一/豆粕/豆油/菜油）",
        "m": "养殖链（豆粕/玉米/菜粕/鸡蛋）",
    }
    chain = chain_map.get(symbol.upper(), "未分类")
    return {"symbol": symbol, "chain": chain, "note": "产业链分类基于commodity-chain-analysis v2.11"}


def get_price_action(symbol: str, days: int = 20) -> dict:
    """获取品种近期价格走势摘要。"""
    data = _load_data()
    for entry in data.get("ranked", []):
        s = entry.get('symbol', '').upper()
        if s == symbol.upper():
            raw_name = f"D1_趋势_动量"
            d1 = entry.get("dims", {}).get(raw_name, None)
            d6 = entry.get("dims", {}).get("D6_确认_量价", None)
            return {
                "symbol": symbol,
                "trend_momentum_rank": d1,
                "volume_price_rank": d6,
                "maturity": entry.get("maturity_stage", ""),
                "note": f"因子排名百分位(0-100), 越高=做空越拥挤; 数据来自TDX TQ-Local"
            }
    return {"symbol": symbol, "error": "未找到价格数据"}


if __name__ == "__main__":
    import json
    result = get_factor_decomp("PK")
    print(json.dumps(result, indent=2, ensure_ascii=False)[:500])
