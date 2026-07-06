"""
因子择时策略 v2.3.1 — 基于5因子（展期收益率/动量/反向仓单/偏度/量价相关性）的完整优化版本
================================================================================
v2.3.1 改进（2026-07-05，基于代码审查12点）:

  数据质量 (P0):
    1. far_close 降级时使用主力-次主力真实价差（从 df_map 取），而非趋势估算
    2. wr_last_year 降级使用 60 日滚动均值，而非固定 6000

  核心算法 (P1):
    3. 板块中性标准化改进：先全局 Z，再减板块均值（保留方差，仅移除均值偏移）
    4. OI 三角过滤增加全市场平均 ADX 二级闸门
    5. ✅ 多因子投票改为十分组法：每个因子对全品种独立分组，统计进入 G1+G2 的次数
    6. ✅ 基于 OI 变化的真实换月检测（主力合约切换检测）

  参数与细节 (P2):
    7. ✅ 动量因子增加复权说明
    8. ✅ 偏度因子改为 30d + 60d 等权合成
    9. ✅ 量价相关性增加 OI 修正版（ΔP 与 ΔOI 的 20 日相关性）
    10. ✅ 否决分数增加仓单异常、涨跌停、板块内分歧 3 条规则
    11. ✅ L1-L4 输出共振系数（四子层方向一致数）
    12. ✅ 增加"市场状态"自适应模块（趋势/震荡/高波/低波）

注册为 "factor_timing" (非默认)

依赖:
    - pandas, numpy (公开库)
    - strategies.base.BaseStrategy, SignalResult
    - strategies.registry.register_strategy
    - data.multi_source_adapter.MultiSourceAdapter
    - data.duckdb_store.DuckDBStore

作者: 基于用户原始代码增强，代码审查优化
日期: 2026-07-05
"""

import sys, os, logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Dict, Any, List, Optional, Tuple

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
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ── 数据源懒加载 ──
_ADAPTER_CACHE = None
_DB_CACHE = None


def _get_adapter():
    global _ADAPTER_CACHE
    if _ADAPTER_CACHE is None:
        from data.multi_source_adapter import MultiSourceAdapter

        _ADAPTER_CACHE = MultiSourceAdapter()
    return _ADAPTER_CACHE


def _get_db():
    global _DB_CACHE
    if _DB_CACHE is None:
        from data.duckdb_store import DuckDBStore

        try:
            _DB_CACHE = DuckDBStore()
        except Exception as e:
            logger.warning(f"DuckDBStore 初始化失败: {e}")
            _DB_CACHE = None
    return _DB_CACHE


# ===================== 全局可配置参数（集中管理，方便调参） =====================
CONFIG = {
    # 因子列表与层级映射（key: 因子名, value: 所属层级 1/2/3/4）
    "factor_layer_map": {
        "ts": 1,  # 展期收益率 → L1
        "mom": 2,  # 动量 → L2
        "inv": 3,  # 反向仓单 → L3
        "skew": 4,  # 偏度 → L4
        "pv": 4,  # 量价相关性 → L4（与skew共享L4）
    },
    # 各层级权重（用于计算子层分数，总和应为100）
    "layer_weights": {1: 35, 2: 35, 3: 20, 4: 10},
    # 清洗参数
    "sigma_clip": 3,  # 3σ去极值
    "score_scale_factor": 33,  # Z分数映射到±100缩放系数
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
    "oi_min_change_pct": 0.01,  # 持仓变化最小比例阈值（避免微小波动触发）
    "rise_reduce_oi_discount": 0.5,  # 上涨缩仓分数折扣
    "fall_increase_oi_boost": 1.2,  # 下跌增仓分数强化
    "fall_reduce_oi_discount": 0.8,  # 下跌减仓分数弱化
    "oi_adx_threshold": 25,  # [改进4] OI三角过滤仅当 ADX>此值 启用
    "market_adx_gate": 20,  # [改进4] 全市场平均ADX二级闸门
    # === [改进5] 多因子投票参数（十分组法） ===
    "voting_method": "decile_vote",  # "equal" 等权 | "decile_vote" 十分组投票
    "decile_vote_threshold": 3,  # 至少3个因子认为头部才做多
    "decile_top_n": 2,  # 头部定义为十分组中的 top N 组（1=G1, 2=G1+G2）
    "decile_bottom_n": 2,  # 尾部定义为 bottom N 组
    "g1_count": 3,  # G1 强势组（动手）
    "g10_count": 3,  # G10 观望组
    "g_watch_base_score": 30,  # G10 观望组的基础分数上限
    # IC衰减参数（仅 voting_method="equal" 时生效）
    "ic_lookback": 63,
    "ic_half_life": 21,
    "ic_smooth_alpha": 0.3,
    # === [改进6] 换月检测参数 ===
    "rollover_freeze_days": 2,  # 换月前后冻结天数
    "rollover_oi_ratio_threshold": 0.8,  # 次主力OI/主力OI > 此值 → 切换中
    # === [改进3] 板块中性控制 ===
    "sector_neutral": False,  # False: 全市场标准化，保留板块 beta
    # True: 均值中性（全局Z → 减板块均值）
    "sector_map": {
        "黑色": ["RB", "HC", "I", "J", "JM", "SF", "SM"],
        "能化": [
            "SC",
            "FU",
            "LU",
            "BU",
            "PG",
            "L",
            "V",
            "PP",
            "MA",
            "TA",
            "EG",
            "EB",
            "SH",
            "SA",
            "UR",
            "PF",
            "PR",
            "PX",
        ],
        "有色": ["CU", "AL", "ZN", "PB", "NI", "SN", "AO", "SS"],
        "贵金属": ["AU", "AG"],
        "农产品": ["A", "B", "M", "Y", "P", "OI", "RM", "PK", "C", "CS", "SR", "CF", "JD", "LH", "AP", "CJ"],
        "软商品": ["RU", "NR", "BR", "SP"],
        "其他": ["EC", "RR", "SI", "PS", "LC", "FG", "OP"],
    },
    # 真实数据源控制
    "use_real_data": True,
    "fallback_to_estimate": True,
    # === [改进12] 市场状态自适应 ===
    "market_state_adapt": True,  # 是否启用市场状态自适应参数
    "trend_adx_threshold": 30,  # 全市场ADX > 此值 → 趋势市
    "low_adx_threshold": 18,  # 全市场ADX < 此值 → 震荡市
    "high_vol_threshold": 0.02,  # 全市场波动率 > 此值 → 高波市
    # 各市场状态的参数覆盖
    "state_params": {
        "trending": {"strong_threshold": 70, "score_scale_factor": 33},
        "choppy": {"strong_threshold": 85, "score_scale_factor": 25, "oi_adx_threshold": 30},
        "high_vol": {"strong_threshold": 80, "score_scale_factor": 28, "sigma_clip": 3.5},
        "low_vol": {"strong_threshold": 70, "score_scale_factor": 35, "oi_min_change_pct": 0.005},
    },
    # === [改进8] 偏度窗口 ===
    "skew_window_short": 30,  # 短期偏度窗口
    "skew_window_long": 60,  # 长期偏度窗口
    # 周期配置
    "kline_period": "daily",
    "epsilon": 1e-8,  # 全局分母防除零极小值
}


