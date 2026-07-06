#!/usr/bin/env python3
"""
产业链分析 CLI — 辩论专家团 P2 链证源入口
==========================================
接受品种列表或 P1 JSON 输出，完成产业链聚类、期限结构、基差分析、冗余检测。
v2.15.0+ 新增：
  - 自动从MultiSourceAdapter获取K线数据（无需外部预生成prices.json）
  - 闫判官裁决建议输出（冗余排除+辩论品种建议）
  - --correlation-prices 仍支持手动传入（优先级高于自动获取）

用法:
  # 直接指定品种（自动获取价格数据）
  python analyze_chain.py --symbols PK,RB,B,UR

  # 读取 P1 JSON 输出（包含价格和信号数据）
  python analyze_chain.py --input ../phase1_output.json

  # 指定品种 + 仅输出 JSON（不打印详细报告）
  python analyze_chain.py --symbols SA,RB,FU --json-only

  # 自定义窗口和阈值
  python analyze_chain.py --symbols ALL --correlation-window 90 --correlation-threshold 0.85
"""

import sys, os, json, math, statistics
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from chains import (
    get_chain_for_symbol,
    CHAIN_PRODUCTS,
    classify_chain,
    cluster_chains,
    WITHIN_CHAIN_HIGH_CORRELATION,
    WITHIN_CHAIN_INDEPENDENT,
)

# ── CLI ──
import argparse

parser = argparse.ArgumentParser(description="产业链分析 — 辩论专家团 P2 链证源")
parser.add_argument("--symbols", "-s", help="品种代码(逗号分隔)，如: PK,RB,B,UR", default=None)
parser.add_argument("--input", "-i", help="P1 JSON 输入文件路径", default=None)
parser.add_argument("--json-only", action="store_true", help="只输出 JSON，不打印详细报告")
parser.add_argument("--correlation-prices", "-c", help="品种历史价格JSON路径(优先级高于自动获取)", default=None)
parser.add_argument("--correlation-window", type=int, default=60, help="滚动相关系数窗口(默认60日)")
parser.add_argument("--correlation-threshold", type=float, default=0.80, help="相关系数阈值(默认0.80)")
args = parser.parse_args()


def _auto_fetch_prices(symbols: list) -> dict:
    """自动从可用的数据适配器获取K线价格数据。

    尝试路径（按优先级）：
    1. quant-daily 的 MultiSourceAdapter
    2. 本地通达信 TQ-Local 桥接
    返回 {SYM: [close_prices]}，失败时返回空dict
    """
    price_series = {}

    # 路径1: 从quant-daily加载MultiSourceAdapter
    for quant_path in [
        os.path.join(os.path.dirname(SKILL_DIR), "quant-daily", "scripts"),
        os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "quant-daily", "scripts"),
    ]:
        if os.path.exists(quant_path):
            try:
                if quant_path not in sys.path:
                    sys.path.insert(0, quant_path)
                from data.multi_source_adapter import MultiSourceAdapter

                adapter = MultiSourceAdapter()
                for sym in symbols:
                    try:
                        result = adapter.get_kline(sym.lower())
                        if result.get("success") and result.get("data"):
                            prices = [r["close"] for r in result["data"] if r.get("close")]
                            if len(prices) >= 20:
                                price_series[sym.upper()] = prices
                    except Exception:
                        continue
                if price_series:
                    return price_series
            except (ImportError, Exception):
                sys.path.pop(0)
                continue

    return price_series


def _compute_pearson(a: list, b: list, window: int) -> float:
    """计算两个品种的滚动Pearson相关系数（最近window日均值）"""
    n = min(len(a), len(b), window)
    if n < 10:
        return 0.0
    a = a[-n:]
    b = b[-n:]
    avg_a = sum(a) / n
    avg_b = sum(b) / n
    num = sum((a[i] - avg_a) * (b[i] - avg_b) for i in range(n))
    den_a = math.sqrt(sum((a[i] - avg_a) ** 2 for i in range(n)))
    den_b = math.sqrt(sum((b[i] - avg_b) ** 2 for i in range(n)))
    if den_a == 0 or den_b == 0:
        return 0.0
    r = num / (den_a * den_b)
    return max(-1.0, min(1.0, r))


def lookup_symbol_names(pids: list) -> list:
    """构建 (pid, name) 列表，从 CHAIN_PRODUCTS 中查找"""
    # 构建 pid→name 反向映射
    pid_to_name = {}
    for chain, members in CHAIN_PRODUCTS.items():
        for m in members:
            pid_to_name[m.upper()] = m  # 用原始大小写
            pid_to_name[m] = m
    result = []
    for pid in pids:
        pid_up = pid.upper()
        if pid_up in pid_to_name:
            result.append((pid_up, pid_to_name[pid_up]))
        else:
            result.append((pid_up, pid))
    return result


