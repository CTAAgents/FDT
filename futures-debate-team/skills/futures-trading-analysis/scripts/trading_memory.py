# -*- coding: utf-8 -*-
"""
交易记忆 & 反思系统 — 供辩论专家团使用
============================================
利用已有 trade_journal.py 的 PnL记录，在辩论环节注入历史决策反思。

功能：
- load_memory(symbol): 读取某品种的历史决策记录+盈亏
- build_reflection_prompt(symbol): 生成供闫判官/策执远参考的反思prompt
- record_decision(symbol, direction, entry, reason): 记录本次决策
- record_outcome(symbol, exit_price, pnl): 记录结果

持久化路径: data/trading_memory/{symbol}.json
"""
import json, os
from datetime import datetime
from typing import Dict, List, Optional

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'data', 'trading_memory')


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _memory_path(symbol: str) -> str:
    return os.path.join(MEMORY_DIR, f'{symbol.lower()}.json')


def load_memory(symbol: str, max_records: int = 10) -> List[Dict]:
    """读取某品种的历史决策记录（最近N条）。"""
    path = _memory_path(symbol)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data if isinstance(data, list) else data.get('records', [])
        return sorted(records, key=lambda r: r.get('timestamp', ''), reverse=True)[:max_records]
    except Exception:
        return []


def record_decision(symbol: str, direction: str, entry_price: float,
                    reason: str, confidence: float = 0.0) -> str:
    """记录本次辩论决策。

    Returns: trade_id (str)
    """
    _ensure_dir()
    path = _memory_path(symbol)
    records = load_memory(symbol, max_records=100)  # 无限制读取

    trade_id = f'{symbol}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    record = {
        'trade_id': trade_id,
        'symbol': symbol.upper(),
        'direction': direction,
        'entry_price': entry_price,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'reason': reason,
        'confidence': confidence,
        'exit_price': None,
        'pnl_pct': None,
        'pnl_points': None,
        'status': 'open',
    }

    records.append(record)
    # 只保留最近的200条
    records = records[-200:]

    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'symbol': symbol.upper(), 'records': records},
                  f, ensure_ascii=False, indent=2)

    return trade_id


def record_outcome(trade_id: str, exit_price: float, pnl_pct: float) -> bool:
    """记录平仓结果。"""
    # 搜索所有记忆文件
    _ensure_dir()
    for fname in os.listdir(MEMORY_DIR):
        if not fname.endswith('.json'):
            continue
        path = os.path.join(MEMORY_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            records = data.get('records', [])
            for i, rec in enumerate(records):
                if rec.get('trade_id') == trade_id:
                    records[i]['exit_price'] = exit_price
                    records[i]['pnl_pct'] = round(pnl_pct, 2)
                    records[i]['pnl_points'] = round(abs(exit_price - rec['entry_price']), 1)
                    records[i]['status'] = 'closed'
                    records[i]['close_date'] = datetime.now().strftime('%Y-%m-%d')
                    data['records'] = records
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return True
        except Exception:
            continue
    return False


def build_reflection_prompt(symbol: str) -> str:
    """生成供闫判官/策执远参考的反思prompt注入。"""
    records = load_memory(symbol, max_records=5)
    if not records:
        return ''

    closed = [r for r in records if r.get('status') == 'closed']
    open_records = [r for r in records if r.get('status') == 'open']

    parts = []
    parts.append(f'【交易记忆 — {symbol.upper()}】')

    if closed:
        total = len(closed)
        wins = sum(1 for r in closed if r.get('pnl_pct', 0) > 0)
        total_pnl = sum(r.get('pnl_pct', 0) for r in closed)
        parts.append(f'近{total}次已平仓: 胜{wins}/{total} ({wins/total*100:.0f}%) 总盈亏{total_pnl:+.1f}%')

        # 最近的3条详细记录
        for r in closed[:3]:
            dir_label = '做多' if r.get('direction') == 'BUY' else '做空'
            pnl = r.get('pnl_pct', 0)
            pnl_icon = '✅' if pnl > 0 else '❌'
            parts.append(f'  {pnl_icon} {r.get("date","?")} {dir_label}@{r.get("entry_price",0)} → {r.get("exit_price",0)} PnL{pnl:+.1f}%')

    if open_records:
        parts.append(f'当前持仓: {len(open_records)}笔')

    return '\n'.join(parts)


def get_performance_summary(symbol: str = None) -> Dict:
    """获取整体表现摘要。"""
    _ensure_dir()
    all_closed = []

    targets = [f'{symbol.lower()}.json'] if symbol else os.listdir(MEMORY_DIR)

    for fname in targets:
        if not fname.endswith('.json'):
            continue
        path = os.path.join(MEMORY_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for rec in data.get('records', []):
                if rec.get('status') == 'closed' and rec.get('pnl_pct') is not None:
                    all_closed.append(rec)
        except Exception:
            continue

    if not all_closed:
        return {'status': 'NO_DATA'}

    total = len(all_closed)
    wins = sum(1 for r in all_closed if r.get('pnl_pct', 0) > 0)
    total_pnl = sum(r.get('pnl_pct', 0) for r in all_closed)
    avg_pnl = total_pnl / total
    max_win = max(r.get('pnl_pct', 0) for r in all_closed)
    max_loss = min(r.get('pnl_pct', 0) for r in all_closed)

    return {
        'status': 'OK',
        'total_trades': total,
        'win_rate': round(wins / total * 100, 1),
        'total_pnl_pct': round(total_pnl, 2),
        'avg_pnl_pct': round(avg_pnl, 2),
        'max_win_pct': round(max_win, 2),
        'max_loss_pct': round(max_loss, 2),
        'symbols': len(set(r.get('symbol') for r in all_closed)),
    }