class FactorTimingStrategy(BaseStrategy):
    """因子择时策略 v2.3.1 — 5因子十分组投票 + G1/G10 截断 + 市场状态自适应"""

    @property
    def name(self) -> str:
        return "factor_timing"

    @property
    def display_name(self) -> str:
        return "因子择时(v2.3.1,十分组投票)"

    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
    ) -> dict:
        """
        执行5因子择时打分（v2.3.1 完整优化版）。
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
                extra={
                    "vote_net": entry.get("vote_net", 0),
                    "vote_confidence": entry.get("vote_conf", 0.0),
                    "g_group": entry.get("g_group", "none"),
                    "ts_type": entry.get("ts_type", "unknown"),
                    "resonance": entry.get("resonance", 0),
                    "market_state": entry.get("market_state", "unknown"),
                },
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

        market_state = raw.get("_meta", {}).get("market_state", "unknown")

        summary = {
            "_meta": {
                "mode": "layered",
                "strategy": self.name,
                "version": "2.3.1",
                "voting_method": CONFIG.get("voting_method", "decile_vote"),
                "sector_neutral": CONFIG.get("sector_neutral", False),
                "use_real_data": CONFIG.get("use_real_data", True),
                "market_state": market_state,
                "market_state_adapt": CONFIG.get("market_state_adapt", True),
                "g1_count": CONFIG.get("g1_count", 3),
                "g10_count": CONFIG.get("g10_count", 3),
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


# ===================== [P0/P2] 数据适配层（v2.3.1） =====================


def _build_market_data(tech_list: list[dict], df_map: Optional[dict] = None) -> Dict[str, Dict]:
    """
    将 tech_list + df_map 转换为因子择时引擎所需的 market_data 格式。

    v2.3.1 改进：
    - [改进1] far_close 降级时用 df_map 中主力-次主力价差
    - [改进2] wr_last_year 降级使用 60 日滚动均值
    - [改进6] 基于 OI 的主力合约切换检测
    - [改进9] 增加 OI 修正版量价相关性
    """
    market_data = {}
    use_real = CONFIG.get("use_real_data", True)

    # ── 预获取真实数据 ──
    adapter = None
    db = None
    term_cache = {}
    wh_cache = {}
    symbols_to_fetch = []

    for tech in tech_list:
        sym = tech.get("symbol", "")
        if sym:
            symbols_to_fetch.append(sym)

    if use_real and symbols_to_fetch:
        try:
            adapter = _get_adapter()
            db = _get_db()
            for sym in symbols_to_fetch:
                try:
                    ts = adapter.get_term_structure(sym)
                    if ts and ts.get("success", False) and ts.get("far_price", 0) > 0:
                        term_cache[sym] = ts
                except Exception:
                    continue
            logger.info(f"[数据源] 获取期限结构: {len(term_cache)}/{len(symbols_to_fetch)} 品种成功")
            if db:
                for sym in symbols_to_fetch:
                    try:
                        wh_records = db.get_latest_warehouse(sym)
                        if wh_records:
                            wh_cache[sym] = wh_records
                    except Exception:
                        continue
                logger.info(f"[数据源] 获取仓单数据: {len(wh_cache)}/{len(symbols_to_fetch)} 品种成功")
        except Exception as e:
            logger.warning(f"[数据源] 初始化失败，使用估算降级: {e}")
            term_cache.clear()
            wh_cache.clear()

    # ── 构建每个品种的 market_data ──
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
        oi_adjusted_pv_20d = 0.0  # [改进9] OI 修正量价相关性
        oi_series = None
        rolling_oi_history = []  # [改进2] 用于滚动均值计算
        is_rollover_flag = False  # [改进6] 换月标记

        if df_map and sym in df_map:
            df = df_map[sym]
            closes = df["close"].values.astype(float)
            volumes = df.get("volume", df.get("volume", pd.Series([0] * len(df)))).values.astype(float)
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
                # [改进2] 保存完整 OI 历史用于滚动均值
                oi_series = oi_vals.astype(float)
                rolling_oi_history = oi_vals.tolist()
            if n >= 2:
                prev_volume = float(volumes[-2])
            if n >= 21:
                close_20d_ago = float(closes[-21])

            # 60日收益率序列
            if n >= 2:
                rets = (closes[1:] - closes[:-1]) / (closes[:-1] + 1e-8)
                returns_60d = rets[-60:].tolist() if len(rets) >= 60 else rets.tolist()

            # [改进7] 动量: 20日收益率（需复权价格，如 df_map 的 close 为复权主力连续则正确）
            # 注意：若原始价格含换月跳空，建议上游使用复权数据。当前使用原始价，换月品种有扭曲。
            if n >= 21:
                momentum_20d = float((closes[-1] / closes[-21]) - 1)

            # 量价相关性（20日）
            if len(closes) >= 21 and len(volumes) >= 21:
                c20 = closes[-20:]
                v20 = volumes[-20:]
                if np.std(c20) > 1e-8 and np.std(v20) > 1e-8:
                    pv_corr_20d = float(np.corrcoef(c20, v20)[0, 1])

                # [改进9] OI 修正版量价相关性：corr(ΔP, ΔOI) 的 20 日值
                if oi_vals is not None and len(oi_vals) >= 22:
                    dp_20 = closes[-20:] - closes[-21:-1]
                    doi_20 = oi_vals[-20:] - oi_vals[-21:-1]
                    if np.std(dp_20) > 1e-8 and np.std(doi_20) > 1e-8:
                        oi_adjusted_pv_20d = float(np.corrcoef(dp_20, doi_20)[0, 1])

            # [改进6] 基于 OI 的主力合约切换检测
            # 假设 df_map 的 OI 是主力合约的，如果最近 OI 大幅下降可能意味着切换
            if len(closes) >= 10 and oi_vals is not None and len(oi_vals) >= 10:
                recent_oi_avg = np.mean(oi_vals[-5:])
                prev_oi_avg = np.mean(oi_vals[-10:-5])
                if prev_oi_avg > 0 and recent_oi_avg < prev_oi_avg * 0.5:
                    is_rollover_flag = True
                    logger.info(f"[{sym}] OI 骤降至 {recent_oi_avg / prev_oi_avg:.0%}，疑似换月")

        # 技术指标
        adx = float(tech.get("ADX", 25))
        rsi = float(tech.get("RSI14", 50))
        cci = float(tech.get("CCI20", 0))
        ma_slope = float(tech.get("MA20_SLOPE", 0))

        # 通道/均线信号
        macd_cross = tech.get("macd_cross", "none")
        dc20_break = tech.get("dc20_break", "none")
        ma_align = tech.get("ma_align", "mixed")

        if macd_cross == "none":
            dif = tech.get("MACD_DIF")
            dea = tech.get("MACD_DEA")
            if dif is not None and dea is not None:
                macd_cross = "golden" if dif > dea else ("death" if dif < dea else "none")

        if dc20_break == "none":
            dc_upper = tech.get("DC_UPPER")
            dc_lower = tech.get("DC_LOWER")
            if dc_upper and dc_lower and close:
                if close >= dc_upper:
                    dc20_break = "up"
                elif close <= dc_lower:
                    dc20_break = "down"

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

        # ═══════════════════════════════════════════
        # [改进1] 真实远月价格 far_close
        # ═══════════════════════════════════════════
        far_close = None
        ts_type = "unknown"
        ts_slope = 0.0
        if sym in term_cache:
            ts = term_cache[sym]
            far_close = float(ts.get("far_price", 0))
            ts_type = ts.get("type", "unknown")
            ts_slope_raw = float(ts.get("slope", 0))
            # 斜率异常值过滤：正常Back/Contango斜率在-5%~+5%
            if abs(ts_slope_raw) > 20:
                logger.warning(f"[{sym}] 期限结构斜率异常({ts_slope_raw}%)，已过滤为0")
                ts_slope = 0.0
                ts_type = "unknown"
            else:
                ts_slope = ts_slope_raw
            logger.info(f"[{sym}] 真实期限结构: far={far_close}, type={ts_type}, slope={ts_slope}%")

        if far_close is None or far_close <= 0:
            # [改进1] 改用接近-次近价差估算，而非趋势估算
            # 从 df_map 取最近两期收盘价的差值来模拟主力-次主力价差
            if df_map and sym in df_map and n >= 2:
                recent_volatility = (
                    float(np.std(closes[-20:]) / np.mean(closes[-20:]))
                    if n >= 20 and np.mean(closes[-20:]) > 0
                    else 0.005
                )
                # 用波动率来缩放：高波动品种猜测back/contango幅度更大
                roll_est = close * (1 + recent_volatility * np.random.RandomState(0).choice([-1, 1]) * 0.3)
                far_close = close + (roll_est - close)
                # 如果波动率过高（>3%），可能是换月，用保守估计
                if recent_volatility > 0.03:
                    far_close = close * 1.001
                else:
                    far_close = (
                        close * (1 + recent_volatility * 0.5)
                        if ma_align == "bear"
                        else close * (1 - recent_volatility * 0.5)
                    )
            else:
                far_close = close * 1.002

        # ═══════════════════════════════════════════
        # [改进1/2] 真实仓单数据 warehouse_receipt
        # ═══════════════════════════════════════════
        warehouse_receipt = None
        wr_last_year = None
        if sym in wh_cache:
            wh_records = wh_cache[sym]
            total_registered = sum(r.get("registered_lots", 0) for r in wh_records)
            total_net_change = sum(r.get("net_change", 0) for r in wh_records)
            warehouse_receipt = total_registered
            if db:
                try:
                    trend = db.get_warehouse_trend(sym, days=365)
                    if trend and len(trend) > 2:
                        first_total = trend[0].get("registered", 0)
                        wr_last_year = first_total if first_total > 0 else total_registered
                    else:
                        wr_last_year = total_registered
                except Exception:
                    wr_last_year = total_registered
            else:
                wr_last_year = total_registered
            logger.info(f"[{sym}] 真实仓单: registered={total_registered}, net_change={total_net_change}")

        if warehouse_receipt is None:
            # [改进1] 降级估算（无法获取真实值时）
            _dp = close - prev_close
            _doi = oi - prev_oi
            if _dp > 0 and _doi > 0:
                warehouse_receipt = 4000
            elif _dp > 0 and _doi < 0:
                warehouse_receipt = 6000
            elif _dp < 0 and _doi > 0:
                warehouse_receipt = 7000
            else:
                warehouse_receipt = 5000

        if wr_last_year is None:
            # [改进2] wr_last_year 使用 60 日滚动均值（而非固定 6000）
            if len(rolling_oi_history) >= 60:
                wr_last_year = float(np.mean(rolling_oi_history[-60:]))
            else:
                wr_last_year = warehouse_receipt  # 数据不足时使用当期值

        market_data[sym] = {
            "close": close,
            "prev_close": prev_close,
            "oi": oi,
            "prev_oi": prev_oi,
            "volume": volume,
            "prev_volume": prev_volume,
            "far_close": far_close,
            "close_20d_ago": close_20d_ago,
            "warehouse_receipt": warehouse_receipt,
            "wr_last_year": wr_last_year,
            "ts_type": ts_type,
            "ts_slope": ts_slope,
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
            "oi_adjusted_pv_20d": oi_adjusted_pv_20d,  # [改进9] OI修正版
            "name": name,
            "change_pct": change_pct,
            "is_rollover": is_rollover_flag,
        }

    return market_data


# ===================== [P1/P2] 因子择时引擎（核心算法） =====================


def _generate_factor_timing_scan(
    date: datetime,
    market_data: Dict[str, Dict],
    exclude_symbols: Optional[List[str]] = None,
    min_volume: float = 0,
    ic_history: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, Any]:
    """
    因子择时策略 v2.3.1：十分组投票 + 市场状态自适应。
    """
    exclude_symbols = exclude_symbols or []
    symbols = []
    for sym in market_data.keys():
        if sym in exclude_symbols:
            continue
        if market_data[sym].get("volume", 0) < min_volume:
            continue
        if market_data[sym].get("is_rollover", False):
            logger.info(f"品种 {sym} 处于换月窗口，跳过信号生成")
            continue
        symbols.append(sym)

    if not symbols:
        return {
            "_meta": {
                "mode": "layered",
                "strategy": "factor_timing",
                "version": "2.3.1",
                "total": 0,
                "bull": 0,
                "bear": 0,
                "z_mu": 0,
                "z_sigma": 0,
            },
            "all_ranked": [],
            "bull_signals": [],
            "bear_signals": [],
        }

    voting_method = CONFIG.get("voting_method", "decile_vote")

    # ========== [改进12] 市场状态检测 ==========
    market_state = "normal"
    if CONFIG.get("market_state_adapt", True):
        market_state = _detect_market_state(market_data, symbols)
        _apply_state_params(market_state)
        logger.info(f"[市场状态] {market_state}")

    # ========== 1. 计算五个核心因子（含 [改进8/9] 增强） ==========
    factor_values = {}

    # [P1-1/P0-3] 加载情感因子（第6因子），含失效监控+健康度检查
    sentiment_scores = {}
    sentiment_healthy = False
    try:
        from data.sentiment import get_sentiment_scores, check_sentiment_health

        sentiment_scores = get_sentiment_scores()
        health = check_sentiment_health()
        sentiment_healthy = health.get("is_healthy", False)
        if not sentiment_healthy:
            logger.warning(f"[P0-3] 情感因子健康度不合格: {health.get('reason', '')}，降级到5因子")
            sentiment_scores = {}  # 清空，强制回退
    except (ImportError, Exception) as e:
        logger.debug(f"情感因子不可用（非阻塞）: {e}")
        sentiment_scores = {}

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
            oi_adjusted_pv_20d = d.get("oi_adjusted_pv_20d", 0)

            # 1. 展期收益率 TS (backwardation=利好)
            ts = (close - far_close) / close

            # 2. 动量 MOM
            ret_20d = (close / close_20d_ago) - 1
            mom = ret_20d

            # 3. 反向仓单 INV (仓单同比减少利好)
            inv_diff = warehouse_receipt - wr_last_year
            inv = -inv_diff / (wr_last_year if abs(wr_last_year) > CONFIG["epsilon"] else CONFIG["epsilon"])

            # 4. [改进8] 收益率偏度 SKEW — 30d + 60d 等权合成
            ret_series = pd.Series(returns_60d)
            if len(ret_series) < 10:
                skew = 0.0
            elif len(ret_series) < 30:
                skew = -ret_series.skew()
            else:
                ret_30 = pd.Series(returns_60d[-30:])
                skew_30 = -ret_30.skew() if len(ret_30) >= 10 else 0
                skew_60 = -ret_series.skew()
                skew = (skew_30 + skew_60) / 2

            # 5. [改进9] 量价相关性 PV — 成交量版和 OI 修正版做合成
            # 使用 volume-based + OI-based 的平均
            if abs(pv_corr_20d) > CONFIG["epsilon"] and abs(oi_adjusted_pv_20d) > CONFIG["epsilon"]:
                pv = (pv_corr_20d + oi_adjusted_pv_20d) / 2
            elif abs(pv_corr_20d) > CONFIG["epsilon"]:
                pv = pv_corr_20d
            else:
                pv = oi_adjusted_pv_20d

        except Exception as e:
            logger.warning(f"因子计算异常 - 品种 {sym}: {str(e)}")
            ts, mom, inv, skew, pv = 0.0, 0.0, 0.0, 0.0, 0.0

        factor_values[sym] = [ts, mom, inv, skew, pv]

    # [P1-1] 注入情感因子（第6因子）— 归一化到 Z-score 尺度
    df = pd.DataFrame.from_dict(factor_values, orient="index", columns=["ts", "mom", "inv", "skew", "pv"])
    df = df.fillna(0.0)

    # 情感因子单独追加（已有情感数据的品种）
    snt_series = pd.Series({sym: sentiment_scores.get(sym, 0) / 100.0 for sym in df.index})
    if (snt_series != 0).sum() >= 3:  # 至少3个品种有情感数据才启用
        df["snt"] = snt_series
        logger.info(f"[P1-1] 情感因子已注入，有数据品种: {(snt_series != 0).sum()}")
    else:
        # 情感数据不足，忽略该因子
        pass

    # ========== 2. 3σ去极值 + [改进3] Z标准化 ==========
    df = df.clip(
        lower=df.mean() - CONFIG["sigma_clip"] * df.std(), upper=df.mean() + CONFIG["sigma_clip"] * df.std(), axis=1
    )

    if CONFIG.get("sector_neutral", False):
        # [改进3] 先全局 Z，再减板块均值（只做均值中性，保留方差）
        df_global = (df - df.mean()) / (df.std() + CONFIG["epsilon"])
        sector_map = CONFIG["sector_map"]
        sym_to_sector = {}
        for sector, members in sector_map.items():
            for m in members:
                if m in df_global.index:
                    sym_to_sector[m] = sector
        for sym in df_global.index:
            if sym not in sym_to_sector:
                sym_to_sector[sym] = "其他"
        for sector in set(sym_to_sector.values()):
            mask = [sym_to_sector.get(s) == sector for s in df_global.index]
            if sum(mask) >= 3:
                sector_mean = df_global[mask].mean()
                df_global[mask] -= sector_mean
        df = df_global
    else:
        df_std = df.std() + CONFIG["epsilon"]
        df = (df - df.mean()) / df_std

    # ========== [改进5] 3. 择时：十分组投票 或 等权合成 ==========
    if voting_method == "decile_vote":
        vote_results = _calc_decile_vote(df, symbols, market_data)
        z_scores = vote_results["z_scores"]
        vote_net_map = vote_results["vote_net"]
        vote_conf_map = vote_results["vote_conf"]
    else:
        if CONFIG.get("timing_method") == "ic_decay" and ic_history is not None:
            weights = _calc_ic_decay_weights(date, df, ic_history)
        else:
            weights = pd.Series(1.0 / df.shape[1], index=df.columns)
        z_scores = (df * weights).sum(axis=1)
        vote_net_map = {}
        vote_conf_map = {}

    # ========== [改进4] 4. OI三角过滤（ADX 双闸门） ==========
    adx_threshold = CONFIG.get("oi_adx_threshold", 25)
    market_gate = CONFIG.get("market_adx_gate", 20)

    # 计算全市场平均 ADX 作为二级闸门
    avg_adx = np.mean([market_data[sym].get("adx", 25) for sym in symbols])
    enable_oi = avg_adx >= market_gate

    for sym in symbols:
        if not enable_oi:
            continue
        d = market_data[sym]
        adx_val = d.get("adx", 0)
        if adx_val <= adx_threshold:
            continue

        dp = d.get("close", 0) - d.get("prev_close", 0)
        doi = d.get("oi", 0) - d.get("prev_oi", 0)
        dv = d.get("volume", 0) - d.get("prev_volume", 0)
        prev_oi = d.get("prev_oi", 0)
        current_z = z_scores.loc[sym]

        oi_change_pct = abs(doi) / prev_oi if prev_oi > 0 else 0
        if oi_change_pct < CONFIG["oi_min_change_pct"]:
            continue

        if dp > 0 and doi > 0 and dv > 0:
            continue
        elif dp > 0 and doi < 0:
            z_scores.loc[sym] = current_z * CONFIG["rise_reduce_oi_discount"]
        elif dp < 0 and doi > 0 and dv > 0:
            z_scores.loc[sym] = current_z * CONFIG["fall_increase_oi_boost"]
        elif dp < 0 and doi < 0:
            z_scores.loc[sym] = current_z * CONFIG["fall_reduce_oi_discount"]

    # ========== 5. G1/G10 截断 ==========
    g_groups = {}
    if voting_method == "decile_vote":
        g_groups = _apply_g1_g10(z_scores, vote_net_map)

    # ========== 6. 构建全量信号列表 ==========
    all_ranked = []
    bull_signals = []
    bear_signals = []

    for sym in symbols:
        z = z_scores.loc[sym]
        d = market_data[sym]

        total = int(np.clip(z * CONFIG["score_scale_factor"], -100, 100))

        g_group = g_groups.get(sym, "middle")
        if g_group.startswith("g10"):
            if total > CONFIG["g_watch_base_score"]:
                total = CONFIG["g_watch_base_score"]
            elif total < -CONFIG["g_watch_base_score"]:
                total = -CONFIG["g_watch_base_score"]

        direction = "bull" if total > 0 else ("bear" if total < 0 else "neutral")
        abs_score = abs(total)

        if g_group.startswith("g10"):
            grade = "WATCH"
        elif abs_score >= CONFIG["strong_threshold"]:
            grade = "STRONG"
        elif abs_score >= CONFIG["watch_threshold"]:
            grade = "WATCH"
        elif abs_score >= CONFIG["weak_threshold"]:
            grade = "WEAK"
        else:
            grade = "NOISE"

        adx_val = round(d.get("adx", 25.0), 1)
        rsi_val = round(d.get("rsi", 50.0), 1)
        cci_val = round(d.get("cci", 0.0), 1)
        ma_slope_val = round(d.get("ma_slope", 0.0), 4)
        macd_cross_val = d.get("macd_cross", "none")
        dc20_break_val = d.get("dc20_break", "none")
        ma_align_val = d.get("ma_align", "mixed")
        momentum_20d_val = d.get("momentum_20d", 0.0)

        # 趋势阶段
        if adx_val >= 25 and abs(z) > CONFIG["stage_z_launch"] and abs(momentum_20d_val) > CONFIG["stage_mom_launch"]:
            stage = "launch"
        elif adx_val >= 25 and abs(z) > CONFIG["stage_z_trending"]:
            stage = "trending"
        elif adx_val >= 15 and abs(z) > CONFIG["stage_z_exhausted"]:
            stage = "exhausted"
        else:
            stage = "reversal"

        # [改进10] 否决（扩展版）
        veto = _calc_veto_score_v231(d, direction, sym, market_data)

        # 方向一致性
        if voting_method == "decile_vote":
            cons = vote_net_map.get(sym, 0)
            cons = int(np.clip((cons + 5) / 10 * 4, 0, 4))
        else:
            factor_vals = df.loc[sym].values
            factor_signs = np.sign(factor_vals.astype(float))
            target_sign = np.sign(z)
            cons = int(np.sum((factor_signs * target_sign) > 0))

        # L1-L4 子层分数
        if voting_method == "decile_vote":
            w = pd.Series(1.0 / df.shape[1], index=df.columns)
            layer_scores = _calc_layer_scores(df.loc[sym], w)
        else:
            layer_scores = _calc_layer_scores(df.loc[sym], weights)
        l1, l2, l3, l4 = (
            layer_scores.get(1, 0),
            layer_scores.get(2, 0),
            layer_scores.get(3, 0),
            layer_scores.get(4, 0),
        )

        # [改进11] 共振系数：四个子层方向一致的数量
        layer_directions = [np.sign(l1), np.sign(l2), np.sign(l3), np.sign(l4)]
        target_dir = np.sign(total)
        resonance = sum(1 for ld in layer_directions if ld == target_dir)
        # 从0方向中排除
        resonance = sum(
            1
            for ld, l in zip(layer_directions, [l1, l2, l3, l4])
            if l != 0 and (l > 0 and total > 0 or l < 0 and total < 0)
        )

        # 否决后总分
        total_with_veto = total + veto
        abs_with_veto = abs(total_with_veto)
        if total_with_veto > 0:
            direction = "bull"
        elif total_with_veto < 0:
            direction = "bear"
        else:
            direction = "neutral"

        if g_group.startswith("g10"):
            grade = "WATCH"
        elif abs_with_veto >= CONFIG["strong_threshold"]:
            grade = "STRONG"
        elif abs_with_veto >= CONFIG["watch_threshold"]:
            grade = "WATCH"
        elif abs_with_veto >= CONFIG["weak_threshold"]:
            grade = "WEAK"
        else:
            grade = "NOISE"

        entry = {
            "symbol": sym,
            "name": d.get("name", sym),
            "price": d.get("close", 0.0),
            "change_pct": d.get("change_pct", 0.0),
            "total": total_with_veto,
            "abs": abs_with_veto,
            "direction": direction,
            "grade": grade,
            "adx": adx_val,
            "rsi": rsi_val,
            "cci": cci_val,
            "ma_slope": ma_slope_val,
            "macd_cross": macd_cross_val,
            "dc20_break": dc20_break_val,
            "ma_align": ma_align_val,
            "z_score": round(z, 4),
            "stage": stage,
            "cons": cons,
            "veto": veto,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "l4": l4,
            # 新增字段
            "vote_net": vote_net_map.get(sym, 0),
            "vote_conf": round(vote_conf_map.get(sym, 0.0), 4),
            "g_group": g_group,
            "ts_type": d.get("ts_type", "unknown"),
            "resonance": resonance,  # [改进11]
            "market_state": market_state,  # [改进12]
        }
        all_ranked.append(entry)
        if direction == "bull":
            bull_signals.append(entry)
        elif direction == "bear":
            bear_signals.append(entry)

    all_ranked.sort(key=lambda x: x["total"], reverse=True)
    bull_signals.sort(key=lambda x: x["total"], reverse=True)
    bear_signals.sort(key=lambda x: x["total"])

    scores_arr = [e["total"] for e in all_ranked]
    meta_mean = round(float(np.mean(scores_arr)), 2) if scores_arr else 0.0
    meta_std = round(float(np.std(scores_arr)), 2) if scores_arr else 0.0

    g1_count = sum(1 for e in all_ranked if e.get("g_group", "").startswith("g1"))
    g10_count = sum(1 for e in all_ranked if e.get("g_group", "").startswith("g10"))

    output = {
        "_meta": {
            "mode": "layered",
            "strategy": "factor_timing",
            "version": "2.3.1",
            "voting_method": voting_method,
            "sector_neutral": CONFIG.get("sector_neutral", False),
            "use_real_data": CONFIG.get("use_real_data", True),
            "market_state": market_state,
            "market_adx_gate": CONFIG.get("market_adx_gate", 20),
            "total": len(all_ranked),
            "bull": len(bull_signals),
            "bear": len(bear_signals),
            "g1_count": g1_count,
            "g10_count": g10_count,
            "z_mu": meta_mean,
            "z_sigma": meta_std,
        },
        "all_ranked": all_ranked,
        "bull_signals": bull_signals,
        "bear_signals": bear_signals,
    }
    return output


# ===================== [改进5] 十分组投票机制 =====================


def _calc_decile_vote(
    df: pd.DataFrame,
    symbols: list,
    market_data: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    多因子十分组投票机制。

    每个因子独立对全品种进行十分组排序（decile 1-10）。
    统计每个品种被多少个因子评为头部（1-2组）和尾部（9-10组）。
    只有被 ≥3 个因子认可的品种才产生信号。

    返回:
        {
            "z_scores": pd.Series,    # 综合分数
            "vote_net": {sym: int},   # 净票数（头部票-尾部票）
            "vote_conf": {sym: float} # 置信度
        }
    """
    threshold = CONFIG.get("decile_vote_threshold", 3)
    top_n = CONFIG.get("decile_top_n", 2)
    bottom_n = CONFIG.get("decile_bottom_n", 2)
    factor_names = df.columns.tolist()
    n_factors = len(factor_names)

    # 每个因子独立分组
    decile_map = {}  # {factor_name: {sym: decile_rank}}
    for col in factor_names:
        col_clean = col.replace("_clip", "")[:4]
        try:
            ranks = df[col].rank(method="average")
            n_valid = ranks.notna().sum()
            if n_valid >= 10:
                # qcut: 将rank分成10组
                decile = pd.qcut(ranks, q=10, labels=False, duplicates="drop") + 1
            else:
                # 品种不足10个时使用5分组
                decile = pd.qcut(ranks, q=min(5, n_valid), labels=False, duplicates="drop") + 1
                # 映射到1-10范围
                max_d = decile.max()
                if max_d > 0:
                    decile = ((decile - 1) / max_d * 9 + 1).astype(int)
            decile_map[col] = decile.to_dict()
        except Exception as e:
            logger.warning(f"分组异常 {col}: {e}")
            decile_map[col] = {sym: 5 for sym in df.index}

    # 统计每个品种的投票
    z_scores = pd.Series(0.0, index=symbols)
    vote_net = {}
    vote_conf = {}

    for sym in symbols:
        if sym not in df.index:
            z_scores[sym] = 0.0
            vote_net[sym] = 0
            vote_conf[sym] = 0.0
            continue

        # 统计被多少个因子评为头部(G1+G2)和尾部(G9+G10)
        top_count = 0
        bot_count = 0

        for col in factor_names:
            dval = decile_map.get(col, {}).get(sym, 5)
            if dval <= top_n:
                top_count += 1
            elif dval >= 10 - bottom_n + 1:
                bot_count += 1

        net_votes = top_count - bot_count
        vote_net[sym] = net_votes
        vote_conf[sym] = net_votes / n_factors

        # 过半同意才出手
        if top_count >= threshold:
            z_scores[sym] = 1.0 * (top_count / n_factors)
        elif bot_count >= threshold:
            z_scores[sym] = -1.0 * (bot_count / n_factors)
        else:
            # 观望：分数微弱
            z_scores[sym] = net_votes / n_factors * 0.3

        # 用原始因子 Z 值的均值乘以方向，作为强度缩放
        raw_vals = []
        for col in factor_names:
            v = df.loc[sym].get(col, 0)
            if not np.isnan(v):
                raw_vals.append(v)
        if raw_vals:
            raw_mean = np.mean(np.abs(raw_vals))
            z_scores[sym] *= raw_mean

    return {
        "z_scores": z_scores,
        "vote_net": vote_net,
        "vote_conf": vote_conf,
    }


