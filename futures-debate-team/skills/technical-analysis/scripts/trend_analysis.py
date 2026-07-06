# -*- coding: utf-8 -*-
"""技术面分析 skill — 趋势判定、动量检查（v2.0 增加多时间框架支持）。

v2.0 改进：
- 多时间框架：daily/60min/15min 三级分析
- ADX分档细化：5档（超强/强/中等/弱/极弱）
- 均线排列支持4种状态（新增"多头但发散/收敛"）
"""

from typing import Dict, Optional, List


# ── 多时间框架分析 ──


def analyze_trend(
    symbol: str,
    kline_data: Optional[Dict] = None,
    timeframe: str = "daily",
) -> Dict:
    """判定品种趋势状态：MA排列、ADX强度、波段方向。

    Args:
        symbol: 品种代码
        kline_data: 可选，外部传入的K线数据
        timeframe: 时间框架 "daily" / "60min" / "15min"

    Returns:
        dict: {ma_alignment, adx, adx_strength, wave_direction, summary, timeframe}
    """
    result = {"timeframe": timeframe, "symbol": symbol}

    if kline_data:
        ma20 = kline_data.get("ma20")
        ma60 = kline_data.get("ma60")
        ma250 = kline_data.get("ma250")
        adx = kline_data.get("adx", 0)

        # 均线排列（细化分级）
        if ma20 and ma60 and ma250:
            ma_alignment = _classify_ma_alignment(ma20, ma60, ma250)
        else:
            ma_alignment = "数据不足"

        # ADX分级细化
        adx_strength = _classify_adx(adx)

        # 波段方向推断
        wave_direction = _infer_wave_direction(kline_data)

        result.update(
            {
                "ma_alignment": ma_alignment,
                "adx": round(adx, 1),
                "adx_strength": adx_strength,
                "wave_direction": wave_direction,
                "summary": f"{timeframe} {ma_alignment}，ADX{adx_strength}，波段{wave_direction}",
            }
        )
        return result

    return {
        "ma_alignment": "待读取scan_all.py数据",
        "adx": None,
        "adx_strength": "待计算",
        "wave_direction": "未知",
        "summary": f"请从数技师数据包中读取{timeframe}MA排列和ADX值后调用",
        "timeframe": timeframe,
    }


def _classify_ma_alignment(ma20: float, ma60: float, ma250: float) -> str:
    """均线排列分级"""
    spread_20_60 = (ma20 / ma60 - 1) * 100
    spread_60_250 = (ma60 / ma250 - 1) * 100

    if ma20 > ma60 > ma250:
        if spread_20_60 > 2 and spread_60_250 > 2:
            return "多头排列（发散）"
        elif spread_20_60 < 0.5:
            return "多头排列（收敛）"
        return "多头排列"
    elif ma20 < ma60 < ma250:
        if spread_20_60 < -2 and spread_60_250 < -2:
            return "空头排列（发散）"
        elif spread_20_60 > -0.5:
            return "空头排列（收敛）"
        return "空头排列"
    elif ma20 > ma250 > ma60 or ma20 > ma250:
        return "多头初期"
    elif ma20 < ma250 < ma60:
        return "空头初期"
    else:
        return "交叉缠绕"


def _classify_adx(adx: float) -> str:
    """ADX分级细化"""
    if adx >= 60:
        return "极强趋势"
    elif adx >= 40:
        return "强趋势"
    elif adx >= 25:
        return "中等趋势"
    elif adx >= 15:
        return "弱趋势"
    else:
        return "极弱/震荡"


def _infer_wave_direction(kline_data: Dict) -> str:
    """从K线波段推断方向"""
    highs = kline_data.get("highs_20", [])
    lows = kline_data.get("lows_20", [])
    if len(highs) < 5:
        return "数据不足"
    # 近5根高点逐级抬升 → 上行
    recent_highs = highs[-5:]
    recent_lows = lows[-5:]
    if all(recent_highs[i] > recent_highs[i - 1] for i in range(1, 5)):
        return "上行（高点抬高）"
    if all(recent_highs[i] < recent_highs[i - 1] for i in range(1, 5)):
        return "下行（高点降低）"
    if all(recent_lows[i] > recent_lows[i - 1] for i in range(1, 5)):
        return "上行（低点抬高）"
    if all(recent_lows[i] < recent_lows[i - 1] for i in range(1, 5)):
        return "下行（低点降低）"
    return "横盘"


def check_momentum(
    symbol: str,
    rsi: Optional[float] = None,
    cci: Optional[float] = None,
    timeframe: str = "daily",
) -> Dict:
    """检查动量状态：RSI超买超卖、CCI极端值。

    Args:
        symbol: 品种代码
        rsi: RSI14值
        cci: CCI值
        timeframe: 时间框架

    Returns:
        dict: {rsi_status, cci_status, momentum_signal, timeframe}
    """
    result = {"timeframe": timeframe, "symbol": symbol}
    if rsi is not None:
        if rsi >= 70:
            result["rsi_status"] = "超买区"
        elif rsi <= 30:
            result["rsi_status"] = "超卖区"
        else:
            result["rsi_status"] = "中性区"
        result["rsi"] = round(rsi, 1)

    if cci is not None:
        if cci >= 200:
            result["cci_status"] = "极度偏高"
        elif cci >= 100:
            result["cci_status"] = "偏高"
        elif cci <= -200:
            result["cci_status"] = "极度偏低"
        elif cci <= -100:
            result["cci_status"] = "偏低"
        else:
            result["cci_status"] = "中性"
        result["cci"] = round(cci, 1)

    return result
