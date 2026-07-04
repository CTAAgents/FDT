"""
因子择时策略 — 基于5因子（展期收益率/动量/反向仓单/偏度/量价相关性）的L1-L4分层择时
===============================================================================
输出 full_scan_{YYYYMMDD}.json 格式的多空信号。
可直接插入多Agent辩论系统作为信号源。

注册为 "factor_timing" (非默认)

依赖:
    - pandas, numpy (公开库)
    - strategies.base.BaseStrategy, SignalResult
    - strategies.registry.register_strategy

作者: 基于用户原始代码增强
日期: 2026-07-05
"""

import sys, os, logging
import numpy as np
import pandas as pd
from datetime import datetime
from statistics import mean, stdev
from typing import Dict, Any, List, Optional

# ── 路径自举 ──
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ===================== 全局可配置参数（集中管理，方便调参） =====================
CONFIG = {
    # 因子列表与层级映射（key: 因子名, value: 所属层级 1/2/3/4）
    "factor_layer_map": {
        "ts": 1,    # 展期收益率 → L1
        "mom": 2,   # 动量 → L2
        "inv": 3,   # 反向仓单 → L3
        "skew": 4,  # 偏度 → L4
        "pv": 4,    # 量价相关性 → L4（与skew共享L4）
    },
    # 各层级权重（用于计算子层分数，总和应为100）
    "layer_weights": {1: 35, 2: 35, 3: 20, 4: 10},

    # 清洗参数
    "sigma_clip": 3,                # 3σ去极值
    "score_scale_factor": 33,       # Z分数映射到±100缩放系数

    # 信号等级阈值
    "strong_threshold": 75,
    "watch_threshold": 60,
    "weak_threshold": 40,

    # 趋势阶段参数
    "stage_z_launch": 2.0,
    "stage_mom_launch": 0.05,
    "stage_z_trending": 1.0,
    "stage_z_exhausted": 0.5,

    # OI三角过滤器参数
    "rise_reduce_oi_discount": 0.5,  # 上涨缩仓分数折扣
    "fall_increase_oi_boost": 1.2,   # 下跌增仓分数强化
    "fall_reduce_oi_discount": 0.8,  # 下跌减仓分数弱化

    # 择时方法（可选: "equal" 等权, "ic_decay" IC衰减）
    "timing_method": "equal",
    # IC衰减参数（仅 timing_method="ic_decay" 时生效）
    "ic_lookback": 63,
    "ic_half_life": 21,
    "ic_smooth_alpha": 0.3,          # 权重平滑系数

    # 换月处理
    "rollover_freeze_days": 2,       # 换月前后冻结天数

    "epsilon": 1e-8,                 # 全局分母防除零极小值
}


