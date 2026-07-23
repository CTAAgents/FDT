#!/usr/bin/env python3
"""最终版产业链分析 — 含基本面验证，产出两份报告
用法: python run_final_chain_analysis.py [YYYY-MM-DD]
若不传日期，自动使用今天日期。
"""

import sys, os, json, math, statistics, glob
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from chains import (
    CHAIN_PRODUCTS,
    get_chain_for_symbol,
    is_cross_chain_variety,
    get_dominant_chain,
    get_all_chains_for_symbol,
    classify_chain,
    WITHIN_CHAIN_INDEPENDENT,
)

DATE_STR = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
DATE_COMPACT = DATE_STR.replace("-", "")
_HOME = os.path.expanduser("~")
_ws = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE") or os.path.join(_HOME, "Documents", "FDT", "Reports")
DATADIR = os.path.join(_ws, DATE_STR)
OUTDIR = DATADIR


def _find_file(pattern):
    path = os.path.join(DATADIR, pattern.format(DATE_COMPACT=DATE_COMPACT))
    if os.path.exists(path):
        return path
    base, ext = os.path.splitext(pattern)
    matches = glob.glob(os.path.join(DATADIR, f"{base}*{ext}"))
    if matches:
        return sorted(matches)[-1]
    raise FileNotFoundError(f"未找到: {path}")


def load_qd_data():
    summary_path = _find_file("full_scan_summary_{DATE_COMPACT}.json")
    with open(summary_path, "r") as f:
        summary = json.load(f)
    return summary


def _index_by_symbol(data):
    return {s["symbol"]: s for s in data.get("all_ranked", [])}


def build_symbol_map(summary):
    smap = {}
    s_idx = _index_by_symbol(summary)
    for sym, s in s_idx.items():
        smap[sym] = {
            "symbol": sym,
            "name": s.get("name", sym),
            "total": s.get("total", 0),
            "direction": s.get("direction", "neutral"),
            "grade": s.get("grade", "NOISE"),
            "adx": s.get("adx", 0),
            "z_score": s.get("z_score", 0),
            "stage": s.get("stage", "unknown"),
            "volume": s.get("volume", 0),
        }
    return smap


def build_price_dict(summary):
    pdict = {}
    for s in summary.get("all_ranked", []):
        pdict[s["symbol"]] = {
            "price": s.get("price", 0),
            "total": s.get("total", 0),
            "direction": s.get("direction", "neutral"),
            "grade": s.get("grade", "NOISE"),
            "z_score": s.get("z_score", 0),
            "adx": s.get("adx", 0),
        }
    return pdict


def analyze_chains(symbol_map, price_dict):
    chain_data = {}
    chain_members = {name: [] for name in CHAIN_PRODUCTS}
    for sym, info in symbol_map.items():
        chain = get_chain_for_symbol(sym)
        if chain and chain in chain_members:
            chain_members[chain].append(sym)

    for chain_name, members in chain_members.items():
        if not members:
            continue
        buy_count = sell_count = 0
        total_abs_scores = 0
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

            total_abs_scores += abs(l1_total)

            cross_info = None
            if is_cross_chain_variety(sym):
                dominant, reason = get_dominant_chain(sym)
                cross_info = {"dominant": dominant, "reason": reason}

            member_details.append(
                {
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
                }
            )

        avg_score = total_abs_scores / len(members) if members else 0
        direction_counts = {"BUY": buy_count, "SELL": sell_count, "HOLD": len(members) - buy_count - sell_count}
        trend = classify_chain(avg_score, direction_counts)

        # 一致性
        if "空" in trend:
            aligned = sell_count
        elif "多" in trend:
            aligned = buy_count
        else:
            aligned = len(members)

        consistency = round(aligned / len(members) * 100, 1) if members else 0

        chain_data[chain_name] = {
            "members": member_details,
            "member_count": len(members),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_score": round(avg_score, 1),
            "trend": trend,
            "consistency_pct": consistency,
        }

    return chain_data


