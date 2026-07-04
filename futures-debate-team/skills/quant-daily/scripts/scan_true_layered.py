#!/usr/bin/env python3
"""
真分层打分扫描器 v2.1 — TDX TQ-Local 实盘 + AKShare OI修正
=========================================================

数据方案（按用户要求，回测用AKShare，实盘用TDX）：
  1. K线数据: 通达信TQ-Local → MultiSourceAdapter（实时精确）
  2. OI持仓量: AKShare futures_main_sina 额外注入（TDX L8无OI）
  3. 技术指标: TDX TQ-Local bridge 补丁（DMI/RSI/CCI/MACD精确值）
  
回测/训练用: scan_all.py --mode true_layered  ← AKShare数据源（含OI）
实盘信号用:  本脚本                              ← TDX数据源+AKShare OI

法官席（6独立裁判，ADX风格感知）：
  D1 趋势_动量       — ROC10（TDX精确）
  D2 回归_乖离率     -BIAS（TDX精确）
  D3 回归_RSI反向    -(RSI14-50)（TDX精确）
  D4 资金_持仓OI     OI_CHANGE_PCT（AKShare注入）
  D5 资金_净流CMF    CMF21
  D6 确认_量价       VOL_RATIO×方向
"""
import sys, os, json, pandas as pd
from datetime import date

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

import akshare as ak
from config.symbols import ALL_SYMBOLS
from data.multi_source_adapter import MultiSourceAdapter
from indicators.indicators_legacy import _compute_indicators_numpy
from signals.true_layered_scoring import compute_true_layered_score, compute_factor_validity, FACTOR_DEFINITIONS


def _collect_kline_live(symbols: list, days: int = 120, min_bars: int = 50) -> dict:
    """实盘数据采集：通达信TQ-Local为主 + AKShare OI注入。
    
    流程：
      1. MultiSourceAdapter（优先TDX）获取K线（TDX精确价量）
      2. AKShare futures_main_sina 额外获取OI序列
      3. 将AKShare的OI覆盖到TDX K线数据上
    """
    print(f'[数据] 通达信TQ-Local + AKShare OI 采集 {len(symbols)} 品种 ({days}日)…')
    adapter = MultiSourceAdapter()
    kline_data = {}

    # 1. TDX获取价格数据
    for i, (sym, name) in enumerate(symbols):
        try:
            resp = adapter.get_kline(variety=sym, days=days)
            if isinstance(resp, dict) and resp.get('success'):
                dlist = resp['data']
                valid = [r for r in dlist if r.get('volume', 0) > 0 and r.get('close', 0) > 0]
                if len(valid) >= min_bars:
                    kline_data[sym] = {'name': name, 'kline': valid}
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f'  TDX [{i+1}/{len(symbols)}] {len(kline_data)} OK')

    # 2. AKShare OI注入
    print(f'  AKShare OI注入 ({len(kline_data)}品种)…')
    oi_ok = 0
    for sym in list(kline_data.keys()):
        try:
            df = ak.futures_main_sina(symbol=f'{sym.upper()}0')
            if df is None or len(df) < 10:
                continue
            oi_series = df['持仓量'].values.astype(float) if '持仓量' in df.columns else None
            if oi_series is None or len(oi_series) == 0:
                continue
            # 取最后 days 条
            oi_series = oi_series[-days:] if len(oi_series) > days else oi_series
            # 按日期对齐注入（从后往前）
            kline = kline_data[sym]['kline']
            for j in range(min(len(kline), len(oi_series))):
                kline[-(j+1)]['oi'] = int(oi_series[-(j+1)])
            oi_ok += 1
        except Exception:
            pass

    # 转换格式
    result = {}
    for sym, v in kline_data.items():
        result[sym] = (v['name'], v['kline'])

    print(f'  完成: {len(result)}/{len(symbols)} 品种 (OI注入{oi_ok}/{len(kline_data)})')
    return result