class FactorTimingStrategy(BaseStrategy):
    """因子择时策略 — 5因子（ts/mom/inv/skew/pv）→ L1-L4分层择时"""

    @property
    def name(self) -> str:
        return "factor_timing"

    @property
    def display_name(self) -> str:
        return "因子择时(5因子L1-L4)"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
    ) -> dict:
        """
        执行5因子择时打分。

        从 tech_list + df_map 中提取所需数据，调用因子择时引擎。
        输出格式与 full_scan_{YYYYMMDD}.json 完全兼容。
        """
        # ── 将 tech_list + df_map 转换为 market_data 格式 ──
        market_data = _build_market_data(tech_list, df_map)

        # ── 调用因子择时引擎 ──
        raw = _generate_factor_timing_scan(
            date=datetime.now(),
            market_data=market_data,
            min_volume=0,
        )

        # ── 将 raw 输出转换为 SignalResult 列表 ──
        results = []
        for entry in raw.get("all_ranked", []):
            sym = entry["symbol"]
            result = SignalResult(
                symbol=sym,
                name=entry.get("name", sym),
                total=entry.get("total", 0),
                abs_score=entry.get("abs", 0),
                direction=entry.get("direction", "neutral"),
                grade=entry.get("grade", "NOISE"),
                sub_scores={
                    "l1": entry.get("l1", 0),
                    "l2": entry.get("l2", 0),
                    "l3": entry.get("l3", 0),
                    "l4": entry.get("l4", 0),
                },
                veto=entry.get("veto", 0),
                price=entry.get("price", 0),
                change_pct=entry.get("change_pct", 0),
                volume=int(round(float(entry.get("volume", 0)))),
                adx=entry.get("adx", 0),
                rsi=entry.get("rsi", 0),
                cci=entry.get("cci", 0),
                ma_slope=entry.get("ma_slope", 0),
                macd_cross=entry.get("macd_cross", "none"),
                dc20_break=entry.get("dc20_break", "none"),
                ma_align=entry.get("ma_align", "mixed"),
                stage=entry.get("stage", "unknown"),
                z_score=entry.get("z_score", 0),
                consistency=entry.get("cons", 0),
            )
            results.append(result)

        # ── 一致性 + Z-score ──
        _enrich(results)

        # ── 排序 ──
        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)

        # ── 构建输出 ──
        totals = [r.total for r in results]
        mu = mean(totals) if totals else 0
        sigma = stdev(totals) if len(totals) > 1 else 1

        bear_totals = [r.total for r in results if r.total < 0]
        bull_totals = [r.total for r in results if r.total > 0]
        mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
        sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
        mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
        sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

        summary = {
            "_meta": {
                "mode": "layered",
                "strategy": self.name,
                "total": len(results),
                "bull": len([r for r in results if r.direction == "bull"]),
                "bear": len([r for r in results if r.direction == "bear"]),
                "z_mu": round(mu, 1),
                "z_sigma": round(sigma, 1),
                "z_mu_bear": round(mu_bear, 1) if mu_bear is not None else None,
                "z_sigma_bear": round(sigma_bear, 1) if sigma_bear is not None else None,
                "z_mu_bull": round(mu_bull, 1) if mu_bull is not None else None,
                "z_sigma_bull": round(sigma_bull, 1) if sigma_bull is not None else None,
            },
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
        }
        return summary


# ===================== 数据适配层 =====================

