#!/usr/bin/env python3
"""
全品种趋势信号扫描 v2.18.0 — 方向感知Z-score
=================================================
独立调用：python scan_all.py [--output <dir>] [--prefix <name>] [--symbols <sym1,sym2,...>]

数据源：futures-data-search MultiSourceAdapter (通达信本地)
指标：commodity-trend-signal L1-L4 + scoring_system.py 统一评分
输出：JSON + HTML报表
v2.18.1: 新增 --symbols 参数支持自定义品种扫描，消除胶水脚本
"""
import sys, os, json, numpy as np, pandas as pd
from datetime import date

# ── 路径自举（quant-daily scripts/ 目录） ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

try:
    from indicators.core import assess_trend_maturity
    from indicators.indicators_legacy import _compute_indicators_numpy
    from indicators.tdx_bridge import get_bridge
    from signals.scoring_system import calculate_composite_score
    from config.symbols import ALL_SYMBOLS
except ImportError:
    from indicators.core import assess_trend_maturity
    from indicators.indicators_legacy import _compute_indicators_numpy
    from indicators.tdx_bridge import get_bridge
    from signals.scoring_system import calculate_composite_score
    from config.symbols import ALL_SYMBOLS
from data.multi_source_adapter import MultiSourceAdapter


def collect_kline_for_all(adapter, symbols, days=120, min_bars=50, today_str=None):
    """通用K线数据采集，供 scan_all.py 和 full_scan_debate.py 共享。"""
    from datetime import date
    if today_str is None:
        today_str = date.today().strftime('%Y%m%d')
    kline_data = {}
    for i, (sym, name) in enumerate(symbols):
        try:
            resp = adapter.get_kline(variety=sym, days=days)
            if isinstance(resp, dict) and resp.get('success'):
                dlist = resp['data']
                valid = [r for r in dlist if r.get('date','') and r.get('volume',0) > 0
                         and r['date'] <= today_str]
                if len(valid) >= min_bars:
                    kline_data[sym] = (name, valid)
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f'  [{i+1}/{len(symbols)}] {len(kline_data)} OK')
    return kline_data