def _classify_signal(dims: dict) -> str:
    """根据维度分数判断信号驱动风格 (v2.1 6因子版)。
    
    返回: 回归 | 趋势 | 资金 | 混合 | 量价
    """
    t = dims.get('D1_趋势_动量', 0)
    r = dims.get('D2_回归_综合', 0)
    f = dims.get('D3_资金_综合', 0)
    v = dims.get('D4_确认_量价', 0)
    term = dims.get('D5_期限_基差', 0)
    vol = dims.get('D6_波动_情绪', 0)

    active = []
    if t >= 50: active.append('趋势')
    if r >= 50: active.append('回归')
    if f >= 50: active.append('资金')
    if v >= 50: active.append('量价')

    if len(active) == 0:
        return '信号弱'
    elif len(active) == 1:
        return active[0]
    else:
        # 取最强的两个
        return '+'.join(active[:2])


def _get_signal_type(style: str, adx: float) -> str:
    """根据风格和ADX判断信号类型。
    
    返回: 'regime_reg' 回归类 | 'regime_trend' 趋势类 | 'hybrid' 混合
    """
    has_reg = '回归' in style
    has_trend = '趋势' in style

    if has_reg and has_trend:
        return 'hybrid'  # 回归+趋势混合
    elif has_reg:
        return 'regime_reg'  # 纯回归
    elif has_trend:
        return 'regime_trend'  # 纯趋势
    else:
        return 'other'


GRID_DEF = {
    ('H','H'): (1, 1.0, '强多区'), ('H','M'): (1, 0.5, '左侧多'), ('H','L'): (1, 0.5, '左侧多'),
    ('M','H'): (1, 0.3, '趋势多'), ('M','M'): (0, 0.0, '混沌区'), ('M','L'): (-1, 0.3, '趋势空'),
    ('L','H'): (-1, 0.5, '右侧空'), ('L','M'): (-1, 0.5, '过渡空'), ('L','L'): (-1, 1.0, '强空区'),
}
GRID_CENTERS = {'L': 0.17, 'M': 0.50, 'H': 0.83}
GRID_SIGMA = 0.2


def _grid_classifier(dims: dict) -> dict:
    """九宫格分类器：高斯模糊隶属度 → 左右侧区分。返回 {direction, strength, grid, side}"""
    import math
    reg_scores = [dims.get(k, 0) / 100.0 for k in ['D2_回归_综合']
                  if dims.get(k) is not None and dims.get(k) != 0]
    tr_scores = [dims.get('D1_趋势_动量', 0) / 100.0] if dims.get('D1_趋势_动量') is not None and dims.get('D1_趋势_动量') != 0 else []
    if not reg_scores or not tr_scores:
        return {'direction': 0, 'strength': 0, 'grid': 'N/A', 'side': 'N/A'}
    reg = sum(reg_scores) / len(reg_scores)
    tr = sum(tr_scores) / len(tr_scores)
    def gauss(x, c): return math.exp(-(x - c)**2 / (2 * GRID_SIGMA**2))
    total_dir, total_str, norm_sum, best_grid, best_m = 0.0, 0.0, 0.0, 'N/A', 0.0
    for (rl, tl), (d, s, label) in GRID_DEF.items():
        m = gauss(reg, GRID_CENTERS[rl]) * gauss(tr, GRID_CENTERS[tl])
        total_dir += m * d * s
        total_str += m * s
        norm_sum += m
        if m > best_m:
            best_m, best_grid = m, label
    if norm_sum == 0:
        return {'direction': 0, 'strength': 0, 'grid': 'N/A', 'side': 'N/A'}
    final_dir = 1 if total_dir / norm_sum > 0.05 else (-1 if total_dir / norm_sum < -0.05 else 0)
    final_str = min(abs(total_dir / norm_sum), 1.0)
    if '左侧' in best_grid or ('多' in best_grid and tr < 0.4):
        side = '左侧'
    elif '右侧' in best_grid or ('空' in best_grid and tr > 0.6):
        side = '右侧'
    elif '趋势' in best_grid or '强' in best_grid:
        side = '右侧'
    else:
        side = '中心'
    return {'direction': final_dir, 'strength': round(final_str, 2),
            'grid': best_grid, 'side': side, 'reg': round(reg, 2), 'trend': round(tr, 2)}


def _get_adx(sym, techs):
    import math
    adx = next((t.get('ADX', 0) for t in techs if t.get('symbol') == sym), 0)
    if adx is None or (isinstance(adx, float) and math.isnan(adx)):
        return 0
    return adx