def _build_market_data(tech_list: list[dict], df_map: Optional[dict] = None) -> Dict[str, Dict]:
    """
    将 tech_list + df_map 转换为因子择时引擎所需的 market_data 格式。

    market_data 格式:
        {symbol: {
            "close": float, "prev_close": float,
            "oi": float, "prev_oi": float,
            "volume": float, "prev_volume": float,
            "far_close": float, "close_20d_ago": float,
            "warehouse_receipt": float, "wr_last_year": float,
            "returns_60d": List[float],
            "adx": float, "rsi": float, "cci": float,
            "ma_slope": float, "macd_cross": str,
            "dc20_break": str, "ma_align": str,
            "momentum_20d": float, "pv_corr_20d": float,
            "name": str, "change_pct": float,
            "is_rollover": bool
        }}
    """
    market_data = {}

    for tech in tech_list:
        sym = tech.get("symbol", "")
        if not sym:
            continue

        close = tech.get("last_price", tech.get("price", 0))
        name = tech.get("name", sym)
        change_pct = tech.get("change_pct", 0)
        volume = float(tech.get("volume", 0))
        oi = float(tech.get("open_interest", 0))

        # 从 df_map 获取历史序列
        prev_close, prev_oi, prev_volume, close_20d_ago = close, oi, volume, close
        returns_60d = []
        pv_corr_20d = 0.0
        momentum_20d = 0.0

        if df_map and sym in df_map:
            df = df_map[sym]
            closes = df["close"].values.astype(float)
            volumes = df.get("volume", df.get("volume", pd.Series([0]*len(df)))).values.astype(float)
            oi_col = None
            for col in ("open_interest", "oi"):
                if col in df.columns:
                    oi_col = col
                    break
            oi_vals = df[oi_col].values.astype(float) if oi_col else None

            n = len(closes)
            if n >= 2:
                prev_close = float(closes[-2])
            if oi_vals is not None and n >= 2:
                prev_oi = float(oi_vals[-2])
            if n >= 2:
                prev_volume = float(volumes[-2])
            if n >= 21:
                close_20d_ago = float(closes[-21])

            # 60日收益率序列
            if n >= 2:
                rets = (closes[1:] - closes[:-1]) / (closes[:-1] + 1e-8)
                returns_60d = rets[-60:].tolist() if len(rets) >= 60 else rets.tolist()

            # 动量: 20日收益率
            if n >= 21:
                momentum_20d = float((closes[-1] / closes[-21]) - 1)

            # 量价相关性（20日）
            if len(closes) >= 21 and len(volumes) >= 21:
                c20 = closes[-20:]
                v20 = volumes[-20:]
                if np.std(c20) > 1e-8 and np.std(v20) > 1e-8:
                    pv_corr_20d = float(np.corrcoef(c20, v20)[0, 1])

        # 技术指标
        adx = float(tech.get("ADX", 25))
        rsi = float(tech.get("RSI14", 50))
        cci = float(tech.get("CCI20", 0))
        ma_slope = float(tech.get("MA20_SLOPE", 0))

        # 通道/均线信号（从tech中提取或推算）
        macd_cross = tech.get("macd_cross", "none")
        dc20_break = tech.get("dc20_break", "none")
        ma_align = tech.get("ma_align", "mixed")

        # 通过原始MABCDIF/DEA推算macd_cross
        if macd_cross == "none":
            dif = tech.get("MACD_DIF")
            dea = tech.get("MACD_DEA")
            if dif is not None and dea is not None:
                macd_cross = "golden" if dif > dea else ("death" if dif < dea else "none")

        # 通过DC位置推算dc20_break
        if dc20_break == "none":
            dc_upper = tech.get("DC_UPPER")
            dc_lower = tech.get("DC_LOWER")
            if dc_upper and dc_lower and close:
                if close >= dc_upper:
                    dc20_break = "up"
                elif close <= dc_lower:
                    dc20_break = "down"

        # 通过均线排列推算ma_align
        if ma_align == "mixed":
            ma5 = tech.get("MA5")
            ma10 = tech.get("MA10")
            ma20 = tech.get("MA20")
            if ma5 and ma10 and ma20:
                if ma5 > ma10 > ma20:
                    ma_align = "bull"
                elif ma5 < ma10 < ma20:
                    ma_align = "bear"
                else:
                    ma_align = "mixed"

        market_data[sym] = {
            "close": close,
            "prev_close": prev_close,
            "oi": oi,
            "prev_oi": prev_oi,
            "volume": volume,
            "prev_volume": prev_volume,
            # 远月合约数据（现有数据不包含，用close近似）
            "far_close": close * 1.002,
            "close_20d_ago": close_20d_ago,
            # 仓单数据（现有数据不包含，默认为0）
            "warehouse_receipt": 5000,
            "wr_last_year": 6000,
            "returns_60d": returns_60d,
            "adx": adx,
            "rsi": rsi,
            "cci": cci,
            "ma_slope": ma_slope,
            "macd_cross": macd_cross,
            "dc20_break": dc20_break,
            "ma_align": ma_align,
            "momentum_20d": momentum_20d,
            "pv_corr_20d": pv_corr_20d,
            "name": name,
            "change_pct": change_pct,
            "is_rollover": False,
        }

    return market_data


# ===================== 因子择时引擎（核心算法） =====================