def get_chain_members(chain_name):
    """获取产业链成员列表"""
    return CHAIN_PRODUCTS.get(chain_name, [])


def build_symbols_data(symbols_list: list) -> list:
    """从 (pid, name) 列表构建 symbols_data（含默认值）"""
    return [
        {
            "product_id": pid,
            "product_name": name,
            "last_price": 0,
            "direction": "NEUTRAL",
            "score": 0,
            "open_interest": 0,
        }
        for pid, name in symbols_list
    ]


def build_symbols_from_p1(input_path: str) -> list:
    """从 P1 JSON 输出构建 symbols_data"""
    with open(input_path, "r", encoding="utf-8") as f:
        p1 = json.load(f)

    symbols_data = []
    contracts = p1.get("contracts", p1.get("all_actionable", []))
    if isinstance(contracts, list) and all(isinstance(c, str) for c in contracts):
        for pid in contracts:
            name = p1.get("verdicts", {}).get(pid, {}).get("name", pid)
            price = p1.get("key_prices", {}).get(pid, 0)
            direction = p1.get("verdicts", {}).get(pid, "NEUTRAL")
            score = 0
            for r in p1.get("all_actionable", []):
                if r.get("symbol") == pid:
                    score = r.get("total", 0)
                    break
            symbols_data.append(
                {
                    "product_id": pid,
                    "product_name": name,
                    "last_price": price,
                    "direction": direction,
                    "score": score,
                    "open_interest": 0,
                }
            )
    elif isinstance(contracts, list) and all(isinstance(c, dict) for c in contracts):
        for c in contracts:
            symbols_data.append(
                {
                    "product_id": c.get("symbol", c.get("product_id", "")),
                    "product_name": c.get("name", c.get("product_name", "")),
                    "last_price": c.get("price", c.get("last_price", 0)),
                    "direction": c.get("direction", c.get("verdict", "NEUTRAL")),
                    "score": abs(c.get("total", c.get("score", 0))),
                    "open_interest": c.get("open_interest", 0),
                }
            )
    return symbols_data


# ============================================================
# 主流程
# ============================================================


