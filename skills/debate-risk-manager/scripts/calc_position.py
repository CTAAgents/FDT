# -*- coding: utf-8 -*-
"""仓位计算模块 — 杠杆/保证金/止损/仓位沙盘推演。

遵循铁律：
- 杠杆 > 3倍权益 → 🔴 red
- 保证金占用 > 60% → 🔴 red
- 单笔止损 > 5%权益 → 🔴 red
- 左侧信号仓位 ≤ 标准仓位50%
"""

from typing import Dict, Tuple


def calc_margin_per_lot(price: float, lot_size: int, margin_rate: float) -> float:
    """计算单手保证金。

    Args:
        price: 合约价格（元/吨 或 点）
        lot_size: 合约乘数（吨/手）
        margin_rate: 保证金率（如 0.10 = 10%）

    Returns:
        单手保证金（元）
    """
    return price * lot_size * margin_rate


def calc_contract_value(price: float, lot_size: int, lots: int) -> float:
    """计算合约总价值。

    Args:
        price: 合约价格
        lot_size: 合约乘数
        lots: 手数

    Returns:
        合约总价值（元）
    """
    return price * lot_size * lots


def calc_leverage(contract_value: float, equity: float) -> float:
    """计算实际杠杆倍数。

    Args:
        contract_value: 合约总价值
        equity: 账户权益

    Returns:
        杠杆倍数（如 2.5 = 2.5倍）
    """
    if equity <= 0:
        return float("inf")
    return round(contract_value / equity, 2)


def calc_margin_usage(total_margin: float, equity: float) -> Tuple[float, str]:
    """计算保证金占用比例。

    Args:
        total_margin: 总保证金占用
        equity: 账户权益

    Returns:
        (比例, 等级): 如 (0.35, 'green')
    """
    if equity <= 0:
        return (1.0, "red")
    ratio = total_margin / equity
    if ratio > 0.60:
        level = "red"
    elif ratio > 0.40:
        level = "yellow"
    else:
        level = "green"
    return (round(ratio, 4), level)


def calc_stop_loss_pct(stop_amount: float, equity: float) -> Tuple[float, str]:
    """计算单笔止损占权益比例。

    Args:
        stop_amount: 止损金额（价差 × 乘数 × 手数）
        equity: 账户权益

    Returns:
        (比例, 等级): 如 (0.04, 'yellow')
    """
    if equity <= 0:
        return (1.0, "red")
    ratio = stop_amount / equity
    if ratio > 0.05:
        level = "red"
    elif ratio > 0.03:
        level = "yellow"
    else:
        level = "green"
    return (round(ratio, 4), level)


def calc_position_risk(
    price: float,
    lot_size: int,
    margin_rate: float,
    equity: float,
    stop_loss_points: float,
    lots: int,
    is_left_signal: bool = False,
) -> Dict:
    """完整计算一手/多手持仓的风控指标。

    Args:
        price: 合约价格
        lot_size: 合约乘数（吨/手）
        margin_rate: 保证金率
        equity: 账户权益
        stop_loss_points: 止损价差（入场价 - 止损价 的绝对值）
        lots: 拟开仓手数
        is_left_signal: 是否为左侧信号（左侧需减半仓）

    Returns:
        dict: 包含 all 风控指标 + red/yellow flags
    """
    margin_per_lot = calc_margin_per_lot(price, lot_size, margin_rate)
    total_margin = margin_per_lot * lots
    contract_value = calc_contract_value(price, lot_size, lots)

    leverage = calc_leverage(contract_value, equity)
    margin_ratio, margin_level = calc_margin_usage(total_margin, equity)
    stop_amount = stop_loss_points * lot_size * lots
    stop_ratio, stop_level = calc_stop_loss_pct(stop_amount, equity)

    # Safe max by stop loss (5% of equity)
    safe_max_by_stop = int((equity * 0.05) / (stop_loss_points * lot_size)) if stop_loss_points > 0 else 0

    # Safe max by leverage (3x)
    safe_max_by_leverage = int((equity * 3) / (price * lot_size)) if price > 0 else 0

    # Left signal adjustment
    if is_left_signal:
        lots = max(1, lots // 2)

    safe_max = (
        min(safe_max_by_stop, safe_max_by_leverage)
        if safe_max_by_stop and safe_max_by_leverage
        else max(safe_max_by_stop, safe_max_by_leverage)
    )

    # Generate flags
    flags = []
    if leverage > 3:
        flags.append({"level": "red", "msg": f"杠杆{leverage}倍，超过3倍红线"})
    if margin_ratio > 0.60:
        flags.append({"level": "red", "msg": f"保证金占用{margin_ratio:.0%}，超过60%红线"})
    if stop_ratio > 0.05:
        flags.append({"level": "red", "msg": f"止损幅度{stop_ratio:.1%}，超过5%权益"})
    if margin_ratio > 0.40 and margin_ratio <= 0.60:
        flags.append({"level": "yellow", "msg": f"保证金占用{margin_ratio:.0%}，接近警戒线"})
    if stop_ratio > 0.03 and stop_ratio <= 0.05:
        flags.append({"level": "yellow", "msg": f"止损幅度{stop_ratio:.1%}，超过3%需注意"})
    if is_left_signal:
        flags.append({"level": "yellow", "msg": "左侧信号，仓位已自动减半"})

    return {
        "lots": lots,
        "margin_per_lot": round(margin_per_lot, 0),
        "total_margin": round(total_margin, 0),
        "contract_value": round(contract_value, 0),
        "leverage": leverage,
        "margin_ratio": margin_ratio,
        "margin_level": margin_level,
        "stop_ratio": stop_ratio,
        "stop_level": stop_level,
        "safe_max_by_stop": safe_max_by_stop,
        "safe_max_by_leverage": safe_max_by_leverage,
        "safe_max": max(1, safe_max),
        "is_left_signal": is_left_signal,
        "flags": flags,
    }