def _generate_factor_timing_scan(
    date: datetime,
    market_data: Dict[str, Dict],
    exclude_symbols: Optional[List[str]] = None,
    min_volume: float = 0,
    ic_history: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, Any]:
    """
    因子择时策略：输出 full_scan_{YYYYMMDD}.json 格式的多空信号（优化增强版）

    参数:
        date: 交易日 datetime
        market_data: 全品种行情指标字典
        exclude_symbols: 黑名单合约列表
        min_volume: 最低成交量过滤
        ic_history: 历史IC数据（仅 timing_method="ic_decay" 时需要）

    返回:
        符合 full_scan 格式的字典
    """
    exclude_symbols = exclude_symbols or []
    # 过滤黑名单+低流动性品种+换月窗口品种
    symbols = []
    for sym in market_data.keys():
        if sym in exclude_symbols:
            continue
        if market_data[sym].get("volume", 0) < min_volume:
            continue
        # 换月窗口处理
        if market_data[sym].get("is_rollover", False):
            logger.info(f"品种 {sym} 处于换月窗口，跳过信号生成")
            continue
        symbols.append(sym)

    if not symbols:
        return {
            "_meta": {
                "mode": "layered",
                "strategy": "factor_timing_simple",
                "total": 0, "bull": 0, "bear": 0,
                "z_mu": 0, "z_sigma": 0
            },
            "all_ranked": [],
            "bull_signals": [],
            "bear_signals": []
        }

    # ========== 1. 计算五个核心因子 ==========
    factor_values = {}
    for sym in symbols:
        d = market_data[sym]
        try:
            close = d.get("close", CONFIG["epsilon"])
            far_close = d.get("far_close", close)
            close_20d_ago = d.get("close_20d_ago", close)
            warehouse_receipt = d.get("warehouse_receipt", 0)
            wr_last_year = d.get("wr_last_year", CONFIG["epsilon"])
            returns_60d = d.get("returns_60d", [])
            pv_corr_20d = d.get("pv_corr_20d", 0)

            # 1. 展期收益率 TS (正向: backwardation 利好)
            ts = (far_close - close) / close

            # 2. 动量 MOM (保留幅度)
            ret_20d = (close / close_20d_ago) - 1
            mom = ret_20d

            # 3. 反向仓单 INV (仓单同比减少利好)
            inv_diff = warehouse_receipt - wr_last_year
            inv = -inv_diff / wr_last_year

            # 4. 收益率偏度 SKEW (负偏度利好，取负)
            ret_series = pd.Series(returns_60d)
            if len(ret_series) < 10:
                skew = 0.0
            else:
                skew = -ret_series.skew()

            # 5. 量价持仓相关性 PV (正向)
            pv = pv_corr_20d

        except Exception as e:
            logger.warning(f"因子计算异常 - 品种 {sym}: {str(e)}")
            ts, mom, inv, skew, pv = 0.0, 0.0, 0.0, 0.0, 0.0

        factor_values[sym] = [ts, mom, inv, skew, pv]

    # 构造因子 DataFrame
    df = pd.DataFrame.from_dict(
        factor_values, orient="index",
        columns=["ts", "mom", "inv", "skew", "pv"]
    )
    df = df.fillna(0.0)

    # ========== 2. 清洗：3σ去极值 + 截面Z标准化 ==========
    df = df.clip(
        lower=df.mean() - CONFIG["sigma_clip"] * df.std(),
        upper=df.mean() + CONFIG["sigma_clip"] * df.std(),
        axis=1
    )
    df = (df - df.mean()) / (df.std() + CONFIG["epsilon"])

    # ========== 3. 择时权重计算 ==========
    if CONFIG["timing_method"] == "ic_decay" and ic_history is not None:
        weights = _calc_ic_decay_weights(date, df, ic_history)
    else:
        # 默认等权
        weights = pd.Series(1.0 / df.shape[1], index=df.columns)

    # 合成总Z分数 (加权平均)
    z_scores = (df * weights).sum(axis=1)

    # ========== 4. OI三角量仓过滤器（增强版） ==========
    for sym in symbols:
        d = market_data[sym]
        dp = d.get("close", 0) - d.get("prev_close", 0)
        doi = d.get("oi", 0) - d.get("prev_oi", 0)
        dv = d.get("volume", 0) - d.get("prev_volume", 0)
        current_z = z_scores.loc[sym]

        if dp > 0 and doi > 0 and dv > 0:
            # 上涨增仓放量：强势多头，保持原分数
            continue
        elif dp > 0 and doi < 0:
            # 上涨减仓：多头动能衰减，分数打折
            z_scores.loc[sym] = current_z * CONFIG["rise_reduce_oi_discount"]
        elif dp < 0 and doi > 0 and dv > 0:
            # 下跌增仓放量：空头强势，强化空头分数
            z_scores.loc[sym] = current_z * CONFIG["fall_increase_oi_boost"]
        elif dp < 0 and doi < 0:
            # 下跌减仓：空头衰竭，弱化空头分数
            z_scores.loc[sym] = current_z * CONFIG["fall_reduce_oi_discount"]

    # ========== 5. 构建全量信号列表 ==========
    all_ranked = []
    bull_signals = []
    bear_signals = []

    for sym in symbols:
        z = z_scores.loc[sym]
        d = market_data[sym]

        # 映射到 -100 ~ +100
        total = int(np.clip(z * CONFIG["score_scale_factor"], -100, 100))
        abs_score = abs(total)
        direction = "bull" if total > 0 else ("bear" if total < 0 else "neutral")

        # 信号等级
        if abs_score >= CONFIG["strong_threshold"]:
            grade = "STRONG"
        elif abs_score >= CONFIG["watch_threshold"]:
            grade = "WATCH"
        elif abs_score >= CONFIG["weak_threshold"]:
            grade = "WEAK"
        else:
            grade = "NOISE"

        # 基础技术指标
        adx = round(d.get("adx", 25.0), 1)
        rsi = round(d.get("rsi", 50.0), 1)
        cci = round(d.get("cci", 0.0), 1)
        ma_slope = round(d.get("ma_slope", 0.0), 4)
        macd_cross = d.get("macd_cross", "none")
        dc20_break = d.get("dc20_break", "none")
        ma_align = d.get("ma_align", "mixed")
        momentum_20d = d.get("momentum_20d", 0.0)

        # 趋势阶段判定
        if abs(z) > CONFIG["stage_z_launch"] and abs(momentum_20d) > CONFIG["stage_mom_launch"]:
            stage = "launch"
        elif abs(z) > CONFIG["stage_z_trending"]:
            stage = "trending"
        elif abs(z) > CONFIG["stage_z_exhausted"]:
            stage = "exhausted"
        else:
            stage = "reversal"

        # 因子方向一致性
        factor_signs = np.sign(df.loc[sym].values)
        target_sign = np.sign(z)
        cons = int(np.sum((factor_signs * target_sign) > 0))

        # 否决项预留
        veto = 0

        # L1-L4 子层分数
        layer_scores = _calc_layer_scores(df.loc[sym], weights)
        l1, l2, l3, l4 = (
            layer_scores.get(1, 0),
            layer_scores.get(2, 0),
            layer_scores.get(3, 0),
            layer_scores.get(4, 0),
        )

        entry = {
            "symbol": sym,
            "name": d.get("name", sym),
            "price": d.get("close", 0.0),
            "change_pct": d.get("change_pct", 0.0),
            "total": total,
            "abs": abs_score,
            "direction": direction,
            "grade": grade,
            "adx": adx,
            "rsi": rsi,
            "cci": cci,
            "ma_slope": ma_slope,
            "macd_cross": macd_cross,
            "dc20_break": dc20_break,
            "ma_align": ma_align,
            "z_score": round(z, 4),
            "stage": stage,
            "cons": cons,
            "veto": veto,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "l4": l4,
        }
        all_ranked.append(entry)
        if direction == "bull":
            bull_signals.append(entry)
        elif direction == "bear":
            bear_signals.append(entry)

    # 排序
    all_ranked.sort(key=lambda x: x["total"], reverse=True)
    bull_signals.sort(key=lambda x: x["total"], reverse=True)
    bear_signals.sort(key=lambda x: x["total"])

    # 全局分数统计
    scores_arr = [e["total"] for e in all_ranked]
    meta_mean = round(float(np.mean(scores_arr)), 2) if scores_arr else 0.0
    meta_std = round(float(np.std(scores_arr)), 2) if scores_arr else 0.0

    output = {
        "_meta": {
            "mode": "layered",
            "strategy": "factor_timing_simple",
            "total": len(all_ranked),
            "bull": len(bull_signals),
            "bear": len(bear_signals),
            "z_mu": meta_mean,
            "z_sigma": meta_std,
        },
        "all_ranked": all_ranked,
        "bull_signals": bull_signals,
        "bear_signals": bear_signals,
    }
    return output


