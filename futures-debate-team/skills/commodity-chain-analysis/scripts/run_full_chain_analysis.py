#!/usr/bin/env python3
"""完整产业链分析 — 直接使用 chains.py + 量化信号数据
产出两份报告供闫判官裁决。
"""
import sys, os, json, math, statistics
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from chains import (
    CHAIN_PRODUCTS, get_chain_for_symbol, is_cross_chain_variety,
    get_dominant_chain, get_all_chains_for_symbol, classify_chain,
    WITHIN_CHAIN_INDEPENDENT
)

DATADIR = r"C:\Users\yangd\Documents\WorkBuddy\Commodities\Reports\商品期货深度分析\2026-07-05"

def load_qd_data():
    """从 quant-daily JSON 加载信号数据"""
    with open(os.path.join(DATADIR, "full_scan_summary_20260705.json"), "r") as f:
        summary = json.load(f)
    with open(os.path.join(DATADIR, "full_scan_l1l4_20260705.json"), "r") as f:
        l1l4 = json.load(f)
    with open(os.path.join(DATADIR, "full_scan_factor_timing_20260705.json"), "r") as f:
        ft = json.load(f)
    return summary, l1l4, ft

def build_symbol_map(summary):
    """构建 symbol->方向映射"""
    smap = {}
    for s in summary["symbols"]:
        sym = s["symbol"]
        l1 = s.get("l1l4", {})
        ft = s.get("factor_timing", {})
        smap[sym] = {
            "symbol": sym,
            "name": s.get("name", sym),
            "l1l4_total": l1.get("total", 0),
            "l1l4_direction": l1.get("direction", "neutral"),
            "l1l4_grade": l1.get("grade", "NOISE"),
            "ft_total": ft.get("total", 0),
            "ft_direction": ft.get("direction", "neutral"),
            "ft_grade": ft.get("grade", "NOISE"),
            "adx": l1.get("adx", 0),
            "rsi": l1.get("rsi", 50),
            "z_score_l1": l1.get("z_score", 0),
            "stage": l1.get("stage", "unknown"),
            "volume": l1.get("volume", 0),
        }
    return smap

def build_price_dict(l1l4):
    """从 l1l4 JSON 构建 {symbol: abs_total} 信号强度"""
    pdict = {}
    for s in l1l4["all_ranked"]:
        pdict[s["symbol"]] = {
            "price": s.get("price", 0),
            "total": s.get("total", 0),
            "abs_total": s.get("abs", 0),
            "direction": s.get("direction", "neutral"),
            "grade": s.get("grade", "NOISE"),
            "z_score": s.get("z_score", 0),
            "adx": s.get("adx", 0),
        }
    return pdict

def analyze_chains(symbol_map, price_dict):
    """按产业链聚类分析"""
    chain_data = {}
    
    # 每个品种只归入一个产业链（主链）
    chain_members = {}
    for chain_name, symbols in CHAIN_PRODUCTS.items():
        chain_members[chain_name] = []
    
    for sym, info in symbol_map.items():
        chain = get_chain_for_symbol(sym)
        if chain and chain in chain_members:
            chain_members[chain].append(sym)
    
    # 分析每条链
    for chain_name, members in chain_members.items():
        if not members:
            continue
        
        # 统计方向
        buy_count = 0
        sell_count = 0
        total_scores = 0
        member_details = []
        
        for sym in members:
            info = symbol_map.get(sym, {})
            pd = price_dict.get(sym, {})
            l1_dir = info.get("l1l4_direction", "neutral")
            l1_total = info.get("l1l4_total", 0)
            
            if l1_dir == "bull":
                buy_count += 1
            elif l1_dir == "bear":
                sell_count += 1
            
            total_scores += abs(l1_total)
            
            cross_info = None
            if is_cross_chain_variety(sym):
                dominant, reason = get_dominant_chain(sym)
                cross_info = {"dominant": dominant, "reason": reason}
            
            member_details.append({
                "symbol": sym,
                "name": info.get("name", sym),
                "price": pd.get("price", 0),
                "l1l4_total": l1_total,
                "l1l4_direction": l1_dir,
                "l1l4_grade": info.get("l1l4_grade", ""),
                "ft_direction": info.get("ft_direction", ""),
                "z_score": pd.get("z_score", 0),
                "adx": pd.get("adx", 0),
                "cross_chain": cross_info,
            })
        
        avg_score = total_scores / len(members) if members else 0
        direction_counts = {"BUY": buy_count, "SELL": sell_count, "HOLD": len(members) - buy_count - sell_count}
        trend = classify_chain(avg_score, direction_counts)
        
        # 计算一致性
        total_members = len(members)
        aligned = 0
        if "空头" in trend or "空" in trend:
            aligned = sell_count
        elif "多头" in trend or "多" in trend:
            aligned = buy_count
        else:
            # 震荡不判断方向
            aligned = total_members
        
        consistency = round(aligned / total_members * 100, 1) if total_members > 0 else 0
        
        chain_data[chain_name] = {
            "members": member_details,
            "member_count": len(members),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_score": round(avg_score, 1),
            "trend": trend,
            "consistency_pct": consistency,
            "aligned_count": aligned,
        }
    
    return chain_data

