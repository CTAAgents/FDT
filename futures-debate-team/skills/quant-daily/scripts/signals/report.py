# -*- coding: utf-8 -*-
"""报告生成：Markdown + HTML（自下而上版本，置信度优先）。"""

import time


def generate_markdown_report(chain_results: dict, all_opportunities: list,
                             buy_opps: list, sell_opps: list,
                             risk_assessments: dict, data_source: str = 'auto') -> str:
    """生成Markdown报告（置信度优先排序）。"""
    date_str = time.strftime('%Y-%m-%d')
    source_label = {'tqsdk': 'TqSdk（实时行情+技术指标）', 'akshare': 'AKShare（futures_main_sina）',
                    'exchange': '交易所官方API（DCE/SHFE/CZCE/CFFEX/GFEX）',
                    'cache': '历史缓存数据（置信度已下调）',
                    'auto': '自动采集'}.get(data_source, data_source)

    lines = [
        f'# 商品期货产业链分析报告（置信度优先）',
        '',
        f'**日期**：{date_str}',
        f'**数据来源**：{source_label}',
        f'**分析逻辑**：自下而上（品种信号→产业链验证→置信度排序）',
        '',
    ]

    # ================================================================
    # 一、交易机会汇总（核心输出）
    # ================================================================
    lines.extend(['## 一、交易机会汇总（按置信度排序）', ''])

    if not all_opportunities:
        lines.append('> 今日无符合置信度要求的交易机会，建议观望。')
        lines.append('')
        # 无机会时跳过后续明细，减少报告长度
        lines.extend([
            '## 二、信号筛选统计', '',
            f'- 扫描品种总数：{sum(c["count"] for c in chain_results.values())}个',
            f'- 有效交易机会：0个',
            '',
            '## 三、产业链概览（信号验证参考）', '',
        ])
    else:
        lines.extend([
            '| 排名 | 品种 | 方向 | 置信度 | 盈亏比 | 推荐分 | 入场价 | 目标价 | 止损价 | 仓位 | 趋势阶段 |',
            '|:----:|------|:----:|:------:|:------:|:------:|-------:|-------:|-------:|:----:|:--------:|',
        ])

        for i, opp in enumerate(all_opportunities, 1):
            tp = opp['trade_plan']
            d = '做多' if tp['decision'] == 'BUY' else '做空'
            stage = opp['trend_stage']['stage']
            stage_cn = {'early': '初期', 'mature': '中期', 'exhausted': '末期'}.get(stage, stage)
            risk = risk_assessments.get(opp['product_id'], {}).get('risk_decision', {})
            pos_adj = risk.get('position_adjustment', '')

            lines.append(
                f"| {i} | {opp['product_id']}({opp['product_name']}) | {d} | "
                f"{tp['confidence']:.0%} | {tp.get('risk_reward_ratio', 0):.1f}:1 | "
                f"{tp.get('recommend_score', 0):.2f} | "
                f"{tp.get('entry_price', 0):.2f} | {tp.get('target_price', 0):.2f} | "
                f"{tp.get('stop_loss', 0):.2f} | {tp.get('position_size', 'N/A')} | {stage_cn} |"
            )

    lines.append('')

    # ================================================================
    # 二、信号筛选统计
    # ================================================================
    total = len(chain_results) and sum(c['count'] for c in chain_results.values())
    lines.extend([
        '## 二、信号筛选统计', '',
        f'- 扫描品种总数：{total}个',
        f'- 通过筛选的候选信号：{len(all_opportunities)}个',
        f'- 做多机会：{len(buy_opps)}个',
        f'- 做空机会：{len(sell_opps)}个',
        '',
    ])

    # ================================================================
    # 三、产业链概览（验证用，非决策依据）
    # ================================================================
    lines.extend(['## 三、产业链概览（信号验证参考）', ''])

    for cn, cd in chain_results.items():
        lines.extend([
            f'### {cn}',
            f"**整体趋势**：{cd['overall_trend']}（平均得分：{cd['avg_score']:.0f}）",
            f"**品种数**：{cd['count']} | **龙头**：{cd['leader']} @ {cd['leader_price']:.2f}",
            '',
            '| 品种 | 价格 | 得分 | 趋势 | 持仓量 |',
            '|------|-----:|:----:|------|-------:|',
        ])
        for m in cd['members']:
            lines.append(
                f"| {m['pid']} | {m['price']:.2f} | {m['score']:.0f} | {m['trend']} | {m['oi']:,} |"
            )
        lines.extend(['', '---', ''])

    # ================================================================
    # 四、风险提示
    # ================================================================
    lines.extend([
        '## 四、风险提示', '',
        '1. 技术指标有滞后性，需结合市场情绪判断',
        '2. 期货交易具有高杠杆特性，风险较大',
        '3. 产业链基本面变化可能影响价格走势',
        '4. 宏观经济政策变化可能带来系统性风险',
        '', '---', '',
        '⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议。投资有风险，决策需谨慎。',
    ])

    return '\n'.join(lines)


