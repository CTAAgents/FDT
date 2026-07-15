"""
趋势跟踪策略 v2 — DC20/DC55/BB 通道突破 + G30/G31/G32/G33 指标扩展（纯简版）。

复用 scan_all 指标管线已有的技术字段（含 G30 新增 Keltner/SAR/Chandelier/
MACD 子信号），零新采集。与 v1 ChannelBreakoutStrategy 的核心逻辑一致但
精简，直接实现 BaseStrategyV2 接口。

⚠️ 去融合（v8.1.8 掌柜铁律）：10 个通道/指标子信号各自独立产出 RawSignal，
signal_type 命名空间独立（trend_following.dc20 / .dc55 / .bb / .keltner /
.supertrend / .sar / .chandelier / .macd / .tsmom / .dual_thrust），
禁止投票累加 / signal_type 拼接融合。每个子信号独立送辩论层裁决。
"""

from __future__ import annotations
import math
from statistics import mean, stdev
from typing import Any

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal, format_reason


def _score_dc20(close: float, dc20_high: float, dc20_low: float) -> tuple[float, str]:
    """DC20 打分：价格相对通道位置。返回 (score_0_1, direction)。"""
    if dc20_high <= 0 or dc20_low <= 0 or dc20_high <= dc20_low:
        return 0.0, "neutral"
    pos = (close - dc20_low) / (dc20_high - dc20_low)
    if pos > 0.95:
        return (pos - 0.95) / 0.05, "bull"
    if pos < 0.05:
        return (0.05 - pos) / 0.05, "bear"
    return 0.0, "neutral"


def _score_dc55(close: float, dc55_high: float, dc55_low: float) -> tuple[float, str]:
    """DC55 打分：趋势方向确认。"""
    if dc55_high <= 0 or dc55_low <= 0 or dc55_high <= dc55_low:
        return 0.0, "neutral"
    pos = (close - dc55_low) / (dc55_high - dc55_low)
    if pos > 0.80:
        return (pos - 0.80) / 0.20, "bull"
    if pos < 0.20:
        return (0.20 - pos) / 0.20, "bear"
    return 0.0, "neutral"


def _score_bb(bb: float) -> tuple[float, str]:
    """布林带 %b 打分。"""
    if not isinstance(bb, (int, float)):
        return 0.0, "neutral"
    if bb > 0.95:
        return (bb - 0.95) / 0.05, "bull"
    if bb < 0.05:
        return (0.05 - bb) / 0.05, "bear"
    return 0.0, "neutral"


def _score_keltner(close: float, kc_u: float, kc_l: float, kc_m: float) -> tuple[float, str]:
    """Keltner 通道突破打分（EMA±ATR 通道）。

    价格突破上轨 → 多头；跌破下轨 → 空头；强度按突破幅度相对通道半宽缩放。
    """
    if kc_u <= 0 or kc_l <= 0 or kc_u <= kc_l or kc_m <= 0:
        return 0.0, "neutral"
    half = (kc_u - kc_m) + 1e-9
    if close > kc_u:
        return min(1.0, (close - kc_u) / half), "bull"
    if close < kc_l:
        return min(1.0, (kc_l - close) / half), "bear"
    return 0.0, "neutral"


def _score_supertrend(close: float, st_dir: int) -> tuple[float, str]:
    """Supertrend 趋势状态打分（1=多头 / -1=空头）。

    作为已确认的趋势状态指标，给中等固定置信度，丰富方向共振。
    """
    if st_dir > 0:
        return 0.5, "bull"
    if st_dir < 0:
        return 0.5, "bear"
    return 0.0, "neutral"


def _score_sar(close: float, sar_val: float, sar_trend: int) -> tuple[float, str]:
    """Parabolic SAR 抛物线转向打分。

    SAR 作为追踪止损：收盘价在 SAR 上方=多头趋势；下方=空头趋势。
    方向优先取 sar_trend（1/-1），回退到 close 与 SAR 比较。
    """
    if sar_val <= 0:
        return 0.0, "neutral"
    if sar_trend > 0 or (sar_trend == 0 and close > sar_val):
        return 0.4, "bull"
    if sar_trend < 0 or (sar_trend == 0 and close < sar_val):
        return 0.4, "bear"
    return 0.0, "neutral"


