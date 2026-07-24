"""OHLC 一致性校验清洗模块。

纯函数，无外部依赖。接收 ``list[dict]`` 格式的 K 线数据，
执行零成交量/持仓剔除、OHLC 一致性修复、负值归零等清洗操作。
"""

from __future__ import annotations

from data_adapter.types import CleaningAction, CleaningReport


def _make_cleaning_id(removed: int, fixed: int) -> str:
    return f"ohlc-{removed}r-{fixed}f"


def clean_ohlc(bars: list[dict]) -> tuple[list[dict], CleaningReport]:
    """对 K 线执行 OHLC 一致性校验清洗。

    Args:
        bars: 原始 K 线列表，每项含 date/open/high/low/close/volume/open_interest。

    Returns:
        (cleaned_bars, report) — 清洗后的 K 线列表 + 清洗报告。
    """
    actions: list[CleaningAction] = []
    result: list[dict] = []

    for idx, bar in enumerate(bars):
        volume = bar.get("volume", 0)
        open_interest = bar.get("open_interest", 0)

        # 1. 零成交量/零持仓剔除（同时为零）
        if volume == 0 and open_interest == 0:
            actions.append(
                CleaningAction(
                    action="removed",
                    field="volume",
                    index=idx,
                    reason="zero volume and open interest",
                    original=f"volume={volume},oi={open_interest}",
                    new="",
                )
            )
            continue  # 被移除的 bar 不进入结果

        # 复制一份，不修改原始 dict
        row = dict(bar)

        o = float(row.get("open", 0.0))
        h = float(row.get("high", 0.0))
        l = float(row.get("low", 0.0))
        c = float(row.get("close", 0.0))
        v = float(row.get("volume", 0.0))
        oi = float(row.get("open_interest", 0.0))

        # 2. OHLC 一致性修复
        # 2a. high < low → 交换两者
        if h < l:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="high",
                    index=idx,
                    reason="high<low swapped",
                    original=f"high={h},low={l}",
                    new=f"high={l},low={h}",
                )
            )
            h, l = l, h

        # 2b. close > high → 截断
        if c > h:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="close",
                    index=idx,
                    reason="close>high capped",
                    original=str(c),
                    new=str(h),
                )
            )
            c = h

        # 2c. close < low → 抬升
        if c < l:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="close",
                    index=idx,
                    reason="close<low raised",
                    original=str(c),
                    new=str(l),
                )
            )
            c = l

        # 2d. open > high → 截断
        if o > h:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="open",
                    index=idx,
                    reason="open>high capped",
                    original=str(o),
                    new=str(h),
                )
            )
            o = h

        # 2e. open < low → 抬升
        if o < l:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="open",
                    index=idx,
                    reason="open<low raised",
                    original=str(o),
                    new=str(l),
                )
            )
            o = l

        # 3. 成交量为负 → 归零
        if v < 0:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="volume",
                    index=idx,
                    reason="negative volume zeroed",
                    original=str(v),
                    new="0",
                )
            )
            v = 0.0

        # 4. 持仓量为负 → 归零
        if oi < 0:
            actions.append(
                CleaningAction(
                    action="fixed",
                    field="open_interest",
                    index=idx,
                    reason="negative oi zeroed",
                    original=str(oi),
                    new="0",
                )
            )
            oi = 0.0

        row["open"] = o
        row["high"] = h
        row["low"] = l
        row["close"] = c
        row["volume"] = v
        row["open_interest"] = oi
        result.append(row)

    removed = sum(1 for a in actions if a.action == "removed")
    fixed = sum(1 for a in actions if a.action == "fixed")
    report = CleaningReport(
        cleaning_id=_make_cleaning_id(removed, fixed),
        actions=actions,
    )
    return result, report


# 兼容性别名
OHLCCleaner = clean_ohlc