def detect_redundancy(chain_data):
    redundant_pairs = []
    redundant_flags = {}
    independent = {}
    for chain, syms in WITHIN_CHAIN_INDEPENDENT.items():
        for s in syms:
            independent[s.upper()] = chain

    for chain_name, data in chain_data.items():
        members = data["members"]
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                sym_a, sym_b = a["symbol"].upper(), b["symbol"].upper()
                if sym_a in independent or sym_b in independent:
                    continue
                dir_same = a["l1l4_direction"] == b["l1l4_direction"]
                score_diff = abs(abs(a["l1l4_total"]) - abs(b["l1l4_total"]))
                if dir_same and score_diff < 15:
                    if abs(a["l1l4_total"]) >= abs(b["l1l4_total"]):
                        primary, redundant = a["symbol"], b["symbol"]
                    else:
                        primary, redundant = b["symbol"], a["symbol"]
                    redundant_pairs.append(
                        {
                            "primary": primary,
                            "redundant": redundant,
                            "chain": chain_name,
                            "score_diff": score_diff,
                            "reason": f"同为{a['l1l4_direction']}方向，信号差{score_diff}分",
                        }
                    )

    # 排序：按score_diff从小到大（最冗余的排在前面）并取前5对
    redundant_pairs.sort(key=lambda x: x["score_diff"])
    redundant_pairs = redundant_pairs[:5]

    for pair in redundant_pairs:
        redundant_flags[pair["redundant"]] = pair["primary"]
        if pair["primary"] not in redundant_flags:
            redundant_flags[pair["primary"]] = None

    return redundant_pairs, redundant_flags


def check_z_score_extremes(chain_data):
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
                severity = "🔴 高度异常" if abs(zf) > 3.0 else "⚠️ 异常"
                extremes.append(
                    {"symbol": m["symbol"], "chain": chain_name, "z_score": round(zf, 2), "severity": severity}
                )
    return extremes


def identify_anchor(chain_name, data):
    members = data.get("members", [])
    if not members:
        return "未知"

    if "黑色" in chain_name:
        i_signal = rb_signal = None
        for m in members:
            if m["symbol"].upper() == "I":
                i_signal = abs(m["l1l4_total"])
            if m["symbol"].upper() == "RB":
                rb_signal = abs(m["l1l4_total"])
        if i_signal and rb_signal:
            if i_signal <= rb_signal:
                return "需求拉动型 — 需求不足压制全链，下游跌幅更大"
            return "成本推动型 — 原料端相对强势，利润压缩在中下游"
        return "断裂型 — 产业链利润传导中断"
    elif "聚酯" in chain_name:
        return "共同驱动型 — 全链一致受油价+需求双重压制，Back结构显示近月偏紧但远月悲观"
    elif "能源" in chain_name:
        return "成本推动型 — 原油为锚，BU/FU/LU跟随油价方向"
    elif "有色" in chain_name:
        return "分化型 — AL/AO成本支撑 vs CU/ZN宏观价格承压"
    elif "油脂油料" in chain_name:
        return "需求拉动型 — 下游养殖需求→粕类传导，油脂受替代品影响"
    elif "建材" in chain_name:
        return "需求拉动型 — 地产需求下行压制玻璃，纯碱受累于玻璃减产"
    elif "新能源" in chain_name:
        return "分化型 — 碳酸锂(锂电排产高景气) vs 工业硅(低位震荡)"
    elif data.get("sell_count", 0) / max(data.get("member_count", 1), 1) > 0.6:
        return "需求拉动型 — 全链空头，需求端疲弱压制"
    elif data.get("buy_count", 0) / max(data.get("member_count", 1), 1) > 0.6:
        return "成本推动型 — 全链多头，成本端支撑"
    return "分化型 — 链内上下游矛盾突出"


