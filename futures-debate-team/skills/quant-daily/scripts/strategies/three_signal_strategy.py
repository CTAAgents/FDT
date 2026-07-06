"""
三层信号策略 v1.0 — 识别突破/回踩/新高三类信号
============================================
基于掌柜的三类买入方法：
  1. 通道突破（唐奇安/布林带）：价格突破N日边界=趋势启动
  2. 均线回踩（20EMA/MA20-60）：趋势已确立，等回踩均线
  3. 新高突破（55日高/杯柄）：新高=上方无压力

本策略不做方向判断，只识别信号类型和可靠性评分。
"""

import sys, os, math
from statistics import mean, stdev
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy


class ThreeSignalStrategy(BaseStrategy):
    """三层信号识别策略"""

    @property
    def name(self) -> str:
        return "three_signal"

    @property
    def display_name(self) -> str:
        return "三层信号(突破/回踩/跳空)"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
    ) -> dict:
        results = []

        for tech in tech_list:
            sym = tech.get("symbol", "")
            name = tech.get("name", sym)
            price = tech.get("last_price", tech.get("price", 0))
            adx = tech.get("ADX14", tech.get("adx", 0))
            rsi = tech.get("RSI14", tech.get("rsi", 0))
            cci = tech.get("CCI20", tech.get("cci", 0))
            ma_slope = tech.get("MA20_SLOPE", tech.get("ma_slope", 0))
            macd = tech.get("macd_cross", "none")
            dc20 = tech.get("dc20_break", "none")
            ma_align = tech.get("ma_align", "mixed")
            volume = tech.get("volume", 0)
            change_pct = tech.get("change_pct", 0)
            atr = tech.get("ATR14", tech.get("atr", 0))

            # 从 df_map 获取K线数据用于计算
            df = df_map.get(sym) if df_map else None

            # ── 三层信号识别 ──
            signals = []

            # 1. 通道突破信号
            breakout_score = 0
            breakout_detail = {}
            if dc20 and dc20 != "none":
                breakout_score += 20
                breakout_detail["dc20_break"] = dc20
                # 成交量确认
                if volume and df is not None and len(df) > 20:
                    avg_vol_20 = df["volume"].iloc[-20:].mean()
                    vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 1
                    if vol_ratio > 1.5:
                        breakout_score += 15
                        breakout_detail["volume_confirm"] = True
                        breakout_detail["vol_ratio"] = round(vol_ratio, 1)
                    else:
                        breakout_detail["volume_confirm"] = False
                        breakout_detail["vol_ratio"] = round(vol_ratio, 1)
                # ADX走向（是上升还是下降）
                if adx > 20:
                    breakout_score += 10
                    breakout_detail["adx_support"] = True
                else:
                    breakout_detail["adx_support"] = False
                # 带宽检查
                if df is not None and len(df) > 20:
                    high_20 = df["high"].iloc[-20:].max()
                    low_20 = df["low"].iloc[-20:].min()
                    bandwidth = (high_20 - low_20) / (low_20 or 1) * 100
                    breakout_detail["bandwidth_pct"] = round(bandwidth, 1)
                    if bandwidth > 5:
                        breakout_score += 5
                if breakout_score >= 25:
                    signals.append("breakout")

            # 2. 均线回踩信号
            pullback_score = 0
            pullback_detail = {}
            # 趋势向上（ma_align=bullish 或 ma_slope>0）
            trend_up = ma_align == "bullish" or ma_slope > 0
            if trend_up:
                pullback_detail["trend_up"] = True
                # 价格接近MA20（距离<1.5%）
                if df is not None and len(df) > 20:
                    ma20 = df["close"].iloc[-20:].mean()
                    dist_to_ma20 = abs(price - ma20) / (ma20 or 1) * 100
                    pullback_detail["dist_to_ma20_pct"] = round(dist_to_ma20, 2)
                    if dist_to_ma20 < 1.5:
                        pullback_score += 20
                        pullback_detail["ma20_touch"] = True
                        # 缩量确认
                        avg_vol_20 = df["volume"].iloc[-20:].mean()
                        vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 1
                        if vol_ratio < 0.8:
                            pullback_score += 15
                            pullback_detail["volume_shrink"] = True
                            pullback_detail["vol_ratio"] = round(vol_ratio, 1)
                        else:
                            pullback_detail["volume_shrink"] = False
                        # 不破前低（支撑确认）
                        low_5 = df["low"].iloc[-5:].min() if len(df) >= 5 else 0
                        if price > low_5 * 1.005:  # 未跌破5日最低
                            pullback_score += 10
                            pullback_detail["support_confirmed"] = True
                    else:
                        pullback_detail["ma20_touch"] = False
                # RSI不在极端区
                if 30 <= rsi <= 70:
                    pullback_score += 5
                    pullback_detail["rsi_safe"] = True
                else:
                    pullback_detail["rsi_safe"] = False
                if pullback_score >= 25:
                    signals.append("pullback")

            # 3. 跳空缺口信号（替代原新高）
            gap_score = 0
            gap_detail = {}
            if df is not None and len(df) > 5:
                prev_close = df["close"].iloc[-2] if len(df) >= 2 else price
                curr_open = df["open"].iloc[-1] if "open" in df.columns else price
                gap_pct = (curr_open - prev_close) / (prev_close or 1) * 100
                gap_detail["gap_pct"] = round(gap_pct, 2)

                # 向上跳空
                if gap_pct > 0.5:
                    gap_score += 20
                    gap_detail["gap_direction"] = "up"
                    gap_detail["gap_size"] = "large" if gap_pct > 1.5 else "medium" if gap_pct > 0.8 else "small"
                    # 成交量确认
                    if volume:
                        avg_vol_5 = df["volume"].iloc[-5:].mean()
                        vol_ratio = volume / avg_vol_5 if avg_vol_5 > 0 else 1
                        if vol_ratio > 1.3:
                            gap_score += 15
                            gap_detail["volume_confirm"] = True
                        else:
                            gap_detail["volume_confirm"] = False
                    # 未回补缺口（强势）
                    curr_low = df["low"].iloc[-1]
                    if curr_low > prev_close:  # 最低价未触及前收盘=缺口未补
                        gap_score += 10
                        gap_detail["gap_filled"] = False
                    else:
                        gap_detail["gap_filled"] = True
                    if gap_score >= 30:
                        signals.append("gap")

                # 向下跳空
                elif gap_pct < -0.5:
                    gap_score += 20
                    gap_detail["gap_direction"] = "down"
                    gap_detail["gap_size"] = "large" if gap_pct < -1.5 else "medium" if gap_pct < -0.8 else "small"
                    if volume:
                        avg_vol_5 = df["volume"].iloc[-5:].mean()
                        vol_ratio = volume / avg_vol_5 if avg_vol_5 > 0 else 1
                        if vol_ratio > 1.3:
                            gap_score += 15
                            gap_detail["volume_confirm"] = True
                        else:
                            gap_detail["volume_confirm"] = False
                    curr_high = df["high"].iloc[-1]
                    if curr_high < prev_close:  # 最高价未触及前收盘=缺口未补
                        gap_score += 10
                        gap_detail["gap_filled"] = False
                    else:
                        gap_detail["gap_filled"] = True
                    if gap_score >= 30:
                        signals.append("gap")

            # 确定主信号类型
            signal_type = "none"
            signal_confidence = 0
            # 优先级: gap > breakout > pullback
            if "gap" in signals:
                signal_type = "gap"
                signal_confidence = gap_score
            elif "breakout" in signals:
                signal_type = "breakout"
                signal_confidence = breakout_score
            elif "pullback" in signals:
                signal_type = "pullback"
                signal_confidence = pullback_score

            # 方向判断（基于趋势）
            direction = "neutral"
            if ma_slope > 5:
                direction = "bull"
            elif ma_slope < -5:
                direction = "bear"
            elif adx > 25:
                if rsi > 50:
                    direction = "bull"
                else:
                    direction = "bear"

            # 总分（三层信号综合分，带方向）
            total_score = breakout_score + pullback_score + gap_score
            if direction == "bear":
                total_score = -total_score

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

            result = SignalResult(
                symbol=sym,
                name=name,
                total=total_score,
                abs_score=abs_score,
                direction=direction,
                grade=grade,
                sub_scores={
                    "breakout": breakout_score,
                    "pullback": pullback_score,
                    "gap": gap_score,
                    "signal_conf": signal_confidence,
                },
                price=price,
                change_pct=change_pct,
                volume=volume,
                adx=adx,
                rsi=rsi,
                cci=cci,
                ma_slope=ma_slope,
                stage=stage,
                ma_align=ma_align,
                dc20_break=dc20,
                extra={
                    "signal_type": signal_type,
                    "signal_confidence": signal_confidence,
                    "breakout_detail": breakout_detail,
                    "pullback_detail": pullback_detail,
                    "gap_detail": gap_detail,
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
                "mode": "three_signal",
                "strategy": self.name,
                "total": len(results),
                "bull": len(bull),
                "bear": len(bear),
                "signal_types": {
                    "breakout": sum(1 for r in results if r.extra.get("signal_type") == "breakout"),
                    "pullback": sum(1 for r in results if r.extra.get("signal_type") == "pullback"),
                    "gap": sum(1 for r in results if r.extra.get("signal_type") == "gap"),
                    "none": sum(1 for r in results if r.extra.get("signal_type") == "none"),
                },
            },
        }


# 注册策略
register_strategy(ThreeSignalStrategy)