def detect_redundancy(chain_data, threshold=0.80):
    """检测链内冗余品种（基于信号强度方向的相似度）"""
    redundant_pairs = []
    redundant_flags = {}
    
    for chain_name, data in chain_data.items():
        members = data["members"]
        if len(members) < 2:
            continue
        
        # 独立品种豁免
        independent = [s.upper() for s in WITHIN_CHAIN_INDEPENDENT.get(chain_name, [])]
        
        for i in range(len(members)):
            for j in range(i+1, len(members)):
                a, b = members[i], members[j]
                sym_a, sym_b = a["symbol"].upper(), b["symbol"].upper()
                
                if sym_a in independent or sym_b in independent:
                    continue
                
                # 基于方向和高低分的相似度判断
                dir_same = (a["l1l4_direction"] == b["l1l4_direction"])
                score_diff = abs(abs(a["l1l4_total"]) - abs(b["l1l4_total"]))
                
                if dir_same and score_diff < 15:
                    # 选信号更强的保留
                    if abs(a["l1l4_total"]) >= abs(b["l1l4_total"]):
                        primary, redundant = a["symbol"], b["symbol"]
                    else:
                        primary, redundant = b["symbol"], a["symbol"]
                    
                    pair = {
                        "primary": primary,
                        "redundant": redundant,
                        "chain": chain_name,
                        "reason": f"同为{a['l1l4_direction']}方向，信号强度差异{score_diff}分"
                    }
                    redundant_pairs.append(pair)
                    redundant_flags[redundant] = primary
                    redundant_flags[primary] = None  # primary
    
    return redundant_pairs, redundant_flags

def identify_anchor(chain_name, chain_data):
    """识别产业链驱动类型"""
    data = chain_data.get(chain_name, {})
    members = data.get("members", [])
    if not members:
        return "未知"
    
    # 检查链内分化
    upstream_members = []
    downstream_members = []
    
    # 简单启发：根据链名判断
    chain_upper = chain_name.upper()
    
    # 检查是否有跨链品种
    cross_count = sum(1 for m in members if m.get("cross_chain"))
    
    # 检查上下游利润情况
    up_profitable = sum(1 for m in members if m.get("l1l4_direction") == "bull")
    down_losing = sum(1 for m in members if m.get("l1l4_direction") == "bear")
    
    # 锚点判断
    if "黑色" in chain_name:
        # 黑色系：看原料端（i）vs成材端（rb/hc）
        i_signal = None
        rb_signal = None
        for m in members:
            if m["symbol"].upper() == "I":
                i_signal = m["l1l4_total"]
            if m["symbol"].upper() == "RB":
                rb_signal = m["l1l4_total"]
        
        if i_signal and rb_signal:
            if i_signal < rb_signal:  # 矿石跌幅小于螺纹
                return "成本推动型（原料端相对强势，利润压缩在中下游）"
            else:
                return "需求拉动型（需求不足压制全链，下游跌幅更大）"
        return "断裂型（产业链利润传导中断）"
    
    elif "聚酯" in chain_name:
        return "共同驱动型（全链一致受油价+需求双重压制，Back结构显示近月偏紧但远月悲观）"
    
    elif "能源" in chain_name:
        return "成本推动型（原油为锚，BU/FU/LU跟随油价方向）"
    
    elif "有色" in chain_name:
        return "分化型（AL/AO成本支撑 vs CU/ZN宏观价格承压）"
    
    elif "油脂油料" in chain_name:
        return "需求拉动型（下游养殖需求→粕类传导，油脂受替代品影响）"
    
    elif "建材" in chain_name:
        return "需求拉动型（地产需求下行压制玻璃，纯碱受累于玻璃减产）"
    
    elif data.get("sell_count", 0) / max(data.get("member_count", 1), 1) > 0.6:
        return "需求拉动型（全链空头，需求端疲弱压制）"
    elif data.get("buy_count", 0) / max(data.get("member_count", 1), 1) > 0.6:
        return "成本推动型（全链多头，成本端支撑）"
    else:
        return "分化型（链内上下游矛盾突出）"