def _score_chandelier(close: float, ch_long: float, ch_short: float) -> tuple[float, str]:
    """Chandelier Exit 吊灯退出打分（多头/空头追踪止损线构成趋势带）。

    两条退出线构成趋势带：
      - 价格突破带上轨（ch_short，空头止损线）上方 → 空头回补/多头突破 → 多头
      - 价格跌破带下轨（ch_long，多头止损线）下方 → 多头止损/空头突破 → 空头
      - 带内（趋势过渡区） → 中性
    强度按价格偏离退出线的相对带宽缩放（带基础 0.3 置信）。
    """
    if ch_long <= 0 or ch_short <= 0 or ch_long >= ch_short:
        return 0.0, "neutral"
    band = (ch_short - ch_long) + 1e-9
    if close > ch_short:
        return min(1.0, 0.3 + (close - ch_short) / band), "bull"
    if close < ch_long:
        return min(1.0, 0.3 + (ch_long - close) / band), "bear"
    return 0.0, "neutral"


def _score_macd(dif: float, dea: float, close: float) -> tuple[float, str]:
    """MACD 系统打分（柱状图 = DIF - DEA）。

    柱为正 → 多头动量；柱为负 → 空头动量；强度按柱相对价格幅度（0.5% 价格=满强度）缩放。
    """
    if dif is None or dea is None or not isinstance(dif, (int, float)) or not isinstance(dea, (int, float)):
        return 0.0, "neutral"
    if close <= 0:
        return 0.0, "neutral"
    hist = dif - dea
    if hist == 0:
        return 0.0, "neutral"
    scale = abs(hist) / (0.005 * close + 1e-9)
    return min(1.0, scale), ("bull" if hist > 0 else "bear")


def _score_tsmom(ret_1m, ret_3m, ret_6m, ret_12m) -> tuple[float, str]:
    """TSMOM 时间序列动量打分（多窗口合成降噪，Moskowitz-Ooi-Pedersen 2012）。

    对 1/3/6/12 月四个窗口的累计收益取平均：
      - sign(平均收益) 定方向（>0 多头 / <0 空头）
      - abs(平均收益) / 10% 定强度（满强=1.0，见 TREND_G31_CONFIG.conviction_scale_pct）
    多窗口合成本身即噪声抑制：单窗口反转会被平均稀释。各窗口中不可用的
    （缺失或填 0.0 / NaN）不参与合成；全不可用 → 中性。
    """
    wins: list[float] = []
    for r in (ret_1m, ret_3m, ret_6m, ret_12m):
        try:
            rv = float(r)
        except (TypeError, ValueError):
            continue
        if rv != 0.0 and math.isfinite(rv):
            wins.append(rv)
    if not wins:
        return 0.0, "neutral"
    avg = sum(wins) / len(wins)
    if avg == 0:
        return 0.0, "neutral"
    direction = "bull" if avg > 0 else "bear"
    score = min(1.0, abs(avg) / 0.10)
    return score, direction


def _score_dual_thrust(close: float, dt_upper: float, dt_lower: float,
                       dt_range: float) -> tuple[float, str]:
    """Dual Thrust 日内突破打分（G33，Michael Chalek 经典算法）。

    基于前 lookback 日 H/L/C 计算的触发区间：
      - close 突破上轨 dt_upper（=open + k1*range） → 多头
      - close 跌破下轨 dt_lower（=open - k2*range） → 空头
      - 轨内（趋势过渡区） → 中性
    强度按价格偏离触发轨的相对区间幅度缩放（基础 0.3 置信，满强=1.0）。
    区间/轨缺失（<=0） → 中性（不投票）。
    """
    if dt_upper <= 0 or dt_lower <= 0 or dt_range <= 0:
        return 0.0, "neutral"
    if close > dt_upper:
        return min(1.0, 0.3 + (close - dt_upper) / (dt_range + 1e-9)), "bull"
    if close < dt_lower:
        return min(1.0, 0.3 + (dt_lower - close) / (dt_range + 1e-9)), "bear"
    return 0.0, "neutral"