def _check_factor_conflict(dims: dict, mode: str = 'short') -> tuple:
    """检查因子方向一致性冲突。

    当品种的**看多/看空因子高度一致**时，排除反向信号。

    看多因子: D1(趋势动量), D4(持仓OI), D5(净流CMF), D7(期限基差)
    看空因子: D2(乖离率), D3(RSI反向)

    Args:
        dims: 7维因子分 dict
        mode: 'short'=检查看多一致性, 'long'=检查看空一致性

    Returns:
        (has_conflict, reason): 是否有冲突及原因
    """
    keys = list(dims.keys())
    if len(keys) < 6:
        return False, ''

    vals = list(dims.values())

    if mode == 'short':
        # 做空候选：检查是否有强烈看多一致性（D1趋势+D3资金+D5期限）
        bullish = sum(1 for v in [vals[0], vals[2], vals[4]] if v >= 70)
        avg_bullish = (max(vals[0], 0) + max(vals[2], 0) + max(vals[4], 0)) / 3
        if bullish >= 2 and avg_bullish >= 65:
            return True, (f'一致看多(bullish={bullish}/3, avg={avg_bullish:.0f})'
                          f' D1={vals[0]:.0f} D3={vals[2]:.0f} D5={vals[4]:.0f}')
    else:
        # 做多候选：检查是否有强烈看空一致性
        bearish = sum(1 for v in [vals[0], vals[2], vals[4]] if v <= 30)
        avg_bearish = (max(100 - vals[0], 0) + max(100 - vals[2], 0) + max(100 - vals[4], 0)) / 3
        if bearish >= 2 and avg_bearish >= 65:
            return True, (f'一致看空(bearish={bearish}/3, avg={avg_bearish:.0f})'
                          f' D1={vals[0]:.0f} D3={vals[2]:.0f} D5={vals[4]:.0f}')
    return False, ''


def _filter_qualified_signals(short_candidates: list, long_candidates: list,
                               tech_list: list, reverse: bool = False) -> dict:
    """筛选值得交易的信号。
    
    规则（仅安全过滤，不再按风格过滤）：
      1. 否决 veto_penalty >= 0.5
      2. ADX > 5（完全无趋势的不做）
      3. 标记 signal_type: regime_reg / regime_trend / hybrid / other
      4. [v2.1] 因子方向一致性检查（reverse模式下排除一致看多/看空的品种）
    """
    qualified = {'short': [], 'long': []}

    for c in short_candidates:
        style = _classify_signal(c['dimensions'])
        vp = c.get('veto_penalty', 1.0)
        stage = c.get('maturity', {}).get('stage', '?')
        adx = _get_adx(c["symbol"], tech_list)
        stype = _get_signal_type(style, adx)

        reasons = []
        if vp < 0.5:
            reasons.append(f'否决={vp:.2f}<0.5')
        if adx < 5:
            reasons.append(f'ADX={adx:.0f}无趋势')
        # v2.1: 因子方向一致性检查
        if reverse:
            conflict, conflict_reason = _check_factor_conflict(c['dimensions'], 'short')
            if conflict:
                reasons.append(f'因子冲突({conflict_reason})')

        if not reasons:
            qualified['short'].append({
                'symbol': c['symbol'],
                'adj_rank': c.get('adjusted_rank', c['avg_rank']),
                'adx': int(round(adx or 0)),
                'veto': round(vp, 2),
                'style': style,
                'signal_type': stype,
                'stage': stage,
                'side': _grid_classifier(c['dimensions'])['side'],
                'reason': '通过',
            })
        else:
            qualified['short'].append({
                'symbol': c['symbol'],
                'adj_rank': c.get('adjusted_rank', c['avg_rank']),
                'adx': int(round(adx or 0)),
                'veto': round(vp, 2),
                'style': style,
                'signal_type': stype,
                'stage': stage,
                'side': _grid_classifier(c['dimensions'])['side'],
                'reason': '; '.join(reasons),
                'filtered': True,
            })

    for c in long_candidates:
        style = _classify_signal(c['dimensions'])
        vp = c.get('veto_penalty', 1.0)
        stage = c.get('maturity', {}).get('stage', '?')
        adx = _get_adx(c["symbol"], tech_list)
        stype = _get_signal_type(style, adx)

        reasons = []
        if vp < 0.5:
            reasons.append(f'否决={vp:.2f}<0.5')
        if adx < 5:
            reasons.append(f'ADX={adx:.0f}无趋势')
        # v2.1: 因子方向一致性检查
        if reverse:
            conflict, conflict_reason = _check_factor_conflict(c['dimensions'], 'long')
            if conflict:
                reasons.append(f'因子冲突({conflict_reason})')

        entry = {
            'symbol': c['symbol'],
            'adj_rank': c.get('adjusted_rank', c['avg_rank']),
            'adx': int(round(adx or 0)),
            'veto': round(vp, 2),
            'style': style,
            'signal_type': stype,
            'stage': stage,
            'side': _grid_classifier(c['dimensions'])['side'],
            'reason': '; '.join(reasons) if reasons else '通过',
        }
        if reasons:
            entry['filtered'] = True
        qualified['long'].append(entry)

    return qualified


