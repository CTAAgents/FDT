# -*- coding: utf-8 -*-
"""
真分层打分回测框架 v1.0
=========================
多截面采样 + 多空评估 + IC分析 + L1-L4对比

方法（与 run_backtest.py 一致）：
  每品种取 250 日 K 线，从第 80 根开始，每 10 根采样一个截面。
  每个截面上：
    1. 对所有品种计算指标 + 真分层打分（修复版 v2.0）
    2. 记录 Top/Bottom 品种
    3. 测量后 N 日收益率
  
  评价指标：
    - Top/Bottom Spread（多空价差）
    - IC / RankIC
    - 胜率（Top 跑赢 Bottom 的比例）
    - 分层收益曲线（Q1~Q5）
"""
import sys, os, json, random, math
from datetime import date, datetime
from statistics import mean, stdev

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(SKILL_DIR, '..')  # 回退到 scripts/
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import akshare as ak

from config.symbols import ALL_SYMBOLS
from indicators.indicators_legacy import _compute_indicators_numpy
from signals.true_layered_scoring import compute_true_layered_score, rank_percentile


# ============================================================
# 配置
# ============================================================

BACKTEST_CONFIG = {
    'days': 1000,          # 用AKShare可获取的深度，定价1000日约4年
    'step': 5,             # 每5根K线采样一个截面（原10，加倍提高统计量）
    'min_start': 120,      # 从第120根K线开始采样（给足指标计算窗口）
    'min_bars': 50,        # 品种最低有效K线数
    'forward_days': [5, 10, 20],  # 向前看多少日
    'quantiles': [0.2, 0.4, 0.6, 0.8],  # 分层分位点
}


# ============================================================
# ============================================================
# 数据采集（仅AKShare — 含真实OI，最长10年历史）
# ============================================================

def collect_all_kline(symbols: list, days: int = 250, min_bars: int = 50) -> dict:
    """采集全品种K线数据。
    
    数据源：AKShare futures_main_sina，含真实持仓量 OI
    历史长度：约2000-5000日（取决于品种上市时间）
    """
    return _collect_akshare(symbols, days, min_bars)


def _collect_akshare(symbols: list, days: int = 250, min_bars: int = 50) -> dict:
    """AKShare 数据采集（含真实持仓量 OI，更长历史）"""
    print(f'[AKShare] 采集 {len(symbols)} 品种 K线 ({days}日)...')
    kline_data = {}

    for i, (sym, name) in enumerate(symbols):
        try:
            df = ak.futures_main_sina(symbol=f'{sym.upper()}0')
            if df is None or len(df) < min_bars:
                continue
            col_map = {
                '日期': 'date', '开盘价': 'open', '最高价': 'high',
                '最低价': 'low', '收盘价': 'close', '成交量': 'volume',
                '持仓量': 'open_interest',
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            records = []
            for _, row in df.iterrows():
                records.append({
                    'date': str(row.get('date', '')),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(row.get('volume', 0)),
                    'oi': int(row.get('open_interest', 0)),
                    'data_source': 'akshare',
                    'confidence': 1.0,
                })
            records = [r for r in records if r['date'] and r['volume'] > 0 and r['close'] > 0]
            records = records[-days:] if len(records) > days else records
            if len(records) >= min_bars:
                kline_data[sym] = (name, records)
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f'  [{i+1}/{len(symbols)}] {len(kline_data)} OK')

    print(f'  AKShare完成: {len(kline_data)}/{len(symbols)}')
    return kline_data


# ============================================================
# 单截面打分
# ============================================================

