# -*- coding: utf-8 -*-
"""早期信号检测模块：识别趋势启动初期的信号，解决信号滞后问题。

核心思路：
1. 检测成交量异动（放量突破）
2. 检测价格突破关键阻力/支撑位
3. 检测波动率突破（ATR收缩后扩张）
4. 检测持仓量变化（增仓突破）
5. 使用更短周期指标（5周期）作为早期预警

设计原则：
- 宁可错过，不可做错：早期信号需要更多确认
- 多重验证：至少3个早期信号同时出现才触发
- 右侧确认：早期信号必须等待价格行为确认
"""

from typing import List
import numpy as np


def detect_volume_surge(volumes: List[float], threshold: float = 1.5, lookback: int = 20) -> dict:
    """检测成交量异动（放量突破）。
    
    Args:
        volumes: 成交量序列
        threshold: 突破阈值（当前成交量/均量）
        lookback: 均量计算周期
    
    Returns:
        {
            'surge': bool,  # 是否出现放量
            'ratio': float,  # 当前成交量/均量
            'avg_volume': float,  # 均量
            'current_volume': float,  # 当前成交量
            'signal_strength': str,  # 信号强度：'strong', 'moderate', 'weak'
        }
    """
    if len(volumes) < lookback + 1:
        return {'surge': False, 'ratio': 0, 'avg_volume': 0, 'current_volume': 0, 'signal_strength': 'weak'}
    
    # 计算均量（排除最后一根K线）
    avg_volume = np.mean(volumes[-(lookback+1):-1])
    current_volume = volumes[-1]
    
    if avg_volume <= 0:
        return {'surge': False, 'ratio': 0, 'avg_volume': 0, 'current_volume': current_volume, 'signal_strength': 'weak'}
    
    ratio = current_volume / avg_volume
    
    # 判断信号强度
    # 基于ratio本身进行强度分类
    # ratio >= 3.0：strong（非常强）
    # ratio >= 2.0：strong（强）
    # ratio >= threshold：moderate（中等）
    # 否则：weak（弱）
    if ratio >= 2.0:
        signal_strength = 'strong'
    elif ratio >= threshold:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'surge': ratio >= threshold,
        'ratio': round(ratio, 2),
        'avg_volume': round(avg_volume, 2),
        'current_volume': current_volume,
        'signal_strength': signal_strength,
    }


def detect_price_breakout(prices: List[float], highs: List[float], lows: List[float], 
                         lookback: int = 20, buffer_pct: float = 0.005) -> dict:
    """检测价格突破关键阻力/支撑位。
    
    Args:
        prices: 收盘价序列
        highs: 最高价序列
        lows: 最低价序列
        lookback: 前高前低计算周期
        buffer_pct: 突破缓冲区（0.5%）
    
    Returns:
        {
            'breakout_up': bool,  # 向上突破
            'breakout_down': bool,  # 向下突破
            'resistance': float,  # 阻力位
            'support': float,  # 支撑位
            'current_price': float,  # 当前价格
            'breakout_pct': float,  # 突破幅度
            'signal_strength': str,  # 信号强度
        }
    """
    if len(prices) < lookback + 1 or len(highs) < lookback + 1 or len(lows) < lookback + 1:
        return {
            'breakout_up': False, 'breakout_down': False,
            'resistance': 0, 'support': 0, 'current_price': 0,
            'breakout_pct': 0, 'signal_strength': 'weak'
        }
    
    # 计算前高前低（排除最后一根K线）
    recent_high = max(highs[-(lookback+1):-1])
    recent_low = min(lows[-(lookback+1):-1])
    current_price = prices[-1]
    
    # 计算缓冲区
    resistance_buffer = recent_high * (1 + buffer_pct)
    support_buffer = recent_low * (1 - buffer_pct)
    
    # 判断突破
    breakout_up = current_price > resistance_buffer
    breakout_down = current_price < support_buffer
    
    # 计算突破幅度
    if breakout_up:
        breakout_pct = (current_price - recent_high) / recent_high * 100
    elif breakout_down:
        breakout_pct = (recent_low - current_price) / recent_low * 100
    else:
        breakout_pct = 0
    
    # 判断信号强度
    if abs(breakout_pct) > 2:
        signal_strength = 'strong'
    elif abs(breakout_pct) > 1:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'breakout_up': breakout_up,
        'breakout_down': breakout_down,
        'resistance': round(recent_high, 2),
        'support': round(recent_low, 2),
        'current_price': current_price,
        'breakout_pct': round(breakout_pct, 2),
        'signal_strength': signal_strength,
    }