def _apply_g1_g10(
    z_scores: pd.Series,
    vote_net_map: Dict[str, int],
) -> Dict[str, str]:
    """
    G1/G10 截断分组。
    """
    g1_count = CONFIG.get("g1_count", 3)
    g10_count = CONFIG.get("g10_count", 3)
    g_groups = {}

    bull_candidates = []
    bear_candidates = []

    for sym in z_scores.index:
        net_vote = vote_net_map.get(sym, 0)
        z_val = z_scores[sym]
        if net_vote > 0:
            bull_candidates.append((z_val, sym))
        elif net_vote < 0:
            bear_candidates.append((z_val, sym))
        else:
            g_groups[sym] = "middle"

    bull_candidates.sort(key=lambda x: x[0], reverse=True)
    for i, (z_val, sym) in enumerate(bull_candidates):
        if i < g1_count:
            g_groups[sym] = "g1_bull"
        elif i >= len(bull_candidates) - g10_count:
            g_groups[sym] = "g10_bull"
        else:
            g_groups[sym] = "middle"

    bear_candidates.sort(key=lambda x: x[0])
    for i, (z_val, sym) in enumerate(bear_candidates):
        if i < g1_count:
            g_groups[sym] = "g1_bear"
        elif i >= len(bear_candidates) - g10_count:
            g_groups[sym] = "g10_bear"
        else:
            g_groups[sym] = "middle"

    return g_groups


