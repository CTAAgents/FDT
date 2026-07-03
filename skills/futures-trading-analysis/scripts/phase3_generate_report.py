#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品期货每日深度分析 — Phase 3: 智能筛选 + HTML报告生成
读取 intermediate_data.json + debate_results.json → 输出 daily_analysis_{YYYYMMDD}.html
"""

import sys, os, json, traceback
from datetime import datetime

# ==================== 辩论结果适配器（兼容新旧格式） ====================
# v2.5: 支持 contracts/ schema 格式和旧版平铺格式
def _detect_format(debate_results: dict) -> str:
    """
    检测 debate_results.json 的数据格式。
    返回: 'per_pid'（{pid: {data}}） 或 'nested'（{verdicts: {pid: {data}}, ...}）
    """
    # 如果任何一个value是dict且包含'judge_verdict'/'verdict'等字段 → per_pid
    for key, val in debate_results.items():
        if isinstance(val, dict) and any(k in val for k in ('judge_verdict', 'verdict', 'direction')):
            return 'per_pid'
    # 如果存在'verdicts'键且其值是dict → nested
    if 'verdicts' in debate_results and isinstance(debate_results['verdicts'], dict):
        return 'nested'
    # 兜底：尝试按per_pid处理
    return 'per_pid'

def adapt_debate_results(debate_results: dict, intermediate: dict) -> dict:
    """
    将 debate_results.json 适配为 report generator 内部格式（per-pid dict）。
    自动检测格式：
    1. per_pid 格式：{'PK': {judge_verdict:..., bull_args:...}, 'SA': {...}}
    2. nested 格式：{'verdicts': {'PK': {direction:..., confidence:...}}, 'overall': {...}}
    """
    fmt = _detect_format(debate_results)
    
    if fmt == 'nested':
        # 扁平化 nested 格式 → per_pid
        verdicts = debate_results.get('verdicts', {})
        overall = debate_results.get('overall', {})
        per_pid = {}
        for pid, v in verdicts.items():
            if not isinstance(v, dict):
                continue
            direction = v.get('direction', 'HOLD')
            conf = v.get('confidence', 0)
            ruling = v.get('risk_ruling', '')
            # 方向映射
            dir_map = {'做多': 'BUY', '做空': 'SELL', '观望': 'HOLD'}
            eng_dir = dir_map.get(direction, direction)
            
            per_pid[pid] = {
                'judge_verdict': {
                    'final_direction': direction,
                    'confidence': conf,
                    'reasoning': v.get('reasoning', '')
                },
                'category': overall.get('tendency', ''),
                'risk_detail': overall.get('core_conflict', ''),
                'bull_args': v.get('bull_args', ''),
                'bear_args': v.get('bear_args', ''),
                'verdict': {'status': direction, 'confidence': conf},
                'direction': eng_dir,
                'risk_ruling': ruling,  # per-pid ruling, NOT global
                'entry_price': v.get('entry_price', 0),
                'target_price': v.get('target_price', 0),
                'stop_loss_price': v.get('stop_loss_price', 0),
                'position_size': v.get('position_size', 0),
                'risk_reward_ratio': v.get('risk_reward_ratio', 0),
            }
        debate_results = per_pid
    
    # 统一 per_pid 处理
    adapted = {}
    for pid, d in debate_results.items():
        if not isinstance(d, dict):
            continue
        entry = dict(d)  # 拷贝
        
        # 1. Judge verdict — 已存在则保留
        if 'judge_verdict' not in entry or not isinstance(entry.get('judge_verdict'), dict):
            entry['judge_verdict'] = {
                'final_direction': entry.get('direction', 'HOLD'),
                'confidence': entry.get('confidence', 0),
                'reasoning': entry.get('reasoning', ''),
            }
        
        # 2. Risk verdict
        if 'risk_output' in d and isinstance(d['risk_output'], dict):
            ro = d['risk_output']
            entry['category'] = ro.get('overall', {}).get('tendency', '')
            entry['risk_detail'] = ro.get('overall', {}).get('core_conflict', '')
        
        # 3. Bull/Bear arguments (fallback if not already present)
        if 'bull_output' in d and isinstance(d['bull_output'], dict) and not entry.get('bull_args'):
            bo = d['bull_output']
            dims = bo.get('dimensions', [])
            dim_summary = '; '.join([f"{dim.get('dim','')}: {dim.get('evidence','')}" for dim in dims[:3]])
            entry['bull_args'] = bo.get('summary_4_risk', '') + (' | ' + dim_summary if dim_summary else '')
        if 'bear_output' in d and isinstance(d['bear_output'], dict) and not entry.get('bear_args'):
            bo = d['bear_output']
            dims = bo.get('dimensions', [])
            dim_summary = '; '.join([f"{dim.get('dim','')}: {dim.get('evidence','')}" for dim in dims[:3]])
            entry['bear_args'] = bo.get('summary_4_risk', '') + (' | ' + dim_summary if dim_summary else '')
        
        # 4. Trading plan
        if 'plan_output' in d and isinstance(d['plan_output'], dict):
            po = d['plan_output']
            actions = po.get('actions', [])
            if actions:
                a = actions[0]
                entry['direction'] = 'BUY' if a.get('direction') == 'long' else 'SELL'
                entry['entry_price'] = a.get('entry_price', 0)
                entry['target_price'] = a.get('take_profit', 0)
                entry['stop_loss_price'] = a.get('stop_loss', 0)
                entry['position_size'] = a.get('position_size_pct', 0)
                entry['risk_reward_ratio'] = po.get('risk_reward_ratio', 0)
        
        # 5. Chain (from chain_results in intermediate_data.json)
        chain_results = intermediate.get('chain_results', {})
        if not entry.get('chain'):
            for cname, cinfo in chain_results.items():
                members = cinfo.get('members', []) if isinstance(cinfo, dict) else []
                if pid in members:
                    entry['chain'] = {'chain': cname, 'term_structure': cinfo.get('term_structure', '')}
                    break
        
        adapted[pid] = entry
    return adapted

# ==================== 配置 ====================
REPORT_DATE = datetime.now().strftime('%Y-%m-%d')
REPORT_DATE_COMPACT = datetime.now().strftime('%Y%m%d')

REPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "WorkBuddy", "Commodities",
    "Reports", "商品期货深度分析", REPORT_DATE
)

INTERMEDIATE_PATH = os.path.join(REPORT_DIR, 'intermediate_data.json')
DEBATE_PATH = os.path.join(REPORT_DIR, 'debate_results.json')
OUTPUT_HTML = os.path.join(REPORT_DIR, f"daily_analysis_{REPORT_DATE_COMPACT}.html")
OUTPUT_JSON = os.path.join(REPORT_DIR, f"analysis_data_{REPORT_DATE_COMPACT}.json")

print(f"{'='*60}")
print(f"Phase 3: 智能筛选 + HTML报告生成 — {REPORT_DATE}")
print(f"{'='*60}")

# ==================== 读取数据 ====================
if not os.path.exists(INTERMEDIATE_PATH):
    print(f"✗ 未找到中间数据: {INTERMEDIATE_PATH}")
    sys.exit(1)

with open(INTERMEDIATE_PATH, 'r', encoding='utf-8') as f:
    intermediate = json.load(f)

debate_results = {}
if os.path.exists(DEBATE_PATH):
    with open(DEBATE_PATH, 'r', encoding='utf-8') as f:
        debate_results = json.load(f)
    # 适配新旧格式（v2.5 contracts/ schema 兼容）
    debate_results = adapt_debate_results(debate_results, intermediate)
    print(f"✓ 辩论结果: {len(debate_results)} 个品种")
else:
    print(f"⚠ 未找到辩论结果: {DEBATE_PATH}，使用空辩论数据")

data_source_used = intermediate.get('data_source', 'unknown')
tdx_available = intermediate.get('_meta', {}).get('tdx_bridge_available', False)
indicator_source = intermediate.get('_meta', {}).get('indicator_source', 'numpy')
print(f"  📡 指标来源: {indicator_source}")
all_actionable = intermediate.get('all_actionable', [])
chain_results = intermediate.get('chain_results', {})
symbols_summary = intermediate.get('symbols_summary', [])
BUY_top5_ids = intermediate.get('BUY_top5', [])
SELL_top5_ids = intermediate.get('SELL_top5', [])

print(f"✓ 读取中间数据: {len(symbols_summary)} 品种, {len(chain_results)} 产业链")
print(f"✓ 有效方案: {len(all_actionable)}")

# ===== 自动计算产业链统计（avg_score/count/direction_counts/leader） =====
# 从 all_actionable 数据中为每个产业链计算聚合指标
for cname, cinfo in chain_results.items():
    if not isinstance(cinfo, dict):
        continue
    members = cinfo.get('members', [])
    # 找到该链下所有在 all_actionable 中的品种
    chain_signals = [s for s in all_actionable if s.get('pid') in members]
    if chain_signals:
        cinfo['count'] = len(chain_signals)
        cinfo['avg_score'] = sum(abs(s.get('confidence', 0) * 100) for s in chain_signals) / len(chain_signals) if chain_signals else 0
        dc = {}
        for s in chain_signals:
            d = s.get('direction', 'HOLD')
            dc[d] = dc.get(d, 0) + 1
        cinfo['direction_counts'] = dc
        # leader: highest confidence
        leader = max(chain_signals, key=lambda s: s.get('confidence', 0))
        cinfo['leader'] = f"{leader.get('product_name', leader.get('pid', ''))}"
        # map trend to standard: use overall_trend if already set
        if 'overall_trend' not in cinfo or not cinfo['overall_trend']:
            buy_cnt = dc.get('BUY', 0)
            sell_cnt = dc.get('SELL', 0)
            if sell_cnt > buy_cnt * 2:
                cinfo['overall_trend'] = '强势空头'
            elif sell_cnt > buy_cnt:
                cinfo['overall_trend'] = '偏空震荡'
            elif buy_cnt > sell_cnt * 2:
                cinfo['overall_trend'] = '强势多头'
            elif buy_cnt > sell_cnt:
                cinfo['overall_trend'] = '偏多震荡'
            else:
                cinfo['overall_trend'] = '高波动震荡'
    else:
        cinfo['count'] = 0
        cinfo['avg_score'] = 0
        cinfo['direction_counts'] = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
        cinfo['leader'] = '—'

# ==================== Step 3: 智能筛选 ====================
print("\n[Step 3] 智能筛选...")
step_start = datetime.now()

filtered_signals = []
T1_signals = []
T2_signals = []
T3_signals = []

for s in all_actionable:
    pid = s.get('pid', '')
    confidence = s.get('confidence', 0)  # 0-1
    direction = s.get('decision', 'HOLD')

    # Debate check — 适配 debate_results.json 的实际结构
    debate = debate_results.get(pid, {})
    if not debate:
        verdict = '—'
        debate_reason = ''
    else:
        # 尝试多种 verdict 字段路径
        judge_verdict = debate.get('judge_verdict', {})
        if isinstance(judge_verdict, dict) and 'final_direction' in judge_verdict:
            verdict = judge_verdict['final_direction']
        else:
            raw_verdict = debate.get('verdict', '—')
            if isinstance(raw_verdict, dict):
                verdict = raw_verdict.get('status', '—')
            else:
                verdict = str(raw_verdict) if raw_verdict else '—'

    cat = debate.get('category', '')
    risk_detail = debate.get('risk_detail', '')

    if confidence < 0.4:
        continue
    if direction not in ['BUY', 'SELL']:
        continue
    if verdict in ('HOLD', 'WATCH', '—'):
        continue

    # Build debate summary from available data
    if debate:
        jv = debate.get('judge_verdict', {})
        if isinstance(jv, dict):
            debate_reason = jv.get('reasoning', '')[:120] or verdict
        else:
            debate_reason = verdict
    else:
        debate_reason = ''

    info = {
        'product_id': pid,
        'product_name': s.get('product_name', pid),
        'direction': direction,
        'confidence': confidence * 100,
        'price': s.get('last_price', s.get('price', 0)),
        'entry': s.get('entry_price', s.get('price', 0)),
        'target': s.get('target_price', 0),
        'stop_loss': s.get('stop_loss', s.get('stop_loss_price', 0)),
        'risk_reward': s.get('risk_reward_ratio', s.get('risk_reward', 0)),
        'position_size': s.get('position_size', 0),
        'verdict': verdict,
        'debate_reason': debate_reason,
        'chain': '',
        '_chain_info': debate.get('chain', ''),
        'bull_args': '',
        'bear_args': f"风控: {cat}{' | ' + risk_detail[:80] if risk_detail else ''}",
    }

    # Find chain
    for cname, cinfo in chain_results.items():
        if pid in cinfo.get('members', []):
            info['chain'] = cname
            info['chain_trend'] = cinfo.get('overall_trend', '')
            break

    # Tier
    if confidence * 100 > 90:
        info['tier'] = 'T3警惕'
        T3_signals.append(info)
    elif confidence * 100 >= 75:
        info['tier'] = 'T2主仓'
        T2_signals.append(info)
    else:
        info['tier'] = 'T1观察'
        T1_signals.append(info)

    filtered_signals.append(info)

T1_signals.sort(key=lambda x: x['confidence'], reverse=True)
T2_signals.sort(key=lambda x: x['confidence'], reverse=True)
T3_signals.sort(key=lambda x: x['confidence'], reverse=True)

print(f"  T1观察: {len(T1_signals)}, T2主仓: {len(T2_signals)}, T3警惕: {len(T3_signals)}")
for s in T1_signals[:10]:
    icon = '🟢BUY' if s['direction'] == 'BUY' else '🔴SELL'
    print(f"    {icon} {s['product_id']} 置信度{s['confidence']:.0f}%  辩论:{s['verdict']}")

# ==================== Step 4: HTML报告 ====================
print("\n[Step 4] 生成HTML报告...")

def build_html():
    """单文件自包含HTML报告"""
    def signal_row(s):
        icon = '🟢' if s['direction'] == 'BUY' else '🔴'
        dt = '做多' if s['direction'] == 'BUY' else '做空'
        pct = ((s['target'] - s['entry']) / s['entry'] * 100) if s['entry'] else 0
        if s['direction'] == 'SELL': pct = -pct
        stop_pct = abs((s['stop_loss'] - s['entry']) / s['entry'] * 100) if s['entry'] else 0
        debate_text = s.get('debate_reason','')
        pname = s.get('product_name', '')
        pid = s.get('product_id', '')
        return f"""
        <tr>
            <td><span class="tag-{s['direction'].lower()}">{icon} {pname} {pid}</span></td>
            <td>{dt}</td>
            <td class="num">{s['confidence']:.0f}%</td>
            <td class="num">{s['entry']:.0f}</td>
            <td class="num">{s['target']:.0f}</td>
            <td class="num">{s['stop_loss']:.0f}</td>
            <td class="num">{s['risk_reward']:.1f}:1</td>
            <td><span class="tier-{'t3' if 'T3' in s.get('tier','') else 't2' if 'T2' in s.get('tier','') else 't1'}">{s.get('tier','')}</span></td>
        </tr>
        <tr style="border-bottom:2px solid #2a2d38;">
            <td colspan="8" style="font-size:0.82em;color:#888;padding:2px 12px 8px 12px;line-height:1.5;white-space:normal;word-break:break-word;">{'📋 ' + debate_text if debate_text else '—'}</td>
        </tr>"""

    def chain_row(name, info):
        t_raw = info.get('overall_trend', 'HOLD')
        # Map Chinese trend names to standard symbols (substring match)
        trend_map = [
            ('强势多头', 'BUY', '📈'),
            ('多头趋势', 'BUY', '📈'),
            ('偏多震荡', 'BUY', '📈'),
            ('强势空头', 'SELL', '📉'),
            ('空头趋势', 'SELL', '📉'),
            ('偏空趋势', 'SELL', '📉'),
            ('偏空震荡', 'SELL', '📉'),
        ]
        t_key, ti, tt = 'HOLD', '➡', t_raw or '震荡'
        for keyword, key, icon in trend_map:
            if keyword in t_raw:
                t_key, ti, tt = key, icon, t_raw  # use original text as display
                break
        dc = info.get('direction_counts', {})
        return f"""
        <tr>
            <td>{name}</td>
            <td><span class="trend-{t_key.lower()}">{ti} {tt}</span></td>
            <td class="num">{info.get('avg_score',0):.1f}</td>
            <td class="num">{info.get('count',0)}</td>
            <td class="num">{dc.get('BUY',0)}/{dc.get('SELL',0)}/{dc.get('HOLD',0)}</td>
            <td>{info.get('leader','—')}</td>
        </tr>"""

    total_buy = sum(1 for s in filtered_signals if s['direction'] == 'BUY')
    total_sell = sum(1 for s in filtered_signals if s['direction'] == 'SELL')
    total = len(filtered_signals)
    sentiment = 'strong_bearish' if total_sell > total_buy * 2 else 'bearish' if total_sell > total_buy else 'neutral'
    sentiment_text = {'strong_bearish': '强烈空头', 'bearish': '偏空', 'neutral': '均衡'}.get(sentiment, '均衡')

    all_rows = ''
    for s in T3_signals + T2_signals + T1_signals:
        all_rows += signal_row(s)
    if not all_rows:
        all_rows = '<tr><td colspan="11" style="text-align:center;color:#888;">⚠️ 无有效信号</td></tr>'

    chain_rows = ''
    for name, info in sorted(chain_results.items(), key=lambda x: x[1].get('avg_score',0)):
        chain_rows += chain_row(name, info)

    # Build debate section — 只处理品种级 key（含 direction 字段），跳过 report_meta/phase_summary/portfolio
    SYMBOL_KEYS = {pid for pid in debate_results if isinstance(debate_results[pid], dict) and 'direction' in debate_results[pid]}
    # Build product name lookup from all_actionable
    product_names = {}
    for s in all_actionable:
        pn = s.get('product_name', '') or s.get('pid', '')
        if pn:
            product_names[s.get('pid', '')] = pn
    debate_rows = ''
    # Collect overall assessment (only once, not per-pid)
    overall_text = ''
    for pid in SYMBOL_KEYS:
        d = debate_results[pid]
        cat = d.get('category', '')
        risk = d.get('risk_detail', '') or d.get('risk_note', '')
        if risk and not overall_text:
            # First non-empty risk_detail = the global core_conflict (same for all pids in nested format)
            overall_text = risk
            break
    if overall_text:
        # Render overall banner once before all cards
        cat_icon = '🔴' if 'bearish' in str(cat).lower() else ('🟢' if 'bullish' in str(cat).lower() else '⚪')
        debate_rows += f"""    <div style="background:#1a1d28;border-radius:8px;padding:14px 18px;margin-bottom:18px;border-left:3px solid #f59e0b;font-size:0.9em;color:#ccc;">
        <span style="color:#f59e0b;font-weight:bold;">{cat_icon} 全场裁定</span> — {overall_text}
    </div>\n"""
    for pid in SYMBOL_KEYS:
        d = debate_results[pid]
        # jury verdict
        jv = d.get('judge_verdict', {})
        if isinstance(jv, dict) and 'final_direction' in jv:
            v = jv['final_direction']
            v_conf = jv.get('confidence', '')
            v_reason = jv.get('reasoning', '')[:150]
        else:
            v_raw = d.get('verdict', '—')
            v = v_raw if isinstance(v_raw, str) else v_raw.get('status', '—')
            v_reason = v_raw.get('reasoning', '')[:150] if isinstance(v_raw, dict) else d.get('judge_verdict', '')[:150] if isinstance(d.get('judge_verdict', ''), str) else ''
            v_conf = d.get('judge_confidence', '') or d.get('confidence', '')
        # category / risk
        cat = d.get('category', '')
        risk = d.get('risk_detail', '') or d.get('risk_note', '')
        # chain info
        chain_info = d.get('chain', {})
        if isinstance(chain_info, dict):
            chain_name = chain_info.get('chain', '') or d.get('chain', '')
            term = chain_info.get('term_structure', '')
            if not term:
                ts_raw = d.get('term_structure', '')
                term = ts_raw if isinstance(ts_raw, str) else ts_raw.get('type', '')
        else:
            chain_name = str(chain_info)
            term = ''
        # trading plan — support dict, flat top-level fields, and options-based format
        tp = d.get('trading_plan', {})
        if isinstance(tp, dict) and (tp.get('options') or tp.get('plan')):
            if tp.get('options'):
                plan_summary = '|'.join([o.get('name','')[:10] for o in tp['options'][:2]])
            else:
                plan_summary = f"{tp.get('plan','')} | {tp.get('entry','')} | 仓{tp.get('position','')} | 损{tp.get('stop_loss','')}"[:80]
        else:
            # flat format: read from top-level fields
            entry = d.get('entry_price', 0)
            target = d.get('target_price', 0)
            sl = d.get('stop_loss_price', 0)
            pos = d.get('position_size', 0)
            rr = d.get('risk_reward_ratio', 0)
            if entry and pos:
                plan_summary = f'入场{entry} | 目标{target} | 仓位{pos}% | 止损{sl} | RR{rr}'
            else:
                is_hold = d.get('direction', '') == 'HOLD' or d.get('category', '') == 'excluded'
                plan_summary = '🚫 被风控排除，不参与交易' if is_hold else ''
        # bull/bear arguments
        bull_args = d.get('bull_args', '')
        bear_args = d.get('bear_args', '')
        # prepend chain/term info to arguments
        chain_label = f'[{chain_name}/{term}]' if chain_name and term else f'[{chain_name}]' if chain_name else ''
        if chain_label:
            if bull_args:
                bull_args = f'{chain_label} {bull_args}'
            if bear_args:
                bear_args = f'{chain_label} {bear_args}'
        if not bull_args and d.get('signal_direction'):
            bull_args = f'P1信号: {d.get("signal_direction")}({d.get("score",0)})'
        if not bear_args and risk:
            bear_args = risk[:60]
        # verdict reasoning
        v_reason_full = v_reason if v_reason else ''
        # direction color mapping
        vc_map = {'BUY': '#22c55e', 'SELL': '#ef4444', 'HOLD': '#f59e0b', 'WATCH': '#f59e0b'}
        vc_bg = {'BUY': 'rgba(34,197,94,0.1)', 'SELL': 'rgba(239,68,68,0.1)', 'HOLD': 'rgba(245,158,11,0.1)', 'WATCH': 'rgba(245,158,11,0.1)'}
        v_color = vc_map.get(v if v in vc_map else 'HOLD', '#888')
        v_bg = vc_bg.get(v if v in vc_bg else 'HOLD', 'rgba(136,136,136,0.1)')
        verdict_tag = f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-weight:bold;font-size:0.9em;color:{v_color};background:{v_bg};">{v}{f"({v_conf})" if v_conf else ""}</span>'
        risk_text = f'{cat}{" | "+str(risk)[:80] if risk else ""}' if cat or risk else '—'
        # Per-card header: only show per-variety ruling, not global conflict (moved to banner)
        ruling = d.get('risk_ruling', '')
        ruling_icons = {'INCLUDE': '✅', 'WATCH': '⚠️', 'EXCLUDE': '🚫'}
        clean_ruling = ruling.split('(')[0].strip() if '(' in str(ruling) else str(ruling)
        ruling_icon = ruling_icons.get(clean_ruling, '')
        per_pid_risk = f'{ruling_icon} {ruling}' if ruling else (f'{cat}' if cat else '—')
        debate_rows += f"""
        <div style="background:#252836;border-radius:10px;padding:20px 24px;margin-bottom:14px;border:1px solid #2a2d38;border-left:3px solid {v_color};width:100%;box-sizing:border-box;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #2a2d38;flex-wrap:wrap;gap:8px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span style="font-weight:bold;font-size:1.1em;color:#e0e0e0;">{product_names.get(pid, pid)} {pid}</span>
                    {verdict_tag}
                </div>
                <span style="color:#888;font-size:0.85em;text-align:right;">{per_pid_risk}</span>
            </div>
            <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;margin-bottom:10px;">
                <div style="color:#f59e0b;font-size:0.78em;margin-bottom:6px;">📋 交易方案</div>
                <div style="color:#ccc;font-size:0.85em;line-height:1.6;white-space:normal;word-break:break-word;">{plan_summary if plan_summary else '—'}</div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;">
                    <div style="color:#22c55e;font-size:0.78em;margin-bottom:6px;">🟢 多头论据</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.6;white-space:normal;word-break:break-word;flex:1;">{bull_args[:300] if bull_args else '—'}</div>
                </div>
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;">
                    <div style="color:#ef4444;font-size:0.78em;margin-bottom:6px;">🔴 空头论据</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.6;white-space:normal;word-break:break-word;flex:1;">{bear_args[:300] if bear_args else '—'}</div>
                </div>
            </div>
            <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                <div style="color:#888;font-size:0.78em;margin-bottom:6px;">⚖️ 裁决依据</div>
                <div style="color:#aaa;font-size:0.82em;line-height:1.6;white-space:normal;word-break:break-word;">{v_reason_full}</div>
            </div>
        </div>"""

    signals_for_chart = [
        {'pid': s.get('pid', ''), 'confidence': s.get('confidence', 0) * 100, 'direction': s.get('decision', 'HOLD')}
        for s in all_actionable[:15]
    ]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>商品期货深度分析 | {REPORT_DATE}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0f1117; color:#e0e0e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.6; }}
.container {{ max-width:1200px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a1d28 0%,#2a1f1f 50%,#1a1d28 100%); padding:40px; border-radius:16px; margin-bottom:30px; text-align:center; border:1px solid #f59e0b33; }}
.header h1 {{ font-size:2em; color:#f59e0b; margin-bottom:8px; }}
.header .subtitle {{ color:#888; font-size:0.9em; }}
.header .meta {{ display:flex; justify-content:center; gap:20px; margin-top:15px; flex-wrap:wrap; }}
.header .meta-item {{ background:#1a1d28; padding:8px 16px; border-radius:8px; border:1px solid #2a2d38; font-size:0.85em; }}
.header .meta-item .label {{ color:#888; }}
.header .meta-item .value {{ color:#f59e0b; font-weight:bold; }}
.section {{ background:#1a1d28; border-radius:12px; padding:24px 32px; margin-bottom:20px; border:1px solid #2a2d38; }}
.section h2 {{ color:#f59e0b; font-size:1.3em; margin-bottom:16px; padding-bottom:8px; border-bottom:1px solid #2a2d38; }}
.section .sub-title {{ color:#888; font-size:0.85em; margin-bottom:12px; }}
table {{ width:100%; border-collapse:collapse; font-size:0.85em; }}
th {{ background:#252836; color:#f59e0b; padding:10px 12px; text-align:left; font-weight:600; border-bottom:2px solid #f59e0b44; }}
td {{ padding:8px 12px; border-bottom:1px solid #2a2d38; }}
tr:hover td {{ background:#25283644; }}
.num {{ text-align:right; font-family:'Courier New',monospace; }}
.tag-buy {{ color:#22c55e; font-weight:bold; }}
.tag-sell {{ color:#ef4444; font-weight:bold; }}
.tier-t1 {{ color:#f59e0b; }}
.tier-t2 {{ color:#22c55e; font-weight:bold; }}
.tier-t3 {{ color:#ef4444; font-weight:bold; }}
.trend-buy {{ color:#22c55e; }}
.trend-sell {{ color:#ef4444; }}
.trend-hold {{ color:#f59e0b; }}
.chart-row {{ display:flex; gap:20px; flex-wrap:wrap; margin-top:16px; }}
.chart-box {{ flex:1; min-width:300px; background:#252836; border-radius:8px; padding:16px; }}
.chart-box h4 {{ color:#888; font-size:0.85em; margin-bottom:8px; }}
.chart-box canvas {{ width:100% !important; height:300px !important; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:20px; }}
.card {{ background:#252836; border-radius:10px; padding:20px; text-align:center; }}
.card .card-value {{ font-size:1.8em; font-weight:bold; color:#f59e0b; }}
.card .card-label {{ color:#888; font-size:0.85em; margin-top:4px; }}
.card .card-sub {{ color:#555; font-size:0.75em; margin-top:2px; }}
.footer {{ text-align:center; color:#555; font-size:0.8em; padding:30px; border-top:1px solid #2a2d38; margin-top:30px; }}
.debate-badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:0.8em; }}
.debate-buy {{ background:#22c55e22; color:#22c55e; }}
.debate-sell {{ background:#ef444422; color:#ef4444; }}
.debate-hold {{ background:#f59e0b22; color:#f59e0b; }}
/* 长文本换行 */
td {{ white-space:normal; word-break:break-word; overflow-wrap:break-word; }}
th, td.num {{ white-space:nowrap; }}
@media (max-width:768px) {{ .header h1 {{ font-size:1.5em; }} .chart-box {{ min-width:100%; }} }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>📊 商品期货深度分析报告</h1>
    <div class="subtitle">多维度量化分析 · 专家团辩论 · 风险评估</div>
    <div class="meta">
        <div class="meta-item"><span class="label">报告日期</span> <span class="value">{REPORT_DATE}</span></div>
        <div class="meta-item"><span class="label">数据基准</span> <span class="value">{intermediate.get('data_benchmark','')}</span></div>
        <div class="meta-item"><span class="label">品种</span> <span class="value">{intermediate.get('symbols_count',0)}</span></div>
        <div class="meta-item"><span class="label">数据源</span> <span class="value">{data_source_used}</span></div>
        <div class="meta-item"><span class="label">辩论裁决</span> <span class="value">{len(debate_results)}个品种</span></div>
    </div>
</div>

<div class="summary-cards">
    <div class="card"><div class="card-value">{total}</div><div class="card-label">总信号数</div></div>
    <div class="card"><div class="card-value">{total_buy}</div><div class="card-label" style="color:#22c55e;">做多信号</div></div>
    <div class="card"><div class="card-value">{total_sell}</div><div class="card-label" style="color:#ef4444;">做空信号</div></div>
    <div class="card"><div class="card-value">{len(chain_results)}</div><div class="card-label">产业链数</div></div>
    <div class="card"><div class="card-value">{len(T1_signals)}</div><div class="card-label" style="color:#f59e0b;">T1观察</div><div class="card-sub">60-75分</div></div>
    <div class="card"><div class="card-value">{len(T2_signals)}</div><div class="card-label" style="color:#22c55e;">T2主仓</div><div class="card-sub">75-90分</div></div>
</div>

<div class="section">
    <h2>🔗 产业链全景</h2>
    <div class="sub-title">12产业链整体趋势 — 排序按平均得分</div>
    <table><thead><tr><th>产业链</th><th>趋势</th><th class="num">平均分</th><th class="num">品种</th><th class="num">BUY/SELL/HOLD</th><th>龙头</th></tr></thead>
    <tbody>{chain_rows}</tbody></table>
</div>

<div class="section">
    <h2>⚖️ 专家团辩论裁决</h2>
    <div class="sub-title">由 数聚石+技研锋(P1)→链证源(P2)→牛势研+熊谋略(P3)→闫判官(P3b)→风控明(P4)→策执远(P5) 8Agent联合产出</div>
"""

    if debate_rows:
        html += f"""    {debate_rows}"""
    else:
        html += '    <p style="color:#888;">辩论数据为空。</p>'

    html += f"""
</div>

<div class="section">
    <h2>📋 全信号列表</h2>
    <div class="sub-title">过滤：置信度≥50%、辩论裁决≠HOLD。排序：T3→T2→T1。</div>
    <table><thead><tr><th>品种</th><th>方向</th><th class="num">置信度</th>
    <th class="num">入场</th><th class="num">目标</th><th class="num">止损</th><th class="num">盈亏比</th><th>等级</th></tr></thead>
    <tbody>{all_rows}</tbody></table>
</div>

<div class="section">
    <h2>📡 数据源与时效性</h2>
    <table><thead><tr><th>数据源</th><th>状态</th><th>数据日期</th><th>说明</th></tr></thead>
    <tbody>
        <tr><td>futures-data-search DuckDB</td><td style="color:#22c55e;">✅ 主数据源</td><td>{intermediate.get('data_benchmark','')}</td><td>{intermediate.get('symbols_count',0)}品种</td></tr>
        <tr><td>AKShare 技术指标补充</td><td style="color:#f59e0b;">⚠ 降级补充</td><td>{intermediate.get('data_benchmark','')}</td><td>150天K线历史</td></tr>
        <tr><td>通达信TQ-Local指标桥接</td><td style="color:{'#22c55e' if tdx_available else '#ef4444'};">{'✅ 已连接' if tdx_available else '❌ 不可用→numpy兜底'}</td><td>{intermediate.get('data_benchmark','')}</td><td>DMI/RSI/CCI/MACD(14,6)</td></tr>
        <tr><td>专家团辩论</td><td style="color:#22c55e;">✅</td><td>{intermediate.get('data_benchmark','')}</td><td>{len(debate_results)}品种裁决</td></tr>
    </tbody></table>
    <p style="color:#888;font-size:0.85em;margin-top:8px;">
    📌 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 数据基准: {intermediate.get('data_benchmark','')}
    </p>
</div>

<div class="section" style="border-color:#ef444466;">
    <h2>⚠️ 风险提示与免责声明</h2>
    <p style="color:#ef4444;font-size:0.9em;line-height:1.8;">
    1. 本报告仅为量化分析参考，不构成任何投资建议。<br>
    2. 右侧交易铁律：所有信号需等待价格突破关键位置确认后方可执行，禁止提前布局。<br>
    3. 期货交易具有高风险性，可能导致本金全部亏损，请谨慎参与。<br>
    4. 报告基于{intermediate.get('data_benchmark','')}收盘数据生成，市场情况可能已发生变化。<br>
    5. 辩论裁决由专家团（数聚石+技研锋→链证源→牛势研+熊谋略→闫判官→风控明→策执远）8Agent联合产出。
    </p>
</div>

<div class="footer">
    <p>商品期货深度分析报告 | {REPORT_DATE}</p>
    <p>数据源: {data_source_used} | 辩论: 专家团(futures-debate-team) | 技术指标: {indicator_source}</p>
    <p style="color:#ef4444;">⚠️ 投资有风险，入市需谨慎。本报告仅供参考，不构成投资建议。</p>
</div>

</div>
</body>
</html>"""
    return html

html_content = build_html()
with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
    f.write(html_content)

# Save results JSON
results = {
    'report_date': REPORT_DATE,
    'data_benchmark': intermediate.get('data_benchmark', ''),
    'data_source': data_source_used,
    'filtered_signals': filtered_signals,
    'T1_count': len(T1_signals),
    'T2_count': len(T2_signals),
    'T3_count': len(T3_signals),
    'debate_count': len(debate_results),
}
with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f"\n{'='*60}")
print(f"✅ Phase 3 完成！")
print(f"📊 报告: {OUTPUT_HTML}")
print(f"🔴 信号: T1={len(T1_signals)}, T2={len(T2_signals)}, T3={len(T3_signals)}")
print(f"{'='*60}")
