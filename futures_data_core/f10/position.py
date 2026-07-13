"""持仓排名数据 [INDEPENDENT]。

数据来源：AKShare（get_rank_sum_daily → get_shfe_rank_table 降级）。
封装在 FDC 内部，系统其余模块不直接调用 AKShare。

A2A 输出：``type=fdc.position_ranking``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES, _default_meta


async def get_position_ranking(
    symbol: str,
    days: int = 30,
) -> A2APayload:
    """获取单个品种的期货持仓排名数据。

    通过 AKShare 获取会员持仓排名，分析主力资金方向。
    降级链：get_rank_sum_daily → get_shfe_rank_table → 空。

    Args:
        symbol: 品种代码（如 'rb', 'CU', 'M'）
        days: 回溯天数，默认 30

    Returns:
        A2APayload，data 结构：
        {
            "symbol": "rb",
            "total_oi": 1234567,
            "long_volume": 123456,
            "short_volume": 123456,
            "net_long": 0,
            "top5_long": 123456,
            "top5_short": 123456,
            "data_source": "AKShare(会员持仓排名)",
            "trade_date": "20260713",
        }
    """
    meta = _default_meta()
    meta["sources"] = ["akshare_position_ranking"]

    try:
        import akshare as ak

        result = _fetch_akshare_rank(ak, symbol, days)
        if result:
            meta["data_grade"] = "DAILY"
            meta["data_grade_label"] = 2
            return A2APayload(
                type=DATA_TYPES.get("POSITION_RANKING", "fdc.position_ranking"),
                data=result,
                meta=meta,
                summary=f"{symbol} 持仓排名（AKShare）",
            )

        # 降级：逐品种 SHFE 排名表
        result = _fetch_shfe_rank(ak, symbol)
        if result:
            meta["data_grade"] = "DAILY"
            meta["data_grade_label"] = 2
            meta["sources"].append("shfe_rank_table")
            return A2APayload(
                type=DATA_TYPES.get("POSITION_RANKING", "fdc.position_ranking"),
                data=result,
                meta=meta,
                summary=f"{symbol} 持仓排名（SHFE降级）",
            )

    except ImportError:
        meta["warnings"].append("akshare not installed")
    except Exception as e:
        meta["warnings"].append(f"AKShare error: {str(e)[:80]}")

    meta["data_grade"] = "UNAVAILABLE"
    meta["data_grade_label"] = 5
    return A2APayload(
        type=DATA_TYPES.get("POSITION_RANKING", "fdc.position_ranking"),
        data={"symbol": symbol.lower()},
        meta=meta,
        summary=f"{symbol} 持仓排名不可用",
    )


def _fetch_akshare_rank(ak, symbol: str, days: int) -> Optional[dict]:
    """通过 AKShare get_rank_sum_daily 获取全品种汇总持仓排名。"""
    try:
        import pandas as pd

        end_day = datetime.now().strftime("%Y%m%d")
        start_day = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        rank_df = ak.get_rank_sum_daily(
            start_day=start_day,
            end_day=end_day,
            vars_list=[symbol.upper()],
        )
        if rank_df is None or rank_df.empty:
            return None

        latest = rank_df.iloc[-1]
        long_vol = float(latest.get("long_position", latest.get("vol", 0)))
        short_vol = float(latest.get("short_position", 0))
        oi = float(latest.get("open_interest", 0))

        return {
            "symbol": symbol.lower(),
            "total_oi": oi,
            "long_volume": long_vol,
            "short_volume": short_vol,
            "net_long": long_vol - short_vol if long_vol and short_vol else None,
            "trade_date": str(latest.get("date", end_day)),
            "data_source": "AKShare(会员持仓排名)",
        }
    except Exception:
        return None


def _fetch_shfe_rank(ak, symbol: str) -> Optional[dict]:
    """降级：从 get_shfe_rank_table 逐品种获取。"""
    try:
        import pandas as pd

        trade_date = datetime.now().strftime("%Y%m%d")
        shfe_rank = ak.get_shfe_rank_table(date=trade_date)
        if shfe_rank is None:
            return None

        sym_upper = symbol.upper()
        for key in shfe_rank:
            if sym_upper in str(key).upper():
                df = shfe_rank[key]
                if isinstance(df, pd.DataFrame) and not df.empty:
                    long_vol = float(df.iloc[:, 1].sum()) if df.shape[1] > 1 else 0
                    short_vol = float(df.iloc[:, 2].sum()) if df.shape[1] > 2 else 0
                    return {
                        "symbol": symbol.lower(),
                        "total_oi": len(df),
                        "long_volume": long_vol,
                        "short_volume": short_vol,
                        "net_long": long_vol - short_vol if long_vol and short_vol else None,
                        "trade_date": trade_date,
                        "data_source": "SHFE(持仓排名降级)",
                    }
        return None
    except Exception:
        return None
