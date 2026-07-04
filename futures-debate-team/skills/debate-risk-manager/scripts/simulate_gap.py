# -*- coding: utf-8 -*-
"""夜盘跳空模拟模块 — 模拟持过夜最大瞬时亏损。

期货特有风险的量化：跳空缺口可能导致止损无效，持仓亏损远超预期。
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class GapRecord:
    """历史跳空记录"""
    pct: float       # 跳空幅度（%）
    date: str        # 日期


# 品种分类跳空幅度经验值（近2年历史统计）
# 来源：各品种主力合约夜盘-日盘跳空幅度 95%分位数
DEFAULT_GAP_PERCENTILES: Dict[str, dict] = {
    'aggressive': {
        'description': '原油/COMEX金属/能化',
        'typical_gap_pct': 0.03,
        'extreme_gap_pct': 0.06,
        'examples': ['sc', 'fu', 'lu', 'ni', 'sn', 'ag'],
    },
    'moderate': {
        'description': '黑色/有色/橡胶',
        'typical_gap_pct': 0.02,
        'extreme_gap_pct': 0.04,
        'examples': ['rb', 'hc', 'i', 'cu', 'al', 'ru'],
    },
    'conservative': {
        'description': '农产品/软商品',
        'typical_gap_pct': 0.015,
        'extreme_gap_pct': 0.03,
        'examples': ['a', 'b', 'm', 'c', 'SR', 'CF'],
    },
}


def get_gap_params(symbol: str) -> dict:
    """获取品种对应的跳空参数。

    Args:
        symbol: 品种代码

    Returns:
        dict: {typical_gap_pct, extreme_gap_pct, category}
    """
    sym_upper = symbol.upper()
    for category, params in DEFAULT_GAP_PERCENTILES.items():
        if sym_upper in [e.upper() for e in params['examples']]:
            return {
                'typical_gap_pct': params['typical_gap_pct'],
                'extreme_gap_pct': params['extreme_gap_pct'],
                'category': category,
                'description': params['description'],
            }
    # 默认保守估计
    return {
        'typical_gap_pct': 0.02,
        'extreme_gap_pct': 0.04,
        'category': 'unknown',
        'description': '默认保守估计（中波动）',
    }


def simulate_gap(
    symbol: str,
    entry_price: float,
    lots: int,
    lot_size: int,
    equity: float,
    stop_loss_points: Optional[float] = None,
) -> Dict:
    """模拟夜盘跳空场景，计算持过夜最大可能亏损。

    Args:
        symbol: 品种代码
        entry_price: 入场价格
        lots: 持仓手数
        lot_size: 合约乘数
        equity: 账户权益
        stop_loss_points: 止损价差（若跳空幅度超过止损，止损失效）

    Returns:
        dict: {typical_loss, extreme_loss, gap_exceeds_stop, max_gap_pct, warnings}
    """
    params = get_gap_params(symbol)
    typical_gap = params['typical_gap_pct']
    extreme_gap = params['extreme_gap_pct']

    # 跳空导致的盈亏（取反向最大值）
    typical_loss = entry_price * typical_gap * lot_size * lots
    extreme_loss = entry_price * extreme_gap * lot_size * lots

    # 检查跳空是否超过止损
    if stop_loss_points and stop_loss_points > 0:
        stop_price = stop_loss_points * lot_size * lots
        gap_exceeds_stop_typical = typical_loss > stop_price
        gap_exceeds_stop_extreme = extreme_loss > stop_price
    else:
        gap_exceeds_stop_typical = True
        gap_exceeds_stop_extreme = True

    # 跳空亏损占权益比例
    typical_loss_pct = typical_loss / equity if equity > 0 else 1
    extreme_loss_pct = extreme_loss / equity if equity > 0 else 1

    warnings = []
    if extreme_loss_pct > 0.05:
        warnings.append(f"极端跳空亏损达权益{extreme_loss_pct:.1%}，超过5%红线")
    if gap_exceeds_stop_extreme:
        warnings.append(f"极端跳空({extreme_gap:.1%})仅止损期({stop_loss_points}点)内，止损可能被跳过")

    return {
        "symbol": symbol,
        "category": params['category'],
        "typical_gap_pct": typical_gap,
        "extreme_gap_pct": extreme_gap,
        "typical_loss": round(typical_loss, 0),
        "extreme_loss": round(extreme_loss, 0),
        "typical_loss_pct": round(typical_loss_pct, 4),
        "extreme_loss_pct": round(extreme_loss_pct, 4),
        "gap_exceeds_stop_typical": gap_exceeds_stop_typical,
        "gap_exceeds_stop_extreme": gap_exceeds_stop_extreme,
        "warnings": warnings,
    }


def calc_margin_call_scenario(
    entry_price: float,
    lots: int,
    lot_size: int,
    margin_per_lot: float,
    equity: float,
    gap_loss: float,
) -> Dict:
    """模拟追保场景：首次跳空后是否需要追加保证金。

    Args:
        entry_price: 入场价格
        lots: 持仓手数
        lot_size: 合约乘数
        margin_per_lot: 单手保证金
        equity: 初始权益
        gap_loss: 跳空亏损额

    Returns:
        dict: {remaining_equity, margin_call_needed, shortfall, new_margin_ratio}
    """
    remaining_equity = equity - gap_loss
    total_margin = margin_per_lot * lots
    new_margin_ratio = total_margin / remaining_equity if remaining_equity > 0 else 1.0
    margin_call_needed = new_margin_ratio > 0.80  # 一般期货公司强平线80%
    shortfall = total_margin - (remaining_equity * 0.80) if margin_call_needed else 0

    return {
        "remaining_equity": round(remaining_equity, 0),
        "total_margin": round(total_margin, 0),
        "new_margin_ratio": round(new_margin_ratio, 4),
        "margin_call_needed": margin_call_needed,
        "shortfall": round(max(0, shortfall), 0) if margin_call_needed else 0,
    }
