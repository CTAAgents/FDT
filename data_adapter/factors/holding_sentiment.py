"""多空持仓因子 — 从 AKShare 获取全市场多空比 + 前20会员持仓。

数据源：
  - ak.futures_hold_pos_sina() — 总持仓量、多空持仓、多空比
  - ak.futures_stock_shfe_js() — 上期所前20会员持仓
  - ak.futures_dce_position_rank() — 大商所前20会员持仓
  - ak.futures_gfex_position_rank() — 广期所前20会员持仓

**注意**：此为持仓存量指标（多空比），而非日内资金净流入流量。
期货市场无类似股票北向资金的实时资金流 API。
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import HoldingSentimentResult

logger = logging.getLogger(__name__)


async def collect_holding_sentiment(symbols: list[str]) -> dict[str, HoldingSentimentResult]:
    """采集多空持仓因子。

    并行采集全市场多空比 + 各交易所前20排名。

    Args:
        symbols: 品种列表

    Returns:
        {symbol: HoldingSentimentResult}
    """
    results: dict[str, HoldingSentimentResult] = {}
    for sym in symbols:
        results[sym.upper()] = HoldingSentimentResult(symbol=sym.upper(), data_grade="UNAVAILABLE")

    # ── 全市场多空比 ──
    await _collect_market_ls_ratio(symbols, results)

    # ── 前20排名（交易所级别） ──
    await _collect_top20_rankings(symbols, results)

    return results


async def _collect_market_ls_ratio(
    symbols: list[str],
    results: dict[str, HoldingSentimentResult],
) -> None:
    """采集全市场多空持仓比（ak.futures_hold_pos_sina）。"""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.futures_hold_pos_sina()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            logger.warning("[HoldingSentiment] 全市场持仓数据为空")
            return

        sym_col = _find_column(df, ["品种", "品种代码", "symbol", "variety", "商品名称"])
        if not sym_col:
            logger.warning("[HoldingSentiment] 无法识别品种列")
            return

        for sym in symbols:
            bare = sym.upper()
            try:
                matched = df[df[sym_col].astype(str).str.upper().str.contains(bare, na=False)]
                if matched.empty:
                    continue

                latest = matched.iloc[-1]
                oi = _safe_float_df(latest, ["持仓量", "open_interest", "total_oi", "oi"])
                long_v = _safe_float_df(latest, ["多头持仓", "long", "long_pos", "buy"])
                short_v = _safe_float_df(latest, ["空头持仓", "short", "short_pos", "sell"])

                long_int = int(long_v) if long_v else None
                short_int = int(short_v) if short_v else None
                ratio = round(long_v / short_v, 4) if (long_v and short_v and short_v > 0) else None

                # 如果已有结果，更新它
                existing = results.get(bare)
                if existing and existing.data_grade == "UNAVAILABLE":
                    existing.total_long = long_int
                    existing.total_short = short_int
                    existing.long_short_ratio = ratio
                    existing.data_grade = "PRIMARY"
                elif existing:
                    existing.total_long = long_int
                    existing.total_short = short_int
                    existing.long_short_ratio = ratio

                results[bare] = HoldingSentimentResult(
                    symbol=bare,
                    total_long=long_int,
                    total_short=short_int,
                    long_short_ratio=ratio,
                    data_grade="PRIMARY",
                )

            except Exception as e:
                logger.warning("[HoldingSentiment] %s 多空比采集失败: %s", sym, e)

    except ImportError:
        logger.error("[HoldingSentiment] akshare 未安装")
    except Exception as e:
        logger.error("[HoldingSentiment] 全市场多空比采集失败: %s", e)


async def _collect_top20_rankings(
    symbols: list[str],
    results: dict[str, HoldingSentimentResult],
) -> None:
    """采集交易所前20会员持仓排名。

    按交易所分组：SHFE / DCE / GFEX。CZCE 郑商所无持仓排名 API。
    """
    # ── SHFE 上期所 ──
    await _collect_shfe_rankings(symbols, results)

    # ── DCE 大商所 ──
    await _collect_dce_rankings(symbols, results)

    # ── GFEX 广期所 ──
    await _collect_gfex_rankings(symbols, results)


async def _collect_shfe_rankings(
    symbols: list[str],
    results: dict[str, HoldingSentimentResult],
) -> None:
    """上期所前20排名。"""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.futures_stock_shfe_js()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return

        # SHFE 数据结构：instrument / rank / vol_b / vol_s
        inst_col = _find_column(df, ["instrument", "合约", "品种", "code"])
        vol_b_col = _find_column(df, ["vol_b", "volume_b", "买持仓", "多单"])
        vol_s_col = _find_column(df, ["vol_s", "volume_s", "卖持仓", "空单"])

        if not all([inst_col, vol_b_col, vol_s_col]):
            return

        for sym in symbols:
            bare = sym.upper()
            sym_df = df[df[inst_col].astype(str).str.contains(bare, na=False)]
            if sym_df.empty:
                continue

            top_long = int(sym_df[vol_b_col].sum()) if vol_b_col else None
            top_short = int(sym_df[vol_s_col].sum()) if vol_s_col else None
            _update_top20(results, bare, top_long, top_short)

    except Exception as e:
        logger.warning("[HoldingSentiment] SHFE 排名采集失败: %s", e)


async def _collect_dce_rankings(
    symbols: list[str],
    results: dict[str, HoldingSentimentResult],
) -> None:
    """大商所前20排名。"""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.futures_dce_position_rank()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return

        inst_col = _find_column(df, ["instrument", "合约", "品种", "code"])
        vol_b_col = _find_column(df, ["vol_b", "volume_b", "买持仓", "多单"])
        vol_s_col = _find_column(df, ["vol_s", "volume_s", "卖持仓", "空单"])

        if not all([inst_col, vol_b_col, vol_s_col]):
            return

        for sym in symbols:
            bare = sym.upper()
            sym_df = df[df[inst_col].astype(str).str.contains(bare, na=False)]
            if sym_df.empty:
                continue

            top_long = int(sym_df[vol_b_col].sum()) if vol_b_col else None
            top_short = int(sym_df[vol_s_col].sum()) if vol_s_col else None
            _update_top20(results, bare, top_long, top_short)

    except Exception as e:
        logger.warning("[HoldingSentiment] DCE 排名采集失败: %s", e)


async def _collect_gfex_rankings(
    symbols: list[str],
    results: dict[str, HoldingSentimentResult],
) -> None:
    """广期所前20排名。"""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.futures_gfex_position_rank()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return

        inst_col = _find_column(df, ["instrument", "合约", "品种", "code"])
        vol_b_col = _find_column(df, ["vol_b", "volume_b", "买持仓", "多单"])
        vol_s_col = _find_column(df, ["vol_s", "volume_s", "卖持仓", "空单"])

        if not all([inst_col, vol_b_col, vol_s_col]):
            return

        for sym in symbols:
            bare = sym.upper()
            sym_df = df[df[inst_col].astype(str).str.contains(bare, na=False)]
            if sym_df.empty:
                continue

            top_long = int(sym_df[vol_b_col].sum()) if vol_b_col else None
            top_short = int(sym_df[vol_s_col].sum()) if vol_s_col else None
            _update_top20(results, bare, top_long, top_short)

    except Exception as e:
        logger.warning("[HoldingSentiment] GFEX 排名采集失败: %s", e)


def _update_top20(
    results: dict[str, HoldingSentimentResult],
    bare: str,
    top_long: Optional[int],
    top_short: Optional[int],
) -> None:
    """更新品种的前20排名数据。"""
    existing = results.get(bare)
    if existing:
        existing.top20_long = top_long
        existing.top20_short = top_short
        if top_long and top_short and top_short > 0:
            existing.top20_ratio = round(top_long / top_short, 4)
        if existing.data_grade == "UNAVAILABLE":
            existing.data_grade = "PRIMARY"


def _find_column(df: "pd.DataFrame", candidates: list[str]) -> Optional[str]:
    """在 DataFrame 中找到第一个匹配的列名。"""
    for col in candidates:
        if col in df.columns:
            return col
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None


def _safe_float_df(row: "pd.Series", candidates: list[str]) -> Optional[float]:
    """从行中安全提取 float 值。"""
    import pandas as pd

    for col in candidates:
        val = row.get(col)
        if val is not None:
            try:
                if pd.isna(val):
                    return None
                return float(val)
            except (ValueError, TypeError):
                continue
    return None
