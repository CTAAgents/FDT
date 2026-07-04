#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品期货产业链分析管道 v2.11
运行完整管道：产业链聚类 → 产业链验证 → 期限结构 → 多空辩论 → 风险评估
"""

import sys
import os
import json
import time
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.chains import CHAIN_PRODUCTS, get_chain_for_symbol, classify_chain, select_leader
from scripts.chain_verifier import chain_verification
from scripts.term_basis import compute_term_basis
from scripts.debate import bull_argument, bear_argument, research_manager_decision
from scripts.risk import aggressive_risk_assessment, conservative_risk_assessment, neutral_risk_assessment

def run_pipeline(symbols_data: list = None):
    """运行产业链分析管道"""
    print("=" * 60)
    print("商品期货产业链分析管道 v2.11")
    print("=" * 60)
    
    # 如果没有提供数据，尝试从commodity-trend-signal的报告中获取
    if symbols_data is None:
        print("未提供数据，尝试从commodity-trend-signal的报告中获取...")
        try:
            # 查找最新的趋势信号报告
            report_date = datetime.now().strftime('%Y-%m-%d')
            report_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'Commodities', 'Reports', '商品期货深度分析', report_date)
            
            # 查找最新的报告文件
            report_files = [f for f in os.listdir(report_dir) if f.startswith('trend_signal_') and f.endswith('.md')]
            if report_files:
                latest_report = sorted(report_files)[-1]
                report_path = os.path.join(report_dir, latest_report)
                
                # 解析报告中的数据
                with open(report_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 简单解析：提取品种数据
                # 这里简化处理，实际应该解析Markdown表格
                symbols_data = []
                print(f"从报告 {latest_report} 中读取数据")
            else:
                print("未找到趋势信号报告")
                return None
        except Exception as e:
            print(f"获取数据失败: {e}")
            return None
    
    if not symbols_data:
        print("错误: 无有效数据，管道终止")
        return None
    
    # 1. 产业链聚类
    print("\n[1/5] 产业链聚类...")
    chain_results = {}
    
    for chain_name, products in CHAIN_PRODUCTS.items():
        # 找到属于该产业链的品种
        chain_symbols = [s for s in symbols_data if s.get('product_id') in products]
        
        if not chain_symbols:
            continue
        
        # 统计方向分布（v2.14修正：score是强度，方向在direction字段）
        direction_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
        for s in chain_symbols:
            direction = s.get('direction', 'HOLD')
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
        
        # 计算产业链平均得分
        scores = [s.get('trend', {}).get('score', 0) or s.get('score', 0) for s in chain_symbols]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # 判断产业链整体趋势（结合方向分布）
        overall_trend = classify_chain(avg_score, direction_counts)
        
        # 选择龙头品种
        leader, leader_reason = select_leader(chain_symbols, overall_trend)
        
        # 构建产业链结果
        chain_results[chain_name] = {
            'overall_trend': overall_trend,
            'avg_score': avg_score,
            'count': len(chain_symbols),
            'leader': leader.get('product_id'),
            'leader_price': leader.get('last_price'),
            'leader_reason': leader_reason,
            'direction_counts': direction_counts,
            'members': [{
                'pid': s['product_id'],
                'name': s.get('product_name', s['product_id']),
                'price': s['last_price'],
                'score': s.get('score', 0),
                'direction': s.get('direction', 'HOLD'),
                'oi': s.get('open_interest', 0)
            } for s in chain_symbols]
        }
        
        print(f"  ✓ {chain_name}: {overall_trend} (平均得分: {avg_score:.1f})")
    
    print(f"产业链聚类完成: {len(chain_results)} 个产业链")
    
    # 2. 产业链验证
    print("\n[2/5] 产业链验证...")
    verification_results = {}
    
    for symbol in symbols_data:
        pid = symbol['product_id']
        chain_name = get_chain_for_symbol(pid)
        
        if chain_name and chain_name in chain_results:
            # 验证信号是否与产业链方向一致
            verification = chain_verification(symbol, chain_results)
            verification_results[pid] = {
                'chain_name': chain_name,
                'chain_trend': chain_results[chain_name]['overall_trend'],
                'symbol_score': symbol.get('trend', {}).get('score', 0),
                'verification': verification
            }
    
    print(f"产业链验证完成: {len(verification_results)} 个品种")
    
    # 3. 期限结构分析 (FIX: compute_term_basis expects list of dicts, not single string)
    print("\n[3/5] 期限结构分析...")
    term_structure_results = {}
    
    # 构建品种列表格式 [{'pid': 'rb', 'exchange': 'SHFE'}, ...]
    symbols_for_term = []
    for symbol in symbols_data:
        pid = symbol.get('product_id', '')
        exchange = symbol.get('exchange', '')
        if pid:
            symbols_for_term.append({'pid': pid, 'exchange': exchange})
    
    # 批量调用
    if symbols_for_term:
        try:
            term_structure_results = compute_term_basis(symbols_for_term)
            print(f"期限结构分析完成: {len(term_structure_results)} 个品种")
        except Exception as e:
            print(f"期限结构分析失败: {e}")
    else:
        print("无有效品种数据")
    
    # 4. 多空辩论（对Top10信号排行品种进行辩论）
    print("\n[4/5] 多空辩论（针对Top10信号排行品种）...")
    debate_results = {}
    
    # 获取Top10品种（按|score|排序）
    top10_symbols = sorted(symbols_data, key=lambda s: abs(s.get('score', 0)), reverse=True)[:10]
    
    # 按产业链分组，每个产业链只保留信号最强的品种
    chain_top_symbols = {}  # {chain_name: symbol}
    for sym in top10_symbols:
        pid = sym['product_id']
        chain_name = get_chain_for_symbol(pid)
        if chain_name:
            # 如果该产业链还没有入选品种，或者当前品种信号更强，则更新
            if chain_name not in chain_top_symbols or abs(sym.get('score', 0)) > abs(chain_top_symbols[chain_name].get('score', 0)):
                chain_top_symbols[chain_name] = sym
    
    print(f"  Top10品种涉及 {len(chain_top_symbols)} 个产业链")
    
    for chain_name, symbol in chain_top_symbols.items():
        try:
            pid = symbol['product_id']
            
            # 构造单品种数据用于辩论
            symbol_debate_data = {
                'overall_trend': symbol.get('direction', 'HOLD'),  # 品种方向
                'avg_score': symbol.get('score', 0),  # 品种得分
                'leader': pid,
                'members': [{
                    'pid': pid,
                    'name': symbol.get('product_name', pid),
                    'price': symbol.get('last_price', 0),
                    'score': symbol.get('score', 0),
                    'direction': symbol.get('direction', 'HOLD'),
                    'oi': symbol.get('open_interest', 0)
                }]
            }
            
            # 从futures-data-search获取资金面/基本面数据（v3.0增强）
            fund_data = {}
            try:
                import sys as _sys
                _fds_path = str(Path(os.path.dirname(__file__)).parent / "futures-data-search" / "scripts")
                if _fds_path not in _sys.path:
                    _sys.path.insert(0, _fds_path)
                from duckdb_store import DuckDBStore
                fds_db = DuckDBStore()
                oi_records = fds_db.get_latest_oi(pid)
                if oi_records:
                    fund_data['oi_ranking'] = oi_records
                wh_records = fds_db.get_latest_warehouse(pid)
                if wh_records:
                    fund_data['warehouse'] = wh_records
                news_records = fds_db.get_latest_news(pid, top_k=5)
                if news_records:
                    fund_data['news'] = news_records
                spread_records = fds_db.get_term_structure(pid)
                if spread_records:
                    fund_data['spread'] = spread_records
                fds_db.close()
                if fund_data:
                    print(f"  📊 futures-data-search数据加载: {list(fund_data.keys())}")
            except Exception as e:
                print(f"  [Info] futures-data-search not available: {e}")

            # 多空辩论（注入fund_data）
            bull = bull_argument(chain_name, symbol_debate_data, fund_data)
            bear = bear_argument(chain_name, symbol_debate_data, fund_data)
            decision = research_manager_decision(bull, bear, symbol_debate_data['overall_trend'], fund_data)
            
            debate_results[chain_name] = {
                'leader': pid,
                'leader_name': symbol.get('product_name', pid),
                'signal_direction': symbol.get('direction', 'HOLD'),
                'signal_score': symbol.get('score', 0),
                'bull': bull,
                'bear': bear,
                'decision': decision
            }
            
            print(f"  ✓ {chain_name} ({pid}): {decision.get('verdict', 'HOLD')} (信号:{symbol.get('direction', 'HOLD')}, 得分:{symbol.get('score', 0):.0f})")
        except Exception as e:
            print(f"  ✗ {chain_name}: {str(e)}")
    
    print(f"多空辩论完成: {len(debate_results)} 个品种信号")
    
    # 5. 风险评估
    print("\n[5/5] 风险评估...")
    risk_results = {}
    
    for chain_name, debate_data in debate_results.items():
        try:
            leader_pid = debate_data['leader']
            leader_symbol = next((s for s in symbols_data if s['product_id'] == leader_pid), None)
            
            if leader_symbol:
                # 三方风险评估 (FIX: Create proper trade_plan with string decision)
                trade_plan = {
                    'decision': debate_data['decision']['verdict'],
                    'symbol': debate_data['leader'],
                    'chain_name': chain_name
                }
                aggressive = aggressive_risk_assessment(trade_plan, debate_data)
                conservative = conservative_risk_assessment(trade_plan, debate_data)
                neutral = neutral_risk_assessment(trade_plan, debate_data)
                
                # 风险主管裁决
                risk_decision = {
                    'aggressive': aggressive,
                    'conservative': conservative,
                    'neutral': neutral
                }
                
                risk_results[chain_name] = risk_decision
                print(f"  ✓ {chain_name}: 风险评估完成")
        except Exception as e:
            print(f"  ✗ {chain_name}: {str(e)}")
    
    print(f"风险评估完成: {len(risk_results)} 个产业链")
    
    # 生成报告
    print("\n生成产业链分析报告...")
    
    report_data = {
        'chain_results': chain_results,
        'verification_results': verification_results,
        'term_structure_results': term_structure_results,
        'debate_results': debate_results,
        'risk_results': risk_results,
        'symbols_data': symbols_data
    }
    
    # 保存报告
    report_date = datetime.now().strftime('%Y-%m-%d')
    report_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'Commodities', 'Reports', '商品期货深度分析', report_date)
    os.makedirs(report_dir, exist_ok=True)
    
    report_file = os.path.join(report_dir, f'chain_analysis_{datetime.now().strftime("%Y%m%d")}.json')
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n报告已保存: {report_file}")
    print("=" * 60)
    
    return report_data

if __name__ == '__main__':
    result = run_pipeline()
    if result:
        print(f"\n管道执行完成:")
        print(f"  产业链数: {len(result['chain_results'])}")
        print(f"  验证品种: {len(result['verification_results'])}")
        print(f"  期限结构: {len(result['term_structure_results'])}")
        print(f"  辩论结果: {len(result['debate_results'])}")
        print(f"  风险评估: {len(result['risk_results'])}")
    else:
        print("\n管道执行失败")