# -*- coding: utf-8 -*-
"""
链证源 — 辩论专家团产业链验证分析
调用 commodity-chain-analysis 模块执行完整分析
"""
import sys
import os
import json
from datetime import datetime

# 添加 skill 路径
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.chains import get_chain_for_symbol, CHAIN_PRODUCTS, classify_chain, cluster_chains

def get_chain_members(chain_name):
    """获取产业链所有成员品种"""
    return CHAIN_PRODUCTS.get(chain_name, [])
from scripts.chain_verifier import chain_verification
from scripts.config import CONFIG_MANAGER

# ============================================================
# 输入数据（来自技研锋和数聚石）
# ============================================================
SYMBOLS_DATA = [
    {"product_id": "cs", "product_name": "玉米淀粉", "last_price": 2734, "direction": "BUY", "score": 67, "open_interest": 0, "term": "back", "term_pct": None},
    {"product_id": "sp", "product_name": "纸浆", "last_price": 4634, "direction": "SELL", "score": 63, "open_interest": 0, "term": "contango", "term_pct": 7.86},
    {"product_id": "rb", "product_name": "螺纹钢", "last_price": 3087, "direction": "SELL", "score": 58, "open_interest": 0, "term": "contango", "term_pct": 0.13},
    {"product_id": "hc", "product_name": "热卷", "last_price": 3310, "direction": "SELL", "score": 57, "open_interest": 0, "term": "contango", "term_pct": 2.42},
    {"product_id": "FG", "product_name": "玻璃", "last_price": 973, "direction": "SELL", "score": 57, "open_interest": 0, "term": "contango", "term_pct": 26.48},
    {"product_id": "a", "product_name": "豆一", "last_price": 4826, "direction": "BUY", "score": 56, "open_interest": 0, "term": "contango", "term_pct": 3.57},
    {"product_id": "PK", "product_name": "花生", "last_price": 8426, "direction": "BUY", "score": 55, "open_interest": 0, "term": "flat", "term_pct": None},
    {"product_id": "SA", "product_name": "纯碱", "last_price": 1096, "direction": "SELL", "score": 55, "open_interest": 0, "term": "contango", "term_pct": 17.39},
    {"product_id": "i", "product_name": "铁矿石", "last_price": 742, "direction": "SELL", "score": 54, "open_interest": 0, "term": "back", "term_pct": -1.42},
    {"product_id": "si", "product_name": "工业硅", "last_price": 8380, "direction": "SELL", "score": 54, "open_interest": 0, "term": "contango", "term_pct": 8.65},
]

def build_signal_dict(symbols):
    """构建供 chain_verification 使用的信号字典"""
    signals = {}
    for s in symbols:
        pid = s['product_id']
        direction = s['direction']
        score = s['score']
        # score 需要带符号
        signed_score = score if direction == 'BUY' else -score
        signals[pid] = {
            'score': signed_score,
            'direction': direction,
            'abs_score': score,
        }
    return signals

def build_cluster_input(symbols):
    """构建供 cluster_chains 使用的输入格式"""
    result = []
    for s in symbols:
        result.append({
            'product_id': s['product_id'],
            'product_name': s['product_name'],
            'last_price': s['last_price'],
            'direction': s['direction'],
            'open_interest': s.get('open_interest', 0),
            'trend': {'score': s['score'] if s['direction'] == 'BUY' else -s['score'], 'trend': 'up' if s['direction'] == 'BUY' else 'down'},
        })
    return result

