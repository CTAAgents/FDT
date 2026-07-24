"""期货专项清洗 — 交割月过滤 + 涨跌停封板标记。

Phase 2 of the cleaning pipeline.

功能：
1. 交割月过滤：对具体合约（非主力连续），剔除交割月前 N 天的低流动性 K 线
2. 涨跌停封板标记：检测价格涨跌幅接近交易所涨跌停板且成交量骤降的 bar
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from data_adapter.types import CleaningAction, CleaningReport

# ── 品种涨跌停板阈值（按产品类别） ──
# 来源：各交易所涨跌停板制度，取基准值
_LIMIT_THRESHOLD: dict[str, float] = {
    # 上海期货交易所（±5-8%）
    "CU": 0.05, "AL": 0.05, "ZN": 0.06, "PB": 0.05, "NI": 0.08, "SN": 0.08,
    "AU": 0.04, "AG": 0.06, "RB": 0.05, "HC": 0.05, "SS": 0.08, "RU": 0.06,
    "BU": 0.06, "FU": 0.08, "SP": 0.05,
    # 大连商品交易所（±4-8%）
    "M": 0.04, "Y": 0.04, "P": 0.04, "B": 0.04, "C": 0.04, "CS": 0.04,
    "A": 0.04, "JM": 0.08, "J": 0.08, "I": 0.08, "FB": 0.05, "BB": 0.05,
    "PP": 0.04, "L": 0.04, "V": 0.04, "EG": 0.05, "EB": 0.05, "PG": 0.05,
    "LH": 0.08, "JD": 0.05,
    # 郑州商品交易所（±4-7%）
    "CF": 0.04, "SR": 0.04, "TA": 0.04, "MA": 0.05, "RM": 0.04, "OI": 0.04,
    "FG": 0.05, "SA": 0.05, "ZC": 0.06, "SM": 0.05, "SF": 0.05, "UR": 0.04,
    "PF": 0.04, "PK": 0.04, "AP": 0.05, "CJ": 0.07, "CY": 0.04,
    # 广期所
    "SI": 0.08, "LC": 0.08,
    # 中金所（股指 ±10%）
    "IF": 0.10, "IH": 0.10, "IC": 0.10, "IM": 0.10,
}


def _get_limit_threshold(symbol: str) -> float:
    """获取品种的涨跌停板阈值（默认 5%）。"""
    bare = symbol.upper().rstrip("0123456789")
    return _LIMIT_THRESHOLD.get(bare, 0.05)


def _parse_contract_month(symbol: str) -> Optional[str]:
    """从合约代码提取交割月份 YYYYMM。

    ``"RB2610"`` → ``"202610"``
    ``"RB"`` / ``"RB0"`` → ``None``（主力连续/品种代码）
    """
    bare = symbol.upper().strip()
    if not bare:
        return None
    # 主力连续：字母+888/999，或字母+"0"（数字部分只有一个0）
    letters = bare.rstrip("0123456789")
    number_part = bare[len(letters):]
    if number_part in ("888", "999", "0"):
        return None
    # 提取末尾 4 位年月数字 → YYYYMM
    m = re.search(r'(\d{2})(\d{2})$', bare)
    if m:
        yy, mm = m.group(1), m.group(2)
        return f"20{yy}{mm}"
    return None


def clean_futures(
    bars: list[dict],
    symbol: str = "",
    delivery_exclude_days: int = 15,
) -> tuple[list[dict], CleaningReport]:
    """期货专项清洗。

    Args:
        bars: K 线列表。
        symbol: 品种/合约代码（如 ``"RB"``, ``"RB2610"``）。
        delivery_exclude_days: 交割月前 N 天开始过滤，默认 15 天。

    Returns:
        (cleaned_bars, report)。
    """
    actions: list[CleaningAction] = []
    result = [dict(b) for b in bars]
    n = len(result)

    if n < 2:
        return result, CleaningReport(cleaning_id="", actions=[])

    # ── 1. 交割月过滤 ──
    contract_month = _parse_contract_month(symbol)
    removed_indices = []
    if contract_month:
        try:
            delivery_date = datetime.strptime(contract_month, "%Y%m")
            for i, bar in enumerate(result):
                date_str = str(bar.get("date", ""))
                if len(date_str) < 8 or not date_str[:8].isdigit():
                    continue
                bar_date = datetime.strptime(date_str[:8], "%Y%m%d")
                if bar_date >= delivery_date - timedelta(days=delivery_exclude_days):
                    actions.append(CleaningAction(
                        action="removed",
                        field="date",
                        index=i,
                        reason=f"near delivery month {contract_month}, excluded",
                        original=date_str,
                    ))
                    removed_indices.append(i)
        except (ValueError, OverflowError):
            pass
        # 逆序移除
        for idx in sorted(removed_indices, reverse=True):
            result.pop(idx)

    # ── 2. 涨跌停封板标记 ──
    threshold = _get_limit_threshold(symbol)
    for i in range(1, n):
        if i >= len(result):
            break  # 可能有 bar 被移除了
        bar = result[i]
        prev = result[i - 1]
        prev_close = prev.get("close", 0)
        if prev_close <= 0:
            continue
        change_pct = abs(bar.get("close", 0) - prev_close) / prev_close

        # 判断条件：涨跌幅接近阈值（>=90% 阈值）且成交量骤降（<= 前一根 30%）
        if change_pct >= threshold * 0.9:
            vol = bar.get("volume", 0)
            prev_vol = prev.get("volume", 0)
            vol_collapsed = (prev_vol > 0 and vol / prev_vol <= 0.3) or (vol == 0 and prev_vol > 0)

            if vol_collapsed:
                is_up = bar.get("close", 0) > prev_close
                flag = "_limit_up" if is_up else "_limit_down"
                bar[flag] = True
                actions.append(CleaningAction(
                    action="marked",
                    field="volume",
                    index=i,
                    reason=f"limit {'up' if is_up else 'down'} day detected (chg={change_pct*100:.1f}%, vol_drop={vol/prev_vol:.1%})" if prev_vol > 0 else f"limit {'up' if is_up else 'down'} day detected (chg={change_pct*100:.1f}%, vol=0)",
                    original=str(bar.get("close", "")),
                ))

    report = CleaningReport(cleaning_id="", actions=actions)
    return result, report


# 兼容性别名
FuturesCleaner = clean_futures