def detect_volatility_expansion(atr_values: List[float], lookback: int = 20, 
                               expansion_threshold: float = 1.5) -> dict:
    """检测波动率突破（ATR收缩后扩张）。
    
    Args:
        atr_values: ATR值序列
        lookback: 均值计算周期
        expansion_threshold: 扩张阈值（当前ATR/均值）
    
    Returns:
        {
            'expansion': bool,  # 是否出现波动率扩张
            'ratio': float,  # 当前ATR/均值
            'avg_atr': float,  # 平均ATR
            'current_atr': float,  # 当前ATR
            'is_contraction': bool,  # 是否处于收缩状态
            'signal_strength': str,  # 信号强度
        }
    """
    if len(atr_values) < lookback + 1:
        return {
            'expansion': False, 'ratio': 0, 'avg_atr': 0, 'current_atr': 0,
            'is_contraction': False, 'signal_strength': 'weak'
        }
    
    # 计算平均ATR（排除最后一根K线）
    avg_atr = np.mean(atr_values[-(lookback+1):-1])
    current_atr = atr_values[-1]
    
    if avg_atr <= 0:
        return {
            'expansion': False, 'ratio': 0, 'avg_atr': 0, 'current_atr': current_atr,
            'is_contraction': False, 'signal_strength': 'weak'
        }
    
    ratio = current_atr / avg_atr
    
    # 判断是否处于收缩状态（历史ATR低于均值）
    # 检查最近5个ATR值是否都低于或等于均值（排除最后一根K线）
    if len(atr_values) >= 6:
        recent_atr = atr_values[-6:-1]  # 最近5个ATR值（排除最后一根）
        is_contraction = all(atr <= avg_atr for atr in recent_atr)
    else:
        is_contraction = ratio < 0.8
    
    # 判断是否出现扩张（从收缩状态突然扩张）
    expansion = is_contraction and ratio > expansion_threshold
    
    # 判断信号强度
    if expansion and ratio > expansion_threshold * 1.5:
        signal_strength = 'strong'
    elif expansion:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'expansion': expansion,
        'ratio': round(ratio, 2),
        'avg_atr': round(avg_atr, 4),
        'current_atr': round(current_atr, 4),
        'is_contraction': is_contraction,
        'signal_strength': signal_strength,
    }


def detect_open_interest_change(open_interests: List[int], prices: List[float], 
                               lookback: int = 5, oi_change_threshold: float = 0.05) -> dict:
    """检测持仓量变化（增仓突破）。
    
    Args:
        open_interests: 持仓量序列
        prices: 收盘价序列
        lookback: 变化计算周期
        oi_change_threshold: 持仓量变化阈值（10%）
    
    Returns:
        {
            'oi_increase': bool,  # 持仓量增加
            'oi_decrease': bool,  # 持仓量减少
            'oi_change_pct': float,  # 持仓量变化百分比
            'price_direction': str,  # 价格方向：'up', 'down', 'flat'
            'divergence': bool,  # 量价背离
            'signal_strength': str,  # 信号强度
        }
    """
    if len(open_interests) < lookback + 1 or len(prices) < lookback + 1:
        return {
            'oi_increase': False, 'oi_decrease': False, 'oi_change_pct': 0,
            'price_direction': 'flat', 'divergence': False, 'signal_strength': 'weak'
        }
    
    # 计算持仓量变化
    current_oi = open_interests[-1]
    past_oi = open_interests[-(lookback+1)]
    
    if past_oi <= 0:
        return {
            'oi_increase': False, 'oi_decrease': False, 'oi_change_pct': 0,
            'price_direction': 'flat', 'divergence': False, 'signal_strength': 'weak'
        }
    
    oi_change_pct = (current_oi - past_oi) / past_oi
    
    # 计算价格方向
    current_price = prices[-1]
    past_price = prices[-(lookback+1)]
    price_change_pct = (current_price - past_price) / past_price if past_price > 0 else 0
    
    if price_change_pct > 0.01:
        price_direction = 'up'
    elif price_change_pct < -0.01:
        price_direction = 'down'
    else:
        price_direction = 'flat'
    
    # 判断持仓量变化
    oi_increase = oi_change_pct >= oi_change_threshold
    oi_decrease = oi_change_pct <= -oi_change_threshold
    
    # 判断量价背离
    divergence = (oi_increase and price_direction == 'down') or (oi_decrease and price_direction == 'up')
    
    # 判断信号强度
    if abs(oi_change_pct) > oi_change_threshold * 2:
        signal_strength = 'strong'
    elif abs(oi_change_pct) > oi_change_threshold:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'oi_increase': oi_increase,
        'oi_decrease': oi_decrease,
        'oi_change_pct': round(oi_change_pct * 100, 2),
        'price_direction': price_direction,
        'divergence': divergence,
        'signal_strength': signal_strength,
    }