def run_analysis(symbols_data: list) -> dict:
    """执行产业链分析，返回结构化结果"""
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chain_results = {}
    chain_groups = {}
    chain_info = {}
    z_scores = {}
    redundant_pairs = []

    # ── Step 1: 产业链归类 ──
    if not args.json_only:
        print("\n📌 Step 1: 产业链归类")
        print("-" * 50)

    for s in symbols_data:
        pid = s["product_id"]
        chain = get_chain_for_symbol(pid)
        if chain is None:
            chain = get_chain_for_symbol(pid.upper())
        if chain is None:
            chain = get_chain_for_symbol(pid.lower())
        members = get_chain_members(chain) if chain else []
        chain_info[pid] = {"chain": chain or "未归类", "members": members}

        if not args.json_only:
            print(f"  {pid:>6} → {chain or '未归类':<16}  成员: {members}")

        if chain:
            if chain not in chain_groups:
                chain_groups[chain] = []
            chain_groups[chain].append(s)

    # ── Step 2: 期限结构与基差估算 ──
    if not args.json_only:
        print("\n📌 Step 2: 期限结构与基差分析")
        print("-" * 50)

    term_structures = {}
    for s in symbols_data:
        pid = s["product_id"]
        # 根据信号方向推断期限结构
        if s["direction"] in ("SELL", "bear", "空头下跌") and s["score"] >= 60:
            ts, basis = "contango", "走弱"
        elif s["direction"] in ("BUY", "bull", "多头上涨") and s["score"] >= 60:
            ts, basis = "back", "走强"
        else:
            ts, basis = "flat", "平稳"
        term_structures[pid] = {"term_structure": ts, "basis": basis}

        if not args.json_only:
            print(f"  {pid:>6}: 期限={ts} | 基差={basis}")

    # ── Step 3: 产业链一致性 ──
    if not args.json_only:
        print("\n📌 Step 3: 产业链一致性验证")
        print("-" * 50)

    chain_trends = {}
    chain_consistencies = {}
    for chain, items in chain_groups.items():
        directions = [s["direction"] for s in items]
        scores = [s["score"] for s in items]
        bull_ct = sum(1 for d in directions if d in ("BUY", "bull", "多头上涨"))
        bear_ct = sum(1 for d in directions if d in ("SELL", "bear", "空头下跌"))
        neutral_ct = len(directions) - bull_ct - bear_ct
        avg_score = sum(scores) / len(scores) if scores else 0

        if bull_ct > 0 and bear_ct == 0:
            trend = "强势多头"
            consistency = 100
        elif bear_ct > 0 and bull_ct == 0:
            trend = "强势空头"
            consistency = 100
        elif bull_ct > bear_ct:
            trend = "偏多震荡"
            consistency = 50
        elif bear_ct > bull_ct:
            trend = "偏空震荡"
            consistency = 50
        else:
            trend = "分化" if neutral_ct < len(items) else "震荡"
            consistency = 0

        chain_trends[chain] = trend
        chain_consistencies[chain] = consistency

        if not args.json_only:
            print(f"  {chain:<16}: {trend} (一致性={consistency}%, 多{bull_ct}空{bear_ct}中{neutral_ct})")

    # ── Step 4: 同链冗余检测（动态相关系数） ──
    if not args.json_only:
        print("\n📌 Step 4: 同链冗余检测（动态相关系数）")
        print("-" * 50)

    # 加载历史价格数据（优先级：--correlation-prices > 自动获取）
    price_series = {}  # {pid: [close_prices]}
    if args.correlation_prices and os.path.exists(args.correlation_prices):
        with open(args.correlation_prices, "r", encoding="utf-8") as f:
            price_series = json.load(f)
        if not args.json_only:
            print(f"  📊 手动传入价格数据: {len(price_series)}个品种")
    else:
        # 自动获取
        fetch_symbols = list(set(s["product_id"].upper() for s in symbols_data))
        price_series = _auto_fetch_prices(fetch_symbols)
        if price_series:
            if not args.json_only:
                print(f"  🔄 自动获取K线数据: {len(price_series)}/{len(fetch_symbols)}个品种")
        else:
            if not args.json_only:
                print(f"  ⚠️ 无可用数据源，跳过动态相关性检测")

    for chain, items in chain_groups.items():
        if len(items) <= 1:
            continue

        # 收集同链所有品种
        chain_symbols = [s["product_id"] for s in items]

        if not args.json_only:
            print(f"\n  [{chain}] 共{len(chain_symbols)}个品种: {', '.join(chain_symbols)}")

        # 检查哪些品种声明为独立（不参与冗余检测）
        independent_syms = [s.upper() for s in WITHIN_CHAIN_INDEPENDENT.get(chain, [])]

        # 计算所有配对的相关性
        checked_pairs = set()
        for i in range(len(chain_symbols)):
            for j in range(i + 1, len(chain_symbols)):
                sym_a = chain_symbols[i].upper()
                sym_b = chain_symbols[j].upper()
                pair_key = tuple(sorted([sym_a, sym_b]))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                # 检查独立声明
                if sym_a in independent_syms or sym_b in independent_syms:
                    if not args.json_only:
                        print(f"    ○ {sym_a}↔{sym_b}: 独立品种(已声明), 跳过")
                    continue

                # 如果有价格数据，计算相关系数
                if sym_a in price_series and sym_b in price_series:
                    r = _compute_pearson(price_series[sym_a], price_series[sym_b], args.correlation_window)
                    r_rounded = round(r, 3)
                    if r > args.correlation_threshold:
                        # 按信号强度决定主/冗余
                        score_a = next((s["score"] for s in items if s["product_id"].upper() == sym_a), 0)
                        score_b = next((s["score"] for s in items if s["product_id"].upper() == sym_b), 0)
                        primary = sym_a if score_a >= score_b else sym_b
                        redundant = sym_b if primary == sym_a else sym_a
                        redundant_pairs.append(
                            {
                                "primary": primary,
                                "redundant": redundant,
                                "chain": chain,
                                "reason": f"滚动相关系数{r_rounded:.2f} (>{args.correlation_threshold}), 动态检测",
                            }
                        )
                        if not args.json_only:
                            print(f"    ⚠️ 冗余: {sym_a}↔{sym_b} (r={r_rounded:.2f}) → 保留{primary}, 排除{redundant}")
                    else:
                        if not args.json_only:
                            print(f"    ✅ 低相关: {sym_a}↔{sym_b} (r={r_rounded:.2f})")
                else:
                    if not args.json_only and args.correlation_prices:
                        missing = [x for x in [sym_a, sym_b] if x not in price_series]
                        print(f"    ? {sym_a}↔{sym_b}: 缺少价格数据({missing}), 跳过")

    if not redundant_pairs and not args.json_only:
        print(f"  本次未检出同链高相关冗余品种")

    # 删除/废弃旧逻辑（已完全替换为动态相关性）

    # ── 闫判官裁决建议（v2.15.0+） ──
    # 按"一链一代表"原则：同链内冗余品种只保留最高score的primary

    # 从 price_series 或 symbols_data 获取全集
    if price_series:
        all_syms = set(price_series.keys())
    else:
        all_syms = set(s["product_id"].upper() for s in symbols_data)

    judge_verdict = {
        "excluded_symbols": sorted(set(r["redundant"] for r in redundant_pairs)),
        "kept_symbols": [],
        "chain_representatives": {},
        "principle": "一链一代表（同链高相关品种只保留信号最强的1个）",
        "all_symbols": sorted(all_syms),
    }
    for rp in redundant_pairs:
        chain = rp["chain"]
        if chain not in judge_verdict["chain_representatives"]:
            judge_verdict["chain_representatives"][chain] = []
        if rp["primary"] not in judge_verdict["chain_representatives"][chain]:
            judge_verdict["chain_representatives"][chain].append(rp["primary"])
    excluded = set(r["redundant"] for r in redundant_pairs)
    judge_verdict["kept_symbols"] = sorted(all_syms - excluded)
    judge_verdict["debate_count"] = len(judge_verdict["kept_symbols"])
    judge_verdict["excluded_count"] = len(judge_verdict["excluded_symbols"])

    if not args.json_only:
        print(f"\n{'=' * 70}")
        print("⚖️ 闫判官裁决建议（链证源产出）")
        print(f"{'=' * 70}")
        print(f"  保留辩论: {judge_verdict['debate_count']}个 → {judge_verdict['kept_symbols']}")
        print(f"  排除冗余: {judge_verdict['excluded_count']}个 → {judge_verdict['excluded_symbols']}")
        for chain, reps in judge_verdict["chain_representatives"].items():
            excl = [r["redundant"] for r in redundant_pairs if r["chain"] == chain]
            print(f"    {chain}: 保留{reps} | 排除{excl}")

    # ── 汇总输出 ──
    chain_results = {}
    for s in symbols_data:
        pid = s["product_id"]
        cinfo = chain_info.get(pid, {})
        chain = cinfo.get("chain", "未归类")
        ts = term_structures.get(pid, {"term_structure": "flat", "basis": "平稳"})

        is_redundant = False
        redundant_with = None
        for rp in redundant_pairs:
            if rp["redundant"] == pid:
                is_redundant = True
                redundant_with = rp["primary"]

        chain_results[pid] = {
            "chain": chain,
            "chain_members": cinfo.get("members", []),
            "term_structure": ts["term_structure"],
            "basis": ts["basis"],
            "chain_trend": chain_trends.get(chain, "未知"),
            "chain_consistency": chain_consistencies.get(chain, 0),
            "redundant": is_redundant,
            "redundant_with": redundant_with,
            "notes": [],
        }

    if not args.json_only:
        print(f"\n{'=' * 70}")
        print("产业链验证汇总")
        print(f"{'=' * 70}")
        for s in symbols_data:
            pid = s["product_id"]
            cr = chain_results[pid]
            print(f"  {pid:>6}({s['product_name']})")
            print(f"    产业链: {cr['chain']}")
            print(f"    期限结构: {cr['term_structure']} | 基差: {cr['basis']}")
            print(f"    链趋势: {cr['chain_trend']} (一致性{cr['chain_consistency']}%)")
            if cr["redundant"]:
                print(f"    ⚠️ 冗余排除: → {cr['redundant_with']}")
            print()

    output = {
        "variant": "chain_analysis",
        "generated_at": dt_str,
        "chain_results": chain_results,
        "redundant_pairs": redundant_pairs,
        "chain_trends": chain_trends,
        "chain_consistencies": chain_consistencies,
        "judge_verdict": judge_verdict,  # v2.15.0+ 闫判官裁决建议
    }

    return output