def score_at_snapshot(kline_data: dict, end_idx: int, symbols: list,
                      mode: str = 'true_layered') -> dict:
    """在历史截面上对全品种打分。
    
    参数:
        kline_data: {sym: (name, kline_list)}
        end_idx: 截面上限（K线数组索引，不含该天）
        symbols: [(sym, name), ...] 待打分的品种
        mode: 'true_layered'  # 仅真分层
    
    返回:
        {'symbol': ..., 'score': ..., 'direction': ..., 'ret_5d': ..., ...}
    """
    import pandas as pd
    observations = []
    tech_list = []

    for sym, name in symbols:
        if sym not in kline_data:
            continue
        _, dlist = kline_data[sym]
        if end_idx >= len(dlist):
            continue
        window = dlist[:end_idx + 1]
        if len(window) < 50:
            continue

        try:
            df = pd.DataFrame({k: [float(r[k]) for r in window]
                               for k in ['open', 'high', 'low', 'close']})
            df['volume'] = [float(r.get('volume', 0)) for r in window]
            # OI: AKShare存oi字段，TDX存oi字段，统一处理
            oi_vals = [float(r.get('oi', 0)) for r in window]
            if 'open_interest' in window[0]:
                oi_vals = [float(r.get('open_interest', 0)) for r in window]
            df['open_interest'] = oi_vals

            tech = _compute_indicators_numpy(df, sym)
            price = tech.get('last_price', float(df['close'].iloc[-1]))
            prev = float(df['close'].iloc[-2]) if len(df) > 1 else price
            tech['price'] = price
            tech['change_pct'] = (price / prev - 1) * 100
            tech['symbol'] = sym
            tech['name'] = name

            # 计算 forward 收益率
            closes = df['close'].tolist()
            forward_rets = {}
            for fd in [5, 10, 20]:
                fwd_idx = end_idx + fd
                if fwd_idx < len(dlist):
                    fwd_price = float(dlist[fwd_idx]['close'])
                    forward_rets[f'ret_{fd}d'] = (fwd_price / price - 1) * 100
                else:
                    forward_rets[f'ret_{fd}d'] = None

            observations.append({
                'symbol': sym,
                'name': name,
                'price': price,
                'tech': tech,
                'forward_rets': forward_rets,
            })
        except Exception:
            pass

    if mode == 'true_layered':
        techs = [ob['tech'] for ob in observations]
        result = compute_true_layered_score(techs)
        ranking_map = {c['symbol']: c for c in result['ranked']}
        for ob in observations:
            sym = ob['symbol']
            if sym in ranking_map:
                r = ranking_map[sym]
                ob['score'] = r['adjusted_rank']
                ob['net_rank'] = r['net_rank']
                ob['avg_rank'] = r['avg_rank']
                ob['active_dims'] = r['active_dims']
                ob['veto_penalty'] = r['veto_penalty']
                ob['maturity_stage'] = r['maturity']['stage']
            else:
                ob['score'] = 0.0
                ob['net_rank'] = 0.0
                ob['avg_rank'] = 0.0
                ob['active_dims'] = 0
                ob['veto_penalty'] = 1.0
                ob['maturity_stage'] = 'unknown'
    else:
        # L1-L4 模式
        for ob in observations:
            tech = ob['tech']
            sym_scoring = {'last_price': tech.get('price', 0),
                           'open_interest': tech.get('open_interest', 0)}
            sc = calculate_composite_score(tech, sym_scoring)
            direction = sc['direction']
            s = 1 if direction == 'BUY' else (-1 if direction == 'SELL' else 0)
            ob['score'] = sc['total'] * s
            ob['net_rank'] = sc['total'] * s
            ob['avg_rank'] = abs(sc['total'])
            ob['active_dims'] = 4
            ob['veto_penalty'] = 1.0
            ob['maturity_stage'] = sc['maturity']['stage']

    # 按 score 降序
    observations.sort(key=lambda x: x['score'], reverse=True)
    for i, ob in enumerate(observations):
        ob['rank'] = i + 1
        ob['n_total'] = len(observations)
        # 清除 tech 字典（太大了，不需要留在结果中）
        del ob['tech']

    return {
        'snapshot_idx': end_idx,
        'n_contracts': len(observations),
        'ranked': observations,
    }


# ============================================================
# 回测主循环
# ============================================================

