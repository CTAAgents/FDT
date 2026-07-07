"""
通道突破策略 v1.0 — 唐奇安通道突破 + 布林带确认
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
        results = []

        for tech in tech_list:
            sym = tech.get("symbol", "")
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
                dc20_score += 30.0
                dc_detail["dc20_direction"] = "up"
                # 突破幅度确认
                if dc20_upper and price:
                    distance_pct = (price / dc20_upper - 1) * 100
                    dc_detail["dc20_break_distance_pct"] = round(distance_pct, 2)
                    if distance_pct > 1.0:
                        dc20_score += 10.0  # 大幅突破加分
                        dc_detail["dc20_break_strength"] = "strong"
                    elif distance_pct > 0.3:
                        dc20_score += 5.0
                        dc_detail["dc20_break_strength"] = "moderate"
                    else:
                        dc_detail["dc20_break_strength"] = "weak"
                # DC20位置确认（上轨上方运行）
                if dc20_pos is not None and dc20_pos > 0.7:
                    dc20_score += 5.0
                    dc_detail["dc20_position"] = "upper_zone"
                elif dc20_pos is not None and dc20_pos > 0.5:
                    dc_detail["dc20_position"] = "mid_upper"

                # ADX趋势评估：ADX是滞后指标，低ADX不否定突破
                # ADX>60警示趋势可能衰竭，ADX25-60确认趋势健康，ADX<25中性
                if adx > 60:
                    dc20_score -= 5.0  # 极端高位警示
                    dc_detail["adx_signal"] = "exhaustion_warning"
                elif adx >= 25:
                    dc20_score += 3.0  # 趋势健康
                    dc_detail["adx_signal"] = "trend_healthy"
                else:
                    dc_detail["adx_signal"] = "neutral"  # ADX低是正常的，趋势可能刚开始

            elif dc20_break == "down":
                dc20_score -= 30.0
                dc_detail["dc20_direction"] = "down"
                if dc20_lower and price:
                    distance_pct = (dc20_lower / price - 1) * 100
                    dc_detail["dc20_break_distance_pct"] = round(distance_pct, 2)
                    if distance_pct > 1.0:
                        dc20_score -= 10.0
                        dc_detail["dc20_break_strength"] = "strong"
                    elif distance_pct > 0.3:
                        dc20_score -= 5.0
                        dc_detail["dc20_break_strength"] = "moderate"
                    else:
                        dc_detail["dc20_break_strength"] = "weak"
                if dc20_pos is not None and dc20_pos < 0.3:
                    dc20_score -= 5.0
                    dc_detail["dc20_position"] = "lower_zone"
                elif dc20_pos is not None and dc20_pos < 0.5:
                    dc_detail["dc20_position"] = "mid_lower"
                # ADX趋势评估（同上，方向取反）
                if adx > 60:
                    dc20_score += 5.0  # 空头衰竭警示→加分(向零靠拢)
                    dc_detail["adx_signal"] = "exhaustion_warning"
                elif adx >= 25:
                    dc20_score -= 3.0  # 空头趋势健康
                    dc_detail["adx_signal"] = "trend_healthy"
                else:
                    dc_detail["adx_signal"] = "neutral"
            else:
                dc_detail["dc20_direction"] = "none"

            dc_detail["dc20_raw_score"] = round(dc20_score, 1)

            # ── A2: DC55 中期通道突破 + 趋势方向 (35% of 75% = 26.25% total) ──
            dc55_score = 0.0
            # DC55价格位置评分
            if dc55_pos is not None and price:
                # 多头侧
                if dc55_pos > 0.85:
                    dc55_score += 25.0
                    dc55_pos_strength = "extreme_upper"
                elif dc55_pos > 0.7:
                    dc55_score += 15.0
                    dc55_pos_strength = "upper"
                elif dc55_pos > 0.5:
                    dc55_score += 5.0
                    dc55_pos_strength = "mid_upper"
                # 空头侧
                elif dc55_pos < 0.15:
                    dc55_score -= 25.0
                    dc55_pos_strength = "extreme_lower"
                elif dc55_pos < 0.3:
                    dc55_score -= 15.0
                    dc55_pos_strength = "lower"
                elif dc55_pos < 0.5:
                    dc55_score -= 5.0
                    dc55_pos_strength = "mid_lower"
                else:
                    dc55_pos_strength = "mid"

                dc_detail["dc55_position"] = round(dc55_pos, 3)
                dc_detail["dc55_pos_strength"] = dc55_pos_strength

            # DC55趋势方向确认
            if dc55_trend == "up":
                dc55_score += 10.0 if dc55_score >= 0 else -10.0  # 趋势与价格位置冲突对冲
                dc_detail["dc55_trend"] = "up"
                # 趋势方向强度
                if dc55_score >= 0:
                    dc55_score += 5.0  # 趋势+位置一致加分
                    dc_detail["dc55_trend_aligned"] = True
                else:
                    # 价格位置与趋势反向→减分
                    dc55_score += 10.0  # 向0靠拢
                    dc_detail["dc55_trend_aligned"] = False
                    dc_detail["dc55_divergence"] = "price_lower_but_trend_up"
            elif dc55_trend == "down":
                dc55_score -= 10.0 if dc55_score <= 0 else 10.0
                dc_detail["dc55_trend"] = "down"
                if dc55_score <= 0:
                    dc55_score -= 5.0
                    dc_detail["dc55_trend_aligned"] = True
                else:
                    dc55_score -= 10.0
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
                # 带宽扩张→波动率上升→趋势可信
                if bb_width_pct > 4.0:
                    bb_score += 6.0 if dc_score >= 0 else -6.0
                    bb_detail["bb_volatility"] = "high"
                elif bb_width_pct > 2.5:
                    bb_score += 3.0 if dc_score >= 0 else -3.0
                    bb_detail["bb_volatility"] = "moderate"
                else:
                    bb_detail["bb_volatility"] = "low"

            # ── B2: BB挤压检测 (5%) ──
            if bb_squeeze is not None:
                bb_detail["bb_squeeze"] = bb_squeeze
                # 挤压后往往有突破
                if bb_squeeze:
                    # 挤压状态：方向待定，小幅加分（突破前兆预警）
                    bb_score += 2.0
                    bb_detail["bb_squeeze_signal"] = "breakout_pending"

            # ── B3: BB %b 位置 (10%) ──
            if bb_pos is not None:
                bb_detail["bb_pos"] = round(bb_pos, 3)
                # 上轨上方（极端多头）
                if bb_pos > 1.05:
                    bb_score += 6.0
                    bb_detail["bb_overbought"] = "extreme"
                elif bb_pos > 1.0:
                    bb_score += 4.0
                    bb_detail["bb_overbought"] = "at_upper"
                # 中部偏上（多头确认）
                elif bb_pos > 0.7:
                    bb_score += 2.0
                    bb_detail["bb_position"] = "mid_upper"
                # 中部
                elif bb_pos > 0.3:
                    bb_detail["bb_position"] = "mid"
                # 中部偏下
                elif bb_pos > 0.15:
                    bb_score -= 2.0
                    bb_detail["bb_position"] = "mid_lower"
                # 下轨下方（极端空头）
                elif bb_pos > 0:
                    bb_score -= 4.0
                    bb_detail["bb_oversold"] = "at_lower"
                else:
                    bb_score -= 6.0
                    bb_detail["bb_oversold"] = "extreme"

                # 一致性检查：DC方向与BB位置一致时加分
                if dc_score > 0 and bb_pos > 0.5:
                    bb_score += 2.0
                    bb_detail["bb_dc_consistency"] = True
                elif dc_score < 0 and bb_pos < 0.5:
                    bb_score += 2.0
                    bb_detail["bb_dc_consistency"] = True
                else:
                    bb_detail["bb_dc_consistency"] = False

            bb_detail["bb_raw_score"] = round(bb_score, 1)

            # ═══════════════════════════════════════════
            # 成交量确认（独立加分/减分，不单独成层）
            # ═══════════════════════════════════════════
            volume_score = 0.0
            vol_detail = {}
            if volume and df is not None and len(df) > 20:
                avg_vol_20 = df["volume"].iloc[-20:].mean()
                vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 1.0
                vol_detail["vol_ratio"] = round(vol_ratio, 2)
                if vol_ratio > 1.5:
                    volume_score = 10.0 if dc_score >= 0 else -10.0
                    vol_detail["volume_style"] = "explosive"
                elif vol_ratio > 1.2:
                    volume_score = 5.0 if dc_score >= 0 else -5.0
                    vol_detail["volume_style"] = "elevated"
                elif vol_ratio > 0.8:
                    vol_detail["volume_style"] = "normal"
                else:
                    # 缩量突破可能不可持续
                    volume_score = -3.0  # 不论方向，缩量都扣分
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

            # 等级
            grade = "NOISE"
            abs_score = abs(total_score)
            if abs_score >= 60:
                grade = "STRONG"
            elif abs_score >= 40:
                grade = "WATCH"
            elif abs_score >= 20:
                grade = "WEAK"

            # 阶段（沿用技术阶段）
            stage = tech.get("stage", "unknown")

            # MA60数值（供闫判官MA60方向规则判断）
            ma60 = tech.get("MA60", tech.get("ma60", None))

            # 信号类型（通道突破+布林带确认的统一描述）
            signal_type = "none"
            if abs(dc20_score) >= 30 and abs(dc_score) >= 20:
                signal_type = "channel_breakout"
            elif abs(dc55_score) >= 15:
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
