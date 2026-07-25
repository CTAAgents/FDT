"""期限结构因子 — 从 AKShare 实时行情获取多合约数据，计算基差/升贴水/曲线形态。

与 data_adapter/sources/akshare_source.py 中 get_term_structure 的
数据源一致（ak.futures_zh_realtime()），但输出为结构化的 TermStructureResult。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .types import TermStructureResult

logger = logging.getLogger(__name__)

# ── 品种 → 现货价格映射（用于基差计算，从生意社/akshare 源） ──
# 部分品种有生意社现货报价，可直接使用
# 其余品种基差暂不可计算


async def collect_term_structure(symbols: list[str]) -> dict[str, TermStructureResult]:
    """采集期限结构因子。

    通过 ak.futures_zh_realtime() 获取实时行情，
    提取同一品种所有合约月份的价格，计算曲线形态。

    Args:
        symbols: 品种列表

    Returns:
        {symbol: TermStructureResult}
    """
    results: dict[str, TermStructureResult] = {}
    for sym in symbols:
        results[sym] = TermStructureResult(symbol=sym.upper(), data_grade="UNAVAILABLE")

    try:
        import akshare as ak
        import pandas as pd

        df = ak.futures_zh_realtime()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            logger.warning("[TermStructure] 实时行情为空")
            return results

        sym_col = _find_column(df, ["symbol", "代码", "合约代码"])
        price_col = _find_column(df, ["current_price", "最新价", "现价", "price", "last_price"])
        if not sym_col or not price_col:
            logger.warning("[TermStructure] 无法识别行情列名")
            return results

        for sym in symbols:
            bare = sym.upper()
            try:
                result = _compute_single_term_structure(df, bare, sym_col, price_col)
                if result:
                    results[bare] = result
            except Exception as e:
                logger.warning("[TermStructure] %s 计算失败: %s", bare, e)

    except ImportError:
        logger.error("[TermStructure] akshare 未安装")
    except Exception as e:
        logger.error("[TermStructure] 采集失败: %s", e)

    return results


def _compute_single_term_structure(
    df: "pd.DataFrame",
    bare: str,
    sym_col: str,
    price_col: str,
) -> Optional[TermStructureResult]:
    """计算单个品种的期限结构。"""
    import pandas as pd
    import numpy as np

    pattern = re.compile(rf"^{bare}(\d+)", re.IGNORECASE)
    matched_rows = []
    for _, row in df.iterrows():
        code = str(row.get(sym_col, "")).strip().upper()
        m = pattern.match(code)
        if m:
            price = _safe_float(row, [price_col])
            if price and price > 0:
                matched_rows.append((code, int(m.group(1)), price))

    if len(matched_rows) < 2:
        return None

    matched_rows.sort(key=lambda x: x[1])
    contracts = [{"contract": c, "month": m, "price": p} for c, m, p in matched_rows]

    # 近月 / 远月
    near = contracts[0]
    far = contracts[-1]
    spread = round(far["price"] - near["price"], 2)
    spread_ratio = round(spread / near["price"] * 100, 2) if near["price"] > 0 else 0.0

    # 曲线类型
    if len(contracts) >= 3:
        mid_idx = len(contracts) // 2
        if contracts[mid_idx]["price"] > near["price"] and contracts[mid_idx]["price"] > far["price"]:
            curve_type = "backwardation"
        elif contracts[mid_idx]["price"] < near["price"] and contracts[mid_idx]["price"] < far["price"]:
            curve_type = "contango"
        else:
            curve_type = "flat"
        # 用斜率辅助判断
        slope = (contracts[-1]["price"] - contracts[0]["price"]) / len(contracts)
        if abs(slope) < 0.5:
            curve_type = "flat"
        elif slope > 0:
            curve_type = "contango"
        else:
            curve_type = "backwardation"
    else:
        curve_type = "backwardation" if spread < 0 else "contango" if spread > 0 else "flat"

    # 主力-次主力价差（作为曲线斜率）
    curve_slope = round(contracts[1]["price"] - contracts[0]["price"], 2) if len(contracts) >= 2 else None

    return TermStructureResult(
        symbol=bare,
        basis=None,  # 基差暂不计算（依赖现货数据）
        basis_ratio=None,
        near_contract=near["contract"],
        far_contract=far["contract"],
        spread=spread,
        spread_ratio=spread_ratio,
        curve_type=curve_type,
        curve_slope=curve_slope,
        delivery_month=str(contracts[-1]["month"]),
        data_grade="PRIMARY",
    )


def _find_column(df: "pd.DataFrame", candidates: list[str]) -> Optional[str]:
    """在 DataFrame 中找到第一个匹配的列名。"""
    for col in candidates:
        if col in df.columns:
            return col
    # 模糊匹配
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None


def _safe_float(row: "pd.Series", candidates: list[str]) -> Optional[float]:
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