class TrendFollowingStrategy(BaseStrategyV2):
    """趋势跟踪：DC20/DC55 + 布林带通道突破（v2）。

    G30 扩展为指标衍生子信号，G31 引入时间序列动量（TSMOM），G33 引入 Dual
    Thrust 日内突破，合计 10 子信号共振：DC20/DC55/BB（原）+ Keltner 通道突破 /
    Supertrend 趋势状态 / Parabolic SAR 转向 / Chandelier Exit 吊灯退出 / MACD
    系统（G30）+ TSMOM 1/3/6/12 月收益合成（G31）+ Dual Thrust 前日区间突破
    （G33）。全部复用价量 + 已有 ATR/OHLC，零新数据源。
    各子信号独立打分后方向投票，子类型标签携带命中清单
    （如 trend_following.dc20+keltner+tsmom+dt）。
    """

    @property
    def name(self) -> str:
        return "trend_following"

    @property
    def display_name(self) -> str:
        return "趋势跟踪(通道突破v2)"

    @property
    def signal_type(self) -> str:
        return "trend_following"

    @property
    def validators(self) -> list[str]:
        return ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing"]

    @property
    def weight(self) -> float:
        return 1.0  # 趋势信号权重最高

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        for t in tech_list:
            sym = t.get("symbol", "")
            close = float(t.get("price", 0))
            if close <= 0:
                continue

            dc20_h = float(t.get("dc20_high", t.get("dc20_max", 0)))
            dc20_l = float(t.get("dc20_low", t.get("dc20_min", 0)))
            dc55_h = float(t.get("dc55_high", t.get("dc55_max", 0)))
            dc55_l = float(t.get("dc55_low", t.get("dc55_min", 0)))
            bb_val = t.get("bb", 0.5)
            adx = float(t.get("adx", 0))

            # 十层打分（DC20/DC55/BB + G30: Keltner/Supertrend/SAR/Chandelier/MACD + G31: TSMOM + G33: Dual Thrust）
            s20, d20 = _score_dc20(close, dc20_h, dc20_l)
            s55, d55 = _score_dc55(close, dc55_h, dc55_l)
            sbb, dbb = _score_bb(bb_val)
            skc, dkc = _score_keltner(
                close,
                float(t.get("kc_upper", 0)),
                float(t.get("kc_lower", 0)),
                float(t.get("kc_mid", 0)),
            )
            sst, dst = _score_supertrend(close, int(t.get("supertrend", 0) or 0))
            ssar, dsar = _score_sar(close, float(t.get("sar", 0)), int(t.get("sar_trend", 0) or 0))
            sch, dch = _score_chandelier(
                close,
                float(t.get("chandelier_long", 0)),
                float(t.get("chandelier_short", 0)),
            )
            smacd, dmacd = _score_macd(
                float(t.get("macd_dif", 0) or 0),
                float(t.get("macd_dea", 0) or 0),
                close,
            )
            # G31 TSMOM：1/3/6/12 月收益合成（缺失/0.0 视为不可用，_score_tsmom 内部剔除）
            sts, dts = _score_tsmom(
                float(t.get("tsmom_1m", 0) or 0),
                float(t.get("tsmom_3m", 0) or 0),
                float(t.get("tsmom_6m", 0) or 0),
                float(t.get("tsmom_12m", 0) or 0),
            )
            # G33 Dual Thrust 日内突破：close vs open±k*range 触发轨（缺失/0.0 视为不可用）
            sdt, ddt = _score_dual_thrust(
                close,
                float(t.get("dt_upper", 0)),
                float(t.get("dt_lower", 0)),
                float(t.get("dt_range", 0)),
            )

            # 去融合（v8.1.8 掌柜铁律）：每个子信号独立产出、独立送辩论层裁决。
            # 禁止投票累加 / signal_type 拼接融合（旧逻辑 trend_following.dc20+... 已废）。
            sub_results = [
                ("dc20", s20, d20), ("dc55", s55, d55), ("bb", sbb, dbb),
                ("keltner", skc, dkc), ("supertrend", sst, dst),
                ("sar", ssar, dsar), ("chandelier", sch, dch),
                ("macd", smacd, dmacd), ("tsmom", sts, dts),
                ("dual_thrust", sdt, ddt),
            ]
            for _name, _score, _dir in sub_results:
                if _dir == "neutral" or _score <= 0:
                    continue
                signals.append(RawSignal(
                    symbol=sym,
                    direction=_dir,
                    signal_type=f"{self.signal_type}.{_name}",
                    raw_score=round(_score, 3),
                    strategy_name=self.name,
                    meta={
                        f"{_name}_score": round(_score, 3),
                        "adx": adx,
                        "close": close,
                    },
                ))
        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)  # ∈ [0,1] 单子信号绝对置信度
            total = raw * 100 if s.direction == "bull" else -raw * 100
            abs_score = raw * 100
            grade = "STRONG" if raw > 0.75 else "WATCH" if raw > 0.5 else "WEAK" if raw > 0.2 else "NOISE"
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(abs_score, 1),
                grade=grade,
                weight=self.weight,
            )
            # reason：子信号身份 + 关键条件，供辩论环节识别"为什么选这个信号"
            _sub = s.signal_type.split(".")[-1] if "." in s.signal_type else "mixed"
            _score_key = f"{_sub}_score"
            _metrics = {_sub.upper(): round(s.meta.get(_score_key, 0), 3)}
            if s.meta.get("adx"):
                _metrics["ADX"] = round(s.meta["adx"], 1)
            ss.reason = format_reason(
                s.signal_type, s.direction, grade,
                metrics=_metrics,
                strength=round(raw, 2),
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