def run_scan(output_dir: str = None, output_prefix: str = "full_scan",
             symbols: list = None) -> dict:
    """执行品种信号扫描，返回结果字典。

    参数:
        output_dir: 输出目录（可选）
        output_prefix: 文件名前缀
        symbols: 指定品种列表，格式 [(sym, name), ...]。None=全品种
    """
    today = date.today()
    today_str = today.strftime('%Y%m%d')

    print(f"{'='*60}")
    mode = "自定义品种" if symbols else "全品种"
    print(f"{mode}趋势信号扫描 v2.18.0 — 方向感知Z-score — {today}")
    print(f"{'='*60}")

    # ── TQ-Local 检测 ──
    bridge = get_bridge()
    tdx_ok = bridge.available
    print(f"\nTQ-Local: {'✅ 可用' if tdx_ok else '⚠️ 不可用→numpy兜底'}")

    # ── 确定品种列表 ──
    target_symbols = symbols if symbols else ALL_SYMBOLS
    print(f"  品种数: {len(target_symbols)}")

    # ── Step 1: 数据采集 ──
    print('\n[1] 数据采集（通达信本地 → MultiSourceAdapter）...')
    adapter = MultiSourceAdapter()
    kline_data = collect_kline_for_all(adapter, target_symbols, days=120, min_bars=50)
    print(f'  成功: {len(kline_data)}/{len(target_symbols)}')

    # ── Step 2: 指标 + L1-L4（使用 scoring_system.py 完整版评分）──
    print('\n[2] 指标计算 + L1-L4评分（scoring_system.py 完整版）...')

    results = []
    for i, (sym, name) in enumerate(target_symbols):
        if sym not in kline_data: continue
        try:
            _, dlist = kline_data[sym]
            df = pd.DataFrame({k: [float(r[k]) for r in dlist] for k in ['open', 'high', 'low', 'close']})
            df['volume'] = [float(r.get('volume', 0)) for r in dlist]
            tech = _compute_indicators_numpy(df, sym)
            price = tech.get('last_price', float(df['close'].iloc[-1]))
            prev = float(df['close'].iloc[-2]) if len(df) > 1 else price
            tech['price'] = price
            tech['change_pct'] = (price / prev - 1) * 100

            # 完整版评分：7+子信号 L1 + 方向投票 + 趋势成熟度
            sym_scoring = {'last_price': price, 'open_interest': tech.get('open_interest', 0)}
            kline_closes = df['close'].tolist()
            sc = calculate_composite_score(tech, sym_scoring, 0, kline_closes, None)

            direction = 'bull' if sc['direction'] == 'BUY' else ('bear' if sc['direction'] == 'SELL' else 'neutral')
            s = 1 if direction == 'bull' else (-1 if direction == 'bear' else 0)
            stage = sc['maturity']['stage']

            results.append(dict(
                symbol=sym, name=name, price=round(price, 1),
                change_pct=round(tech.get('change_pct', 0), 2),
                volume=int(round(float(df['volume'].iloc[-1]))) if not df['volume'].empty else 0,
                total=sc['total'] * s, abs=sc['total'],
                l1=sc['L1_score'] * s, l2=sc['L2_score'] * s,
                l3=sc['L3_score'] * s, l4=sc['L4_score'] * s,
                veto=sc['veto_score'],
                direction=direction, grade=sc['grade'],
                adx=round(tech.get('ADX', 0), 1), rsi=round(tech.get('RSI14', 0), 1),
                cci=round(tech.get('CCI20', 0), 1), ma_slope=round(tech.get('MA20_SLOPE', 0), 2),
                macd_cross=tech.get('macd_cross', 'none'), dc20_break=tech.get('dc20_break', 'none'),
                ma_align=tech.get('ma_align', 'mixed'),
                _tdx_patched=tech.get('_tdx_patched', False),
                stage=stage,
            ))
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f'  [{i+1}] {len(results)} OK')

    all_ranked = sorted(results, key=lambda x: x['abs'], reverse=True)

    # v2.18: 方向感知 Z-score（修复：失衡分布下多头Z虚高问题）
    # 当 55/61 品种为空头时，全局均值严重偏负，多头品种的 Z 值因稀缺性而非统计学意义被夸大
    # 修复：多头只与多头比，空头只与空头比
    from statistics import mean, stdev
    totals = [r['total'] for r in results]
    mu, sigma = mean(totals), stdev(totals) if len(totals) > 1 else 1
    bear_totals = [r['total'] for r in results if r['total'] < 0]
    bull_totals = [r['total'] for r in results if r['total'] > 0]
    mu_bear, sigma_bear = (mean(bear_totals), stdev(bear_totals)) if len(bear_totals) > 1 else (None, None)
    mu_bull, sigma_bull = (mean(bull_totals), stdev(bull_totals)) if len(bull_totals) > 1 else (None, None)
    for r in results:
        if r['direction'] == 'bear' and sigma_bear and sigma_bear > 0:
            r['z_score'] = round((r['total'] - mu_bear) / sigma_bear, 2)
        elif r['direction'] == 'bull' and sigma_bull and sigma_bull > 0:
            r['z_score'] = round((r['total'] - mu_bull) / sigma_bull, 2)
        else:
            r['z_score'] = 0.0
        layers = [r['l1'], r['l2'], r['l3'], r['l4']]
        cons = sum(1 for l in layers if (l > 0 and r['total'] > 0) or (l < 0 and r['total'] < 0))
        r['cons'] = cons
    bull = [r for r in all_ranked if r['direction'] == 'bull']
    bear = [r for r in all_ranked if r['direction'] == 'bear']
    tdx_ct = sum(1 for r in all_ranked if r.get('_tdx_patched'))

    summary = {
        '_meta': {'date': today_str, 'total': len(results), 'bull': len(bull), 'bear': len(bear),
                  'tdx_patched_count': tdx_ct, 'source': '通达信本地→MultiSourceAdapter',
                  'indicators': 'TQ-Local bridge v2.18.0 (18组formula_zb/44项指标)',
                  'z_mode': 'directional',  # v2.18: 方向感知 Z-score，多头/空头各自独立计算
                  'z_mu': round(mu, 1), 'z_sigma': round(sigma, 1),
                  'z_mu_bear': round(mu_bear, 1) if mu_bear is not None else None,
                  'z_sigma_bear': round(sigma_bear, 1) if sigma_bear is not None else None,
                  'z_mu_bull': round(mu_bull, 1) if mu_bull is not None else None,
                  'z_sigma_bull': round(sigma_bull, 1) if sigma_bull is not None else None,
                  },
        'bull_signals': bull, 'bear_signals': bear, 'all_ranked': all_ranked,
    }

    print(f'\n完成: {len(results)}品种 | 空头{len(bear)} 多头{len(bull)} | TDX桥接{tdx_ct}')

    # ── 终端表格 ──
    print(f'\n{"#":>3} {"品种":<8} {"方向":<6} {"价格":>8} {"涨跌":>6} {"总分":>5} {"L1":>4} {"L2":>4} {"L3":>4} {"L4":>4} {"否决":>4} {"ADX":>5} {"RSI":>5} {"Z":>5} {"CONS":>4} {"阶段":>8} {"等级":>6} {"源":>4}')
    print('-' * 115)
    for i, r in enumerate(all_ranked):
        d = '多头' if r['direction'] == 'bull' else ('空头' if r['direction'] == 'bear' else '中性')
        src = 'TDX' if r.get('_tdx_patched') else 'NP'
        print(f'{i+1:>3} {r['symbol']:<8} {d:<6} {r['price']:>8.0f} {r['change_pct']:>+5.1f}% {r['total']:>+4.0f} {r['l1']:>+3} {r['l2']:>+3} {r['l3']:>+3} {r['l4']:>+3} {r['veto']:>+3} {r['adx']:>5.1f} {r['rsi']:>5.1f} {r['z_score']:>5.1f} {r['cons']:>3.0f}/4 {r.get('stage','?'):>8} {r['grade']:>6} {src:>4}')

    # ── 写入文件（如指定output_dir） ──
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f'{output_prefix}_{today_str}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f'\n📊 JSON: {json_path}')

        # HTML — 交互式排序表格
        import json as _json
        rows_json = _json.dumps([{
            'i': i+1, 'sym': r['symbol'], 'name': r['name'],
            'dir': r['direction'], 'price': r['price'], 'chg': r['change_pct'],
            'total': r['total'], 'l1': r['l1'], 'l2': r['l2'], 'l3': r['l3'], 'l4': r['l4'],
            'veto': r['veto'], 'adx': r['adx'], 'rsi': r['rsi'], 'z': r['z_score'],
            'cons': r['cons'], 'stage': r.get('stage','?'), 'grade': r['grade'],
            'tdx': r.get('_tdx_patched', False),
        } for r in all_ranked], ensure_ascii=False)

        b, bl_sig = len(bear), len(bull)
        n_neutral = len(results) - b - bl_sig
        tdx_pct = tdx_ct / len(results) * 100 if results else 0

        # 构建 HTML（用三引号避免 JS 模板字面量冲突）
        html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>全品种信号 — {today} (v2.18.0)</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #2a2d3a}}