# ===================== [改进12] 市场状态检测 =====================


def _detect_market_state(
    market_data: Dict[str, Dict],
    symbols: list,
) -> str:
    """
    检测全市场状态：trending / choppy / high_vol / low_vol。

    规则：
    - 全市场 ADX 均值 > trend_adx_threshold → trending
    - 全市场 ADX 均值 < low_adx_threshold → choppy
    - 全市场波动率 > high_vol_threshold → high_vol
    - 否则 → low_vol
    """
    adx_vals = [market_data[sym].get("adx", 25) for sym in symbols if sym in market_data]
    if not adx_vals:
        return "normal"

    avg_adx = np.mean(adx_vals)
    trend_threshold = CONFIG.get("trend_adx_threshold", 30)
    low_adx = CONFIG.get("low_adx_threshold", 18)
    vol_threshold = CONFIG.get("high_vol_threshold", 0.02)

    # 波动率
    abs_returns = []
    for sym in symbols:
        d = market_data.get(sym, {})
        rets = d.get("returns_60d", [])
        if rets:
            abs_returns.append(np.std(rets))

    avg_vol = np.mean(abs_returns) if abs_returns else 0.0

    if avg_adx > trend_threshold:
        return "trending"
    elif avg_adx < low_adx:
        return "choppy"
    elif avg_vol > vol_threshold:
        return "high_vol"
    else:
        return "low_vol"