def main():
    print("=" * 70)
    print("  链证源 — 辩论专家团产业链验证分析报告")
    print(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ========== Step 1: 产业链归类 ==========
    print("\n📌 Step 1: 产业链归类")
    print("-" * 50)
    
    chain_groups = {}
    for s in SYMBOLS_DATA:
        pid = s['product_id']
        chain = get_chain_for_symbol(pid)
        members = get_chain_members(chain)
        print(f"  {pid}({s['product_name']}) → {chain}  成员: {members}")
        
        if chain not in chain_groups:
            chain_groups[chain] = []
        chain_groups[chain].append(s)

    # ========== Step 2: 期限结构分析 ==========
    print("\n📌 Step 2: 期限结构分析")
    print("-" * 50)
    for s in SYMBOLS_DATA:
        pid = s['product_id']
        term = s['term']
        term_pct = s['term_pct']
        direction = s['direction']
        
        # 期限结构对交易方向的指导
        if term == 'back':
            term_verdict = '✅ Back结构（近强远弱），现货紧张，做多有利'
            term_align = '利多' if direction == 'BUY' else '⚠️ Back结构做空不利，期现结构矛盾'
        elif term == 'contango':
            pct_str = f"(+{term_pct}%)" if term_pct else ""
            term_verdict = f'⚠️ Contango结构（远强近弱）{pct_str}，供应宽松，做空有利'
            term_align = '利空' if direction == 'SELL' else '⚠️ Contango结构做多不利，展仓成本高'
        else:  # flat
            term_verdict = '➡️ Flat结构（价差<0.5%），无显著倾向'
            term_align = '中性'
        
        print(f"  {pid}({s['product_name']}): {term_verdict}")
        print(f"       方向:{direction} → 期限结构评估: {term_align}")

    # ========== Step 3: 产业链一致性验证 ==========
    print("\n📌 Step 3: 产业链一致性验证")
    print("-" * 50)
    
    signals = build_signal_dict(SYMBOLS_DATA)
    cluster_input = build_cluster_input(SYMBOLS_DATA)
    
    # 使用 cluster_chains 进行产业链聚类
    chain_results = cluster_chains(cluster_input)
    
    verification_results = {}
    for s in SYMBOLS_DATA:
        pid_upper = s['product_id']
        pid_lower = pid_upper.lower()
        direction = s['direction']
        score = s['score']
        
        # 找到对应的 chain_result
        chain = get_chain_for_symbol(pid_upper)
        if chain and chain in chain_results:
            chain_info = chain_results[chain]
            chain_trend = chain_info['overall_trend']
            
            # 判断一致性
            is_bull = direction == 'BUY'
            if chain_trend in ('强势多头', '多头趋势', '偏多震荡'):
                aligned = is_bull
            elif chain_trend in ('强势空头', '空头趋势', '偏空震荡'):
                aligned = not is_bull
            else:
                aligned = True  # 震荡市不做惩罚
            
            # 计算同向比例
            chain_members_same_dir = 0
            chain_total = chain_info['count']
            for m in chain_info['members']:
                m_dir = 'BUY' if m['score'] > 0 else 'SELL'
                if m_dir == direction:
                    chain_members_same_dir += 1
            chain_ratio = chain_members_same_dir / chain_total if chain_total > 0 else 0
            
            verification_results[pid_upper] = {
                'chain': chain,
                'chain_trend': chain_trend,
                'chain_avg_score': chain_info['avg_score'],
                'aligned': aligned,
                'same_direction': f"{chain_members_same_dir}/{chain_total}",
                'same_direction_ratio': round(chain_ratio, 2),
            }
            
            align_str = '✅一致' if aligned else '❌背离'
            print(f"  {pid_upper}({s['product_name']}): {chain}趋势={chain_trend} | {align_str} | 同向{chain_members_same_dir}/{chain_total}={chain_ratio:.0%}")
        else:
            verification_results[pid_upper] = {
                'chain': chain or '未知',
                'chain_trend': '未知',
                'aligned': False,
                'same_direction': "0/0",
                'same_direction_ratio': 0,
            }
            print(f"  {pid_upper}({s['product_name']}): 未找到产业链")

    # ========== Step 4: Z分数极端性检查 ==========
    print("\n📌 Step 4: Z分数极端性检查")
    print("-" * 50)
    print("  ⚠️ 由于无200日历史数据，依赖技研锋提供的评分体系进行极端性评估")
    print("  Z分数基于评分偏离度估算：")
    
    for s in SYMBOLS_DATA:
        pid = s['product_id']
        score = s['score']
        direction = s['direction']
        
        # 估算z-score（基于评分体系）
        # 50分是基准，10分约1个标准差
        est_z = (score - 50) / 10
        if direction == 'BUY':
            est_z = est_z  # 多头为正
        else:
            est_z = -est_z  # 空头为负
            
        if abs(est_z) > 2:
            z_status = '⚠️极端' if abs(est_z) <= 3 else '🔴极度极端'
        elif abs(est_z) > 1.5:
            z_status = '⚠️偏极端'
        else:
            z_status = '✅正常'
        
        print(f"  {pid}({direction} {score}分): 估算z={est_z:.2f} → {z_status}")

    # ========== Step 5: 组合级产业链聚合（同链高相关冗余检测） ==========
    print("\n📌 Step 5: 组合级产业链聚合（同链高相关冗余检测）")
    print("-" * 50)
    
    # 导入品种级相关性配置
    try:
        from scripts.chains import WITHIN_CHAIN_HIGH_CORRELATION, WITHIN_CHAIN_INDEPENDENT
    except ImportError:
        # fallback: 空配置
        WITHIN_CHAIN_HIGH_CORRELATION = {}
        WITHIN_CHAIN_INDEPENDENT = {}
    
    redundant_marks = {}
    
    for chain_name, symbols_in_chain in chain_groups.items():
        if len(symbols_in_chain) < 2:
            redundant_marks[chain_name] = {'has_redundant': False, 'details': '仅1个品种，无需冗余检测'}
            print(f"  {chain_name}: 仅1个品种({symbols_in_chain[0]['product_id']})，无需冗余检测")
            continue
        
        print(f"\n  📊 {chain_name} ({len(symbols_in_chain)}个品种):")
        
        # 获取该链的高相关配对列表
        high_corr_pairs = WITHIN_CHAIN_HIGH_CORRELATION.get(chain_name, [])
        independent_pids = [p.upper() for p in WITHIN_CHAIN_INDEPENDENT.get(chain_name, [])]
        
        chain_redundant_info = {'has_redundant': False, 'details': []}
        
        # 遍历每个高相关配对，检查同方向冗余
        for pid_a, pid_b in high_corr_pairs:
            a_upper = pid_a.upper()
            b_upper = pid_b.upper()
            a_data = next((s for s in symbols_in_chain if s['product_id'].upper() == a_upper), None)
            b_data = next((s for s in symbols_in_chain if s['product_id'].upper() == b_upper), None)
            
            if not a_data or not b_data:
                continue  # 配对品种之一不在候选列表中
            
            if a_data['direction'] != b_data['direction']:
                print(f"    {pid_a.upper()}({a_data['direction']}) vs {pid_b.upper()}({b_data['direction']}) — 方向不同，无需冗余")
                continue
            
            # 同方向 → 按score保留高的
            if a_data['score'] >= b_data['score']:
                primary, redundant = a_data, b_data
            else:
                primary, redundant = b_data, a_data
            
            print(f"    {primary['product_id']}({primary['score']}分) vs {redundant['product_id']}({redundant['score']}分) — 同向高相关，保留{primary['product_id']}")
            
            chain_redundant_info['has_redundant'] = True
            chain_redundant_info['details'].append({
                'direction': primary['direction'],
                'primary': primary['product_id'],
                'redundant': [redundant['product_id']],
            })
        
        # 标记独立品种（不参与冗余检测）
        for s in symbols_in_chain:
            pid = s['product_id'].upper()
            if pid in independent_pids:
                print(f"    {s['product_id']}({s['direction']} {s['score']}分) — 独立品种(驱动因素独立)，不冗余排除")
        
        # 其余品种（非高相关对、非独立品种）— 不触发自动冗余，仅信息标注
        processed_redundant_pids = set()
        for detail in chain_redundant_info.get('details', []):
            processed_redundant_pids.update(detail.get('redundant', []))
            processed_redundant_pids.add(detail['primary'])
        
        for s in symbols_in_chain:
            pid = s['product_id'].upper()
            if pid not in processed_redundant_pids and pid not in independent_pids:
                print(f"    {s['product_id']}({s['direction']} {s['score']}分) — 非同链高相关品种，保留独立")
        
        redundant_marks[chain_name] = chain_redundant_info

    # ========== 汇总输出 ==========
    print("\n" + "=" * 70)
    print("  📋 最终产业链验证报告")
    print("=" * 70)
    
    final_output = {}
    
    for s in SYMBOLS_DATA:
        pid = s['product_id']
        pid_upper = pid.upper() if pid.isupper() else pid
        chain = get_chain_for_symbol(pid)
        direction = s['direction']
        score = s['score']
        term = s['term']
        
        # 检查冗余
        redundant = False
        redundant_with = None
        notes = []
        
        if chain in redundant_marks and redundant_marks[chain]['has_redundant']:
            for detail in redundant_marks[chain]['details']:
                if pid in detail['redundant']:
                    redundant = True
                    redundant_with = detail['primary']
                    notes.append(f"⚠️同链冗余: 与{redundant_with}同{chain}同{direction}方向，建议取{redundant_with}")
                    break
                elif pid == detail['primary'] and detail.get('redundant', []):
                    notes.append(f"主品种: 同链另有{detail['redundant']}同向冗余")
        
        # 一致性信息
        v = verification_results.get(pid_upper, {})
        ver = verification_results.get(pid, v)
        
        if not ver:
            ver = {'chain': chain, 'chain_trend': '未知', 'aligned': True, 'same_direction': '0/0', 'same_direction_ratio': 0}
        
        # 添加分析笔记
        if term == 'contango' and direction == 'BUY':
            notes.append(f"⚠️期限结构矛盾: Contango结构做多不利 (展仓成本{s.get('term_pct', '?')}%)")
        elif term == 'back' and direction == 'SELL':
            notes.append(f"⚠️期限结构矛盾: Back结构做空不利 (现货紧张)")

        if ver['aligned']:
            notes.append(f"✅产业链一致: {chain}{ver['chain_trend']}同向")
        elif ver.get('chain_trend') and ver['chain_trend'] not in ('未知',):
            notes.append(f"⚠️产业链背离: 信号{direction} vs {chain}{ver['chain_trend']}")
        
        if ver.get('same_direction_ratio', 0) >= 0.6:
            notes.append(f"产业链共振: 同链{ver['same_direction']}同向")
        
        # Z-score 估算
        est_z = (score - 50) / 10
        if direction == 'SELL':
            est_z = -est_z
        z_status = '正常' if abs(est_z) <= 1.5 else ('极端' if abs(est_z) > 2 else '偏极端')
        if abs(est_z) > 2:
            notes.append(f"⚠️Z分数极端(z={est_z:.2f})，均值回归风险")
        
        final_output[pid] = {
            'chain': chain,
            'chain_members': get_chain_members(chain) if chain else [],
            'term_structure': term,
            'chain_trend': ver['chain_trend'],
            'chain_avg_score': ver.get('chain_avg_score', 0),
            'chain_consistency': 100 if ver['aligned'] else 0,
            'aligned': ver['aligned'],
            'z_score': round(est_z, 2),
            'z_status': z_status,
            'redundant': redundant,
            'redundant_with': redundant_with,
            'notes': notes,
        }

    # 打印表格
    print(f"\n{'品种':>6} | {'方向':>4} | {'得分':>4} | {'产业链':<12} | {'期限结构':<12} | {'趋势':<10} | {'一致':>4} | {'冗余':>5} | {'Z分':>5}")
    print("-" * 85)
    for pid, info in final_output.items():
        # 找原始数据
        orig = next((s for s in SYMBOLS_DATA if s['product_id'] == pid), None)
        dir_str = orig['direction'] if orig else '?'
        score_str = str(orig['score']) if orig else '?'
        term_str = info['term_structure']
        trend_str = info['chain_trend']
        align_str = '✅' if info['aligned'] else '❌'
        red_str = '⚠️' if info['redundant'] else '—'
        z_str = str(info['z_score'])
        print(f"{pid:>6} | {dir_str:>4} | {score_str:>4} | {info['chain']:<12} | {term_str:<12} | {trend_str:<10} | {align_str:>4} | {red_str:>5} | {z_str:>5}")

    # 输出JSON格式
    print("\n\n--- JSON OUTPUT ---")
    print(json.dumps(final_output, indent=2, ensure_ascii=False))
    
    print("\n\n###END_CHAIN_ANALYSIS")
    
    # 保存到文件
    output_path = os.path.join(SKILL_DIR, "chain_verification_output.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {output_path}")

if __name__ == '__main__':
    main()
