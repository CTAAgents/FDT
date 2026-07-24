#!/usr/bin/env python3
"""
三类信号策略回测 v1.0
============================
策略规则：
- 三类信号（gap/breakout/pullback）置信度超过阈值时开仓
- 金字塔加仓：每N个ATR加一次，最多M次，每次为前次的K%
- 退出条件：动量衰退（信号反向） OR N×ATR移动跟踪止损
- 所有参数可配置，不硬编码

用法：
  python -m scripts.backtest.three_signal_backtest --conf 50 --position 15 --stop-atr 2.0
"""
import argparse
import json
import os
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

import pandas as pd
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy


class ThreeSignalBacktest:

    def __init__(self):
        self.adapter = MultiSourceAdapter()

    def run(self, symbols, days=365, output_dir='.', **kwargs):
        """运行回测
        参数:
            conf_threshold: 开仓置信度阈值(%)，默认60
            position_pct: 每品种仓位(%)，默认15
            pyramid_atr: 加仓间隔(ATR倍数)，默认1.0
            pyramid_max: 最多加仓次数，默认3
            pyramid_ratio: 加仓比例，默认0.5
            stop_atr: 跟踪止损ATR倍数，默认2.0
            step: 采样间隔(K线)，默认10
        """
        config = {
            'conf_threshold': 60, 'position_pct': 15,
            'pyramid_atr': 1.0, 'pyramid_max': 3, 'pyramid_ratio': 0.5,
            'stop_atr': 2.0, 'step': 10, 'signal_filter': 'all',  # all/gap/breakout/pullback
            'ma60_filter': False,  # 60日均线多空过滤
        }
        config.update(kwargs)

        results = {}
        for sym in symbols:
            result = self._backtest_single(sym, days, config)
            results[sym] = result
            r = result
            print(f'  {sym}: {r["trades"]}笔 胜率{r["win_rate"]:.1f}% CR={r["cr"]:+.2f}%')
        return self._aggregate(results, output_dir, config)

    def _backtest_single(self, sym, days, cfg):
        resp = self.adapter.get_kline(variety=sym, days=days)
        all_bars = resp.get('data', [])
        if len(all_bars) < 80:
            return {'trades': 0, 'win_rate': 0, 'cr': 0, 'error': '数据不足'}

        df = pd.DataFrame(all_bars)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        positions = []

        for i in range(80, len(df), cfg['step']):
            slice_df = df.iloc[:i+1].copy()
            if len(slice_df) < 80:
                continue

            curr = df.iloc[i]
            curr_price = float(curr['close'])
            curr_date = curr['date']

            try:
                tech = _compute_indicators_numpy(slice_df)
            except Exception:
                continue

            rsi = float(tech.get('RSI14', tech.get('rsi', 0)))
            ma_slope = float(tech.get('MA20_SLOPE', tech.get('ma_slope', 0)))
            dc20_break = tech.get('dc20_break', 'none')
            ma_align = tech.get('ma_align', 'mixed')

            atr = float(tech.get('ATR14', tech.get('atr', 0)))
            if atr == 0:
                atr = float((slice_df['high'] - slice_df['low']).rolling(14).mean().iloc[-1]) if len(slice_df) >= 14 else 0

            # 三类信号检测
            b_score = 0
            dc_upper = float(tech.get('DC_UPPER', 0) or 0)
            dc_lower = float(tech.get('DC_LOWER', 0) or 0)
            if dc_upper > 0 and dc_lower > 0:
                if curr_price >= dc_upper or curr_price <= dc_lower:
                    b_score += 20
                    avg_vol_20 = slice_df['volume'].iloc[-20:].mean()
                    if float(curr['volume']) / avg_vol_20 > 1.5:
                        b_score += 15
                    dc_bandwidth = (dc_upper - dc_lower) / (dc_lower or 1) * 100
                    if dc_bandwidth > 5:
                        b_score += 10

            pb_score = 0
            trend_up = ma_align == 'bullish' or ma_slope > 0
            if trend_up and len(slice_df) >= 20:
                ma20 = slice_df['close'].iloc[-20:].mean()
                dist = abs(curr_price - ma20) / (ma20 or 1) * 100
                if dist < 1.5:
                    pb_score += 20
                    avg_vol_20 = slice_df['volume'].iloc[-20:].mean()
                    if float(curr['volume']) / avg_vol_20 < 0.8:
                        pb_score += 15
                    if curr_price > slice_df['low'].iloc[-5:].min() * 1.005:
                        pb_score += 10
                if 30 <= rsi <= 70:
                    pb_score += 5

            g_score = 0
            if len(slice_df) >= 2:
                prev_close = float(slice_df['close'].iloc[-2])
                curr_open = float(slice_df['open'].iloc[-1])
                gap_pct = (curr_open - prev_close) / (prev_close or 1) * 100
                if abs(gap_pct) > 0.5:
                    g_score += 20
                    avg_vol_5 = slice_df['volume'].iloc[-5:].mean()
                    if float(curr['volume']) / avg_vol_5 > 1.3:
                        g_score += 15
                    if gap_pct > 0 and float(slice_df['low'].iloc[-1]) > prev_close:
                        g_score += 10
                    elif gap_pct < 0 and float(slice_df['high'].iloc[-1]) < prev_close:
                        g_score += 10

            direction = 'bull' if ma_slope > 5 else 'bear' if ma_slope < -5 else 'neutral'

            # 60日均线过滤
            ma60_enabled = cfg.get('ma60_filter', False)
            if ma60_enabled and len(slice_df) >= 60:
                from pandas import Series
                ma60 = Series(slice_df['close']).rolling(60).mean().iloc[-1]
                if not pd.isna(ma60):
                    # 只在60MA上方做多，60MA下方做空
                    if curr_price < ma60 and direction == 'bull':
                        direction = 'neutral'
                    elif curr_price > ma60 and direction == 'bear':
                        direction = 'neutral'

            abs_score = abs(b_score + pb_score + g_score)
            confidence = min(abs_score, 100)

            signal_type = 'none'
            if g_score >= 30: signal_type = 'gap'
            elif b_score >= 25: signal_type = 'breakout'
            elif pb_score >= 25: signal_type = 'pullback'

            active = [p for p in positions if p['exit_date'] is None]

            # 持仓管理：止损 + 动量退出
            for pos in list(active):
                low = float(curr.get('low', curr_price))
                high = float(curr.get('high', curr_price))
                if pos['direction'] == 'long':
                    pos['trailing_stop'] = max(pos['trailing_stop'], pos['avg_price'] - cfg['stop_atr'] * pos['entry_atr'])
                    if low <= pos['trailing_stop']:
                        pos['exit_price'] = pos['trailing_stop']
                        pos['exit_date'] = curr_date
                        pos['exit_reason'] = 'trailing_stop'
                    elif direction == 'bear':
                        pos['exit_price'] = curr_price
                        pos['exit_date'] = curr_date
                        pos['exit_reason'] = 'momentum_decay'
                else:
                    pos['trailing_stop'] = min(pos['trailing_stop'], pos['avg_price'] + cfg['stop_atr'] * pos['entry_atr'])
                    if high >= pos['trailing_stop']:
                        pos['exit_price'] = pos['trailing_stop']
                        pos['exit_date'] = curr_date
                        pos['exit_reason'] = 'trailing_stop'
                    elif direction == 'bull':
                        pos['exit_price'] = curr_price
                        pos['exit_date'] = curr_date
                        pos['exit_reason'] = 'momentum_decay'

            active = [p for p in positions if p['exit_date'] is None]

            # 开新仓
            sf = cfg.get('signal_filter', 'all')
            if confidence >= cfg['conf_threshold'] and signal_type != 'none' and direction != 'neutral':
                if sf != 'all' and signal_type != sf:
                    pass  # 信号类型不匹配，不交易
                elif not any(p['direction'] == ('long' if direction == 'bull' else 'short') for p in active):
                    pct = cfg['position_pct']
                    dir_long = direction == 'bull'
                    pos = {
                        'symbol': sym, 'direction': 'long' if dir_long else 'short',
                        'entry_price': curr_price, 'entry_date': str(curr_date)[:10],
                        'avg_price': curr_price, 'base_size': pct / 100,
                        'total_size': pct / 100, 'add_count': 0, 'add_prices': [],
                        'entry_atr': atr if atr > 0 else curr_price * 0.01,
                        'trailing_stop': curr_price - 2 * atr if dir_long else curr_price + 2 * atr,
                        'exit_price': None, 'exit_date': None, 'exit_reason': None,
                    }
                    positions.append(pos)

            # 金字塔加仓
            for pos in list(active):
                if pos['add_count'] >= cfg['pyramid_max']:
                    continue
                move = (curr_price - pos['entry_price']) / pos['entry_atr']
                level = pos['add_count'] + 1
                if pos['direction'] == 'long' and move >= cfg['pyramid_atr'] * level:
                    add = pos['base_size'] * (cfg['pyramid_ratio'] ** level)
                    pos['add_count'] += 1
                    pos['add_prices'].append(curr_price)
                    pos['avg_price'] = (pos['avg_price'] * pos['total_size'] + curr_price * add) / (pos['total_size'] + add)
                    pos['total_size'] += add
                elif pos['direction'] == 'short' and -move >= cfg['pyramid_atr'] * level:
                    add = pos['base_size'] * (cfg['pyramid_ratio'] ** level)
                    pos['add_count'] += 1
                    pos['add_prices'].append(curr_price)
                    pos['avg_price'] = (pos['avg_price'] * pos['total_size'] + curr_price * add) / (pos['total_size'] + add)
                    pos['total_size'] += add

        closed = [p for p in positions if p['exit_date'] is not None]
        wins = [p for p in closed if (p['direction'] == 'long' and p['exit_price'] > p['avg_price']) or
                                      (p['direction'] == 'short' and p['exit_price'] < p['avg_price'])]
        total_cr = sum(
            ((p['exit_price'] - p['avg_price']) / p['avg_price'] * p['total_size']) * (-1 if p['direction']=='short' else 1)
            for p in closed
        )
        return {
            'trades': len(closed), 'wins': len(wins),
            'win_rate': len(wins) / len(closed) * 100 if closed else 0,
            'cr': total_cr / len(closed) * 100 if closed else 0,
            'max_adds': max((p['add_count'] for p in positions), default=0),
        }

    def _aggregate(self, results, output_dir, config):
        total_trades = sum(r.get('trades', 0) for r in results.values())
        total_wins = sum(r.get('wins', 0) for r in results.values())
        win_rate = total_wins / total_trades * 100 if total_trades else 0
        avg_cr = sum(r.get('cr', 0) for r in results.values()) / max(len(results), 1)

        summary = {
            'config': {k: v for k, v in config.items()},
            'symbols': len(results), 'total_trades': total_trades,
            'win_rate': round(win_rate, 1), 'avg_cr': round(avg_cr, 2),
            'per_symbol': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, 'three_signal_backtest_results.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # HTML
        rows = ''
        for sym, r in sorted(summary['per_symbol'].items()):
            err = r.get('error', '')
            if err:
                rows += f'<tr><td>{sym}</td><td colspan="5" style="color:#888">{err}</td></tr>'
            else:
                rows += f'<tr><td>{sym}</td><td>{r["trades"]}</td><td>{r["win_rate"]:.1f}%</td>'
                rows += f'<td class="{"green" if r["cr"]>0 else "red"}">{r["cr"]:+.2f}%</td>'
                rows += f'<td>{r["max_adds"]}</td><td>{r["wins"]}/{r["trades"]}</td></tr>'

        cfg = config
        html = f'''<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><title>三类信号策略回测报告</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;background:#0a0e1a;color:#e0e0e0;padding:20px}}
h1{{color:#f0b429}} h2{{color:#8890e0;font-size:16px}}
.green{{color:#4bc94b}} .red{{color:#ef4444}}
table{{width:100%;border-collapse:collapse;margin:15px 0}}
th{{background:#1a2040;color:#8890e0;padding:8px;text-align:left;border-bottom:2px solid #2a3050}}
td{{padding:8px;border-bottom:1px solid #1a2040}}
.card{{background:#11162a;border-radius:8px;padding:15px;margin:10px 0;border:1px solid #1e2340}}
</style></head><body>
<h1>三类信号策略回测报告</h1>
<p>{summary["timestamp"]}</p>
<div class="card"><h2>参数配置</h2>
<p>开仓阈值={cfg["conf_threshold"]}% | 仓位={cfg["position_pct"]}% | 加仓:{cfg["pyramid_atr"]}ATR×{cfg["pyramid_max"]}次×{cfg["pyramid_ratio"]} | 止损={cfg["stop_atr"]}ATR | 采样步长={cfg["step"]}</p>
</div>
<div class="card"><h2>汇总</h2>
<p>品种: {summary["symbols"]} | 总交易: {summary["total_trades"]} | 胜率: <b>{summary["win_rate"]}%</b> | 平均CR: <b class="{"green" if summary["avg_cr"]>0 else "red"}">{summary["avg_cr"]:+.2f}%</b></p>
</div>
<table><tr><th>品种</th><th>交易</th><th>胜率</th><th>CR</th><th>最大加仓</th><th>胜/负</th></tr>{rows}</table>
</body></html>'''
        html_path = os.path.join(output_dir, 'three_signal_backtest_report.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'\n📁 {html_path}')
        return summary


def main():
    p = argparse.ArgumentParser(description='三类信号金字塔加仓回测')
    p.add_argument('--symbols', '-s', default='C,CJ,LC,AU,CU', help='品种(逗号分隔)')
    p.add_argument('--days', '-d', type=int, default=365, help='历史天数')
    p.add_argument('--conf', type=float, default=60, help='开仓置信度阈值(%)')
    p.add_argument('--position', type=float, default=15, help='仓位(%)')
    p.add_argument('--stop-atr', type=float, default=2.0, help='跟踪止损ATR倍数')
    p.add_argument('--pyramid-atr', type=float, default=1.0, help='加仓间隔(ATR)')
    p.add_argument('--pyramid-max', type=int, default=3, help='最多加仓次数')
    p.add_argument('--pyramid-ratio', type=float, default=0.5, help='加仓比例')
    p.add_argument('--step', type=int, default=10, help='采样间隔(K线)')
    p.add_argument('--signal', choices=['all','gap','breakout','pullback'], default='all', help='信号类型过滤')
    p.add_argument('--ma60', action='store_true', help='60日均线多空过滤')
    p.add_argument('--output', '-o', default='backtest_results', help='输出目录')
    args = p.parse_args()

    bt = ThreeSignalBacktest()
    symbols = [s.strip() for s in args.symbols.split(',')]
    print(f'三类信号回测: {symbols} | {args.days}天 | 信>={args.conf}% | 仓={args.position}% | '
          f'加仓{args.pyramid_atr}ATR×{args.pyramid_max}次×{args.pyramid_ratio} | 止损{args.stop_atr}ATR | 步长={args.step}')
    bt.run(symbols, days=args.days, output_dir=args.output,
           conf_threshold=args.conf, position_pct=args.position,
           stop_atr=args.stop_atr, pyramid_atr=args.pyramid_atr,
           pyramid_max=args.pyramid_max, pyramid_ratio=args.pyramid_ratio,
           step=args.step, signal_filter=args.signal, ma60_filter=args.ma60)

if __name__ == '__main__':
    main()
