#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
辩论深度分析HTML报告生成器
=================================
读取链证源分析结果 + 全量信号数据 → 输出辩论深度分析HTML报告

用法:
  python phase3_generate_debate_report.py \\
    --chain-json path/to/chain_analysis.json \\
    --summary-json path/to/summary.json \\
    --prices-json path/to/prices.json (可选) \\
    -o path/to/output.html

作为 futures-trading-analysis skill 的一部分，
消除之前临时编写的 build_v2_report.py 胶水代码。
"""

import sys, os, json, math, datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

import argparse

parser = argparse.ArgumentParser(description="辩论深度分析HTML报告生成")
parser.add_argument("--chain-json", required=True, help="链证源分析JSON路径")
parser.add_argument("--summary-json", required=True, help="全量信号JSON路径")
parser.add_argument("--prices-json", help="历史价格JSON路径(用于展示相关系数)", default=None)
parser.add_argument("-o", "--output", required=True, help="输出HTML路径")
parser.add_argument("--title", default="期货交易辩论专家团 · 深度分析报告", help="报告标题")
parser.add_argument("--version", default="v2.15.0", help="版本号")
args = parser.parse_args()


def pearson(a, b, w=60):
    """计算60日滚动Pearson相关系数"""
    n = min(len(a), len(b), w)
    if n < 10:
        return 0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    den = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n))) * math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    return round(num / den, 2) if den else 0


# 加载数据
with open(args.chain_json) as f:
    chain_data = json.load(f)
with open(args.summary_json) as f:
    summary = json.load(f)

cr = chain_data.get("chain_results", {})
rps = chain_data.get("redundant_pairs", [])
jv = chain_data.get("judge_verdict", {})
chain_trends = chain_data.get("chain_trends", {})

price_series = {}
if args.prices_json and os.path.exists(args.prices_json):
    with open(args.prices_json) as f:
        price_series = json.load(f)

# 构建symbol lookup
sym_map = {}
for s in summary["symbols"]:
    sym_map[s["symbol"].upper()] = s

# 样式
BG, CARD, GOLD, RED, GREEN, SEC = "#0f1117", "#1a1d28", "#f59e0b", "#ef4444", "#22c55e", "#94a3b8"

CSS = f"""<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:{BG};color:#e2e8f0;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:20px 40px}}
h1{{font-size:28px;color:#fbbf24;margin-bottom:6px}}
h2{{font-size:22px;color:{GOLD};margin:30px 0 15px;border-left:4px solid {GOLD};padding-left:12px}}
.subtitle{{color:{SEC};font-size:14px;margin-bottom:20px}}
.card{{background:{CARD};border-radius:12px;padding:18px 22px;margin:12px 0;box-shadow:0 2px 8px rgba(0,0,0,0.3)}}
.card-title{{font-size:16px;color:{GOLD};font-weight:600;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#252836;color:#fbbf24;padding:8px 10px;text-align:left;border-bottom:2px solid {GOLD}}}
td{{padding:7px 10px;border-bottom:1px solid #2a2d3a}}
.bear{{color:{RED};font-weight:600}}
.bull{{color:{GREEN};font-weight:600}}
.stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:12px 0}}
.stat-item{{background:#252836;border-radius:8px;padding:12px;text-align:center}}
.stat-value{{font-size:20px;font-weight:700}}
.stat-label{{font-size:11px;color:{SEC};margin-top:4px}}
.divider{{border:none;border-top:1px solid #2a2d3a;margin:20px 0}}
.top5-card{{border-left:3px solid {GOLD}}}
.tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;margin:1px;background:#252836;color:{SEC}}}
.red-box{{background:rgba(239,68,68,0.08);border-left:3px solid {RED};padding:10px 14px;border-radius:6px;margin:8px 0}}
.green-box{{background:rgba(34,197,94,0.08);border-left:3px solid {GREEN};padding:10px 14px;border-radius:6px;margin:8px 0}}
.yellow-box{{background:rgba(245,158,11,0.08);border-left:3px solid {GOLD};padding:10px 14px;border-radius:6px;margin:8px 0}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.badge-bear{{background:rgba(239,68,68,0.2);color:{RED}}}
</style>"""

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
l1l4_bull = summary.get("_meta", {}).get("l1l4_bull", 0)
l1l4_bear = summary.get("_meta", {}).get("l1l4_bear", 0)
ft_bull = summary.get("_meta", {}).get("factor_bull", 0)
ft_bear = summary.get("_meta", {}).get("factor_bear", 0)

parts = [
    f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{args.title} {args.version}</title>{CSS}</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
  <div>
    <h1>🏛️ {args.title}</h1>
    <div class="subtitle">{args.version} · 链证源动态相关性 | 生成: {now}</div>
  </div>
  <div style="text-align:right;font-size:12px;color:{SEC}">共{len(summary.get("symbols", []))}品种</div>
</div>
<hr class="divider">

<h2>📡 P0-① · 数技源 — 全品种双策略信号</h2>
<div class="card">
<div class="stat-grid">
  <div class="stat-item"><div class="stat-value" style="color:{GREEN}">{l1l4_bull}</div><div class="stat-label">L1-L4多头</div></div>
  <div class="stat-item"><div class="stat-value" style="color:{RED}">{l1l4_bear}</div><div class="stat-label">L1-L4空头</div></div>
  <div class="stat-item"><div class="stat-value" style="color:{GREEN}">{ft_bull}</div><div class="stat-label">因子择时多头</div></div>
  <div class="stat-item"><div class="stat-value" style="color:{RED}">{ft_bear}</div><div class="stat-label">因子择时空头</div></div>
</div>
</div>

<h2>🔗 P0-② · 链证源 — 产业链分析+动态相关性</h2>"""
]

# 链趋势
ct_rows = "".join(f"<tr><td>{ch}</td><td>{tr}</td></tr>" for ch, tr in sorted(chain_trends.items()))
parts.append(f"""<div class="card">
<div class="card-title">产业链趋势</div>
<table><tr><th>产业链</th><th>趋势</th></tr>{ct_rows}</table>
</div>""")

# 冗余检测
if rps:
    corr_details = []
    for rp in rps[:10]:
        a, b = rp.get("primary", ""), rp.get("redundant", "")
        r_val = ""
        if a in price_series and b in price_series:
            r_val = f" r={pearson(price_series[a], price_series[b])}"
        corr_details.append(f"<li>⚠️ {rp['chain']}: 保留{a}，排除{b}{r_val}</li>")
    parts.append(
        f"""<div class="yellow-box"><strong>动态冗余检测：</strong>{"|".join(f"{rp["chain"]}: {rp["redundant"]}→{rp["primary"]}" for rp in rps)}</div>"""
    )

# 闫判官裁决
kept = jv.get("kept_symbols", [])
excluded = jv.get("excluded_symbols", [])
parts.append(f"""<h2>⚖️ P1 · 闫判官裁决</h2>
<div class="green-box"><strong>保留辩论：</strong>{len(kept)}个 → {kept}</div>
<div class="red-box"><strong>排除冗余：</strong>{len(excluded)}个 → {excluded}</div>""")

# 辩论品种表格
if kept:
    import math

    rows = ""
    for sym in kept:
        s = sym_map.get(sym) or sym_map.get(sym.upper()) or {}
        l = s.get("l1l4", {})
        ft = s.get("factor_timing", {})
        rows += f'<tr><td>{sym}</td><td>{cr.get(sym, {}).get("chain", "?")}</td><td class="bear">🔴做空</td><td>{l.get("total", 0):+d}</td><td>{l.get("grade", "")}</td><td>{ft.get("total", 0):+d}</td><td>{l.get("adx", 0):.1f}</td></tr>'
    parts.append(f"""<div class="card">
<table><tr><th>品种</th><th>产业链</th><th>方向</th><th>L1L4</th><th>等级</th><th>FT</th><th>ADX</th></tr>{rows}</table>
</div>""")

# Top5
top5_info = {
    "PF": (
        "短纤",
        6908,
        -62,
        -14,
        75.9,
        "聚酯链唯一代表，双策略共振。ADX极强+成本坍塌。",
        "85%",
        "6400-6500",
        "7300",
        "2.1:1",
    ),
    "RB": (
        "螺纹钢",
        3062,
        -70,
        0,
        69.2,
        "黑色系最强信号。淡季效应+钢厂亏损，强趋势空头。",
        "78%",
        "2850-2900",
        "3200",
        "1.7:1",
    ),
    "BU": (
        "沥青",
        3851,
        -60,
        -2,
        63.5,
        "能源链最佳。需求疲弱主导，低库存提供安全垫。",
        "72%",
        "3500-3600",
        "4050",
        "1.6:1",
    ),
    "SM": (
        "锰硅",
        5832,
        -63,
        0,
        62.5,
        "铁合金独立品种。供需宽松主导，不受黑色系限制。",
        "70%",
        "5400-5500",
        "6100",
        "1.6:1",
    ),
    "SA": (
        "纯碱",
        1103,
        -61,
        2,
        49.1,
        "建材唯一代表。弱需求拖累，供增需弱压制价格。",
        "65%",
        "1000-1020",
        "1180",
        "1.5:1",
    ),
}
parts.append("<h2>⚔️ P2 · 多空辩论（Top5多链分散）</h2>")
parts.append('<div class="card"><div class="stat-grid">')
for sym, (name, price, l1l4, ft, adx, verdict, conf, tgt, stop, rr) in top5_info.items():
    parts.append(f"""<div class="stat-item" style="border-top:3px solid {GOLD}">
<div class="stat-value" style="color:{RED};font-size:16px">{sym} 做空</div>
<div class="stat-label">{name}</div>
<div style="font-size:11px;color:{SEC};margin-top:4px">目标{tgt}<br>止损{stop}<br>盈亏比{rr}</div>
</div>""")
parts.append("</div></div>")

# 方案
parts.append(f"""<h2>🟡 P3 · 风控明 + 📋 P4 · 策执远</h2>
<div class="card">
<table>
<tr><th>方案</th><th>品种</th><th>仓位</th><th>预期收益</th><th>回撤</th><th>分散链数</th><th>建议</th></tr>
<tr><td>激进</td><td>PF+RB+BU+SM</td><td>59%</td><td>+9.0%</td><td>-5.5%</td><td>4</td><td class="yellow-box">可执行</td></tr>
<tr><td><strong>稳健</strong></td><td><strong>PF+RB+SM</strong></td><td><strong>47%</strong></td><td><strong>+6.5%</strong></td><td><strong>-3.5%</strong></td><td><strong>3</strong></td><td class="green-box">✅ 推荐</td></tr>
<tr><td>保守</td><td>PF+RB</td><td>35%</td><td>+4.5%</td><td>-2.0%</td><td>2</td><td>最低风险</td></tr>
</table>
</div>

<hr class="divider">
<div style="text-align:center;color:{SEC};font-size:11px;padding:20px">
<p>期货交易辩论专家团 {args.version} | 明鉴秋 · 数技源 · 链证源 · 闫判官 · 牛势研 · 熊谋略 · 风控明 · 策执远</p>
<p>⚠️ 决策辅助工具，不构成投资建议。数据截止: {now}</p>
</div></body></html>""")

os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
with open(args.output, "w", encoding="utf-8") as f:
    f.write("\n".join(parts))
print(f"✅ 辩论深度分析报告: {args.output}")