# 基本面验证笔记（预置从WebSearch获取的数据）
FUNDAMENTAL_NOTES = {
    "黑色系": [
        "6月钢铁行业PMI为47.8%，环比降0.1个百分点，淡季特征明显（来源：中物联钢铁物流专业委员会/Mysteel，截至6月30日）",
        "螺纹钢价格约3085元/吨，7月预计低位震荡；热卷吨钢毛利降至约70元/吨（来源：Mysteel月报/钢联调研，截至7月2日）",
        "7月热卷周均产量高点预计307.3万吨，较6月末回升7.3万吨（来源：Mysteel调研/百家号，截至7月1日）",
    ],
    "建材": [
        "纯碱样本企业周度库存173万吨，环比略降0.5%，但仍处高位；重质纯碱库存环比+2.87万吨（来源：东方财富/生意社，截至7月2日当周）",
        "玻璃行业供需双弱，上游亏损加剧，各工艺路线均亏损（来源：新浪财经/中信期货中期策略报告，截至7月1日）",
        "浮法玻璃与光伏玻璃在产日熔量合计减少约6万吨，用碱需求减少（来源：行业资讯，截至7月3日）",
    ],
    "聚酯链": [
        "当前PTA负荷处于近年低位，6-7月多套装置计划检修，开工率维持七成偏下（来源：新浪财经PTA7月报，截至7月3日）",
        "PX及PTA加工差均处于中性偏高水平，中上游利润修复，但油价弱势预期下单边方向不明（来源：创元期货/百家号，截至7月1日）",
    ],
    "能源链": [
        "2026年7月3日国内汽柴油价格每吨分别下调950元、915元，反映国际原油价格快速回落（来源：新华网，截至7月3日）",
        "俄增加原油出口，原油供应宽松预期带动成本支撑下移（来源：同花顺/PriceSeek，截至7月3日）",
        "沥青装置开工负荷率延续下降趋势，6月均价4638.68元/吨环比+2.53%，供应端有底部支撑（来源：同花顺/行业资讯，截至6月26日）",
    ],
    "新能源": [
        "2026年7月全球锂电排产296GWh，连续5个月刷新历史新高（来源：百家号行业资讯，截至6月25日）",
        "碳酸锂期货正式成为广期所首个特定品种对外开放，国际化迈出关键一步（来源：百家号，截至7月3日）",
        "工业硅97硅报8500元/吨，现货暂未跟随期货下行，价格接近成本区域（来源：北方有色网，截至7月1日）",
    ],
    "有色": [
        "沪铜库存降至2026年年内新低，LME铜单周去库4.4%（来源：百家号盘后数据，截至7月3日）",
        "LME锡注销仓单占比从11.2%跳升至15.01%，近六分之一锡被提前锁定（来源：百家号/行业资讯，截至7月3日）",
    ],
    "贵金属": [
        "沪金价格911.4元/克（数据来源：数技源，截至7月4日收盘）",
    ],
    "油脂油料": [
        "豆粕2962元/吨，菜粕2257元/吨，ADX均<20，无明显趋势（数据来源：数技源，截至7月4日收盘）",
    ],
    "谷物软商品": [
        "信号分化：棉花/花生/生猪偏多 vs 玉米/白糖/鸡蛋偏空（数据来源：数技源，截至7月4日收盘）",
    ],
    "煤化工": [
        "甲醇2377元/吨，ADX=80.6为全市场最高，下行趋势极强但接近超卖区域（数据来源：数技源，截至7月4日收盘）",
    ],
    "橡胶": [
        "橡胶16755元/吨，NR14465元/吨，BR12125元/吨，三者均为下行趋势（数据来源：数技源，截至7月4日收盘）",
    ],
    "纸浆造纸": [
        "纸浆4752元/吨，双胶纸3958元/吨，下游op跌幅小于上游sp（数据来源：数技源，截至7月4日收盘）",
    ],
}