def generate_html_report(chain_results: dict, all_opportunities: list,
                         buy_opps: list, sell_opps: list,
                         risk_assessments: dict, data_source: str = 'auto') -> str:
    """生成HTML可视化报告（Chart.js，内联样式，置信度优先）。"""
    import json as _json

    date_str = time.strftime('%Y-%m-%d')
    source_label = {'tqsdk': 'TqSdk（实时行情+技术指标）', 'akshare': 'AKShare（futures_main_sina）',
                    'exchange': '交易所官方API（DCE/SHFE/CZCE/CFFEX/GFEX）',
                    'cache': '历史缓存数据（置信度已下调）',
                    'auto': '自动采集'}.get(data_source, data_source)
    total_symbols = sum(c['count'] for c in chain_results.values())

    # ================================================================
    # 交易机会卡片
    # ================================================================
    tp_rows = ''
    for i, opp in enumerate(all_opportunities, 1):
        tp = opp['trade_plan']
        d = '做空' if tp['decision'] == 'SELL' else '做多'
        cls = 'sell' if tp['decision'] == 'SELL' else 'buy'
        stage = opp['trend_stage']['stage']
        stage_cn = {'early': '初期', 'mature': '中期', 'exhausted': '末期'}.get(stage, stage)
        resonance = opp['resonance']
        chain_v = opp['chain_verify']
        risk = risk_assessments.get(opp['product_id'], {})

        tp_rows += (
            f'<div class="tp-card {cls}">'
            f'<div class="tp-header">'
            f'<span class="tp-rank">#{i}</span>'
            f'<strong>{opp["product_id"]}（{opp["product_name"]}）</strong>'
            f'<span class="tp-dir">{d}</span>'
            f'<span class="tp-badge conf">置信度 {tp["confidence"]:.0%}</span>'
            f'<span class="tp-badge rr">盈亏比 {tp.get("risk_reward_ratio", 0):.1f}:1</span>'
            f'</div>'
            f'<div class="tp-body">'
            f'<div class="tp-prices">'
            f'<span>入场: <strong>{tp.get("entry_price", 0):.2f}</strong></span>'
            f'<span>目标: <strong>{tp.get("target_price", 0):.2f}</strong></span>'
            f'<span>止损: <strong>{tp.get("stop_loss", 0):.2f}</strong></span>'
            f'<span>仓位: {tp.get("position_size", "N/A")}</span>'
            f'</div>'
            f'<div class="tp-meta">'
            f'<span>趋势阶段: {stage_cn}</span>'
            f'<span>共振: {resonance["confirmations"]}/{resonance["total_checks"]}</span>'
            f'<span>产业链: {chain_v["chain_name"]} ({chain_v["chain_trend"]})</span>'
            f'<span>辩论: 多{opp["debate"]["bull_strength"]} vs 空{opp["debate"]["bear_strength"]}</span>'
            f'</div></div></div>\n'
        )

    if not tp_rows:
        tp_rows = '<div class="tp-card hold"><strong>今日无符合置信度要求的交易机会</strong></div>'

    # ================================================================
    # 产业链详情卡片
    # ================================================================
    chain_cards = ''
    for cn, cd in chain_results.items():
        members_html = ''
        for m in cd['members']:
            sc = '#22c55e' if m['score'] > 0 else ('#ef4444' if m['score'] < 0 else '#f59e0b')
            members_html += (
                f'<tr><td>{m["pid"]}</td><td>{m["name"]}</td><td>{m["price"]:.2f}</td>'
                f'<td style="color:{sc};font-weight:bold">{m["score"]:.0f}</td>'
                f'<td>{m["trend"]}</td><td>{m["oi"]:,}</td></tr>\n'
            )

        tc = 'bull' if '多' in cd['overall_trend'] else ('bear' if '空' in cd['overall_trend'] else 'neutral')
        chain_cards += (
            f'<div class="chain-card">'
            f'<h3>{cn} <span class="trend-badge {tc}">{cd["overall_trend"]}</span></h3>'
            f'<p>品种数: {cd["count"]} | 龙头: <strong>{cd["leader"]}</strong> @ {cd["leader_price"]:.2f} | '
            f'平均得分: <strong>{cd["avg_score"]:.0f}</strong></p>'
            f'<table class="member-table"><thead><tr><th>品种</th><th>名称</th><th>价格</th><th>得分</th><th>趋势</th><th>持仓量</th></tr></thead>'
            f'<tbody>{members_html}</tbody></table></div>\n'
        )

    # ================================================================
    # 图表数据
    # ================================================================
    # 置信度-盈亏比散点图数据
    scatter_data = []
    for opp in all_opportunities:
        tp = opp['trade_plan']
        scatter_data.append({
            'x': tp.get('risk_reward_ratio', 0),
            'y': tp['confidence'] * 100,
            'label': opp['product_id'],
        })

    # 产业链评分柱状图
    chain_names = list(chain_results.keys())
    chain_scores = [chain_results[n]['avg_score'] for n in chain_names]

    labels_js = _json.dumps([n[:4] for n in chain_names], ensure_ascii=False)
    colors = _json.dumps(['#22c55e' if s > 0 else '#ef4444' if s < 0 else '#f59e0b' for s in chain_scores])
    scatter_js = _json.dumps(scatter_data)

    # 统计
    buy_c = len(buy_opps)
    sell_c = len(sell_opps)
    hold_c = total_symbols - buy_c - sell_c

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>商品期货产业链分析报告（置信度优先） - {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:1200px;margin:0 auto;padding:24px;background:#0f172a;color:#e2e8f0}}
.header{{background:linear-gradient(135deg,#1e293b,#334155);padding:32px;border-radius:16px;margin-bottom:24px;border:1px solid #475569}}
.header h1{{font-size:28px;margin:0 0 8px;color:#f8fafc}}
.header p{{color:#94a3b8;margin:4px 0}}
.stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-top:16px}}
.stat{{background:rgba(255,255,255,0.05);padding:16px;border-radius:12px;text-align:center;border:1px solid #334155}}
.stat .num{{font-size:28px;font-weight:bold;color:#f8fafc}}
.stat .label{{font-size:13px;color:#94a3b8;margin-top:4px}}
.chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px}}
.chart-card{{background:#1e293b;padding:24px;border-radius:12px;border:1px solid #334155}}
.chart-card h2{{margin:0 0 16px;font-size:18px;color:#f8fafc}}
.chain-card{{background:#1e293b;padding:24px;border-radius:12px;margin-bottom:16px;border:1px solid #334155}}
.chain-card h3{{margin:0 0 12px;font-size:18px}}
.trend-badge{{font-size:13px;padding:2px 10px;border-radius:12px;font-weight:normal}}
.trend-badge.bull{{background:#166534;color:#86efac}}
.trend-badge.bear{{background:#991b1b;color:#fca5a5}}
.trend-badge.neutral{{background:#78350f;color:#fde68a}}
.member-table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}}
.member-table th{{background:#334155;padding:8px 12px;text-align:left}}
.member-table td{{padding:6px 12px;border-bottom:1px solid #1e293b}}
.tp-card{{background:#1e293b;padding:16px;border-radius:12px;margin-bottom:12px;border:1px solid #334155}}
.tp-card.sell{{border-left:4px solid #ef4444}}.tp-card.buy{{border-left:4px solid #22c55e}}.tp-card.hold{{border-left:4px solid #f59e0b}}
.tp-header{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.tp-rank{{background:#475569;color:#f8fafc;padding:2px 10px;border-radius:8px;font-weight:bold;font-size:14px}}
.tp-dir{{font-weight:bold;font-size:15px}}
.tp-badge{{font-size:12px;padding:2px 8px;border-radius:8px}}
.tp-badge.conf{{background:#1e3a5f;color:#60a5fa}}
.tp-badge.rr{{background:#1e3a2f;color:#4ade80}}
.tp-body{{margin-top:10px}}
.tp-prices{{display:flex;gap:20px;font-size:14px;color:#cbd5e1}}
.tp-prices strong{{color:#f8fafc}}
.tp-meta{{display:flex;gap:16px;font-size:12px;color:#94a3b8;margin-top:6px}}
.disclaimer{{color:#64748b;font-size:13px;padding:16px;border-top:1px solid #334155;margin-top:24px}}
canvas{{max-height:350px}}
</style></head><body>
<div class="header">
<h1>📊 商品期货产业链分析报告（置信度优先）</h1>
<p>日期：{date_str} | 数据来源：{source_label}</p>
<p>分析逻辑：自下而上（品种信号→产业链验证→置信度排序） | 扫描品种：{total_symbols}个</p>
<div class="stats">
<div class="stat"><div class="num">{total_symbols}</div><div class="label">扫描品种</div></div>
<div class="stat"><div class="num" style="color:#22c55e">{buy_c}</div><div class="label">做多机会</div></div>
<div class="stat"><div class="num" style="color:#ef4444">{sell_c}</div><div class="label">做空机会</div></div>
<div class="stat"><div class="num" style="color:#f59e0b">{hold_c}</div><div class="label">观望</div></div>
<div class="stat"><div class="num">{len(all_opportunities)}</div><div class="label">有效机会</div></div>
</div></div>

<div class="chart-row">
<div class="chart-card"><h2>📈 置信度 vs 盈亏比</h2><canvas id="scatterChart"></canvas></div>
<div class="chart-card"><h2>📊 产业链趋势评分</h2><canvas id="trendChart"></canvas></div>
</div>

<h2 style="margin-top:32px">🎯 交易机会（置信度优先排序）</h2>
{tp_rows}

<h2 style="margin-top:32px">📋 产业链概览（信号验证参考）</h2>
{chain_cards}

<div class="disclaimer">⚠️ 以上内容由 AI 基于公开信息自动分析生成，仅供参考，不构成任何投资建议。投资有风险，决策需谨慎。</div>
<script>
// 置信度-盈亏比散点图
new Chart(document.getElementById('scatterChart').getContext('2d'),{{
  type:'scatter',
  data:{{
    datasets:[{{
      label:'交易机会',
      data:{scatter_js},
      backgroundColor:function(ctx){{return ctx.raw&&ctx.raw.x>0?'#22c55e':'#ef4444'}},
      pointRadius:8,
    }}]
  }},
  options:{{
    scales:{{
      x:{{title:{{display:true,text:'盈亏比',color:'#94a3b8'}},grid:{{color:'#334155'}},ticks:{{color:'#94a3b8'}}}},
      y:{{title:{{display:true,text:'置信度(%)',color:'#94a3b8'}},grid:{{color:'#334155'}},ticks:{{color:'#94a3b8'}},min:0,max:100}}
    }},
    plugins:{{
      legend:{{display:false}},
      tooltip:{{
        callbacks:{{
          label:function(ctx){{
            var d=ctx.raw;
            return d.label+': 盈亏比'+d.x+':1, 置信度'+d.y+'%';
          }}
        }}
      }}
    }}
  }}
}});

// 产业链评分柱状图
new Chart(document.getElementById('trendChart').getContext('2d'),{{
  type:'bar',
  data:{{
    labels:{labels_js},
    datasets:[{{label:'趋势评分',data:{_json.dumps(chain_scores)},{colors}}}]
  }},
  options:{{
    scales:{{
      y:{{grid:{{color:'#334155'}},ticks:{{color:'#94a3b8'}}}},
      x:{{grid:{{color:'#334155'}},ticks:{{color:'#94a3b8'}}}}
    }},
    plugins:{{legend:{{display:false}}}}
  }}
}});
</script></body></html>'''


def generate_debate_html_report(truth: dict) -> str:
    """从 scan_true_layered.py 的 JSON 输出生成辩论风格 HTML 报告。

    Args:
        truth: true_layered_YYYYMMDD.json 解析后的 dict

    Returns:
        str: 完整 HTML 报告字符串
    """
    import json as _json
    date_str = truth['meta']['date']
    fmt_date = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    n_all = truth['meta']['n_contracts']
    n_bull = truth['meta'].get('bull', 0)
    n_bear = truth['meta'].get('bear', 0)
    ranked = truth['ranked']
    qs = truth.get('qualified_signals', {})
    shorts = qs.get('short', [])
    longs = qs.get('long', [])
    s_qualified = [s for s in shorts if not s.get('filtered')]
    l_qualified = [s for s in longs if not s.get('filtered')]

    factor_names = ['D1趋势','D2回归','D3回归','D4资金','D5资金','D6量价','D7期限']

    def _factor_bar_html(dims: dict) -> str:
        keys = list(dims.keys())[:7]
        html = '<div class="fb">'
        for i, k in enumerate(keys):
            v = dims[k]
            cl = 'fg' if v >= 70 else ('fy' if v >= 40 else 'fr')
            html += f'<div class="fr"><span class="fl">{factor_names[i]}</span>'
            html += f'<div class="fbb"><div class="fb-f {cl}" style="width:{v:.0f}%"></div></div>'
            html += f'<span class="fs {cl}">{v:.0f}</span></div>'
        html += '</div>'
        return html

    def _card(s: dict, cls: str, rank_label: str) -> str:
        side = s.get('side', 'N/A')
        sc_cls = 'sc-s' if side == '右侧' else ('sc-l' if side == '左侧' else 'sc-h')
        sd_cls = 'sd-s' if cls == 'short' else 'sd-l'
        dir_text = '做空' if cls == 'short' else '做多'
        style_raw = s.get('style', '趋势')
        _style_colors = {'趋势':'#3b82f6','回归':'#f59e0b','资金':'#22c55e','量价':'#a78bfa'}
        style_tags = '+'.join(
            f'<span style="color:{_style_colors.get(t,"#94a3b8")}">{t}</span>'
            for t in style_raw.split('+')
        )
        sig_label = s.get('signal_type', '')
        sig_map = {'regime_trend':'趋势驱动','regime_reg':'回归驱动','hybrid':'混合'}
        sig_text = sig_map.get(sig_label, sig_label or '其他')
        dims = s.get('dims', {})
        adx = s.get('adx', 0)
        veto = s.get('veto', 1.0)
        rank_num = s.get('rank', 0) if cls == 'short' else s.get('rank', 0)
        # 辩论论点
        pro_pts, con_pts = _get_debate_pts(s['symbol'], side, dims, adx, veto)
        pro_html = ''.join(f'<div class="di dp">✅ {p}</div>' for p in pro_pts)
        con_html = ''.join(f'<div class="di dc">⚠️ {c}</div>' for c in con_pts)

        return f'''<div class="sc {sc_cls}">
<div class="sh"><span class="sr">#{rank_label}</span><span class="sn">{s["symbol"]}</span><span class="sd {sd_cls}">{dir_text}</span><span style="font-size:11px;color:#94a3b8">确排 {s.get("adj_rank",0):.1f}</span></div>
<div class="sm"><span>ADX <span style="color:{"#ef4444" if adx>30 else "#22c55e"}">{adx}</span></span><span>否决 <span style="color:{"#22c55e" if veto>=1 else "#f59e0b"}">{veto:.2f}</span></span><span>侧: <strong>{side}</strong></span><span>{style_tags}</span><span>{sig_text}</span></div>
{_factor_bar_html(dims)}
<div class="db"><h4>📢 辩论论点</h4>{pro_html}{con_html}</div>
</div>'''

    def _get_debate_pts(sym: str, side: str, dims: dict, adx: float, veto: float) -> tuple:
        """为品种生成多/空辩论论点。"""
        d_vals = list(dims.values())[:7] if dims else [0]*7
        pro, con = [], []
        # 做空方论点（强力支持做空的因子）
        strong_dims = [(factor_names[i], d_vals[i]) for i in range(7) if d_vals[i] >= 70]
        if strong_dims:
            top = strong_dims[:3]
            pro.append(f"高评分因子: {', '.join(f'{n}={v:.0f}' for n,v in top)}")
        if adx > 25:
            pro.append(f"ADX={adx:.0f} 趋势强度确认")
        if d_vals[6] >= 70:  # D7期限
            pro.append("D7期限结构强烈支持")
        if d_vals[3] >= 70 or d_vals[4] >= 70:  # D4/D5资金
            pro.append("资金面确认(D4/D5)")

        # 做空方反方论点（风险）
        if d_vals[6] < 30:
            con.append("D7期限支持偏弱")
        if d_vals[0] < 20:  # D1趋势
            con.append("D1趋势已衰竭，纯回归信号")
        if adx > 60:
            con.append(f"ADX={adx:.0f} 极度过熟")
        if d_vals[5] < 30:  # D6量价
            con.append("D6量价未确认")
        if veto < 1:
            con.append(f"否决系数={veto:.2f}<1.0 信号信度折扣")
        if side == '左侧':
            con.append("左侧信号，需等右侧确认")
        elif side == '中心':
            con.append("中心分类，方向不明确")
        if d_vals[0] >= 80 and d_vals[1] <= 15:
            con.append("D1强趋势 vs D2极低乖离，修复风险")

        # 确保每个品种至少有2条
        if len(pro) < 2:
            pro.append("量化信号排名靠前")
        if len(con) < 2:
            con.append("需关注回归风险")
        return pro[:3], con[:3]

    # 构建卡片HTML
    short_cards = ''.join(_card(s, 'short', str(i+1)) for i, s in enumerate(s_qualified))
    long_cards = ''.join(_card(s, 'long', str(s.get('rank', 0))) for s in l_qualified)

    # 全品种排名表数据 JS
    rank_rows_js = _json.dumps([
        {
            'r': r['rank'], 's': r['symbol'],
            'a': r.get('adjusted_rank', 0), 'v': r.get('veto_penalty', 1),
            'd': [r['dims'].get(k, 0) for k in list(r['dims'].keys())[:7]],
            'sig': _classify_signal(r)
        }
        for r in ranked
    ])

    # 雷达图数据 (Top5 short / Top5 long with veto>=0.5)
    short_top5 = [s for s in s_qualified[:5]]
    long_top5 = [s for s in l_qualified if s.get('veto', 0) >= 0.5][:5]

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>期货辩论专家团深度分析报告 — {fmt_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0b1120;color:#e2e8f0;padding:8px}}
.c{{max-width:1400px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1e293b,#0f172a);border-radius:16px;padding:32px;margin-bottom:24px;border:1px solid #334155}}
.hd h1{{font-size:28px;font-weight:700;color:#f8fafc;margin-bottom:4px}}
.hd .sub{{color:#94a3b8;font-size:14px;margin-bottom:16px}}
.bd{{display:flex;gap:8px;flex-wrap:wrap}}
.bd span{{padding:4px 12px;border-radius:20px;font-size:12px;font-weight:500}}
.st{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:24px}}
.st>div{{border-radius:12px;padding:16px;text-align:center;border:1px solid #334155;background:#1e293b}}
.st .n{{font-size:28px;font-weight:700;line-height:1.2}}
.st .l{{font-size:12px;color:#94a3b8;margin-top:4px}}
.sec{{background:#1e293b;border-radius:12px;padding:24px;margin-bottom:20px;border:1px solid #334155}}
.sec h2{{font-size:20px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
.sec h2 .c{{font-size:13px;font-weight:400;color:#94a3b8;background:#334155;padding:2px 10px;border-radius:12px}}
.cr{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:20px}}
.cb{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
.cb h3{{font-size:15px;font-weight:500;margin-bottom:12px;color:#94a3b8}}
.cb canvas{{max-height:280px}}
.sg{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
.sc{{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155;transition:all .2s}}
.sc:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}}
.sc.sc-s{{border-left:4px solid #ef4444}}
.sc.sc-l{{border-left:4px solid #22c55e}}
.sc.sc-h{{border-left:4px solid #f59e0b}}
.sh{{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}}
.sr{{background:#334155;color:#94a3b8;padding:2px 8px;border-radius:6px;font-size:12px}}
.sn{{font-size:18px;font-weight:700}}
.sd{{font-size:12px;padding:2px 8px;border-radius:8px;font-weight:500}}
.sd.sd-s{{background:#3b1f1f;color:#fca5a5}}
.sd.sd-l{{background:#1e3a2f;color:#4ade80}}
.sm{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px}}
.sm span{{font-size:12px;color:#94a3b8;padding:2px 8px;background:#0f172a;border-radius:6px}}
.fb{{display:grid;gap:3px;margin-top:6px;margin-bottom:8px}}
.fr{{display:flex;align-items:center;gap:8px;font-size:11px}}
.fl{{color:#94a3b8;width:80px;flex-shrink:0;font-size:11px}}
.fbb{{flex:1;height:14px;background:#0f172a;border-radius:7px;overflow:hidden}}
.fb-f{{height:100%;border-radius:7px}}
.fb-f.fg{{background:linear-gradient(90deg,#166534,#22c55e)}}
.fb-f.fy{{background:linear-gradient(90deg,#78350f,#f59e0b)}}
.fb-f.fr{{background:linear-gradient(90deg,#991b1b,#ef4444)}}
.fs{{width:30px;text-align:right;font-weight:600;font-size:11px}}
.fs.fg{{color:#4ade80}}.fs.fy{{color:#fde68a}}.fs.fr{{color:#fca5a5}}
.db{{background:#0f172a;border-radius:8px;padding:12px;margin-top:10px}}
.db h4{{font-size:13px;color:#94a3b8;margin-bottom:6px}}
.di{{font-size:12px;line-height:1.6;margin-bottom:4px;padding-left:10px;border-left:2px solid #334155}}
.di.dp{{color:#4ade80;border-color:#22c55e}}
.di.dc{{color:#fca5a5;border-color:#ef4444}}
.rt{{width:100%;border-collapse:collapse;font-size:13px}}
.rt th{{background:#0f172a;padding:10px 12px;text-align:left;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;position:sticky;top:0}}
.rt td{{padding:10px 12px;border-bottom:1px solid #1e293b}}
.rt tr:hover{{background:rgba(255,255,255,.03)}}
.vg{{background:#166534;color:#86efac;padding:2px 10px;border-radius:10px;font-size:12px}}
.vy{{background:#78350f;color:#fde68a;padding:2px 10px;border-radius:10px;font-size:12px}}
.footer{{text-align:center;color:#475569;font-size:12px;padding:24px 0;border-top:1px solid #1e293b;margin-top:32px}}
@media(max-width:900px){{.st{{grid-template-columns:repeat(3,1fr)}}.cr{{grid-template-columns:1fr}}.sg{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="c">

<div class="hd">
<h1>⚖️ 期货辩论专家团 <span style="color:#3b82f6">深度分析报告</span></h1>
<div class="sub">{fmt_date} · 全品种扫描 {n_all}个品种 · 量化多头{n_bull} / 量化空头{n_bear}</div>
<div class="bd">
<span style="background:#1e3a5f;color:#60a5fa">📡 通达信TDX + AKShare OI</span>
<span style="background:#3b1f1f;color:#fca5a5">🔴 7因子真分层打分</span>
<span style="background:#1e3a2f;color:#4ade80">📊 九宫格分类·左右侧识别</span>
</div></div>

<div class="st">
<div><div class="n" style="color:#f8fafc">{n_all}</div><div class="l">全品种扫描</div></div>
<div style="border-top:3px solid #22c55e"><div class="n" style="color:#22c55e">{n_bull}</div><div class="l">量化多头</div></div>
<div style="border-top:3px solid #ef4444"><div class="n" style="color:#ef4444">{n_bear}</div><div class="l">量化空头</div></div>
<div style="border-top:3px solid #f59e0b"><div class="n" style="color:#f59e0b">{len(s_qualified)}</div><div class="l">合格做空信号</div></div>
<div style="border-top:3px solid #f59e0b"><div class="n" style="color:#60a5fa">{len(l_qualified)}</div><div class="l">合格做多信号</div></div>
<div><div class="n" style="color:#c084fc">7</div><div class="l">因子维度</div></div>
</div>

<div class="cr">
<div class="cb"><h3>🔴 做空 TOP5 · 7因子分布</h3><canvas id="sRadar"></canvas></div>
<div class="cb"><h3>🟢 做多 TOP5 · 7因子分布</h3><canvas id="lRadar"></canvas></div>
<div class="cb"><h3>📊 截面排名分布 ({n_all}品种)</h3><canvas id="rDist"></canvas></div>
</div>

<div class="sec" style="border-left:4px solid #ef4444">
<h2>🔴 做空 TOP {len(s_qualified)} 辩论分析 <span class="c">截面排名最高→最超买→预期下跌</span></h2>
<div class="sg">{short_cards}</div>
</div>

<div class="sec" style="border-left:4px solid #22c55e">
<h2>🟢 做多 BOTTOM {len(l_qualified)} 辩论分析 <span class="c">截面排名最低→最超卖→预期上涨</span></h2>
<div class="sg">{long_cards}</div>
</div>

<div class="sec">
<h2>📊 全品种排名表 <span class="c">{n_all}品种·按adj_rank降序</span></h2>
<div style="max-height:500px;overflow-y:auto;border:1px solid #334155;border-radius:8px">
<table class="rt"><thead><tr><th>#</th><th>品种</th><th>确排</th><th>D1趋势</th><th>D2回归</th><th>D3回归</th><th>D4资金</th><th>D5资金</th><th>D6量价</th><th>D7期限</th><th>否决</th><th>信号</th></tr></thead>
<tbody id="rb"></tbody></table></div></div>

<div class="footer">
<p>⚠️ 以上内容由 AI 辩论专家团基于公开数据生成，仅供参考，不构成任何投资建议。</p>
<p>数据来源：通达信TDX-Local + AKShare OI注入 · quant-daily v2.0 · 辩论专家团 v3.1</p></div></div>

<script>
var ALL = {rank_rows_js};
function sc(v){{return v>=70?'#22c55e':v>=40?'#f59e0b':'#ef4444'}}
var tb='';ALL.forEach(function(r){{tb+='<tr><td>'+r.r+'</td><td><strong>'+r.s+'</strong></td><td>'+r.a.toFixed(1)+'</td>';r.d.forEach(function(v){{tb+='<td style="color:'+sc(v)+'">'+v.toFixed(0)+'</td>'}});tb+='<td>'+r.v.toFixed(2)+'</td><td style="color:#94a3b8;font-size:12px">'+r.sig+'</td></tr>'}});
document.getElementById('rb').innerHTML=tb;
try{{if(typeof Chart!=='undefined'){{
var sl={_json.dumps(factor_names,ensure_ascii=False)};
new Chart(document.getElementById('sRadar'),{{type:'radar',data:{{labels:sl,datasets:[
{''.join(f'{{label:"{s["symbol"]}",data:{_json.dumps(list(s.get("dims",{}).values())[:7])},borderColor:c[{i}],backgroundColor:c[{i}]+"33",borderWidth:2,pointRadius:3}},' for i,s in enumerate(short_top5))}
]}},options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},scales:{{r:{{angleLines:{{color:'#334155'}},grid:{{color:'#334155'}},pointLabels:{{color:'#94a3b8',font:{{size:10}}}},suggestedMin:0,suggestedMax:100,ticks:{{display:false}}}}}}}}}});
new Chart(document.getElementById('lRadar'),{{type:'radar',data:{{labels:sl,datasets:[
{''.join(f'{{label:"{s["symbol"]}",data:{_json.dumps(list(s.get("dims",{}).values())[:7])},borderColor:lc[{i}],backgroundColor:lc[{i}]+"33",borderWidth:2,pointRadius:3}},' for i,s in enumerate(long_top5))}
]}},options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},scales:{{r:{{angleLines:{{color:'#334155'}},grid:{{color:'#334155'}},pointLabels:{{color:'#94a3b8',font:{{size:10}}}},suggestedMin:0,suggestedMax:100,ticks:{{display:false}}}}}}}}}});
var rv=ALL.map(function(r){{return r.a}});
new Chart(document.getElementById('rDist'),{{type:'bar',data:{{labels:ALL.map(function(r){{return r.s}}),datasets:[{{label:'调整排名',data:rv,backgroundColor:rv.map(function(v){{return v>=50?'#ef4444':v>=30?'#f59e0b':'#22c55e'}}),borderRadius:3}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#94a3b8',font:{{size:8}},maxRotation:90}},grid:{{display:false}}}},y:{{ticks:{{color:'#94a3b8'}},grid:{{color:'#334155'}},suggestedMin:0,suggestedMax:100}}}}}}}});
}}catch(e){{console.warn('Chart:',e)}}
</script></body></html>'''


def _classify_signal(r: dict) -> str:
    """从排名条目推断信号风格。"""
    d = r.get('dims', {})
    keys = list(d.keys())
    if len(keys) < 2:
        return '其他'
    vals = list(d.values())
    has_trend = vals[0] >= 50 if len(vals) > 0 else False
    has_reg = vals[1] >= 50 if len(vals) > 1 else False
    has_fund = (vals[2] >= 50 or vals[3] >= 50) if len(vals) > 3 else False
    if has_trend and has_fund:
        return '趋势+资金'
    if has_reg and has_fund:
        return '回归+资金'
    if has_trend and has_reg:
        return '趋势+回归'
    if has_trend:
        return '趋势'
    if has_reg:
        return '回归'
    return '其他'
