# -*- coding: utf-8 -*-
"""技术面分析 skill — 观澜 Agent 的方法 skill。

趋势判定、量价分析、背离捕捉、席位资金流、形态识别与假突破验证。
"""

from typing import Dict, Optional, List

# ── 趋势判定 ──

def analyze_trend(symbol: str, kline_data: Optional[Dict] = None) -> Dict:
    """判定品种趋势状态：MA排列、ADX强度、波段方向。

    Args:
        symbol: 品种代码
        kline_data: 可选，外部传入的K线数据（含 ma20/ma60/ma250/adx 等字段）

    Returns:
        dict: {ma_alignment, adx_strength, wave_direction, summary}
    """
    if kline_data:
        ma20 = kline_data.get('ma20')
        ma60 = kline_data.get('ma60')
        ma250 = kline_data.get('ma250')
        adx = kline_data.get('adx', 0)
        if ma20 and ma60 and ma250:
            if ma20 > ma60 > ma250:
                ma_alignment = '多头排列'
            elif ma20 < ma60 < ma250:
                ma_alignment = '空头排列'
            else:
                ma_alignment = '交叉缠绕'
        else:
            ma_alignment = '数据不足'
        if adx >= 40:
            adx_strength = '强趋势'
        elif adx >= 25:
            adx_strength = '中等趋势'
        else:
            adx_strength = '弱趋势/震荡'
        return {
            "ma_alignment": ma_alignment,
            "adx": round(adx, 1),
            "adx_strength": adx_strength,
            "summary": f"{ma_alignment}，ADX{adx_strength}",
        }

    # 无数据时返回模板说明
    return {
        "ma_alignment": "待读取scan_all.py数据",
        "adx": None,
        "adx_strength": "待计算",
        "summary": "请从数技师数据包中读取MA排列和ADX值后调用本函数",
    }


def check_momentum(symbol: str, rsi: Optional[float] = None, cci: Optional[float] = None) -> Dict:
    """检查动量状态：RSI超买超卖、CCI极端值。

    Args:
        symbol: 品种代码
        rsi: RSI14值
        cci: CCI值

    Returns:
        dict: {rsi_status, cci_status, momentum_signal}
    """
    result = {}
    if rsi is not None:
        if rsi >= 70:
            result['rsi_status'] = '超买区'
            result['rsi_signal'] = '超买预警'
        elif rsi <= 30:
            result['rsi_status'] = '超卖区'
            result['rsi_signal'] = '超卖预警'
        else:
            result['rsi_status'] = '中性区'
            result['rsi_signal'] = '正常'
        result['rsi'] = round(rsi, 1)

    if cci is not None:
        if cci >= 200:
            result['cci_status'] = '极度偏高'
            result['cci_signal'] = '超买'
        elif cci >= 100:
            result['cci_status'] = '偏高'
            result['cci_signal'] = '偏多'
        elif cci <= -200:
            result['cci_status'] = '极度偏低'
            result['cci_signal'] = '超卖'
        elif cci <= -100:
            result['cci_status'] = '偏低'
            result['cci_signal'] = '偏空'
        else:
            result['cci_status'] = '中性'
            result['cci_signal'] = '正常'
        result['cci'] = round(cci, 1)

    return result