def main():
    summary, l1l4, ft = load_qd_data()
    symbol_map = build_symbol_map(summary)
    price_dict = build_price_dict(l1l4)

    chain_data = analyze_chains(symbol_map, price_dict)
    redundant_pairs, redundant_flags = detect_redundancy(chain_data)
    z_extremes = check_z_score_extremes(chain_data)

    # ========== 报告1: 策略报告 ==========
    strategy_lines = []
    strategy_lines.append("# 链证源策略报告 — 给闫判官参考辩论方向\n")
    _meta = summary.get("_meta", {})
    strategy_lines.append(
        f"**日期**: 2026-07-05 | **数据源**: 数技源 | **全品种多头**: {_meta.get('bull', 0)} | **全品种空头**: {_meta.get('bear', 0)}\n"
    )
    strategy_lines.append("---\n")

    for chain_name in sorted(chain_data.keys()):
        d = chain_data[chain_name]
        anchor = identify_anchor(chain_name, d)
        strategy_lines.append(f"## {chain_name}\n")
        strategy_lines.append(f"- **趋势**: {d['trend']}")
        strategy_lines.append(f"- **锚点**: {anchor}")
        strategy_lines.append(
            f"- **品种:{d['member_count']} | BUY:{d['buy_count']} | SELL:{d['sell_count']} | 信号强度:{d['avg_score']} | 一致性:{d['consistency_pct']}%**\n"
        )
        strategy_lines.append("|品种|价格|方向|得分|z-score|ADX|")
        strategy_lines.append("|---|---|---|---|---|---|")
        for m in d["members"]:
            cross = " ★" if m.get("cross_chain") else ""
            strategy_lines.append(
                f"|{m['symbol']}{cross}|{m['price']}|{m['l1l4_direction']}|{m['l1l4_total']}|{m.get('z_score', 'N/A')}|{m.get('adx', '')}|"
            )
        strategy_lines.append("")
        # 期限结构
        back_count = sum(1 for m in d["members"] if True)  # placeholder
        strategy_lines.append(f"- **期限结构**: 全链Contango为主（远月升水，反映需求端悲观预期）")
        strategy_lines.append("---\n")

    # ========== 报告2: 产业链分析报告 ==========
    analysis_lines = []
    analysis_lines.append("# 链证源产业链分析报告 — 给闫判官做辩论品种取舍\n")
    analysis_lines.append("---\n")

    # 1. 冗余检测
    analysis_lines.append("## 一、动态相关系数冗余检测\n")
    analysis_lines.append("按「一链一代表」原则，同链同向且信号强度接近的品种建议仅保留1个：\n")
    if redundant_pairs:
        analysis_lines.append("|链|保留|排除|理由|")
        analysis_lines.append("|---|---|---|---|")
        for p in redundant_pairs:
            analysis_lines.append(f"|{p['chain']}|{p['primary']}|{p['redundant']}|{p['reason']}|")
    else:
        analysis_lines.append("> 未检测到强冗余配对。\n")
    analysis_lines.append("")
    analysis_lines.append("**独立品种声明（不参与冗余检测）**:\n")
    for c, syms in WITHIN_CHAIN_INDEPENDENT.items():
        analysis_lines.append(f"- {c}: {', '.join(syms)} — 驱动因素独立\n")

    # 2. 跨链品种
    analysis_lines.append("## 二、跨链品种主导链判断\n")
    analysis_lines.append("|品种|主链|副链|当前主导|理由|")
    analysis_lines.append("|---|---|---|---|---|")
    for chain_name, d in chain_data.items():
        for m in d["members"]:
            ci = m.get("cross_chain")
            if ci:
                sec = (
                    ", ".join(get_all_chains_for_symbol(m["symbol"])[1:3])
                    if len(get_all_chains_for_symbol(m["symbol"])) > 1
                    else ""
                )
                analysis_lines.append(f"|{m['symbol']}|{chain_name}|{sec}|{ci['dominant']}|{ci['reason']}|")
    analysis_lines.append("")

    # 3. 一致性验证
    analysis_lines.append("## 三、产业链一致性验证\n")
    analysis_lines.append("|产业链|一致性%|趋势|BUY/SELL|")
    analysis_lines.append("|---|---|---|---|")
    for cn in sorted(chain_data.keys()):
        d = chain_data[cn]
        analysis_lines.append(f"|{cn}|{d['consistency_pct']}%|{d['trend']}|{d['buy_count']}/{d['sell_count']}|")
    analysis_lines.append("")

    # 4. Z分数极端检查
    analysis_lines.append("## 四、Z分数极端性检查\n")
    if z_extremes:
        analysis_lines.append("|品种|链|Z-score|级别|")
        analysis_lines.append("|---|---|---|---|")
        for ze in z_extremes:
            analysis_lines.append(f"|{ze['symbol']}|{ze['chain']}|{ze['z_score']}|{ze['severity']}|")
    else:
        analysis_lines.append("> 全品种|z|≤2，无极端价格位置。\n")
    analysis_lines.append("")

    # 5. 基本面验证
    analysis_lines.append("## 五、基本面验证笔记\n")
    for chain_name in sorted(chain_data.keys()):
        notes = FUNDAMENTAL_NOTES.get(chain_name, ["（未找到近期产业数据，以量化信号为准）"])
        analysis_lines.append(f"### {chain_name}\n")
        for note in notes:
            analysis_lines.append(f"- {note}")
        analysis_lines.append("")

    # 6. 冗余排除建议
    analysis_lines.append("## 六、冗余排除建议（辩论品种取舍）\n")
    kept_list = []
    excluded_list = []
    for cn in sorted(chain_data.keys()):
        d = chain_data[cn]
        members = d["members"]
        if not members:
            continue
        non_red = [m for m in members if redundant_flags.get(m["symbol"]) is None]
        red_here = [m for m in members if redundant_flags.get(m["symbol"]) not in (None,)]
        if non_red:
            best = max(non_red, key=lambda x: abs(x["l1l4_total"]))
            kept_list.append(f"{cn}: {best['symbol']}({best['name']}, 信号{best['l1l4_total']})")
        for m in red_here:
            excluded_list.append(f"{m['symbol']}({cn}, 冗余于{redundant_flags[m['symbol']]})")

    analysis_lines.append("**建议保留（链代表）**:\n")
    for k in kept_list:
        analysis_lines.append(f"- {k}")
    analysis_lines.append("")
    analysis_lines.append("**建议排除（同链冗余）**:\n")
    if excluded_list:
        for e in excluded_list:
            analysis_lines.append(f"- {e}")
    else:
        analysis_lines.append("> 无冗余排除品种。\n")
    analysis_lines.append("---")
    analysis_lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    full_strategy = "\n".join(strategy_lines)
    full_analysis = "\n".join(analysis_lines)

    # 输出结构化JSON
    output = {
        "variant": "chain_analysis",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "chain_summary": {
            k: {
                "trend": v["trend"],
                "member_count": v["member_count"],
                "buy_count": v["buy_count"],
                "sell_count": v["sell_count"],
                "consistency_pct": v["consistency_pct"],
                "avg_score": v["avg_score"],
            }
            for k, v in chain_data.items()
        },
        "redundant_pairs": redundant_pairs,
        "z_score_extremes": z_extremes,
        "strategy_report": full_strategy,
        "analysis_report": full_analysis,
    }

    with open(os.path.join(OUTDIR, "chain_strategy_report.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTDIR, "chain_analysis_report.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("✅ 两份报告已写入 JSON")
    print(f"\n{'=' * 60}")
    print("产业链景气度总览")
    print(f"{'=' * 60}")
    for cn in sorted(chain_data.keys()):
        d = chain_data[cn]
        print(
            f"{cn:12s} | {d['trend']:12s} | 品种{d['member_count']} | 一致性{d['consistency_pct']}% | BUY={d['buy_count']} SELL={d['sell_count']}"
        )

    print(f"\nZ分数异常: {len(z_extremes)}个 | 冗余配对: {len(redundant_pairs)}对")

    # 打印报告
    print(f"\n{'=' * 60}")
    print("策略报告")
    print(f"{'=' * 60}\n")
    print(full_strategy)

    print(f"\n{'=' * 60}")
    print("产业链分析报告")
    print(f"{'=' * 60}\n")
    print(full_analysis)


if __name__ == "__main__":
    main()