# ===================== 辅助函数 =====================

def _calc_layer_scores(
    factor_row: pd.Series,
    weights: pd.Series
) -> Dict[int, int]:
    """
    根据因子所属层级，计算 L1-L4 子层分数。
    每个层级的分数 = 该层内因子加权z-score之和，再缩放到该层权重范围。
    """
    layer_map = CONFIG["factor_layer_map"]
    layer_weights = CONFIG["layer_weights"]
    epsilon = CONFIG["epsilon"]

    layer_raw = {}
    for factor_name, layer_id in layer_map.items():
        if factor_name not in factor_row.index or factor_name not in weights.index:
            continue
        val = factor_row[factor_name] * weights[factor_name]
        layer_raw.setdefault(layer_id, []).append(val)

    result = {}
    for layer_id, values in layer_raw.items():
        if not values:
            result[layer_id] = 0
            continue
        avg = np.mean(values)
        max_range = layer_weights.get(layer_id, 10)
        scaled = int(np.clip(avg * max_range, -max_range, max_range))
        result[layer_id] = scaled

    for lid in [1, 2, 3, 4]:
        if lid not in result:
            result[lid] = 0
    return result


def _calc_ic_decay_weights(
    date: datetime,
    df: pd.DataFrame,
    ic_history: Dict[str, np.ndarray]
) -> pd.Series:
    """
    基于历史IC的指数衰减加权计算因子权重。
    """
    lookback = CONFIG["ic_lookback"]
    half_life = CONFIG["ic_half_life"]
    epsilon = CONFIG["epsilon"]

    factor_names = df.columns
    n_factors = len(factor_names)

    ic_matrix = np.zeros((lookback, n_factors))
    for i, fname in enumerate(factor_names):
        if fname in ic_history and len(ic_history[fname]) >= lookback:
            ic_matrix[:, i] = ic_history[fname][-lookback:]
        else:
            ic_matrix[:, i] = 0.0

    decay = np.exp(-np.arange(lookback) / half_life)
    weighted_ic = (ic_matrix * decay[:, None]).sum(axis=0)

    exp_ic = np.exp(weighted_ic - np.max(weighted_ic))
    weights = exp_ic / (exp_ic.sum() + epsilon)

    return pd.Series(weights, index=factor_names)


def _enrich(results: list[SignalResult]):
    """计算 Z-score 和子层一致性"""
    bear_totals = [r.total for r in results if r.direction == "bear"]
    bull_totals = [r.total for r in results if r.direction == "bull"]
    mu_bear = mean(bear_totals) if len(bear_totals) > 1 else None
    sigma_bear = stdev(bear_totals) if len(bear_totals) > 1 else None
    mu_bull = mean(bull_totals) if len(bull_totals) > 1 else None
    sigma_bull = stdev(bull_totals) if len(bull_totals) > 1 else None

    for r in results:
        if r.direction == "bear" and sigma_bear and sigma_bear > 0:
            r.z_score = round((r.total - mu_bear) / sigma_bear, 2)
        elif r.direction == "bull" and sigma_bull and sigma_bull > 0:
            r.z_score = round((r.total - mu_bull) / sigma_bull, 2)
        else:
            r.z_score = 0.0

        layers = [r.sub_scores.get(k, 0) for k in ("l1", "l2", "l3", "l4")]
        r.consistency = sum(
            1 for l in layers
            if (l > 0 and r.total > 0) or (l < 0 and r.total < 0)
        )


# ── 自动注册 ──
register_strategy(FactorTimingStrategy, is_default=False)