def run_backtest(symbols: list = None, mode: str = 'true_layered',
                 config: dict = None) -> dict:
    """执行真分层打分回测。
    
    参数:
        symbols: [(sym, name), ...] 品种列表
        mode: 'true_layered'  # 仅真分层
        config: 覆盖 BACKTEST_CONFIG
    
    返回: 包含所有截面数据和评价指标
    """
    if config is None:
        config = BACKTEST_CONFIG
    if symbols is None:
        symbols = ALL_SYMBOLS

    days = config['days']
    step = config['step']
    min_start = config['min_start']
    forward_days = config['forward_days']

    today = date.today()
    print(f"{'='*60}")
    print(f"真分层打分回测 — {today}")
    print(f"模式: {mode}  品种: {len(symbols)}  step={step}  min_start={min_start}")
    print(f"{'='*60}")

    # Step 1: 数据采集
    print('\n[1] 数据采集...')
    kline_data = collect_all_kline(symbols, days=days, min_bars=min_start + 30)

    # 确定可用的品种列表（按ALL_SYMBOLS顺序过滤，排除数据太短的品种）
    active_symbols = [(s, n) for s, n in symbols if s in kline_data]
    print(f'  可用品种: {len(active_symbols)}/{len(symbols)}')

    # 品种最小K线长度阈值（排除上市时间过短的合约，避免压缩采样截面数）
    MIN_KLINE_FOR_BT = 500  # 排除上市时间过短的合约（<500日），当前排op/ps/PR
    active_symbols = [(s, n) for s, n in active_symbols if len(kline_data[s][1]) >= MIN_KLINE_FOR_BT]
    short_ct = len(symbols) - len(active_symbols) - sum(1 for s, n in symbols if s not in kline_data)
    if short_ct > 0:
        print(f'  排除数据不足{MIN_KLINE_FOR_BT}天的品种: {short_ct}')

    # 确定最小K线长度（取所有活跃品种的最小公共长度）
    min_kline_len = min(len(kline_data[s][1]) for s, n in active_symbols)
    print(f'  最小K线长度: {min_kline_len} 根')

    # Step 2: 多截面采样
    print(f'\n[2] 多截面采样 (每{step}根, 从{min_start}开始)...')
    snapshot_indices = list(range(min_start, min_kline_len - max(forward_days), step))
    print(f'  采样截面数: {len(snapshot_indices)}')

    snapshots = []
    for si, end_idx in enumerate(snapshot_indices):
        try:
            snap = score_at_snapshot(kline_data, end_idx, active_symbols, mode=mode)
            snapshots.append(snap)
        except Exception as e:
            print(f'  [!!] 截面 {end_idx} 失败: {e}')
        if (si + 1) % max(1, len(snapshot_indices) // 10) == 0:
            print(f'  [{si+1}/{len(snapshot_indices)}] {len(snapshots)} OK')

    print(f'  完成: {len(snapshots)}/{len(snapshot_indices)} 截面')

    # Step 3: 评估
    print(f'\n[3] 评估...')
    evaluation = evaluate_backtest(snapshots, forward_days)
    evaluation['config'] = config
    evaluation['mode'] = mode
    evaluation['n_symbols'] = len(active_symbols)
    evaluation['n_snapshots'] = len(snapshots)

    return evaluation


# ============================================================
# 评估
# ============================================================

def evaluate_backtest(snapshots: list, forward_days: list) -> dict:
    """对回测结果进行全面评估。"""
    result = {}

    # --- 3a: 截面IC ---
    print('  计算截面IC...')
    ics_by_forward = {fd: [] for fd in forward_days}
    rank_ics_by_forward = {fd: [] for fd in forward_days}
    for snap in snapshots:
        ranked = snap['ranked']
        scores = [r['score'] for r in ranked if r.get('forward_rets')]
        for fd in forward_days:
            rets = [r['forward_rets'].get(f'ret_{fd}d') for r in ranked
                    if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
            if len(scores) != len(rets):
                continue
            n = len(scores)
            if n < 10:
                continue
            # Pearson IC
            sx, sy, sxy, sx2, sy2 = 0, 0, 0, 0, 0
            for i in range(n):
                sx += scores[i]; sy += rets[i]
                sxy += scores[i] * rets[i]
                sx2 += scores[i] ** 2; sy2 += rets[i] ** 2
            r_num = n * sxy - sx * sy
            r_den = math.sqrt((n * sx2 - sx ** 2) * (n * sy2 - sy ** 2))
            ic_val = r_num / r_den if r_den > 0 else 0
            ics_by_forward[fd].append(ic_val)

    for fd in forward_days:
        vals = [v for v in ics_by_forward[fd] if v is not None and not math.isnan(v)]
        if vals:
            result[f'IC_mean_{fd}d'] = round(mean(vals), 4)
            result[f'IC_std_{fd}d'] = round(stdev(vals), 4) if len(vals) > 1 else 0
            result[f'IC_winrate_{fd}d'] = round(sum(1 for v in vals if v > 0) / len(vals), 3)
            result[f'IC_t_stat_{fd}d'] = round(mean(vals) / (stdev(vals) / math.sqrt(len(vals))), 2) if stdev(vals) > 0 else 0
        else:
            result[f'IC_mean_{fd}d'] = 0
            result[f'IC_std_{fd}d'] = 0
            result[f'IC_winrate_{fd}d'] = 0
            result[f'IC_t_stat_{fd}d'] = 0

    # --- 3b: Top/Bottom 多空收益 ---
    print('  计算Top/Bottom多空价差...')
    for top_pct in [0.1, 0.2, 0.3]:
        tag = f'top{int(top_pct*100)}'
        for fd in forward_days:
            spreads = []
            for snap in snapshots:
                ranked = snap['ranked']
                n_top = max(1, int(len(ranked) * top_pct))
                top_rets = [r['forward_rets'].get(f'ret_{fd}d') for r in ranked[:n_top]
                            if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
                bottom_rets = [r['forward_rets'].get(f'ret_{fd}d') for r in ranked[-n_top:]
                               if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
                if len(top_rets) < 3 or len(bottom_rets) < 3:
                    continue
                top_avg = mean(top_rets)
                bottom_avg = mean(bottom_rets)
                spreads.append(top_avg - bottom_avg)

            if spreads:
                result[f'spread_mean_{tag}_{fd}d'] = round(mean(spreads), 2)
                result[f'spread_winrate_{tag}_{fd}d'] = round(sum(1 for s in spreads if s > 0) / len(spreads), 3)
                result[f'top_mean_ret_{tag}_{fd}d'] = round(mean([mean(
                    [r['forward_rets'].get(f'ret_{fd}d') for r in snap['ranked'][:max(1, int(len(snap['ranked'])*top_pct))]
                    if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
                ) for snap in snapshots if len(snap['ranked']) >= 3]), 2)
                bottom_mean = mean([mean(
                    [r['forward_rets'].get(f'ret_{fd}d') for r in snap['ranked'][-max(1, int(len(snap['ranked'])*top_pct)):]
                     if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
                ) for snap in snapshots if len(snap['ranked']) >= 3])
                result[f'bottom_mean_ret_{tag}_{fd}d'] = round(bottom_mean, 2)

    # --- 3c: 分层收益（Q1-Q5）---
    print('  计算分层收益（Q1-Q5）...')
    for fd in forward_days:
        q_rets = {1: [], 2: [], 3: [], 4: [], 5: []}
        for snap in snapshots:
            ranked = snap['ranked']
            n_contracts = len(ranked)
            if n_contracts < 10:
                continue
            for qi in range(5):
                start = int(n_contracts * qi / 5)
                end = int(n_contracts * (qi + 1) / 5)
                rets = [r['forward_rets'].get(f'ret_{fd}d') for r in ranked[start:end]
                        if r.get('forward_rets') and r['forward_rets'].get(f'ret_{fd}d') is not None]
                if rets:
                    q_rets[qi + 1].append(mean(rets))

        for qi in range(5):
            r = q_rets[qi + 1]
            if r:
                result[f'Q{qi+1}_mean_ret_{fd}d'] = round(mean(r), 2)
                
        # Q1-Q5 spread (monotonicity)
        q1 = q_rets.get(1, [])
        q5 = q_rets.get(5, [])
        if q1 and q5:
            result[f'Q1Q5_spread_{fd}d'] = round(mean(q1) - mean(q5), 2)
            result[f'Q1Q5_monotonic_{fd}d'] = round(
                sum(1 for qi in range(4) if mean(q_rets.get(qi+1, [0])) >= mean(q_rets.get(qi+2, [0])) and mean(q_rets.get(qi+1, [0])) != 0) / 4,
                2) if all(q_rets.get(qi+1, []) for qi in range(4)) else 0

    return result


# ============================================================
# 双模式对比运行
# ============================================================

def run_comparison(symbols: list = None) -> dict:
    """同时运行 true_layered 和 l1l4 模式并对比。"""
    print(f"\n{'#'*60}")
    print("# 双模式对比回测")
    print(f"{'#'*60}\n")

    # 同一天采集的数据，两种模式分别打分
    # 这里直接各跑一次
    tl_result = run_backtest(symbols=symbols, mode='true_layered')
    # 注意：l1l4 这里不会真的跑（需要完整数据），仅作为框架预留
    # 实际对比可以后续实现

    return tl_result


# ============================================================
# 报告输出
# ============================================================

def print_report(eval_result: dict):
    """打印回测评估报告。"""
    mode = eval_result.get('mode', 'true_layered')
    n_sym = eval_result.get('n_symbols', 0)
    n_snap = eval_result.get('n_snapshots', 0)

    print(f"\n{'='*60}")
    print(f"回测报告 — {mode}")
    print(f"品种数: {n_sym}  截面数: {n_snap}")
    print(f"{'='*60}")

    for fd in [5, 10, 20]:
        print(f"\n── 向前 {fd} 日 ──")
        # IC
        ic_mean = eval_result.get(f'IC_mean_{fd}d', 0)
        ic_std = eval_result.get(f'IC_std_{fd}d', 0)
        ic_wr = eval_result.get(f'IC_winrate_{fd}d', 0)
        ic_t = eval_result.get(f'IC_t_stat_{fd}d', 0)
        print(f"  IC: 均值={ic_mean:.4f} 标准差={ic_std:.4f} 胜率={ic_wr:.1%} t值={ic_t:.2f}")

        # Top20 spread
        sp20 = eval_result.get(f'spread_mean_top20_{fd}d', 0)
        wr20 = eval_result.get(f'spread_winrate_top20_{fd}d', 0)
        print(f"  Top20-Bottom20 Spread: {sp20:.2f}%  胜率={wr20:.1%}")

        # Top10 spread
        sp10 = eval_result.get(f'spread_mean_top10_{fd}d', 0)
        wr10 = eval_result.get(f'spread_winrate_top10_{fd}d', 0)
        print(f"  Top10-Bottom10 Spread: {sp10:.2f}%  胜率={wr10:.1%}")

        # Q1-Q5
        q1 = eval_result.get(f'Q1_mean_ret_{fd}d', 0)
        q5 = eval_result.get(f'Q5_mean_ret_{fd}d', 0)
        q1q5 = eval_result.get(f'Q1Q5_spread_{fd}d', 0)
        mono = eval_result.get(f'Q1Q5_monotonic_{fd}d', 0)
        print(f"  Q1收益={q1:.2f}%  Q5收益={q5:.2f}%  Q1-Q5={q1q5:.2f}%  单调性={mono:.0%}")


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='真分层打分回测 v1.0')
    parser.add_argument('--mode', '-m', default='true_layered',
                        choices=['true_layered'])
    parser.add_argument('--symbols', '-s', help='指定品种')
    args = parser.parse_args()

    custom_symbols = None
    if args.symbols:
        sym_map = {sym: name for sym, name in ALL_SYMBOLS}
        codes = [s.strip().upper() for s in args.symbols.split(',')]
        custom_symbols = [(s, sym_map.get(s, s)) for s in codes]

    result = run_backtest(symbols=custom_symbols, mode=args.mode)
    print_report(result)

    # 输出 JSON
    today_str = date.today().strftime('%Y%m%d')
    output_dir = os.path.join(SCRIPTS_DIR, 'backtest', 'results')
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f'backtest_true_layered_{today_str}.json')
    
    # 清理不可序列化的内容
    clean_result = {k: v for k, v in result.items()}
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(clean_result, f, ensure_ascii=False, indent=2)
    print(f'\n[OK] 结果已保存: {json_path}')