.hd h1{{font-size:22px;color:#f59e0b}} .hd .m{{color:#9ca3af;font-size:12px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px}}
.st{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700}} .sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
.sc.b .n{{color:#ef4444}} .sc.bl .n{{color:#22c55e}} .sc.n .n{{color:#9ca3af}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:13px}}
thead{{background:#252940}}
th{{padding:9px 10px;text-align:left;font-weight:600;color:#9ca3af;font-size:11px;letter-spacing:.5px;white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#f59e0b}} th.asc::after{{content:" \\25B2";font-size:10px}} th.dsc::after{{content:" \\25BC";font-size:10px}}
td{{padding:7px 10px;border-top:1px solid #2a2d3a20;white-space:nowrap}} tr:hover{{background:#f59e0b08!important}}
.fb{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}
.fb button{{background:#252940;border:1px solid #2a2d3a;color:#9ca3af;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s}}
.fb button:hover{{border-color:#f59e0b;color:#e5e7eb}} .fb button.act{{background:#f59e0b20;border-color:#f59e0b;color:#f59e0b;font-weight:600}}
#si{{color:#6b7280;font-size:12px;margin-left:12px}}
</style>
</head><body>
<div class="hd"><h1>全品种趋势信号强度排序 (v2.18.0)</h1>
<div class="m"><span>{today}</span><span>{len(results)}品种</span><span>TQ-Local桥接 + numpy兜底</span><span><span style="color:#f59e0b">点击列头排序</span> | L1-L4四层打分</span></div></div>
<div class="st"><div class="sc b"><div class="n">{b}</div><div class="l">空头</div></div><div class="sc bl"><div class="n">{bl_sig}</div><div class="l">多头</div></div><div class="sc n"><div class="n">{n_neutral}</div><div class="l">中性</div></div></div>

<div class="fb">
<button onclick="filterTable('all')" class="act" id="fa">全部</button>
<button onclick="filterTable('bear')" id="fbear">仅空头</button>
<button onclick="filterTable('bull')" id="fbull">仅多头</button>
<button onclick="filterTable('STRONG')" id="fSTRONG">STRONG</button>
<button onclick="filterTable('WATCH')" id="fWATCH">WATCH</button>
<button onclick="filterTable('WEAK')" id="fWEAK">WEAK</button>
<button onclick="filterTable('NOISE')" id="fNOISE">NOISE</button>
<span id="si">点击列头按该列排序，再次点击切换升降序</span>
</div>

<table id="tbl"><thead><tr>
<th onclick="sortBy(0)" data-num="1">#</th>
<th onclick="sortBy(1)">品种</th>
<th onclick="sortBy(2)">名称</th>
<th onclick="sortBy(3)">方向</th>
<th onclick="sortBy(4)" data-num="1" style="text-align:right">价格</th>
<th onclick="sortBy(5)" data-num="1" style="text-align:right">涨跌</th>
<th onclick="sortBy(6)" data-num="1" style="text-align:center">总分</th>
<th onclick="sortBy(7)" data-num="1" style="text-align:center">L1</th>
<th onclick="sortBy(8)" data-num="1" style="text-align:center">L2</th>
<th onclick="sortBy(9)" data-num="1" style="text-align:center">L3</th>
<th onclick="sortBy(10)" data-num="1" style="text-align:center">L4</th>
<th onclick="sortBy(11)" data-num="1" style="text-align:center">否决</th>
<th onclick="sortBy(12)" data-num="1" style="text-align:center">ADX</th>
<th onclick="sortBy(13)" data-num="1" style="text-align:center">RSI</th>
<th onclick="sortBy(14)" data-num="1" style="text-align:center">Z</th>
<th onclick="sortBy(15)" data-num="1" style="text-align:center">CONS</th>
<th onclick="sortBy(16)">阶段</th>
<th onclick="sortBy(17)">等级</th>
<th>指标源</th>
</tr></thead><tbody id="tb"></tbody></table>

<div style="margin-top:24px;display:flex;gap:14px">
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #f59e0b30">
<span style="color:#f59e0b;font-weight:600">指标来源: </span><span style="color:#f59e0b">TQ-Local formula_zb ({tdx_ct}/{len(results)}品种, {tdx_pct:.0f}%)</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">ADX/RSI/CCI/MACD/MA/BOLL/OBV 来自通达信实盘公式</p></div>
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">
<span style="color:#22c55e;font-weight:600">数据: </span><span style="color:#e5e7eb">通达信本地 → MultiSourceAdapter</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">commodity-trend-signal v2.18.0 | {today} | 方向感知Z-score</p></div></div>

<div style="margin-top:14px;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">

<div style="color:#f59e0b;font-weight:600;font-size:13px;margin-bottom:6px">使用方法 & 栏位说明</div>
<div style="margin-top:10px;font-size:12px;line-height:1.7">
<p style="color:#e5e7eb;font-weight:600">使用方法</p>
<p style="color:#9ca3af">- 总分降序，绝对值越大信号越强。多头(红)只做多、空头(绿)只做空<br>
- <b>等级</b>: <span style="color:#22c55e">STRONG</span> &ge;75(最强) / <span style="color:#f59e0b">WATCH</span> &ge;60(重点) / <span style="color:#ef4444">WEAK</span> &ge;40(可观察) / <span style="color:#6b7280">NOISE</span> &lt;40(忽略)<br>
- <b>趋势阶段</b>: <span style="color:#22c55e">launch</span> 刚启动 / <span style="color:#3b82f6">trending</span> 主趋势运行 / <span style="color:#f59e0b">exhausted</span> 衰竭中 / <span style="color:#ef4444">reversal</span> 反转中<br>
- <b>Z</b>: 方向感知Z-score，绝对值&gt;|1.5|为同方向统计显著</p>

<p style="color:#e5e7eb;font-weight:600;margin-top:10px">Z值解读（方向感知模式）</p>
<p style="color:#9ca3af">Z值反映品种在<b>同方向内部</b>的偏离程度——<b>不是信号强度本身</b>。理解关键在于方向+符号的组合：</p>
<table style="width:100%;border-collapse:collapse;font-size:11px">
<tr style="background:#252940"><th style="padding:4px 8px;text-align:left;color:#9ca3af">品种示例</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">方向</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">总分</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">Z</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">含义</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">操作参考</th></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px">hc 热卷</td><td style="padding:3px 8px"><span style="color:#ef4444">空头</span></td><td style="padding:3px 8px;color:#ef4444">-76</td><td style="padding:3px 8px;color:#22c55e">-1.8</td><td style="padding:3px 8px;color:#9ca3af">比平均空头更强</td><td style="padding:3px 8px;color:#22c55e">✅ 强空头，可信度高</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px">zn 沪锌</td><td style="padding:3px 8px"><span style="color:#ef4444">空头</span></td><td style="padding:3px 8px;color:#ef4444">-39</td><td style="padding:3px 8px;color:#ef4444">+2.5</td><td style="padding:3px 8px;color:#9ca3af">比平均空头弱很多</td><td style="padding:3px 8px;color:#f59e0b">⚠️ 边缘空头，接近中性</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px">b 豆二</td><td style="padding:3px 8px"><span style="color:#22c55e">多头</span></td><td style="padding:3px 8px;color:#22c55e">+76</td><td style="padding:3px 8px;color:#22c55e">+1.3</td><td style="padding:3px 8px;color:#9ca3af">比平均多头更强</td><td style="padding:3px 8px;color:#22c55e">✅ 强多头，可信度高</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px">AP 苹果</td><td style="padding:3px 8px"><span style="color:#22c55e">多头</span></td><td style="padding:3px 8px;color:#22c55e">+51</td><td style="padding:3px 8px;color:#ef4444">-0.9</td><td style="padding:3px 8px;color:#9ca3af">比平均多头更弱</td><td style="padding:3px 8px;color:#f59e0b">⚠️ 弱多头，需谨慎</td></tr>
</table>
<p style="color:#9ca3af;margin-top:6px">核心口诀：<b>空头Z负→更强空头，空头Z正→偏弱空头；多头Z正→更强多头，多头Z负→偏弱多头</b>。<br>|Z|越大的品种在同方向内越极端，但一定要结合方向判断。|Z|&gt;1.5 在同方向内统计显著。</p>

<p style="color:#e5e7eb;font-weight:600;margin-top:10px">排序方法</p>
<p style="color:#9ca3af">- 点击任意列头按该列排序，再次点击切换升降序<br>
- 筛选按钮可只看空头/多头或特定等级<br>
- 默认排序：总分降序（按绝对值）</p>

<p style="color:#e5e7eb;font-weight:600;margin-top:10px">趋势阶段含义</p>
<table style="width:100%;border-collapse:collapse;font-size:11px">
<tr style="background:#252940"><th style="padding:4px 8px;text-align:left;color:#9ca3af">阶段</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">判断依据</th><th style="padding:4px 8px;text-align:left;color:#9ca3af">操作建议</th></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#22c55e">launch</td><td style="padding:3px 8px;color:#9ca3af">突破DC20通道+Boll收口或DC55同向拐头</td><td style="padding:3px 8px;color:#6b7280">早期布局，空间最大，但需确认信号强度</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#3b82f6">trending</td><td style="padding:3px 8px;color:#9ca3af">DC20通道上半区运行或ADX&ge;25</td><td style="padding:3px 8px;color:#6b7280">趋势确认，顺势持有，核心持仓区</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#f59e0b">exhausted</td><td style="padding:3px 8px;color:#9ca3af">DC20通道极值+RSI极端(多头>75/空头<25)</td><td style="padding:3px 8px;color:#6b7280">趋势末端，减仓或设紧止损。ADX>60时衰竭信号更强</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#ef4444">reversal</td><td style="padding:3px 8px;color:#9ca3af">价格穿越DC55中轨反方向+ADX<35</td><td style="padding:3px 8px;color:#6b7280">方向可能转变，平仓观望。ADX越低反转信号越可信</td></tr>
</table>

<p style="color:#e5e7eb;font-weight:600;margin-top:10px">栏位计算方法</p>
<table style="width:100%;border-collapse:collapse;font-size:11px"><tr style="background:#252940"><th>栏位<th>说明<th>范围</tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">总分</td><td style="padding:3px 8px;color:#9ca3af">L1+L2+L3+L4+否决</td><td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L1</td><td style="padding:3px 8px;color:#9ca3af">OI/基差/期限/ROC/斜率/HL</td><td style="padding:3px 8px;color:#6b7280">-40~+40</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L2</td><td style="padding:3px 8px;color:#9ca3af">Vortex/CCI/Supertrend/HMA</td><td style="padding:3px 8px;color:#6b7280">-25~+25</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L3</td><td style="padding:3px 8px;color:#9ca3af">RSI健康区/DMI方向/前高前低</td><td style="padding:3px 8px;color:#6b7280">-25~+25</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L4</td><td style="padding:3px 8px;color:#9ca3af">通道突破/均线排列/MACD/DC55</td><td style="padding:3px 8px;color:#6b7280">-10~+10</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">否决</td><td style="padding:3px 8px;color:#9ca3af">ADX/RSI/CCI极端+缩量+偏离</td><td style="padding:3px 8px;color:#6b7280">-20~0</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">ADX</td><td style="padding:3px 8px;color:#9ca3af">趋势强度 Wilder平滑</td><td style="padding:3px 8px;color:#6b7280">大于25</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">RSI</td><td style="padding:3px 8px;color:#9ca3af">14日相对强弱指数</td><td style="padding:3px 8px;color:#6b7280">大于80 小于20</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">Z</td><td style="padding:3px 8px;color:#9ca3af">方向感知Z-score，多头/空头各自独立计算。<br>空头Z负=强空头，空头Z正=弱空头；<br>多头Z正=强多头，多头Z负=弱多头</td><td style="padding:3px 8px;color:#6b7280">理论无界</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">CONS</td><td style="padding:3px 8px;color:#9ca3af">四层方向一致数</td><td style="padding:3px 8px;color:#6b7280">0-4/4</td></tr></table></div></div>

<script>
var DATA = {rows_json};

function _gc(g) {{
    if (g==='STRONG') return '#22c55e';
    if (g==='WATCH') return '#f59e0b';
    if (g==='WEAK') return '#ef4444';
    return '#6b7280';
}}
function _gc_bg(g) {{
    if (g==='STRONG') return '#22c55e20';
    if (g==='WATCH') return '#f59e0b20';
    if (g==='WEAK') return '#ef444420';
    return '#ffffff08';
}}

var _filter = 'all';
var _sortCol = -1;
var _sortAsc = true;

function render() {{
    var data = DATA.slice();
    if (_filter === 'bear') data = data.filter(function(d){{ return d.dir === 'bear'; }});
    else if (_filter === 'bull') data = data.filter(function(d){{ return d.dir === 'bull'; }});
    else if (_filter !== 'all') data = data.filter(function(d){{ return d.grade === _filter; }});

    if (_sortCol >= 0) {{
        var asc = _sortAsc;
        data.sort(function(a,b){{
            var va = _val(a,_sortCol), vb = _val(b,_sortCol);
            if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            return asc ? (va - vb) : (vb - va);
        }});
    }}

    var h = '';
    for (var i=0;i<data.length;i++) {{
        var d = data[i];
        var dt = d.dir==='bull' ? '<span style="color:#22c55e">多头</span>' : (d.dir==='bear' ? '<span style="color:#ef4444">空头</span>' : '<span style="color:#9ca3af">中性</span>');
        var cc = d.chg>0?'#22c55e':(d.chg<0?'#ef4444':'#9ca3af');
        var tc = d.total>0?'#22c55e':(d.total<0?'#ef4444':'#9ca3af');
        var src = d.tdx ? '<span style="display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;background:#f59e0b20;color:#f59e0b">通达信</span>' : '<span style="display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;background:#6b728020;color:#9ca3af">numpy</span>';
        var bg = _gc_bg(d.grade);
        var gc = _gc(d.grade);
        h += '<tr style="background:'+bg+'">';
        h += '<td style="text-align:center;color:#9ca3af">'+(i+1)+'</td>';
        h += '<td style="font-weight:700">'+d.sym+'</td><td>'+d.name+'</td><td>'+dt+'</td>';
        h += '<td style="text-align:right">'+d.price.toFixed(0)+'</td><td style="text-align:right;color:'+cc+'">'+(d.chg>0?'+':'')+d.chg.toFixed(1)+'%</td>';
        h += '<td style="text-align:center;font-weight:700;color:'+tc+'">'+(d.total>0?'+':'')+d.total+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l1>0?'+':'')+d.l1+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l2>0?'+':'')+d.l2+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l3>0?'+':'')+d.l3+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l4>0?'+':'')+d.l4+'</td>';
        h += '<td style="text-align:center;color:#ef4444">'+(d.veto>0?'+':'')+d.veto+'</td>';
        h += '<td style="text-align:center">'+d.adx.toFixed(1)+'</td><td style="text-align:center">'+d.rsi.toFixed(1)+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.z>0?'+':'')+d.z.toFixed(1)+'</td>';
        h += '<td style="text-align:center;color:#f59e0b">'+d.cons+'/4</td>';
        h += '<td style="text-align:center;color:#9ca3af;font-size:11px">'+d.stage+'</td>';
        h += '<td style="text-align:center"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:'+gc+'20;color:'+gc+'">'+d.grade+'</span></td>';
        h += '<td style="text-align:center">'+src+'</td></tr>';
    }}
    document.getElementById('tb').innerHTML = h;
}}

function _val(d,col) {{
    var a = [d.i, d.sym, d.name, d.dir, d.price, d.chg, d.total, d.l1, d.l2, d.l3, d.l4,
             d.veto, d.adx, d.rsi, d.z, d.cons, d.stage, d.grade];
    return a[col];
}}

function sortBy(col) {{
    if (_sortCol === col) {{ _sortAsc = !_sortAsc; }}
    else {{ _sortCol = col; _sortAsc = col===0 ? true : false; }}
    var ths = document.querySelectorAll('#tbl th');
    for (var i=0;i<ths.length;i++) ths[i].className = '';
    var el = ths[col];
    if (el) el.className = _sortAsc ? 'asc' : 'dsc';
    render();
}}

function filterTable(f) {{
    _filter = f;
    var btns = document.querySelectorAll('.fb button');
    for (var i=0;i<btns.length;i++) btns[i].className = '';
    var el = document.getElementById('f'+f);
    if (el) el.className = 'act';
    render();
}}

render();
</script>
</body></html>'''
        html_path = os.path.join(output_dir, f'{output_prefix}_ranking_{today_str}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅ HTML: {html_path} ({os.path.getsize(html_path)} bytes)')

    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='品种趋势信号扫描 v2.18.1')
    parser.add_argument('--output', '-o', help='输出目录', default=None)
    parser.add_argument('--prefix', '-p', help='文件名前缀', default='full_scan')
    parser.add_argument('--symbols', '-s', help='指定品种代码（逗号分隔），如 "PK,RB,B,UR"。不传则全品种。', default=None)
    args = parser.parse_args()

    # 解析自定义品种列表
    if args.symbols:
        # 从 ALL_SYMBOLS 构建代码→名称映射
        sym_map = {sym: name for sym, name in ALL_SYMBOLS}
        codes = [s.strip().upper() for s in args.symbols.split(',')]
        custom_symbols = [(s, sym_map.get(s, s)) for s in codes]
        print(f'自定义品种扫描: {[(s,n) for s,n in custom_symbols]}')
    else:
        custom_symbols = None

    OUT = args.output
    if not OUT:
        # 默认输出到工作空间 Reports 目录
        workspace = r'C:\Users\yangd\Documents\WorkBuddy'
        OUT = os.path.join(workspace, 'Commodities', 'Reports', '商品期货深度分析',
                          date.today().strftime('%Y-%m-%d'))

    run_scan(output_dir=OUT, output_prefix=args.prefix, symbols=custom_symbols)