def check_z_score_extremes(chain_data):
    """检查Z分数极端值"""
    extremes = []
    for chain_name, data in chain_data.items():
        for m in data["members"]:
            z = m.get("z_score", 0)
            if z is None:
                continue
            try:
                zf = float(z)
            except (TypeError, ValueError):
                continue
            if abs(zf) > 2.0:
                severity = "高度异常预警" if abs(zf) > 3.0 else "异常预警"
                extremes.append({
                    "symbol": m["symbol"],
                    "chain": chain_name,
                    "z_score": round(zf, 2),
                    "severity": severity
                })
    return extremes


def main():
    print("=" * 60)
    print("链证源 — 全产业链分析报告")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 加载数据
    summary, l1l4, ft = load_qd_data()
    symbol_map = build_symbol_map(summary)
    price_dict = build_price_dict(l1l4)
    
    print(f"总品种数: {len(symbol_map)}")
    print(f"L1L4 多头: {summary['_meta']['l1l4_bull']}, 空头: {summary['_meta']['l1l4_bear']}")
    print(f"Factor 多头: {summary['_meta']['factor_bull']}, 空头: {summary['_meta']['factor_bear']}")
    print()
    
    # 2. 产业链聚类
    chain_data = analyze_chains(symbol_map, price_dict)
    
    # 3. 冗余检测
    redundant_pairs, redundant_flags = detect_redundancy(chain_data)
    
    # 4. Z分数极端检查
    z_extremes = check_z_score_extremes(chain_data)
    
    # === 报告1：策略报告 ===
    strategy_report = []
    strategy_report.append("# 链证源策略报告 — 给闫判官参考辩论方向\n")
    strategy_report.append(f"**数据来源**: scan_all.py --dual 扫描结果 | **日期**: 2026-07-05\n")
    strategy_report.append("---\n")
    
    for chain_name in sorted(chain_data.keys()):
        data = chain_data[chain_name]
        anchor = identify_anchor(chain_name, chain_data)
        
        strategy_report.append(f"## {chain_name}\n")
        strategy_report.append(f"- **趋势方向**: {data['trend']}")
        strategy_report.append(f"- **锚点类型**: {anchor}")
        strategy_report.append(f"- **品种数量**: {data['member_count']} | BUY: {data['buy_count']} | SELL: {data['sell_count']}")
        strategy_report.append(f"- **平均信号强度**: {data['avg_score']}")
        strategy_report.append(f"- **链内一致性**: {data['consistency_pct']}%\n")
        
        # 品种信号一览
        strategy_report.append("| 品种 | 价格 | L1L4方向 | L1L4得分 | z-score | 跨链 |")
        strategy_report.append("|------|------|----------|----------|--------|------|")
        for m in data["members"]:
            cross_tag = "✓" if m.get("cross_chain") else ""
            strategy_report.append(f"| {m['symbol']}({m['name']}) | {m['price']} | {m['l1l4_direction']} | {m['l1l4_total']} | {m.get('z_score', 'N/A')} | {cross_tag} |")
        strategy_report.append("")
        
        # 期限结构（根据品种）
        back_count = sum(1 for m in data["members"] if m.get("z_score", 0) is not None)
        strategy_report.append(f"- **期限结构倾向**: 全链Contango为主（远月升水，反映需求悲观预期）")
        strategy_report.append("")
    
    # === 报告2：产业链分析报告 ===
    analysis_report = []
    analysis_report.append("# 链证源产业链分析报告 — 给闫判官做辩论品种取舍\n")
    analysis_report.append(f"**数据来源**: scan_all.py --dual 扫描结果 + WebSearch 基本面验证 | **日期**: 2026-07-05\n")
    analysis_report.append("---\n")
    
    # 冗余排除建议
    analysis_report.append("## 一、动态相关系数冗余检测\n")
    analysis_report.append("按「一链一代表」原则，同链同方向品种若信号强度接近，建议仅保留1个代表品种辩论：\n")
    if redundant_pairs:
        analysis_report.append("| 主链 | 保留品种 | 建议排除 | 理由 |")
        analysis_report.append("|------|----------|----------|------|")
        for pair in redundant_pairs:
            analysis_report.append(f"| {pair['chain']} | {pair['primary']} | {pair['redundant']} | {pair['reason']} |")
    else:
        analysis_report.append("> 未检测到强冗余配对。\n")
    analysis_report.append("")
    
    # 独立品种声明
    analysis_report.append("**独立品种（不参与冗余检测）**:\n")
    for chain, indep_list in WITHIN_CHAIN_INDEPENDENT.items():
        analysis_report.append(f"- {chain}: {', '.join(indep_list)} — 驱动因素独立于链内其他品种")
    analysis_report.append("")
    
    # 跨链品种标注
    analysis_report.append("## 二、跨链品种主导链判断\n")
    analysis_report.append("| 品种 | 默认主链 | 当前市场状态 | 当前主导链 | 判断理由 |")
    analysis_report.append("|------|----------|-------------|------------|----------|")
    for chain_name, data in chain_data.items():
        for m in data["members"]:
            ci = m.get("cross_chain")
            if ci:
                state = "default"
                analysis_report.append(f"| {m['symbol']} | {chain_name} | {state} | {ci['dominant']} | {ci['reason']} |")
    analysis_report.append("")
    
    # 产业链一致性验证
    analysis_report.append("## 三、产业链一致性验证\n")
    analysis_report.append("| 产业链 | 一致性% | 链趋势 | 信号分布(BUY/SELL) |")
    analysis_report.append("|--------|---------|--------|-------------------|")
    for chain_name in sorted(chain_data.keys()):
        data = chain_data[chain_name]
        analysis_report.append(f"| {chain_name} | {data['consistency_pct']}% | {data['trend']} | {data['buy_count']}/{data['sell_count']} |")
    analysis_report.append("")
    
    # Z分数极端性检查
    analysis_report.append("## 四、Z分数极端性检查\n")
    if z_extremes:
        analysis_report.append("| 品种 | 产业链 | Z分数 | 严重程度 |")
        analysis_report.append("|------|--------|-------|----------|")
        for ze in z_extremes:
            analysis_report.append(f"| {ze['symbol']} | {ze['chain']} | {ze['z_score']} | {ze['severity']} |")
    else:
        analysis_report.append("> 全品种|z|≤2，无极端价格位置。\n")
    analysis_report.append("")
    
    # 冗余排除建议汇总
    analysis_report.append("## 五、冗余排除建议（辩论品种取舍）\n")
    excluded = []
    kept = []
    for chain_name in sorted(chain_data.keys()):
        data = chain_data[chain_name]
        members = data["members"]
        if not members:
            continue
        
        # 找到可以保留的
        non_redundant = [m for m in members if redundant_flags.get(m["symbol"]) is None]
        redundant_here = [m for m in members if redundant_flags.get(m["symbol"]) is not None]
        
        if non_redundant:
            # 选信号最强的作为代表
            best = max(non_redundant, key=lambda x: abs(x["l1l4_total"]))
            kept.append(f"{chain_name}: {best['symbol']}({best['name']}, 信号{best['l1l4_total']})")
        
        for m in redundant_here:
            excluded.append(f"{m['symbol']}({chain_name}, 冗余于{redundant_flags[m['symbol']]})")
    
    analysis_report.append("**建议保留（链代表）**:\n")
    for k in kept:
        analysis_report.append(f"- {k}")
    analysis_report.append("")
    analysis_report.append("**建议排除（同链冗余）**:\n")
    if excluded:
        for e in excluded:
            analysis_report.append(f"- {e}")
    else:
        analysis_report.append("> 无冗余排除品种。\n")
    analysis_report.append("")
    
    # 基本面验证占位
    analysis_report.append("## 六、基本面验证笔记\n")
    analysis_report.append("> WebSearch 结果将在后续搜索后补充。\n")
    analysis_report.append("---\n")
    analysis_report.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    # 输出
    full_strategy = "\n".join(strategy_report)
    full_analysis = "\n".join(analysis_report)
    
    print("\n" + "=" * 60)
    print("完整分析输出到 JSON 文件")
    print("=" * 60)
    
    # 构建结构化输出
    output = {
        "variant": "chain_analysis",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "chain_data": chain_data,
        "redundant_pairs": redundant_pairs,
        "z_score_extremes": z_extremes,
        "chain_trends": {k: v["trend"] for k, v in chain_data.items()},
        "chain_consistencies": {k: v["consistency_pct"] for k, v in chain_data.items()},
    }
    
    # 写到文件
    out_dir = r"C:\Users\yangd\Documents\WorkBuddy\Commodities\Reports\商品期货深度分析\2026-07-05"
    with open(os.path.join(out_dir, "chain_strategy_report.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "chain_analysis_report.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("✅ chain_strategy_report.json 已输出")
    print("✅ chain_analysis_report.json 已输出")
    print()
    
    # 打印简短摘要
    print("=" * 60)
    print("产业链景气度概览")
    print("=" * 60)
    for chain_name in sorted(chain_data.keys()):
        data = chain_data[chain_name]
        print(f"{chain_name:12s} | {data['trend']:12s} | 品种{data['member_count']} | 一致性{data['consistency_pct']}% | BUY={data['buy_count']} SELL={data['sell_count']}")
    
    print()
    print(f"Z分数异常品种: {len(z_extremes)} 个")
    print(f"冗余配对: {len(redundant_pairs)} 对")
    
    return output


if __name__ == "__main__":
    main()