def detect_short_term_momentum(closes: List[float], period: int = 5) -> dict:
    """检测短期动量（5周期RSI、5周期MA）。
    
    Args:
        closes: 收盘价序列
        period: 短周期
    
    Returns:
        {
            'rsi_5': float,  # 5周期RSI
            'ma_5': float,  # 5周期MA
            'price_vs_ma5': str,  # 价格相对于MA5：'above', 'below', 'at'
            'momentum': str,  # 动量：'strong_up', 'up', 'neutral', 'down', 'strong_down'
            'signal_strength': str,  # 信号强度
        }
    """
    if len(closes) < period + 1:
        return {
            'rsi_5': 50, 'ma_5': 0, 'price_vs_ma5': 'at',
            'momentum': 'neutral', 'signal_strength': 'weak'
        }
    
    # 计算5周期RSI
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(0, change) for change in changes[-period:]]
    losses = [max(0, -change) for change in changes[-period:]]
    
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0
    
    if avg_loss == 0 and avg_gain == 0:
        rsi_5 = 50  # 无变化时RSI为50
    elif avg_loss == 0:
        rsi_5 = 100
    else:
        rs = avg_gain / avg_loss
        rsi_5 = 100 - (100 / (1 + rs))
    
    # 计算5周期MA
    ma_5 = np.mean(closes[-period:])
    current_price = closes[-1]
    
    # 判断价格相对于MA5
    if current_price > ma_5 * 1.005:
        price_vs_ma5 = 'above'
    elif current_price < ma_5 * 0.995:
        price_vs_ma5 = 'below'
    else:
        price_vs_ma5 = 'at'
    
    # 判断动量
    if rsi_5 > 70 and price_vs_ma5 == 'above':
        momentum = 'strong_up'
    elif rsi_5 > 60:
        momentum = 'up'
    elif rsi_5 < 30 and price_vs_ma5 == 'below':
        momentum = 'strong_down'
    elif rsi_5 < 40:
        momentum = 'down'
    else:
        momentum = 'neutral'
    
    # 判断信号强度
    if momentum in ['strong_up', 'strong_down']:
        signal_strength = 'strong'
    elif momentum in ['up', 'down']:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'rsi_5': round(rsi_5, 2),
        'ma_5': round(ma_5, 2),
        'price_vs_ma5': price_vs_ma5,
        'momentum': momentum,
        'signal_strength': signal_strength,
    }


def detect_ma_convergence(prices: List[float], short_period: int = 5, long_period: int = 20) -> dict:
    """检测均线收敛（短期均线向长期均线靠拢）。
    
    Args:
        prices: 收盘价序列
        short_period: 短期均线周期
        long_period: 长期均线周期
    
    Returns:
        {
            'convergence': bool,  # 是否出现均线收敛
            'spread': float,  # 均线间距（百分比）
            'ma_short': float,  # 短期均线
            'ma_long': float,  # 长期均线
            'signal_strength': str,  # 信号强度
        }
    """
    if len(prices) < long_period + 1:
        return {
            'convergence': False, 'spread': 0, 'ma_short': 0, 'ma_long': 0,
            'signal_strength': 'weak'
        }
    
    # 计算均线
    ma_short = np.mean(prices[-short_period:])
    ma_long = np.mean(prices[-long_period:])
    
    # 计算均线间距（百分比）
    spread = abs(ma_short - ma_long) / ma_long * 100
    
    # 判断是否收敛（间距小于1%且不为0）
    # 当spread为0时，可能是数据问题，不是真正的收敛
    convergence = 0 < spread < 1.0
    
    # 判断信号强度
    # 当spread为0时，可能是数据问题，不是真正的收敛，信号强度为weak
    if spread == 0:
        signal_strength = 'weak'
    elif spread < 0.5:
        signal_strength = 'strong'
    elif spread < 1.0:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'
    
    return {
        'convergence': convergence,
        'spread': round(spread, 2),
        'ma_short': round(ma_short, 2),
        'ma_long': round(ma_long, 2),
        'signal_strength': signal_strength,
    }


