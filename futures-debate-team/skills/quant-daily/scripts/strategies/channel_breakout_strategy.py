"""
通道突破策略 v1.1 — 唐奇安通道突破 + 布林带确认 + Tick逼近 + 大小写修复
=============================================
基于双重通道体系识别趋势启动与延续：

  Layer A — 唐奇安通道 (Donchian Channel, 权重75%)
    DC20短期通道: 价格突破N日边界=短期趋势启动
    DC55中期通道: 价格突破N日边界+趋势方向=中期趋势确认

  Layer B — 布林带 (Bollinger Band, 权重25%)
    BB带宽扩张: 波动率上升=趋势可信度加分
    BB挤压: 低波动收缩=突破前兆预警
    %b位置: 价格处于通道极端=趋势强度佐证

不依赖移动均线、MACD、RSI等滞后指标，直接以价格行为为核心。
"""

import sys, os, math
from datetime import datetime
from statistics import mean, stdev
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy
from config.settings import resolve_param, SYMBOL_CHAIN_MAP, SIGNAL_GRADE_THRESHOLDS, get_tick_size


class ChannelBreakoutStrategy(BaseStrategy):
    """双通道(唐奇安+布林带)突破识别策略"""

    @property
    def name(self) -> str:
        return "channel_breakout"

    @property
    def display_name(self) -> str:
        return "通道突破(唐奇安DC20/DC55+布林带)"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
        period: str = "daily",
        window_mode: str = "fixed",
    ) -> dict:
        # ── 参数解析速记（品种×周期四层回落，所有参数来自 config.settings） ──
        # resolve_param(section, key, symbol, chain, period)
        # 回落链: per_symbol → per_chain → per_period → default
        _r = lambda sec, key, sym="", chain="", per="daily": resolve_param(sec, key, sym, chain, per)
        _get_chain = lambda sym: SYMBOL_CHAIN_MAP.get(sym, "其他")

        # ── 等效时间窗口缩放 ──
        # 在 time 模式下,将 DC20/DC55/MA60 的窗口从固定bar数缩放为等效天数
        if window_mode == "time" and df_map:
            trading_min_per_day = _r("time_window", "trading_min_per_day")
            _bar_min = {"1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
                        "60m": 60, "120m": 120, "240m": 240, "daily": 1440}
            bar_min = _bar_min.get(period, 60)
            scale = trading_min_per_day / max(bar_min, 1)
            _dc20_t = int(_r("time_window", "dc20_period") * scale)
            _dc55_t = int(_r("time_window", "dc55_period") * scale)
            _ma60_t = int(_r("time_window", "ma60_period") * scale)
            for tech in tech_list:
                sym = tech.get("symbol", "")
                df = df_map.get(sym)
                if df is not None and len(df) >= max(_dc55_t, _r("time_window", "min_bars_required")):
                    closes = df["close"].values.astype(float)
                    highs = df["high"].values.astype(float)
                    lows = df["low"].values.astype(float)
                    import numpy as np
                    # DC20
                    dc20_upper = np.max(highs[-_dc20_t:])
                    dc20_lower = np.min(lows[-_dc20_t:])
                    tech["DC20_UPPER"] = dc20_upper
                    tech["DC20_LOWER"] = dc20_lower
                    tech["DC20_POS"] = (closes[-1] - dc20_lower) / (dc20_upper - dc20_lower + 1e-10)
                    # DC55
                    dc55_upper = np.max(highs[-_dc55_t:])
                    dc55_lower = np.min(lows[-_dc55_t:])
                    tech["DC55_UPPER"] = dc55_upper
                    tech["DC55_LOWER"] = dc55_lower
                    tech["DC55_POS"] = (closes[-1] - dc55_lower) / (dc55_upper - dc55_lower + 1e-10)
                    # DC55趋势: 比较前一半与后一半的中点
                    half = _dc55_t // 2
                    mid_first = (np.max(highs[-_dc55_t:-half]) + np.min(lows[-_dc55_t:-half])) / 2
                    mid_last = (np.max(highs[-half:]) + np.min(lows[-half:])) / 2
                    tech["DC55_TREND"] = "up" if mid_last > mid_first else "down"
                    # MA60 (等效时间)
                    if len(closes) >= _ma60_t:
                        ma60 = np.mean(closes[-_ma60_t:])
                        tech["MA60"] = ma60

        results = []

        for tech in tech_list:
            sym = tech.get("symbol", "")
            chain_name = _get_chain(sym)
            name = tech.get("name", sym)
            price = tech.get("last_price", tech.get("price", 0))
            adx = tech.get("ADX", tech.get("ADX14", 0))
            volume = tech.get("volume", 0)
            change_pct = tech.get("change_pct", 0)
            atr = tech.get("ATR", tech.get("ATR14", 0))
            dc20_break = tech.get("dc20_break", "none")

            # ── 技术指标已有字段 ──
            # 唐奇安
            dc20_upper = tech.get("DC20_UPPER")
            dc20_lower = tech.get("DC20_LOWER")
            dc20_pos = tech.get("DC20_POS")  # 0-1, >0.7=上轨附近, <0.3=下轨附近
            dc55_upper = tech.get("DC55_UPPER")
            dc55_lower = tech.get("DC55_LOWER")
            dc55_mid = tech.get("DC55_MID")
            dc55_pos = tech.get("DC55_POS")  # 0-1
            dc55_trend = tech.get("DC55_TREND", "flat")  # 'up'/'down'/'flat'

            # 布林带
            bb_upper = tech.get("BB_UPPER")
            bb_middle = tech.get("BB_MIDDLE")
            bb_lower = tech.get("BB_LOWER")
            bb_pos = tech.get("BB_POS")  # 0-1
            bb_width_pct = tech.get("BB_WIDTH_PCT")
            bb_squeeze = tech.get("BB_SQUEEZE", False)

            # ── 从 df_map 获取完整K线计算 ──
            df = df_map.get(sym) if df_map else None

            # ═══════════════════════════════════════════
            # Layer A: 唐奇安通道突破 (75%)
            # ═══════════════════════════════════════════
            dc_score = 0.0
            dc_detail = {}

            # ── A1: DC20 短期通道突破 (40% of 75% = 30% total) ──
            dc20_score = 0.0
            if dc20_break == "up":
                dc20_score += _r("dc20", "break_base_score", sym, chain_name, period)
                dc_detail["dc20_direction"] = "up"
                # 突破幅度确认
                if dc20_upper and price:
                    distance_pct = (price / dc20_upper - 1) * 100
                    dc_detail["dc20_break_distance_pct"] = round(distance_pct, 2)
                    if distance_pct > _r("dc20", "break_strong_pct", sym, chain_name, period):
                        dc20_score += _r("dc20", "break_strong_bonus", sym, chain_name, period)
                        dc_detail["dc20_break_strength"] = "strong"
                    elif distance_pct > _r("dc20", "break_moderate_pct", sym, chain_name, period):
                        dc20_score += _r("dc20", "break_moderate_bonus", sym, chain_name, period)
                        dc_detail["dc20_break_strength"] = "moderate"
                    else:
                        dc_detail["dc20_break_strength"] = "weak"
                # DC20位置确认（上轨上方运行）
                if dc20_pos is not None and dc20_pos > _r("dc20", "pos_upper_threshold", sym, chain_name, period):
                    dc20_score += _r("dc20", "pos_upper_bonus", sym, chain_name, period)
                    dc_detail["dc20_position"] = "upper_zone"
                elif dc20_pos is not None and dc20_pos > 0.5:
                    dc_detail["dc20_position"] = "mid_upper"

                # ADX趋势评估
                if adx > _r("adx", "exhaustion_threshold", sym, chain_name, period):
                    dc20_score -= _r("adx", "exhaustion_penalty", sym, chain_name, period)
                    dc_detail["adx_signal"] = "exhaustion_warning"
                elif adx >= _r("adx", "trend_threshold", sym, chain_name, period):
                    dc20_score += _r("adx", "trend_bonus", sym, chain_name, period)
                    dc_detail["adx_signal"] = "trend_healthy"
                else:
                    dc_detail["adx_signal"] = "neutral"

            elif dc20_break == "down":
                dc20_score -= _r("dc20", "break_base_score", sym, chain_name, period)
                dc_detail["dc20_direction"] = "down"
                if dc20_lower and price:
                    distance_pct = (dc20_lower / price - 1) * 100
                    dc_detail["dc20_break_distance_pct"] = round(distance_pct, 2)
                    if distance_pct > _r("dc20", "break_strong_pct", sym, chain_name, period):
                        dc20_score -= _r("dc20", "break_strong_bonus", sym, chain_name, period)
                        dc_detail["dc20_break_strength"] = "strong"
                    elif distance_pct > _r("dc20", "break_moderate_pct", sym, chain_name, period):
                        dc20_score -= _r("dc20", "break_moderate_bonus", sym, chain_name, period)
                        dc_detail["dc20_break_strength"] = "moderate"
                    else:
                        dc_detail["dc20_break_strength"] = "weak"
                if dc20_pos is not None and dc20_pos < _r("dc20", "pos_lower_threshold", sym, chain_name, period):
                    dc20_score += _r("dc20", "pos_lower_bonus", sym, chain_name, period)  # 负值=减分
                    dc_detail["dc20_position"] = "lower_zone"
                elif dc20_pos is not None and dc20_pos < 0.5:
                    dc_detail["dc20_position"] = "mid_lower"
                if adx > _r("adx", "exhaustion_threshold", sym, chain_name, period):
                    dc20_score += _r("adx", "exhaustion_penalty", sym, chain_name, period)  # 空头衰竭→向0靠拢
                    dc_detail["adx_signal"] = "exhaustion_warning"
                elif adx >= _r("adx", "trend_threshold", sym, chain_name, period):
                    dc20_score -= _r("adx", "trend_bonus", sym, chain_name, period)
                    dc_detail["adx_signal"] = "trend_healthy"
                else:
                    dc_detail["adx_signal"] = "neutral"
            else:
                dc_detail["dc20_direction"] = "none"
                # ── tick size 逼近判定：价格距DC20边界≤N个tick → 视为"趋势前夜" ──
                # （从 df_map 直接计算DC20边界，不依赖 window_mode="time" 的预计算）
                if price and price > 0:
                    tick_size = get_tick_size(sym)
                    near_ticks = _r("dc20", "near_breakout_ticks", sym, chain_name, period)
                    near_score = _r("dc20", "near_breakout_score", sym, chain_name, period)
                    if tick_size > 0 and near_ticks > 0 and df is not None and len(df) >= 20:
                        import numpy as np
                        closes = df["close"].values.astype(float)
                        highs = df["high"].values.astype(float)
                        lows = df["low"].values.astype(float)
                        _dc20u = np.max(highs[-20:])
                        _dc20l = np.min(lows[-20:])
                        if _dc20u > _dc20l:
                            ticks_to_upper = (_dc20u - price) / tick_size
                            ticks_to_lower = (price - _dc20l) / tick_size
                            if 0 < ticks_to_upper <= near_ticks:
                                dc20_score += near_score
                                dc_detail["dc20_near_breakout"] = "upper"
                                dc_detail["dc20_near_ticks"] = round(ticks_to_upper, 1)
                            elif 0 < ticks_to_lower <= near_ticks:
                                dc20_score -= near_score
                                dc_detail["dc20_near_breakout"] = "lower"
                                dc_detail["dc20_near_ticks"] = round(ticks_to_lower, 1)

            dc_detail["dc20_raw_score"] = round(dc20_score, 1)

            # ── A2: DC55 中期通道突破 + 趋势方向 (35% of 75% = 26.25% total) ──
            dc55_score = 0.0
            # DC55价格位置评分（遍历配置阈值，从高到低匹配）
            if dc55_pos is not None and price:
                dc55_pos_strength = "mid"
                for pt in _r("dc55", "pos_thresholds", sym, chain_name, period):
                    if "min" in pt and dc55_pos > pt["min"]:
                        dc55_score += pt["score"]
                        dc55_pos_strength = pt["label"]
                        break
                    if "max" in pt and dc55_pos < pt["max"]:
                        dc55_score += pt["score"]
                        dc55_pos_strength = pt["label"]
                        break

                dc_detail["dc55_position"] = round(dc55_pos, 3)
                dc_detail["dc55_pos_strength"] = dc55_pos_strength

            # DC55趋势方向确认
            trend_base = _r("dc55", "trend_base_score", sym, chain_name, period)
            align_bonus = _r("dc55", "trend_alignment_bonus", sym, chain_name, period)
            divergence = _r("dc55", "divergence_penalty", sym, chain_name, period)
            if dc55_trend == "up":
                dc55_score += trend_base if dc55_score >= 0 else -trend_base
                dc_detail["dc55_trend"] = "up"
                if dc55_score >= 0:
                    dc55_score += align_bonus
                    dc_detail["dc55_trend_aligned"] = True
                else:
                    dc55_score += divergence
                    dc_detail["dc55_trend_aligned"] = False
                    dc_detail["dc55_divergence"] = "price_lower_but_trend_up"
            elif dc55_trend == "down":
                dc55_score -= trend_base if dc55_score <= 0 else trend_base
                dc_detail["dc55_trend"] = "down"
                if dc55_score <= 0:
                    dc55_score -= align_bonus
                    dc_detail["dc55_trend_aligned"] = True
                else:
                    dc55_score -= divergence
                    dc_detail["dc55_trend_aligned"] = False
                    dc_detail["dc55_divergence"] = "price_upper_but_trend_down"
            else:
                dc_detail["dc55_trend"] = "flat"

            dc_detail["dc55_raw_score"] = round(dc55_score, 1)

            # ── 汇总 Layer A ──
            dc_score = dc20_score + dc55_score
            dc_detail["dc_total"] = round(dc_score, 1)

            # ═══════════════════════════════════════════
            # Layer B: 布林带确认 (25%)
            # ═══════════════════════════════════════════
            bb_score = 0.0
            bb_detail = {}

            # ── B1: BB带宽扩张/收缩 (10%) ──
            if bb_width_pct is not None:
                bb_detail["bb_width_pct"] = round(bb_width_pct, 2)
                if bb_width_pct > _r("bb", "width_high_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "width_high_score", sym, chain_name, period) if dc_score >= 0 else -_r("bb", "width_high_score", sym, chain_name, period)
                    bb_detail["bb_volatility"] = "high"
                elif bb_width_pct > _r("bb", "width_moderate_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "width_moderate_score", sym, chain_name, period) if dc_score >= 0 else -_r("bb", "width_moderate_score", sym, chain_name, period)
                    bb_detail["bb_volatility"] = "moderate"
                else:
                    bb_detail["bb_volatility"] = "low"

            # ── B2: BB挤压检测 (5%) ──
            if bb_squeeze is not None:
                bb_detail["bb_squeeze"] = bb_squeeze
                if bb_squeeze:
                    bb_score += _r("bb", "squeeze_bonus", sym, chain_name, period)
                    bb_detail["bb_squeeze_signal"] = "breakout_pending"

            # ── B3: BB %b 位置 (10%) ──
            if bb_pos is not None:
                bb_detail["bb_pos"] = round(bb_pos, 3)
                if bb_pos > _r("bb", "pos_extreme_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "pos_extreme_score", sym, chain_name, period)
                    bb_detail["bb_overbought"] = "extreme"
                elif bb_pos > _r("bb", "pos_upper_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "pos_upper_score", sym, chain_name, period)
                    bb_detail["bb_overbought"] = "at_upper"
                elif bb_pos > _r("bb", "pos_mid_upper_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "pos_mid_upper_score", sym, chain_name, period)
                    bb_detail["bb_position"] = "mid_upper"
                elif bb_pos > 0.3:
                    bb_detail["bb_position"] = "mid"
                elif bb_pos > _r("bb", "pos_mid_lower_threshold", sym, chain_name, period):
                    bb_score += _r("bb", "pos_mid_lower_score", sym, chain_name, period)
                    bb_detail["bb_position"] = "mid_lower"
                elif bb_pos > 0:
                    bb_score += _r("bb", "pos_lower_score", sym, chain_name, period)
                    bb_detail["bb_oversold"] = "at_lower"
                else:
                    bb_score += _r("bb", "pos_extreme_lower_score", sym, chain_name, period)
                    bb_detail["bb_oversold"] = "extreme"

                # 一致性检查
                consistency_bonus = _r("bb", "dc_consistency_bonus", sym, chain_name, period)
                if dc_score > 0 and bb_pos > 0.5:
                    bb_score += consistency_bonus
                    bb_detail["bb_dc_consistency"] = True
                elif dc_score < 0 and bb_pos < 0.5:
                    bb_score += consistency_bonus
                    bb_detail["bb_dc_consistency"] = True
                else:
                    bb_detail["bb_dc_consistency"] = False

            bb_detail["bb_raw_score"] = round(bb_score, 1)

            # ═══════════════════════════════════════════
            # 成交量确认（独立加分/减分，不单独成层）
            # ═══════════════════════════════════════════
            volume_score = 0.0
            vol_detail = {}
            if volume and df is not None and len(df) > _r("volume", "ma_period", sym, chain_name, period):
                avg_vol_20 = df["volume"].iloc[-_r("volume", "ma_period", sym, chain_name, period):].mean()
                vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 1.0
                vol_detail["vol_ratio"] = round(vol_ratio, 2)
                if vol_ratio > _r("volume", "explosive_ratio", sym, chain_name, period):
                    volume_score = _r("volume", "explosive_score", sym, chain_name, period) if dc_score >= 0 else -_r("volume", "explosive_score", sym, chain_name, period)
                    vol_detail["volume_style"] = "explosive"
                elif vol_ratio > _r("volume", "elevated_ratio", sym, chain_name, period):
                    volume_score = _r("volume", "elevated_score", sym, chain_name, period) if dc_score >= 0 else -_r("volume", "elevated_score", sym, chain_name, period)
                    vol_detail["volume_style"] = "elevated"
                elif vol_ratio > _r("volume", "normal_lower_ratio", sym, chain_name, period):
                    vol_detail["volume_style"] = "normal"
                else:
                    volume_score = _r("volume", "weak_penalty", sym, chain_name, period)
                    vol_detail["volume_style"] = "weak"
            else:
                vol_detail["volume_style"] = "unknown"

            # ═══════════════════════════════════════════
            # 综合评分
            # ═══════════════════════════════════════════
            # 标准化: dc_score(75%) + bb_score(25%) + volume_adjust
            # dc_score 范围约[-50, 50], bb_score 约[-16, 16], vol 约[-10, 10]
            total_score = dc_score + bb_score + volume_score

            # 方向
            direction = "bull" if total_score > 0 else ("bear" if total_score < 0 else "neutral")

            # 等级（阈值来自 config.settings.SIGNAL_GRADE_THRESHOLDS，支持自进化调参）
            grade = "NOISE"
            abs_score = abs(total_score)
            if abs_score >= SIGNAL_GRADE_THRESHOLDS["strong"]:
                grade = "STRONG"
            elif abs_score >= SIGNAL_GRADE_THRESHOLDS["watch"]:
                grade = "WATCH"
            elif abs_score >= SIGNAL_GRADE_THRESHOLDS["weak"]:
                grade = "WEAK"

            # 阶段（沿用技术阶段）
            stage = tech.get("stage", "unknown")

            # MA60数值（供闫判官MA60方向规则判断）
            ma60 = tech.get("MA60", tech.get("ma60", None))

            # 信号类型（通道突破+布林带确认的统一描述）
            signal_type = "none"
            if abs(dc20_score) >= _r("signal_type", "channel_breakout_dc20_min", sym, chain_name, period) and abs(dc_score) >= _r("signal_type", "channel_breakout_dc_total_min", sym, chain_name, period):
                signal_type = "channel_breakout"
            elif abs(dc20_score) >= _r("signal_type", "near_breakout_dc20_min", sym, chain_name, period):
                signal_type = "near_breakout"
            elif abs(dc55_score) >= _r("signal_type", "trend_confirmation_dc55_min", sym, chain_name, period):
                signal_type = "trend_confirmation"
            elif bb_squeeze:
                signal_type = "bb_squeeze_prebreakout"
            else:
                signal_type = "minor_signal"

            result = SignalResult(
                symbol=sym,
                name=name,
                total=total_score,
                abs_score=abs_score,
                direction=direction,
                grade=grade,
                sub_scores={
                    "dc20": round(dc20_score, 1),
                    "dc55": round(dc55_score, 1),
                    "bb": round(bb_score, 1),
                    "vol_score": round(volume_score, 1),
                },
                price=price,
                change_pct=change_pct,
                volume=volume,
                adx=adx,
                atr=atr,
                rsi=tech.get("RSI14", tech.get("rsi", 50)),
                cci=tech.get("CCI20", tech.get("cci", 0)),
                ma_slope=tech.get("MA20_SLOPE", tech.get("ma_slope", 0)),
                stage=stage,
                ma_align=tech.get("ma_align", "mixed"),
                dc20_break=dc20_break,
                z_score=tech.get("Z_SCORE", tech.get("z_score", 0.0)),
                consistency=tech.get("cons", tech.get("consistency", 0)),
                extra={
                    "signal_type": signal_type,
                    "channel_detail": dc_detail,
                    "bb_detail": bb_detail,
                    "vol_detail": vol_detail,
                    "dc55_pos": round(dc55_pos, 3) if dc55_pos is not None else None,
                    "dc55_trend": dc55_trend,
                    "bb_width_pct": round(bb_width_pct, 2) if bb_width_pct is not None else None,
                    "bb_squeeze": bb_squeeze,
                    "ma60": round(ma60, 1) if ma60 else None,
                    "tdx_note": tech.get("_tdx_note", ""),
                },
            )
            results.append(result)

        # 排序
        results.sort(key=lambda r: r.abs_score, reverse=True)

        bull = [r.to_dict() for r in results if r.direction == "bull"]
        bear = [r.to_dict() for r in results if r.direction == "bear"]

        return {
            "all_ranked": [r.to_dict() for r in results],
            "bull_signals": bull,
            "bear_signals": bear,
            "_meta": {
                "mode": "channel_breakout",
                "strategy": self.name,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "total": len(results),
                "bull": len(bull),
                "bear": len(bear),
                "signal_types": {
                    "channel_breakout": sum(
                        1 for r in results if r.extra.get("signal_type") == "channel_breakout"
                    ),
                    "near_breakout": sum(
                        1 for r in results if r.extra.get("signal_type") == "near_breakout"
                    ),
                    "trend_confirmation": sum(
                        1 for r in results if r.extra.get("signal_type") == "trend_confirmation"
                    ),
                    "bb_squeeze_prebreakout": sum(
                        1 for r in results if r.extra.get("signal_type") == "bb_squeeze_prebreakout"
                    ),
                    "minor_signal": sum(
                        1 for r in results if r.extra.get("signal_type") == "minor_signal"
                    ),
                },
                "period": period,
                "window_mode": window_mode,
            },
        }


# 注册策略
register_strategy(ChannelBreakoutStrategy)
