#!/usr/bin/env python3
"""
组合回测引擎 v2.0 — 多品种并行持仓
======================================
- 多品种可同时持仓，单品最高25%，总仓位≤75%
- 退出条件: 2ATR跟踪止损 OR 价格破60MA OR RSI反穿50
- 支持有/无60MA入场过滤对比

用法:
  python portfolio_backtest.py --ma60-entry --output results_ma60
  python portfolio_backtest.py --output results_noma60
"""
import argparse
import json
import os
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

import pandas as pd
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy

ALL_SYMBOLS = [
    'A','B','M','Y','P','OI','RM','PK','C','CS','SR','CF','CY','JD','LH','AP','CJ','RR',
    'I','J','JM','RB','HC','SF','SM','SC','LU','FU','BU','PG','EC',
    'CU','AL','ZN','PB','NI','SN','AO','SS','AD','BC','AU','AG','PT',
    'LC','SI','PS','MA','SH','V','RU','NR','BR','PX','TA','PF','PR',
    'EG','EB','PP','L','PL','BZ','FG','SA','UR','SP','OP',
]


class PortfolioBacktest:

    def __init__(self):
        self.adapter = MultiSourceAdapter()

    def run(self, symbols=ALL_SYMBOLS, days=365, output_dir='.', **kwargs):
        config = {
            'position_max': 25, 'portfolio_max': 75, 'stop_atr': 2.0,
            'conf_threshold': 0, 'step': 1,
            'ma60_entry': False,  # 入场60MA过滤
            'ma60_exit': True,    # 破60MA出场
            'rsi50_exit': True,   # RSI反穿50出场
        }
        config.update(kwargs)
        os.makedirs(output_dir, exist_ok=True)

        print(f'\n加载{len(symbols)}品种数据 ({days}天)...')
        data_map = {}
        for sym in symbols:
            resp = self.adapter.get_kline(variety=sym, days=days)
            bars = resp.get('data', [])
            if len(bars) < 80:
                continue
            df = pd.DataFrame(bars)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            data_map[sym.lower()] = df

        print(f'有效品种: {len(data_map)}')

        # 统一时间轴
        min_start = max(df['date'].min() for df in data_map.values())
        max_end = min(df['date'].max() for df in data_map.values())
        all_dates = pd.date_range(start=min_start, end=max_end, freq='D')
        print(f'时间轴: {min_start.date()} ~ {max_end.date()} ({len(all_dates)}天)')

        positions = []
        trades_log = []
        cf = config
        step = cf['step']

        for idx in range(80, len(all_dates), step):
            curr_date = all_dates[idx]
            active = [p for p in positions if p['exit_date'] is None]
            total_exposure = sum(p['total_size'] for p in active)

            for sym, df in data_map.items():
                match = df[df['date'] <= curr_date]
                i = len(match) - 1
                if i < 80:
                    continue
                curr = df.iloc[i]
                curr_price = float(curr['close'])
                slice_df = df.iloc[:i+1].copy()

                try:
                    tech = _compute_indicators_numpy(slice_df)
                except Exception:
                    continue

                ma_slope = float(tech.get('MA20_SLOPE', 0))
                rsi = float(tech.get('RSI14', tech.get('rsi', 50)))
                dc_upper = float(tech.get('DC_UPPER', 0) or 0)
                dc_lower = float(tech.get('DC_LOWER', 0) or 0)
                atr = float(tech.get('ATR14', tech.get('atr', 0)))
                if atr == 0:
                    atr = float((slice_df['high']-slice_df['low']).rolling(14).mean().iloc[-1]) if len(slice_df)>=14 else curr_price*0.01

                ma60 = float(slice_df['close'].rolling(60).mean().iloc[-1]) if len(slice_df)>=60 else None

                # 方向
                direction = 'bull' if ma_slope > 5 else 'bear' if ma_slope < -5 else 'neutral'

                # 入场60MA过滤
                if cf['ma60_entry'] and ma60 is not None:
                    if direction == 'bull' and curr_price < ma60:
                        direction = 'neutral'
                    elif direction == 'bear' and curr_price > ma60:
                        direction = 'neutral'

                # 突破信号
                b_score = 0
                if dc_upper > 0 and dc_lower > 0 and (curr_price >= dc_upper or curr_price <= dc_lower):
                    b_score += 20
                    avg_v = slice_df['volume'].iloc[-20:].mean()
                    if float(curr['volume'])/avg_v > 1.5:
                        b_score += 15
                    bw = (dc_upper-dc_lower)/dc_lower*100
                    if bw > 5:
                        b_score += 10

                # === 持仓管理 ===
                for pos in [p for p in positions if p['symbol']==sym and p['exit_date'] is None]:
                    low = float(curr.get('low', curr_price))
                    high = float(curr.get('high', curr_price))
                    exit_reason = None

                    # 2ATR止损
                    if pos['direction'] == 'long':
                        pos['trailing_stop'] = max(pos['trailing_stop'], pos['avg_price']-cf['stop_atr']*pos['entry_atr'])
                        if low <= pos['trailing_stop']:
                            exit_reason = 'trailing_stop'
                    else:
                        pos['trailing_stop'] = min(pos['trailing_stop'], pos['avg_price']+cf['stop_atr']*pos['entry_atr'])
                        if high >= pos['trailing_stop']:
                            exit_reason = 'trailing_stop'

                    # 破MA60出场
                    if exit_reason is None and cf['ma60_exit'] and ma60 is not None:
                        if pos['direction']=='long' and curr_price<ma60:
                            exit_reason = 'ma60_cross'
                        elif pos['direction']=='short' and curr_price>ma60:
                            exit_reason = 'ma60_cross'

                    # RSI反穿50
                    if exit_reason is None and cf['rsi50_exit'] and rsi>0:
                        if pos['direction']=='long' and rsi<50:
                            exit_reason = 'rsi50_cross'
                        elif pos['direction']=='short' and rsi>50:
                            exit_reason = 'rsi50_cross'

                    if exit_reason:
                        pos['exit_price'] = curr_price
                        pos['exit_date'] = str(curr_date.date())
                        pos['exit_reason'] = exit_reason

                # === 开新仓 ===
                active = [p for p in positions if p['exit_date'] is None]
                total_exposure = sum(p['total_size'] for p in active)

                if b_score >= 25 and direction != 'neutral':
                    if not any(p['symbol']==sym and p['exit_date'] is None for p in positions):
                        size = cf['position_max']/100
                        max_add = cf['portfolio_max']/100 - total_exposure
                        size = min(size, max_add)
                        if size <= 0:
                            continue
                        pos = {
                            'symbol': sym, 'direction': 'long' if direction=='bull' else 'short',
                            'entry_price': curr_price, 'entry_date': str(curr_date.date()),
                            'avg_price': curr_price, 'total_size': size,
                            'entry_atr': atr,
                            'trailing_stop': curr_price-2*atr if direction=='bull' else curr_price+2*atr,
                            'exit_price': None, 'exit_date': None, 'exit_reason': None,
                        }
                        positions.append(pos)

        # === 计算统计 ===
        closed = [p for p in positions if p['exit_date'] is not None]
        sym_trades = {}
        for p in closed:
            s = p['symbol']; sym_trades.setdefault(s,[]).append(p)

        per_sym = {}
        total_pnl = 0
        for s, tlist in sym_trades.items():
            wins = [p for p in tlist if (p['direction']=='long' and p['exit_price']>p['avg_price']) or
                                          (p['direction']=='short' and p['exit_price']<p['avg_price'])]
            pnl = sum(((p['exit_price']-p['avg_price'])/p['avg_price']*p['total_size'])*(-1 if p['direction']=='short' else 1) for p in tlist)
            total_pnl += pnl
            per_sym[s] = {'trades': len(tlist), 'wins': len(wins),
                          'win_rate': len(wins)/len(tlist)*100 if tlist else 0,
                          'total_pnl': round(pnl*100,2)}

        overall_pnl = round(total_pnl*100, 2)

        summary = {
            'config': {k: v for k, v in cf.items() if isinstance(v, (int,float,bool,str))},
            'symbols_traded': len(per_sym), 'total_trades': len(closed),
            'total_wins': sum(v['wins'] for v in per_sym.values()),
            'win_rate': round(sum(v['wins'] for v in per_sym.values())/max(len(closed),1)*100, 1),
            'overall_pnl_pct': overall_pnl,
            'per_symbol': per_sym,
            'exit_reasons': {r:len([p for p in closed if p.get('exit_reason')==r]) for r in set(p.get('exit_reason','') for p in closed)},
        }

        print(f'\n结果: {summary["total_trades"]}笔 | 胜率{summary["win_rate"]}% | 总PnL {summary["overall_pnl_pct"]:+.2f}%')
        print('出场原因:', summary['exit_reasons'])

        # 保存
        with open(os.path.join(output_dir, 'portfolio_results.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # HTML
        rows = ''
        for s, r in sorted(per_sym.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            c = 'green' if r['total_pnl']>0 else 'red'
            rows += f'<tr><td>{s}</td><td>{r["trades"]}</td><td>{r["win_rate"]:.0f}%</td><td class="{c}">{r["total_pnl"]:+.2f}%</td></tr>'

        cfg = cf
        html = f'''<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><title>组合回测报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#0a0e1a;color:#e0e0e0;padding:20px}}
h1{{color:#f0b429}} table{{width:100%;border-collapse:collapse;margin:15px 0;font-size:12px}}
th{{background:#1a2040;color:#8890e0;padding:8px;text-align:left;border-bottom:2px solid #2a3050}}
td{{padding:6px;border-bottom:1px solid #1a2040}}
.green{{color:#4bc94b!important;font-weight:bold}} .red{{color:#ef4444!important}}
.card{{background:#11162a;border-radius:8px;padding:15px;margin:10px 0;border:1px solid #1e2340}}
</style></head><body>
<h1>组合回测报告</h1>
<p>{datetime.now().strftime("%Y-%m-%d %H:%M")} | 单品≤{cfg["position_max"]}% 总仓≤{cfg["portfolio_max"]}%</p>
<div class="card">
<p>总交易: {summary["total_trades"]}笔 | 胜率: <b>{summary["win_rate"]}%</b> | 总PnL: <b class="{"green" if overall_pnl>0 else "red"}">{overall_pnl:+.2f}%</b></p>
<p>出场原因: {json.dumps(summary.get("exit_reasons",{}), ensure_ascii=False)}</p>
</div>
<div class="card"><table><tr><th>品种</th><th>交易</th><th>胜率</th><th>PnL</th></tr>{rows}</table></div>
</body></html>'''
        with open(os.path.join(output_dir, 'portfolio_report.html'), 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'📁 {output_dir}')
        return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='组合回测')
    p.add_argument('--symbols', default=','.join(ALL_SYMBOLS))
    p.add_argument('--days', type=int, default=365)
    p.add_argument('--position-max', type=float, default=25)
    p.add_argument('--portfolio-max', type=float, default=75)
    p.add_argument('--stop-atr', type=float, default=2.0)
    p.add_argument('--step', type=int, default=1)
    p.add_argument('--ma60-entry', action='store_true', help='入场60MA过滤')
    p.add_argument('--output', default='results_portfolio')
    args = p.parse_args()

    bt = PortfolioBacktest()
    syms = [s.strip() for s in args.symbols.split(',') if s.strip()]
    bt.run(syms, days=args.days, output_dir=args.output,
           position_max=args.position_max, portfolio_max=args.portfolio_max,
           stop_atr=args.stop_atr, step=args.step,
           ma60_entry=args.ma60_entry)
