#!/usr/bin/env python3
"""
产业链分析 CLI — 辩论专家团 P2 链证源入口
==========================================
接受品种列表或 P1 JSON 输出，完成产业链聚类、期限结构、基差分析、冗余检测。

用法:
  # 直接指定品种
  python analyze_chain.py --symbols PK,RB,B,UR

  # 读取 P1 JSON 输出（包含价格和信号数据）
  python analyze_chain.py --input ../phase1_output.json

  # 指定品种 + 仅输出 JSON（不打印详细报告）
  python analyze_chain.py --symbols SA,RB,FU --json-only
"""
import sys, os, json
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from chains import (
    get_chain_for_symbol, CHAIN_PRODUCTS, classify_chain, cluster_chains,
    WITHIN_CHAIN_HIGH_CORRELATION, WITHIN_CHAIN_INDEPENDENT
)

# ── CLI ──
import argparse
parser = argparse.ArgumentParser(description='产业链分析 — 辩论专家团 P2 链证源')
parser.add_argument('--symbols', '-s', help='品种代码(逗号分隔)，如: PK,RB,B,UR', default=None)
parser.add_argument('--input', '-i', help='P1 JSON 输入文件路径', default=None)
parser.add_argument('--json-only', action='store_true', help='只输出 JSON，不打印详细报告')
args = parser.parse_args()


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
    return [{
        "product_id": pid,
        "product_name": name,
        "last_price": 0,
        "direction": "NEUTRAL",
        "score": 0,
        "open_interest": 0,
    } for pid, name in symbols_list]


def build_symbols_from_p1(input_path: str) -> list:
    """从 P1 JSON 输出构建 symbols_data"""
    with open(input_path, 'r', encoding='utf-8') as f:
        p1 = json.load(f)

    symbols_data = []
    contracts = p1.get('contracts', p1.get('all_actionable', []))
    if isinstance(contracts, list) and all(isinstance(c, str) for c in contracts):
        for pid in contracts:
            name = p1.get('verdicts', {}).get(pid, {}).get('name', pid)
            price = p1.get('key_prices', {}).get(pid, 0)
            direction = p1.get('verdicts', {}).get(pid, 'NEUTRAL')
            score = 0
            for r in p1.get('all_actionable', []):
                if r.get('symbol') == pid:
                    score = r.get('total', 0)
                    break
            symbols_data.append({
                "product_id": pid,
                "product_name": name,
                "last_price": price,
                "direction": direction,
                "score": score,
                "open_interest": 0,
            })
    elif isinstance(contracts, list) and all(isinstance(c, dict) for c in contracts):
        for c in contracts:
            symbols_data.append({
                "product_id": c.get('symbol', c.get('product_id', '')),
                "product_name": c.get('name', c.get('product_name', '')),
                "last_price": c.get('price', c.get('last_price', 0)),
                "direction": c.get('direction', c.get('verdict', 'NEUTRAL')),
                "score": abs(c.get('total', c.get('score', 0))),
                "open_interest": c.get('open_interest', 0),
            })
    return symbols_data


# ============================================================
# 主流程
# ============================================================

def run_analysis(symbols_data: list) -> dict:
    """执行产业链分析，返回结构化结果"""
    dt_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

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
        pid = s['product_id']
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
        pid = s['product_id']
        # 根据信号方向推断期限结构
        if s['direction'] in ('SELL', 'bear', '空头下跌') and s['score'] >= 60:
            ts, basis = "contango", "走弱"
        elif s['direction'] in ('BUY', 'bull', '多头上涨') and s['score'] >= 60:
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
        directions = [s['direction'] for s in items]
        scores = [s['score'] for s in items]
        bull_ct = sum(1 for d in directions if d in ('BUY', 'bull', '多头上涨'))
        bear_ct = sum(1 for d in directions if d in ('SELL', 'bear', '空头下跌'))
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

    # ── Step 4: 同链冗余检测 ──
    if not args.json_only:
        print("\n📌 Step 4: 同链冗余检测")
        print("-" * 50)

    for chain, items in chain_groups.items():
        if len(items) <= 1:
            continue
        chain_pairs = WITHIN_CHAIN_HIGH_CORRELATION.get(chain, [])
        for item in items:
            pid = item['product_id']
            for pair_a, pair_b in chain_pairs:
                if pid.upper() == pair_a.upper() or pid.upper() == pair_b.upper():
                    other = pair_b if pid.upper() == pair_a.upper() else pair_a
                    if any(s['product_id'].upper() == other.upper() for s in items):
                        primary = pid if item['score'] >= 60 else other
                        redundant = other if item['score'] >= 60 else pid
                        redundant_pairs.append({
                            "primary": primary,
                            "redundant": redundant,
                            "chain": chain,
                            "reason": f"{pair_a}≈{pair_b}高相关（驱动重叠）"
                        })
                        if not args.json_only:
                            print(f"  ⚠️ 冗余: {pid} ↔ {other} ({chain})")

    if not redundant_pairs and not args.json_only:
        print(f"  本次未检出同链高相关冗余品种")

    # ── 汇总输出 ──
    chain_results = {}
    for s in symbols_data:
        pid = s['product_id']
        cinfo = chain_info.get(pid, {})
        chain = cinfo.get('chain', '未归类')
        ts = term_structures.get(pid, {"term_structure": "flat", "basis": "平稳"})

        is_redundant = False
        redundant_with = None
        for rp in redundant_pairs:
            if rp['redundant'] == pid:
                is_redundant = True
                redundant_with = rp['primary']

        chain_results[pid] = {
            "chain": chain,
            "chain_members": cinfo.get('members', []),
            "term_structure": ts['term_structure'],
            "basis": ts['basis'],
            "chain_trend": chain_trends.get(chain, "未知"),
            "chain_consistency": chain_consistencies.get(chain, 0),
            "redundant": is_redundant,
            "redundant_with": redundant_with,
            "notes": [],
        }

    if not args.json_only:
        print(f"\n{'='*70}")
        print("产业链验证汇总")
        print(f"{'='*70}")
        for s in symbols_data:
            pid = s['product_id']
            cr = chain_results[pid]
            print(f"  {pid:>6}({s['product_name']})")
            print(f"    产业链: {cr['chain']}")
            print(f"    期限结构: {cr['term_structure']} | 基差: {cr['basis']}")
            print(f"    链趋势: {cr['chain_trend']} (一致性{cr['chain_consistency']}%)")
            if cr['redundant']:
                print(f"    ⚠️ 冗余排除: → {cr['redundant_with']}")
            print()

    output = {
        "variant": "chain_analysis",
        "generated_at": dt_str,
        "chain_results": chain_results,
        "redundant_pairs": redundant_pairs,
        "chain_trends": chain_trends,
        "chain_consistencies": chain_consistencies,
    }

    return output


if __name__ == '__main__':
    # ── 确定输入数据 ──
    symbols_data = None

    if args.input:
        # 从 P1 JSON 读取
        symbols_data = build_symbols_from_p1(args.input)
        print(f"📥 从 P1 输入读取: {args.input} → {len(symbols_data)}品种")
    elif args.symbols:
        # 从 --symbols 参数解析
        pids = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
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
    output_dir = os.path.join(SKILL_DIR, 'Reports')
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f'chain_analysis_{datetime.now().strftime("%Y%m%d")}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 链分析输出: {out_path}")

    # 也输出到工作目录
    local_path = os.path.join(os.getcwd(), 'phase2_chain_output.json')
    with open(local_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 本地副本: {local_path}")

    if args.json_only:
        print(json.dumps(output, ensure_ascii=False, indent=2))