def detect_early_signals(tech_data: dict, volumes: List[float], highs: List[float], 
                        lows: List[float], closes: List[float], open_interests: List[int]) -> dict:
    """综合早期信号检测。
    
    Args:
        tech_data: 技术指标数据
        volumes: 成交量序列
        highs: 最高价序列
        lows: 最低价序列
        closes: 收盘价序列
        open_interests: 持仓量序列
    
    Returns:
        {
            'early_signals_detected': int,  # 检测到的早期信号数量
            'signal_details': dict,  # 各信号详情
            'overall_signal_strength': str,  # 整体信号强度
            'early_direction': str,  # 早期方向：'bullish', 'bearish', 'neutral'
            'confidence': float,  # 置信度
            'requires_confirmation': bool,  # 是否需要确认
        }
    """
    signals = []
    signal_details = {}
    
    # 1. 成交量异动检测
    volume_signal = detect_volume_surge(volumes)
    if volume_signal['surge']:
        signals.append('volume_surge')
    signal_details['volume'] = volume_signal
    
    # 2. 价格突破检测
    breakout_signal = detect_price_breakout(closes, highs, lows)
    if breakout_signal['breakout_up'] or breakout_signal['breakout_down']:
        signals.append('price_breakout')
    signal_details['breakout'] = breakout_signal
    
    # 3. 波动率突破检测
    atr_values = tech_data.get('ATR14', [])
    if isinstance(atr_values, (int, float)):
        atr_values = [atr_values] * 20  # 如果只有单个值，创建序列
    volatility_signal = detect_volatility_expansion(atr_values)
    if volatility_signal['expansion']:
        signals.append('volatility_expansion')
    signal_details['volatility'] = volatility_signal
    
    # 4. 持仓量变化检测
    oi_signal = detect_open_interest_change(open_interests, closes)
    if oi_signal['oi_increase'] and oi_signal['price_direction'] == 'up':
        signals.append('oi_increase_up')
    elif oi_signal['oi_decrease'] and oi_signal['price_direction'] == 'down':
        signals.append('oi_decrease_down')
    signal_details['open_interest'] = oi_signal
    
    # 5. 短期动量检测
    momentum_signal = detect_short_term_momentum(closes)
    if momentum_signal['momentum'] in ['strong_up', 'strong_down']:
        signals.append('short_term_momentum')
    signal_details['momentum'] = momentum_signal
    
    # 6. 均线收敛检测
    convergence_signal = detect_ma_convergence(closes)
    if convergence_signal['convergence']:
        signals.append('ma_convergence')
    signal_details['convergence'] = convergence_signal
    
    # 计算整体信号强度
    strong_signals = sum(1 for s in signal_details.values() if s.get('signal_strength') == 'strong')
    moderate_signals = sum(1 for s in signal_details.values() if s.get('signal_strength') == 'moderate')
    
    if strong_signals >= 2:
        overall_signal_strength = 'strong'
    elif strong_signals >= 1 or moderate_signals >= 2:
        overall_signal_strength = 'moderate'
    else:
        overall_signal_strength = 'weak'
    
    # 判断早期方向
    bullish_signals = 0
    bearish_signals = 0
    
    if breakout_signal['breakout_up']:
        bullish_signals += 1
    if breakout_signal['breakout_down']:
        bearish_signals += 1
    if momentum_signal['momentum'] in ['strong_up', 'up']:
        bullish_signals += 1
    if momentum_signal['momentum'] in ['strong_down', 'down']:
        bearish_signals += 1
    if oi_signal['oi_increase'] and oi_signal['price_direction'] == 'up':
        bullish_signals += 1
    if oi_signal['oi_decrease'] and oi_signal['price_direction'] == 'down':
        bearish_signals += 1
    
    if bullish_signals > bearish_signals:
        early_direction = 'bullish'
    elif bearish_signals > bullish_signals:
        early_direction = 'bearish'
    else:
        early_direction = 'neutral'
    
    # 计算置信度（0-1）
    total_signals = len(signals)
    if total_signals >= 4:
        confidence = 0.8
    elif total_signals >= 3:
        confidence = 0.6
    elif total_signals >= 2:
        confidence = 0.4
    else:
        confidence = 0.2
    
    # 是否需要确认（早期信号需要等待价格行为确认）
    requires_confirmation = total_signals < 3
    
    return {
        'early_signals_detected': total_signals,
        'signal_details': signal_details,
        'overall_signal_strength': overall_signal_strength,
        'early_direction': early_direction,
        'confidence': confidence,
        'requires_confirmation': requires_confirmation,
        'signals_list': signals,
    }