if __name__ == "__main__":
    # ── 确定输入数据 ──
    symbols_data = None

    if args.input:
        # 从 P1 JSON 读取
        symbols_data = build_symbols_from_p1(args.input)
        print(f"📥 从 P1 输入读取: {args.input} → {len(symbols_data)}品种")
    elif args.symbols:
        # 从 --symbols 参数解析
        pids = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        symbols_list = lookup_symbol_names(pids)
        symbols_data = build_symbols_data(symbols_list)
        print(f"🎯 指定品种分析: {[s['product_id'] for s in symbols_data]}")
    else:
        print("❌ 请指定 --symbols 或 --input")
        print("用法: python analyze_chain.py --symbols PK,RB,B,UR")
        print("      python analyze_chain.py --input ../phase1_output.json")
        sys.exit(1)

    # ── 执行分析 ──
    output = run_analysis(symbols_data)

    # ── 输出 JSON ──
    output_dir = os.path.join(SKILL_DIR, "Reports")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"chain_analysis_{datetime.now().strftime('%Y%m%d')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 链分析输出: {out_path}")

    # 也输出到工作目录
    local_path = os.path.join(os.getcwd(), "phase2_chain_output.json")
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 本地副本: {local_path}")

    if args.json_only:
        print(json.dumps(output, ensure_ascii=False, indent=2))