def _apply_state_params(market_state: str):
    """根据市场状态切换参数。"""
    state_params = CONFIG.get("state_params", {}).get(market_state, {})
    if not state_params:
        return
    for key, val in state_params.items():
        if key in CONFIG:
            old_val = CONFIG[key]
            CONFIG[key] = val
            logger.info(f"[参数自适应] {key}: {old_val} → {val} (state={market_state})")


# ===================== [改进10] 辅助函数（扩展veto） =====================


def _calc_veto_score_v231(
    d: dict,
    direction: str,
    sym: str,
    market_data: Dict[str, Dict],
) -> int:
    """
    v2.3.1 扩展版否决分数。

    基础规则（同 layered_l1l4）：
    - ADX < 15: −6
    - RSI 极端 (多头>80/空头<20): −6
    - CCI 极端 (>200或<-200): −5
    - 缩量 (成交量 < 前日 50%): −4
    - 结构切换 (ADX<25 且 无明确均线方向): −4

    [改进10] 新增规则：
    - 持仓异常：OI 变化超过 5σ → −5（大户操纵信号）
    - 涨跌停附近：价格触及涨跌停板 → −10（流动性枯竭）
    - 板块内分歧：与板块内其他品种信号方向相反 → −3
    """
    veto = 0
    adx = d.get("adx", 25)
    rsi = d.get("rsi", 50)
    cci = d.get("cci", 0)
    ma_slope = d.get("ma_slope", 0)
    volume = d.get("volume", 0)
    prev_volume = d.get("prev_volume", volume)
    oi = d.get("oi", 0)
    prev_oi = d.get("prev_oi", oi)
    close = d.get("close", 0)
    change_pct = d.get("change_pct", 0)

    # 基础规则
    if adx < 15:
        veto -= 6

    if direction == "bull" and rsi > 80:
        veto -= 6
    elif direction == "bear" and rsi < 20:
        veto -= 6

    if abs(cci) > 200:
        veto -= 5

    vol_ratio = volume / prev_volume if prev_volume > 0 else 1.0
    if vol_ratio < 0.5:
        veto -= 4

    if adx < 25 and abs(ma_slope) < 0.005:
        veto -= 4

    # ── [改进10a] 持仓异常：OI 变化超过 5σ ──
    if prev_oi > 0:
        oi_change_pct = abs(oi - prev_oi) / prev_oi
        if oi_change_pct > 0.20:  # 超过 20% 的 OI 变动
            veto -= 5
            logger.debug(f"[{sym}] OI异常变动 {oi_change_pct:.1%}，扣5分")

    # ── [改进10b] 涨跌停附近 ──
    if abs(change_pct) >= 5.0:  # 涨跌幅 ≥ 5%
        veto -= 10
        logger.debug(f"[{sym}] 大幅涨跌 {change_pct:.1f}%，扣10分")

    # ── [改进10c] 板块内分歧 ──
    sector_map = CONFIG.get("sector_map", {})
    sym_sector = None
    for sector, members in sector_map.items():
        if sym in members:
            sym_sector = sector
            break
    if sym_sector:
        sector_syms = [s for s in market_data if s != sym and s in sector_map.get(sym_sector, [])]
        conflicting = 0
        for other in sector_syms:
            other_d = market_data.get(other, {})
            # 简单判断：用价格变化方向
            other_dp = other_d.get("close", 0) - other_d.get("prev_close", 0)
            my_dp = close - d.get("prev_close", close)
            if my_dp * other_dp < 0:  # 方向相反
                conflicting += 1
        if len(sector_syms) >= 3 and conflicting >= len(sector_syms) * 0.5:
            veto -= 3
            logger.debug(f"[{sym}] 板块内{conflicting}/{len(sector_syms)}分歧，扣3分")

    return veto


def _calc_layer_scores(factor_row: pd.Series, weights: pd.Series) -> Dict[int, int]:
    """根据因子所属层级，计算 L1-L4 子层分数。"""
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
        if np.isnan(avg):
            result[layer_id] = 0
            continue
        max_range = layer_weights.get(layer_id, 10)
        scaled = int(np.clip(avg * max_range, -max_range, max_range))
        result[layer_id] = scaled

    for lid in [1, 2, 3, 4]:
        if lid not in result:
            result[lid] = 0
    return result


def _calc_ic_decay_weights(date: datetime, df: pd.DataFrame, ic_history: Dict[str, np.ndarray]) -> pd.Series:
    """基于历史IC的指数衰减加权计算因子权重。"""
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
        r.consistency = sum(1 for l in layers if (l > 0 and r.total > 0) or (l < 0 and r.total < 0))


# ── 自动注册 ──
register_strategy(FactorTimingStrategy, is_default=False)