def generate_early_signal_alert(early_signals: dict, product_id: str, product_name: str) -> str:
    """生成早期信号预警消息。
    
    Args:
        early_signals: 早期信号检测结果
        product_id: 品种代码
        product_name: 品种名称
    
    Returns:
        str: 预警消息
    """
    if early_signals['early_signals_detected'] == 0:
        return ""
    
    direction_emoji = "🟢" if early_signals['early_direction'] == 'bullish' else "🔴" if early_signals['early_direction'] == 'bearish' else "⚪"
    strength_emoji = "🔥" if early_signals['overall_signal_strength'] == 'strong' else "⚡" if early_signals['overall_signal_strength'] == 'moderate' else "💤"
    
    alert = f"{direction_emoji} {strength_emoji} 早期信号预警: {product_id} ({product_name})\n"
    alert += f"信号数量: {early_signals['early_signals_detected']}\n"
    alert += f"整体强度: {early_signals['overall_signal_strength']}\n"
    alert += f"早期方向: {early_signals['early_direction']}\n"
    alert += f"置信度: {early_signals['confidence']:.1%}\n"
    
    if early_signals['requires_confirmation']:
        alert += "⚠️ 需要等待价格行为确认\n"
    
    # 添加信号详情
    details = early_signals['signal_details']
    if details.get('volume', {}).get('surge'):
        alert += f"📊 成交量异动: {details['volume']['ratio']}倍\n"
    if details.get('breakout', {}).get('breakout_up'):
        alert += f"📈 向上突破: {details['breakout']['breakout_pct']}%\n"
    if details.get('breakout', {}).get('breakout_down'):
        alert += f"📉 向下突破: {details['breakout']['breakout_pct']}%\n"
    if details.get('volatility', {}).get('expansion'):
        alert += f"💥 波动率扩张: {details['volatility']['ratio']}倍\n"
    if details.get('open_interest', {}).get('oi_increase'):
        alert += f"📈 持仓量增加: {details['open_interest']['oi_change_pct']}%\n"
    if details.get('momentum', {}).get('momentum') in ['strong_up', 'strong_down']:
        alert += f"🚀 短期动量: {details['momentum']['momentum']}\n"
    
    return alert


# ============================================================
# v2.13 期货专属早期信号（L1层）
# ============================================================

