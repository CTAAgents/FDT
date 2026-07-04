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
