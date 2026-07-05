# -*- coding: utf-8 -*-
"""
期货手续费参考表 — 供风控明交易摩擦计算使用
===========================================
来源：各交易所官网公布标准（2026年更新）
注意：实际费率因期货公司加收而不同，此处为交易所基准

fee_type: 'fixed' = 元/手, 'ratio' = 万分之
"""
from typing import Dict

# fee: 开仓手续费
# close_fee: 平仓手续费（注意：部分品种平今仓免收或加倍）

FEE_TABLE: Dict[str, Dict] = {
    # 黑色系
    'rb': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},
    'hc': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},
    'i':  {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 100},
    'j':  {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.00014, 'multiplier': 100},
    'jm': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.00014, 'multiplier': 60},
    'SF': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'SM': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},

    # 能源链
    'sc': {'fee_type': 'fixed', 'fee': 20.0, 'close_today': 20.0, 'multiplier': 1000},
    'lu': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},
    'fu': {'fee_type': 'ratio', 'fee': 0.00005, 'close_today': 0.00005, 'multiplier': 10},
    'bu': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},
    'pg': {'fee_type': 'fixed', 'fee': 6.0, 'close_today': 6.0, 'multiplier': 20},
    'PX': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},

    # 聚酯链
    'TA': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'PF': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'PR': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'eg': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 10},
    'eb': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},

    # 塑化链
    'v':  {'fee_type': 'fixed', 'fee': 1.0, 'close_today': 1.0, 'multiplier': 5},
    'pp': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 5},
    'l':  {'fee_type': 'fixed', 'fee': 1.0, 'close_today': 1.0, 'multiplier': 5},
    'MA': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},

    # 化工
    'SH': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},
    'SA': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 20},
    'UR': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 20},

    # 有色金属
    'cu': {'fee_type': 'ratio', 'fee': 0.00005, 'close_today': 0.0001, 'multiplier': 5},
    'al': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'zn': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 5},
    'pb': {'fee_type': 'ratio', 'fee': 0.00004, 'close_today': 0.00004, 'multiplier': 5},
    'ni': {'fee_type': 'fixed', 'fee': 1.0, 'close_today': 1.0, 'multiplier': 1},
    'sn': {'fee_type': 'fixed', 'fee': 1.0, 'close_today': 1.0, 'multiplier': 1},
    'ao': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 20},
    'SS': {'fee_type': 'fixed', 'fee': 2.0, 'close_today': 2.0, 'multiplier': 5},

    # 贵金属
    'au': {'fee_type': 'fixed', 'fee': 10.0, 'close_today': 10.0, 'multiplier': 1000},
    'ag': {'fee_type': 'ratio', 'fee': 0.00005, 'close_today': 0.00005, 'multiplier': 15},

    # 油脂油料
    'a':  {'fee_type': 'fixed', 'fee': 2.0, 'close_today': 2.0, 'multiplier': 10},
    'b':  {'fee_type': 'fixed', 'fee': 2.0, 'close_today': 2.0, 'multiplier': 10},
    'm':  {'fee_type': 'fixed', 'fee': 1.5, 'close_today': 1.5, 'multiplier': 10},
    'y':  {'fee_type': 'fixed', 'fee': 2.5, 'close_today': 2.5, 'multiplier': 10},
    'p':  {'fee_type': 'fixed', 'fee': 2.5, 'close_today': 2.5, 'multiplier': 10},
    'OI': {'fee_type': 'fixed', 'fee': 2.0, 'close_today': 2.0, 'multiplier': 10},
    'RM': {'fee_type': 'fixed', 'fee': 1.5, 'close_today': 1.5, 'multiplier': 10},
    'PK': {'fee_type': 'fixed', 'fee': 4.0, 'close_today': 4.0, 'multiplier': 5},

    # 农产品
    'c':  {'fee_type': 'fixed', 'fee': 1.2, 'close_today': 1.2, 'multiplier': 10},
    'cs': {'fee_type': 'fixed', 'fee': 1.5, 'close_today': 1.5, 'multiplier': 10},
    'SR': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 10},
    'CF': {'fee_type': 'fixed', 'fee': 4.3, 'close_today': 4.3, 'multiplier': 5},
    'jd': {'fee_type': 'ratio', 'fee': 0.00015, 'close_today': 0.00015, 'multiplier': 5},
    'lh': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0002, 'multiplier': 16},

    # 果蔬
    'AP': {'fee_type': 'fixed', 'fee': 5.0, 'close_today': 5.0, 'multiplier': 10},
    'CJ': {'fee_type': 'fixed', 'fee': 5.0, 'close_today': 5.0, 'multiplier': 5},

    # 建材化工
    'FG': {'fee_type': 'fixed', 'fee': 6.0, 'close_today': 6.0, 'multiplier': 20},
    'ru': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 10},
    'nr': {'fee_type': 'fixed', 'fee': 3.0, 'close_today': 3.0, 'multiplier': 10},
    'br': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 5},
    'sp': {'fee_type': 'ratio', 'fee': 0.00005, 'close_today': 0.00005, 'multiplier': 10},
    'op': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 10},

    # 新能源
    'lc': {'fee_type': 'ratio', 'fee': 0.00008, 'close_today': 0.00008, 'multiplier': 1},
    'si': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 5},
    'ps': {'fee_type': 'ratio', 'fee': 0.0001, 'close_today': 0.0001, 'multiplier': 5},

    # 航运
    'ec': {'fee_type': 'ratio', 'fee': 0.00005, 'close_today': 0.0001, 'multiplier': 50},
}


def get_fee_info(symbol: str) -> Dict:
    """获取品种手续费信息。未找到时返回默认值（万1）。"""
    return FEE_TABLE.get(symbol.lower(), {
        'fee_type': 'ratio', 'fee': 0.0001,
        'close_today': 0.0001, 'multiplier': 10,
    })


def calc_total_fee(symbol: str, entry_price: float, lots: int) -> float:
    """计算完整交易手续费（双边）。"""
    info = get_fee_info(symbol)
    multiplier = info.get('multiplier', 10)

    if info['fee_type'] == 'fixed':
        # 固定元/手
        fee_per_lot = info['fee']
        close_fee = info.get('close_today', fee_per_lot)
        return (fee_per_lot + close_fee) * lots
    else:
        # 万分之
        notional = entry_price * lots * multiplier
        fee_rate = info['fee']
        close_rate = info.get('close_today', fee_rate)
        return notional * (fee_rate + close_rate)