def detect_oi_triangle(prices: List[float], open_interests: List[int],
                       volumes: List[float], lookback: int = 10) -> dict:
    """检测OI三角信号（期货专属，最早最核心）。

    OI + 价 + 量 三角组合：
    - 价横 + OI↑ + 量稳 → 建仓胚（突破前5-20根K）
    - 价微涨 + OI↑ → 多头底部建仓
    - 突破 + OI↑ + 量↑ → 真突破确认
    - 突破 + OI↓ → 假突破

    Args:
        prices: 收盘价序列
        open_interests: 持仓量序列
        volumes: 成交量序列
        lookback: 回看周期

    Returns:
        dict: OI三角信号详情
    """
    if len(prices) < lookback + 2 or len(open_interests) < lookback + 2:
        return {
            'signal': 'none', 'strength': 'weak',
            'oi_rate': 0, 'price_change_pct': 0,
            'volume_ratio': 0, 'is_building_position': False,
            'is_true_breakout': False, 'is_false_breakout': False,
        }

    current_oi = open_interests[-1]
    avg_oi = np.mean(open_interests[-(lookback+1):-1])
    current_price = prices[-1]
    past_price = prices[-(lookback+1)]
    current_vol = volumes[-1]
    avg_vol = np.mean(volumes[-(lookback+1):-1])

    oi_rate = current_oi / avg_oi if avg_oi > 0 else 1.0
    price_change_pct = (current_price - past_price) / past_price * 100 if past_price > 0 else 0
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # 判断信号类型
    is_building = False
    is_true_breakout = False
    is_false_breakout = False
    signal = 'none'
    strength = 'weak'

    # 建仓胚：价横±1.5% + OI↑
    if abs(price_change_pct) < 1.5 and oi_rate > 1.1:
        is_building = True
        signal = 'building_position'
        strength = 'strong' if oi_rate > 1.2 else 'moderate'

    # 真突破：价突破 + OI↑ + 量↑
    elif abs(price_change_pct) > 1.5 and oi_rate > 1.05 and vol_ratio > 1.2:
        is_true_breakout = True
        signal = 'true_breakout'
        strength = 'strong'

    # 假突破：价突破但OI↓
    elif abs(price_change_pct) > 1.5 and oi_rate < 0.95:
        is_false_breakout = True
        signal = 'false_breakout'
        strength = 'moderate'

    # 多头建仓：价微涨 + OI↑
    elif price_change_pct > 0.5 and price_change_pct < 3 and oi_rate > 1.05:
        signal = 'bullish_accumulation'
        strength = 'moderate'

    # 空头建仓：价微跌 + OI↑
    elif price_change_pct < -0.5 and price_change_pct > -3 and oi_rate > 1.05:
        signal = 'bearish_accumulation'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'oi_rate': round(oi_rate, 3),
        'price_change_pct': round(price_change_pct, 2),
        'volume_ratio': round(vol_ratio, 2),
        'is_building_position': is_building,
        'is_true_breakout': is_true_breakout,
        'is_false_breakout': is_false_breakout,
    }


def detect_basis_signal(basis_history: List[float], lookback: int = 5) -> dict:
    """检测基差走强/走弱信号（期货专属，比价格早1-4周）。

    Args:
        basis_history: 基差序列（正=现货升水，负=期货升水）
        lookback: MA计算周期

    Returns:
        dict: 基差信号详情
    """
    if len(basis_history) < lookback + 5:
        return {
            'signal': 'none', 'strength': 'weak',
            'basis_ma5': None, 'basis_ma20': None,
            'is_strengthening': False, 'is_weakening': False,
        }

    basis_ma5 = np.mean(basis_history[-5:])
    basis_ma20 = np.mean(basis_history[-20:]) if len(basis_history) >= 20 else np.mean(basis_history)
    current_basis = basis_history[-1]

    is_strengthening = basis_ma5 > basis_ma20
    is_weakening = basis_ma5 < basis_ma20 * 0.9

    signal = 'none'
    strength = 'weak'
    if is_strengthening:
        signal = 'basis_strengthening'
        strength = 'strong' if basis_ma5 > basis_ma20 * 1.1 else 'moderate'
    elif is_weakening:
        signal = 'basis_weakening'
        strength = 'strong' if basis_ma5 < basis_ma20 * 0.8 else 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'basis_ma5': round(basis_ma5, 2),
        'basis_ma20': round(basis_ma20, 2),
        'current_basis': round(current_basis, 2),
        'is_strengthening': is_strengthening,
        'is_weakening': is_weakening,
    }


def detect_term_structure_signal(term_structure_history: List[str]) -> dict:
    """检测期限结构切换信号（期货专属，见顶见底预警）。

    Args:
        term_structure_history: 期限结构类型序列 ('back', 'contango', 'super_back', 'super_contango', 'flat')

    Returns:
        dict: 期限结构信号详情
    """
    if len(term_structure_history) < 5:
        return {
            'signal': 'none', 'strength': 'weak',
            'current': term_structure_history[-1] if term_structure_history else 'unknown',
            'structure_alert': None,
        }

    current = term_structure_history[-1]
    recent = term_structure_history[-5:]

    # 检测结构切换预警
    structure_alert = None

    # Super Back → Flat：见顶预警
    if 'super_back' in recent[:3] and current in ('flat', 'contango', 'back'):
        structure_alert = 'super_back_to_flat'
    # Super Contango → Flat：见底预警
    elif 'super_contango' in recent[:3] and current in ('flat', 'back', 'contango'):
        structure_alert = 'super_contango_to_flat'
    # Back → Contango：趋势转折
    elif 'back' in recent[:3] and current == 'contango':
        structure_alert = 'back_to_contango'
    elif 'contango' in recent[:3] and current == 'back':
        structure_alert = 'contango_to_back'

    signal = 'none'
    strength = 'weak'
    if structure_alert:
        signal = 'structure_switch'
        strength = 'strong'

    return {
        'signal': signal,
        'strength': strength,
        'current': current,
        'recent': recent,
        'structure_alert': structure_alert,
    }