def run_scan(output_dir: str = None, symbols: list = None,
                          reverse: bool = False) -> dict:
    """执行真分层打分扫描。
    
    参数:
        reverse: True=反向信号（排名靠前=做空, 排名靠后=做多）
                 回测显示 IC 为负，反向操作有效
    """
    today = date.today()
    today_str = today.strftime('%Y%m%d')
    mode = 'REVERSE(做空高排名)' if reverse else 'NORMAL(做多高排名)'

    print(f"{'='*60}")
    print(f"真分层打分 v2.0 — AKShare OI + 通达信TDX — {today}")
    print(f"  模式: {mode}")
    print(f"{'='*60}")

    target_symbols = symbols if symbols else ALL_SYMBOLS
    print(f"  品种数: {len(target_symbols)}")

    # Step 1: 通达信TQ-Local + AKShare OI
    print('\n[1] 通达信K线 + AKShare OI注入…')
    kline_data = _collect_kline_live(target_symbols, days=120, min_bars=50)
    print(f'\n[2] 指标计算 + 通达信TDX补丁…')
    from indicators.tdx_bridge import get_bridge
    bridge = get_bridge()
    tdx_ok = bridge.available
    print(f'  通达信TQ-Local: [OK] 已连接' if tdx_ok else f'  通达信TQ-Local: [!!] 未连接（使用numpy兜底）')

    tech_list = []
    oi_valid_ct = 0
    cmf_valid_ct = 0
    for i, (sym, name) in enumerate(target_symbols):
        if sym not in kline_data:
            continue
        try:
            _, dlist = kline_data[sym]
            df = pd.DataFrame({k: [float(r[k]) for r in dlist] for k in ['open', 'high', 'low', 'close']})
            df['volume'] = [float(r.get('volume', 0)) for r in dlist]
            # OI来自AKShare注入（已在_collect_kline_live中对齐）
            oi_values = [float(r.get('oi', 0)) for r in dlist]
            df['open_interest'] = oi_values

            tech = _compute_indicators_numpy(df, sym)
            price = tech.get('last_price', float(df['close'].iloc[-1]))
            prev = float(df['close'].iloc[-2]) if len(df) > 1 else price
            tech['price'] = price
            tech['change_pct'] = (price / prev - 1) * 100
            tech['symbol'] = sym
            tech['name'] = name

            # TDX补丁
            if tdx_ok:
                bridge.patch_indicators(tech, sym)

            # OI有效计数
            oi_val = tech.get('OI_CHANGE_PCT')
            if oi_val is not None and oi_val != 0:
                oi_valid_ct += 1
            if tech.get('CMF21') is not None:
                cmf_valid_ct += 1

            tech_list.append(tech)
        except Exception as e:
            pass
        if (i + 1) % 15 == 0:
            print(f'  [{i+1}/{len(target_symbols)}] {len(tech_list)} OK')

    print(f'  完成: {len(tech_list)} 个品种')
    print(f'  OI有效: {oi_valid_ct}/{len(tech_list)}  CMF有效: {cmf_valid_ct}/{len(tech_list)}')

    # Step 2.5: 期限结构因子注入（期货专用，完全正交于价量因子）
    print('\n[2.5] 期限结构因子注入（D7: 期限_基差）…')
    try:
        from config.symbols import SYMBOL_DETAILS
        from signals.term_basis import compute_term_basis
        # 构建term_basis所需格式
        term_symbols = []
        for t in tech_list:
            sym = t['symbol']
            info = SYMBOL_DETAILS.get(sym, {})
            term_symbols.append({'pid': sym, 'exchange': info.get('exchange', 'SHFE')})
        # 获取期限结构数据
        term_data = compute_term_basis(term_symbols)
        # 注入每个品种的TERM_SIGNAL
        term_inject_ct = 0
        for t in tech_list:
            sym = t['symbol']
            td = term_data.get(sym.lower(), {})
            sig = td.get('term_signal')
            if sig is not None:
                t['TERM_SIGNAL'] = sig
                term_inject_ct += 1
        print(f'  期限结构注入: {term_inject_ct}/{len(tech_list)} 品种')
    except Exception as e:
        print(f'  [!] 期限结构获取失败: {e}')

    # Step 3: 真分层打分
    print('\n[3] 真分层打分（截面排序→秩变换→等权汇总）…')
    result = compute_true_layered_score(tech_list)

    ranked = result['ranked']
    bull = [c for c in ranked if c['net_rank'] > 0]
    bear = [c for c in ranked if c['net_rank'] < 0]
    neutral = [c for c in ranked if c['net_rank'] == 0]
    print(f'  多头 {len(bull)}  空头 {len(bear)}  中性 {len(neutral)}')

    # Step 4: 控制台输出
    # 动态获取因子短名称
    factor_short_names = [f['name'].split('_')[1] for f in FACTOR_DEFINITIONS]
    dim_field_names = [f['name'] for f in FACTOR_DEFINITIONS]
    header_line = f"{'排':>4} {'品种':<8} {'确排':>6} {'净排':>6}"
    for sn in factor_short_names:
        header_line += f' {sn:>6}'
    header_line += f"{'否決':>5} {'阶段':>10} {'维度':>4}"
    print(f"\n{'#'*100}")
    print(header_line)
    print('-' * 100)
    for c in ranked[:30]:
        d = c['dimensions']
        adj = c.get('adjusted_rank', c['avg_rank'])
        mat = c.get('maturity', {}).get('stage', '?')
        ad = c.get('active_dims', 0)
        dim_vals = ' '.join([f'{d.get(fn, 0):>6.0f}' for fn in dim_field_names])
        print(f"{c['rank']:>4} {c['symbol']:<8} {adj:>6.1f} {c['net_rank']:>+6.1f} {dim_vals} {c.get('veto_penalty',1.0):>5.2f} {mat:>10} {ad:>3}/{len(dim_field_names)}")
    if len(ranked) > 30:
        print(f"  … 另有 {len(ranked)-30} 个品种")

    # Step 5: 因子有效性
    print(f'\n[4] 因子数据可用率（法官席清理依据）:')
    validity = compute_factor_validity(tech_list)
    for name, info in validity.items():
        tag = '[OK]' if info['usable'] else '[!!]'
        print(f'  {tag} {name}: {info["valid_ct"]}/{len(tech_list)} ({info["valid_rate"]:.1%})')

    # Step 6: 反向信号输出
    n_signal = min(10, len(ranked))
    if reverse:
        # 反向信号：排名前10做空，排名后10做多
        short = ranked[:n_signal]
        long = ranked[-n_signal:]
        long.reverse()  # 最弱的排第一
        print(f'\n{"="*60}')
        print(f'📊 REVERSE 模式 — 可交易信号')
        print(f'{"="*60}')
        print(f'\n🔴 做空 TOP {n_signal}（排名最高 = 最超买 = 预期下跌）:')
        print(f'{"#":>3} {"品种":<8} {"确排":>6} {"ADX":>5} {"否决":>5} {"风格":>10} {"左右侧":>6} {"阶段":>10}')
        print('-' * 65)
        for c in short:
            adx = next((t.get('ADX', 0) for t in tech_list if t.get('symbol') == c['symbol']), 0)
            mat = c.get('maturity', {}).get('stage', '?')
            vp = c.get('veto_penalty', 1.0)
            style = _classify_signal(c['dimensions'])
            grid = _grid_classifier(c['dimensions'])
            side = grid['side']
            print(f'{c["rank"]:>3} {c["symbol"]:<8} {c.get("adjusted_rank", c["avg_rank"]):>6.1f} {adx:>5.0f} {vp:>5.2f} {style:>10} {side:>6} {mat:>10}')

        print(f'\n🟢 做多 BOTTOM {n_signal}（排名最低 = 最超卖 = 预期上涨）:')
        print(f'{"#":>3} {"品种":<8} {"确排":>6} {"ADX":>5} {"否决":>5} {"风格":>10} {"左右侧":>6} {"阶段":>10}')
        print('-' * 65)
        for c in long:
            adx = next((t.get('ADX', 0) for t in tech_list if t.get('symbol') == c['symbol']), 0)
            mat = c.get('maturity', {}).get('stage', '?')
            vp = c.get('veto_penalty', 1.0)
            style = _classify_signal(c['dimensions'])
            grid = _grid_classifier(c['dimensions'])
            side = grid['side']
            print(f'{c["rank"]:>3} {c["symbol"]:<8} {c.get("adjusted_rank", c["avg_rank"]):>6.1f} {adx:>5.0f} {vp:>5.2f} {style:>10} {side:>6} {mat:>10}')

        print(f'\n📋 调仓建议: 持仓5-10个交易日, 等权分配, 止损设入场价±3%')

        # ── 合格信号筛选（按回归规则过滤）──
        qualified = _filter_qualified_signals(short, long, tech_list, reverse=reverse)
        if qualified['short'] or qualified['long']:
            print(f'\n{"="*60}')
            print(f'🏆 已筛选信号（否决≥0.5 · ADX>5）')
            print(f'   信号类型: regime_reg=回归驱动 | regime_trend=趋势驱动 | hybrid=混合')
            print(f'{"="*60}')
            for label, signals in [('🔴 做空', qualified['short']), ('🟢 做多', qualified['long'])]:
                if not signals:
                    continue
                # 分通过和过滤两组
                passed = [s for s in signals if not s.get('filtered')]
                filtered = [s for s in signals if s.get('filtered')]
                if passed:
                    print(f'\n{label} [OK] 可操作:')
                    print(f'{"品种":<8} {"确排":>6} {"ADX":>5} {"否决":>5} {"信号类型":<14} {"左右侧":>6} {"风格":>10} {"阶段":>10}')
                    print('-' * 75)
                    for s in passed:
                        print(f'{s["symbol"]:<8} {s["adj_rank"]:>6.1f} {s["adx"]:>5.0f} {s["veto"]:>5.2f} {s["signal_type"]:<14} {s["side"]:>6} {s["style"]:>10} {s["stage"]:>10}')
                if filtered:
                    print(f'\n{label} [!!] 已过滤（否决<0.5或ADX<5）:')
                    for s in filtered:
                        print(f'  {s["symbol"]:<6} {s["reason"]}')
            print()

        # 输出到下一个Agent的JSON
        agent_signal = {
            'date': today_str,
            'method': 'true_layered_reverse_v2',
            'qualified_signals': {
                'short': qualified['short'],
                'long': qualified['long'],
            },
            'total_short_candidates': len(short),
            'total_long_candidates': len(long),
            'qualified_short': len(qualified['short']),
            'qualified_long': len(qualified['long']),
        }
        agent_path = os.path.join(output_dir, f'signals_{today_str}.json')
        with open(agent_path, 'w', encoding='utf-8') as f:
            json.dump(agent_signal, f, ensure_ascii=False, indent=2)
        print(f'📡 Agent信号: {agent_path}')
    else:
        print(f'\n（使用 --reverse 参数可查看反向交易信号）')

    # Step 6: 输出
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output = {
            'meta': {
                'date': today_str,
                'method': 'true_layered_scoring_v2',
                'data_source': 'akshare_oi + tdx_patch',
                'n_contracts': len(tech_list),
                'n_factors': result['meta'].get('n_factors_usable', 0),
                'bull': len(bull), 'bear': len(bear), 'neutral': len(neutral),
                'oi_valid': oi_valid_ct, 'cmf_valid': cmf_valid_ct,
            },
            'factor_validity': validity,
            'ranked': [{
                'rank': c['rank'], 'symbol': c['symbol'],
                'adjusted_rank': c.get('adjusted_rank', c['avg_rank']),
                'net_rank': c['net_rank'],
                'active_dims': c.get('active_dims', 0),
                'veto_penalty': c.get('veto_penalty', 1.0),
                'maturity_stage': c.get('maturity', {}).get('stage', ''),
                'dims': c['dimensions'],
                '_provenance': c.get('_provenance', {}),
            } for c in ranked],
            'qualified_signals': {
                'short': qualified.get('short', []) if reverse else [],
                'long': qualified.get('long', []) if reverse else [],
            } if reverse else {},
        }
        json_path = os.path.join(output_dir, f'true_layered_{today_str}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f'\n[OK] JSON: {json_path}')

        # 简易HTML
        html = _gen_html(result, validity, today_str, oi_valid_ct, cmf_valid_ct)
        html_path = os.path.join(output_dir, f'true_layered_{today_str}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'[OK] HTML: {html_path}')

    return result, output if output_dir else (result, None)


def _gen_html(result: dict, validity: dict, date_str: str, oi_ct: int, cmf_ct: int) -> str:
    """生成交互式 HTML 报告"""
    import json as _json
    ranked = result['ranked']
    factors = result['factors']
    # 只用可用因子列，与dims字段数一致（修复列数不匹配bug）
    usable_factors = [f for f in factors if f.get('usable', False)]
    n_f_display = len(usable_factors)

    rows = []
    for c in ranked:
        rows.append({
            'r': c['rank'], 'sym': c['symbol'],
            'adj': c.get('adjusted_rank', c['avg_rank']),
            'net': c['net_rank'],
            'dims': c['dimensions'],
            'ad': c.get('active_dims', 0),
            'veto': c.get('veto_penalty', 1.0),
            'mat': c.get('maturity', {}).get('stage', ''),
        })
    rows_json = _json.dumps(rows, ensure_ascii=False)

    validity_rows = ''.join([
        f"<tr><td>{'✅' if v['usable'] else '❌'}</td><td>{n.split('_')[1]}</td>"
        f"<td>{v['valid_ct']}/{result['meta']['n_contracts']}</td>"
        f"<td>{v['valid_rate']:.0%}</td></tr>"
        for n, v in validity.items()
    ])

    bull = [c for c in ranked if c['net_rank'] > 0]
    bear = [c for c in ranked if c['net_rank'] < 0]

    f_cols = ''.join([
        f'<th onclick="sortBy({i})" data-num="1">{f["name"].split("_")[1]}</th>'
        for i, f in enumerate(usable_factors)
    ])

    return f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8">
<title>真分层打分(含OI) — {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #c9a84c}}
.hd h1{{font-size:22px;color:#c9a84c}}
.hd .sub{{color:#9ca3af;font-size:13px;margin-top:6px}}
.hd .m{{margin-top:10px;display:flex;gap:10px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px;font-size:12px;color:#9ca3af}}
.stats{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700}}
.sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
.sc.b .n{{color:#c0392b}} .sc.g .n{{color:#22c55e}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:13px}}
thead{{background:#252940}}
th{{padding:9px 10px;text-align:left;font-weight:600;color:#9ca3af;font-size:11px;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#c9a84c}} th.asc::after{{content:" \\25B2";font-size:10px}} th.dsc::after{{content:" \\25BC";font-size:10px}}
td{{padding:7px 10px;border-top:1px solid #2a2d3a20;white-space:nowrap}}
tr:hover{{background:#c9a84c08!important}}
</style></head><body>
<div class="hd">
  <h1>真分层打分 — AKShare OI + 通达信TDX补丁</h1>
  <div class="sub">截面排序→秩变换→等权汇总 | v2.0 法官席: OI={oi_ct}/{result['meta']['n_contracts']} CMF={cmf_ct}/{result['meta']['n_contracts']}</div>
  <div class="m">
    <span>{date_str}</span><span>{result['meta']['n_contracts']} 品种</span>
    <span>{n_f_display} 可用因子</span><span>点击列头排序</span>
  </div>
</div>
<div class="stats">
  <div class="sc b"><div class="n">{len(bull)}</div><div class="l">多头</div></div>
  <div class="sc g"><div class="n">{len(bear)}</div><div class="l">空头</div></div>
  <div class="sc"><div class="n" style="color:#c9a84c">{result['meta']['n_contracts']-len(bull)-len(bear)}</div><div class="l">中性</div></div>
</div>

<div style="margin:16px 0;display:flex;flex-wrap:wrap;gap:6px;font-size:11px">
{''.join([f'<span style="background:#c9a84c20;padding:2px 8px;border-radius:4px;color:#c9a84c">{f["name"].split("_")[1]}: {f["desc"]}</span>' for f in usable_factors])}
</div>

<table id="tbl"><thead><tr>
<th onclick="sortBy(0)" data-num="1">#</th>
<th onclick="sortBy(1)">品种</th>
<th onclick="sortBy(2)" data-num="1">确排</th>
<th onclick="sortBy(3)" data-num="1">净排</th>
{f_cols}
<th>否决</th><th>阶段</th><th>维度</th>
</tr></thead><tbody id="tb"></tbody></table>

<div style="margin-top:20px;background:#1a1d28;border-radius:10px;padding:16px 20px;border:1px solid #2a2d3a">
<h3 style="color:#c9a84c;font-size:14px;margin-bottom:8px">法官席状态</h3>
<table style="width:auto;font-size:12px">
<tr style="background:#252940"><th>状态</th><th>维度</th><th>有效/总数</th><th>可用率</th></tr>
{validity_rows}
</table>
</div>

<script>
var DATA = {rows_json};
var _sortCol = -1, _sortAsc = true;
function render() {{
    var data = DATA.slice();
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
        var nc = d.net > 0 ? '#c0392b' : (d.net < 0 ? '#22c55e' : '#9ca3af');
        h += '<tr><td style="text-align:center;color:#9ca3af">'+(i+1)+'</td>';
        h += '<td style="font-weight:700">'+d.sym+'</td>';
        h += '<td style="text-align:center;font-weight:700">'+d.adj.toFixed(1)+'</td>';
        h += '<td style="text-align:center;font-weight:700;color:'+nc+'">'+(d.net>0?'+':'')+d.net.toFixed(1)+'</td>';
        var dimKeys = Object.keys(d.dims);
        for (var j=0;j<dimKeys.length;j++) {{
            var v = d.dims[dimKeys[j]];
            var dc = v >= 70 ? '#22c55e' : (v <= 30 ? '#ef4444' : '#9ca3af');
            h += '<td style="text-align:center;color:'+dc+'">'+v.toFixed(0)+'</td>';
        }}
        h += '<td style="text-align:center;color:#ef4444;font-size:11px">'+d.veto.toFixed(2)+'</td>';
        h += '<td style="text-align:center;font-size:11px;color:#9ca3af">'+d.mat+'</td>';
        h += '<td style="text-align:center;color:#f59e0b;font-size:11px">'+d.ad+'/6</td></tr>';
    }}
    document.getElementById('tb').innerHTML = h;
}}
function _val(d,col) {{
    var dimKeys = Object.keys(d.dims);
    var dimVals = dimKeys.map(function(k){{ return d.dims[k]; }});
    return [d.r, d.sym, d.adj, d.net].concat(dimVals)[col];
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
render();
</script>
</body></html>'''


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='真分层打分 v2.0 — AKShare OI + 通达信TDX')
    parser.add_argument('--output', '-o', help='输出目录')
    parser.add_argument('--symbols', '-s', help='指定品种')
    parser.add_argument('--reverse', '-r', action='store_true', default=False,
                        help='反向模式：做空高排名品种（回测显示IC为负，反向有效）')
    parser.add_argument('--report', type=str, default=None,
                        help='扫描后生成报告: debate（辩论报告）')
    args = parser.parse_args()

    custom_symbols = None
    if args.symbols:
        sym_map = {sym: name for sym, name in ALL_SYMBOLS}
        codes = [s.strip().upper() for s in args.symbols.split(',')]
        custom_symbols = [(s, sym_map.get(s, s)) for s in codes]

    output_dir = args.output
    if not output_dir:
        workspace = os.path.expanduser('~')
        output_dir = os.path.join(workspace, 'Documents', 'WorkBuddy', 'Commodities',
                                  'Reports', '商品期货深度分析', date.today().strftime('%Y-%m-%d'))

    _result = run_scan(output_dir=output_dir, symbols=custom_symbols, reverse=args.reverse)
    if output_dir:
        result, output = _result
    else:
        result, output = _result[0], None

    # 报告生成（不干扰主流程）
    if args.report == 'debate' and output:
        try:
            from signals.report import generate_debate_html_report
            html = generate_debate_html_report(output)
            path = os.path.join(output_dir, f'debate_{output["meta"]["date"]}.html')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f'[OK] 辩论报告: {path}')
        except Exception as e:
            import traceback
            print(f'[!] 辩论报告生成失败: {e}')
            traceback.print_exc()