def detect_spread_signal(spread_history: List[float], lookback: int = 5) -> dict:
    """检测跨期Spread加速信号（期货专属）。

    Args:
        spread_history: 近远月价差序列
        lookback: 斜率计算周期

    Returns:
        dict: Spread信号详情
    """
    if len(spread_history) < lookback + 1:
        return {
            'signal': 'none', 'strength': 'weak',
            'spread_slope_5d': 0, 'is_widening': False, 'is_narrowing': False,
        }

    recent_spread = spread_history[-lookback:]
    # 线性回归斜率
    x = np.arange(lookback)
    slope = np.polyfit(x, recent_spread, 1)[0]

    is_widening = slope > 0.1
    is_narrowing = slope < -0.1

    signal = 'none'
    strength = 'weak'
    if abs(slope) > 0.5:
        signal = 'spread_acceleration'
        strength = 'strong'
    elif abs(slope) > 0.2:
        signal = 'spread_moderate'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'spread_slope_5d': round(slope, 3),
        'is_widening': is_widening,
        'is_narrowing': is_narrowing,
    }


def inject_early_signals_to_tech(early_signals: dict, tech: dict) -> dict:
    """将早期信号检测结果注入tech字典，供萌芽维度打分使用。

    v2.12 集成：早期信号不再仅用于预警，直接参与打分。

    Args:
        early_signals: detect_early_signals() 的输出
        tech: 技术指标字典（会被原地修改）

    Returns:
        dict: 修改后的tech字典
    """
    if not early_signals or not isinstance(early_signals, dict):
        return tech

    details = early_signals.get('signal_details', {})

    # 成交量异动 → 注入 VOL_5D_RATIO
    vol_info = details.get('volume', {})
    if vol_info.get('surge') and vol_info.get('ratio', 0) > 0:
        tech['VOL_5D_RATIO'] = vol_info['ratio']
        tech['EARLY_VOL_SURGE'] = True

    # 波动率扩张 → 注入标记
    vol_exp = details.get('volatility', {})
    if vol_exp.get('expansion'):
        tech['VOLATILITY_EXPANSION'] = True
        tech['VOL_EXPANSION_RATIO'] = vol_exp.get('ratio', 1.0)

    # 持仓量变化 → 注入标记
    oi_info = details.get('open_interest', {})
    if oi_info.get('oi_increase'):
        tech['OI_INCREASING'] = True
        tech['OI_CHANGE_PCT'] = oi_info.get('oi_change_pct', 0)
    elif oi_info.get('oi_decrease'):
        tech['OI_DECREASING'] = True

    # 短期动量 → 注入标记
    mom_info = details.get('momentum', {})
    if mom_info.get('momentum') in ('strong_up', 'up'):
        tech['SHORT_MOMENTUM_BULL'] = True
    elif mom_info.get('momentum') in ('strong_down', 'down'):
        tech['SHORT_MOMENTUM_BEAR'] = True

    # 均线收敛 → 注入标记
    conv_info = details.get('convergence', {})
    if conv_info.get('convergence'):
        tech['MA_CONVERGENCE'] = True
        tech['MA_CONVERGENCE_SPREAD'] = conv_info.get('spread', 0)

    # 早期信号整体 → 注入汇总信息
    tech['EARLY_SIGNALS_COUNT'] = early_signals.get('early_signals_detected', 0)
    tech['EARLY_SIGNALS_STRENGTH'] = early_signals.get('overall_signal_strength', 'weak')
    tech['EARLY_DIRECTION'] = early_signals.get('early_direction', 'neutral')

    return tech