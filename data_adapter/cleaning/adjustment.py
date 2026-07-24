"""复权处理模块。

纯函数，无外部依赖。接收 ``list[dict]`` 格式的 K 线数据，
执行跳空检测和前复权调整，使主力连续合约价格连续。

用法：:

    from data_adapter.cleaning.adjustment import clean_adjustment

    cleaned, report = clean_adjustment(bars, method="forward")
"""

from __future__ import annotations

from data_adapter.types import CleaningAction, CleaningReport


def _detect_roll_gaps(
    bars: list[dict],
    gap_threshold: float,
) -> list[int]:
    """检测疑似换月跳空位置。

    遍历 K 线序列，找到收盘价跳空 > gap_threshold
    且成交量未异常放大（vol_t < 3 * vol_{t-1}）的位置。

    Returns:
        跳空 bar 的索引列表（标记 bar 为跳空后的那根）。
    """
    gaps: list[int] = []
    for t in range(1, len(bars)):
        prev_close = float(bars[t - 1].get("close", 0.0))
        cur_close = float(bars[t].get("close", 0.0))

        if prev_close == 0.0:
            continue

        gap_ratio = abs(cur_close - prev_close) / prev_close

        vol_prev = float(bars[t - 1].get("volume", 0.0))
        vol_cur = float(bars[t].get("volume", 0.0))

        if gap_ratio > gap_threshold and vol_cur < 3 * vol_prev:
            gaps.append(t)

    return gaps


def _forward_adjust(
    bars: list[dict],
    gaps: list[int],
    actions: list[CleaningAction],
) -> list[dict]:
    """对跳空位置执行前复权。

    对每个跳空，计算复权因子 = close_{t-1} / close_t，
    将跳空之后（含跳空 bar）的 open/high/low/close 乘以该因子。

    Returns:
        调整后的 bars（新 list，不修改传入的 bars）。
    """
    result = [dict(b) for b in bars]  # 深拷贝，不修改传入数据

    for t in gaps:
        prev_close = float(result[t - 1].get("close", 0.0))
        cur_close = float(result[t].get("close", 0.0))

        if cur_close == 0.0:
            continue

        factor = prev_close / cur_close

        for i in range(t, len(result)):
            bar = result[i]
            bar["open"] = float(bar.get("open", 0.0)) * factor
            bar["high"] = float(bar.get("high", 0.0)) * factor
            bar["low"] = float(bar.get("low", 0.0)) * factor
            bar["close"] = float(bar.get("close", 0.0)) * factor

        actions.append(
            CleaningAction(
                action="adjusted",
                field="close",
                index=t,
                reason=f"forward adj factor={factor:.6f}",
            )
        )

    return result


def clean_adjustment(
    bars: list[dict],
    method: str = "forward",
    gap_threshold: float = 0.03,
) -> tuple[list[dict], CleaningReport]:
    """对 K 线序列执行复权处理。

    检测主力连续合约的换月跳空缺口，提供前复权调整能力。
    至少需要 5 根 bar 才能做有意义的检测。

    Args:
        bars: K 线列表，每项含 date/open/high/low/close/volume/open_interest。
        method: 复权方法，当前仅支持 ``"forward"``（前复权）。
        gap_threshold: 跳空比例阈值，默认 0.03（3%）。

    Returns:
        (cleaned_bars, report) — 复权后的 K 线 + 清洗报告。
    """
    actions: list[CleaningAction] = []

    if len(bars) < 5:
        report = CleaningReport(cleaning_id="adj-0g-0a", actions=[])
        return list(bars), report

    # 1. 检测所有疑似换月跳空
    gaps = _detect_roll_gaps(bars, gap_threshold)

    # 2. 标记 _roll_gap（无论是否调整）
    result = [dict(b) for b in bars]
    for t in gaps:
        result[t].update({"_roll_gap": True})

    # 3. 前复权调整
    if method == "forward" and gaps:
        result = _forward_adjust(result, gaps, actions)

    cleaning_id = f"adj-{len(gaps)}g-{len(actions)}a"
    report = CleaningReport(cleaning_id=cleaning_id, actions=actions)
    return result, report


# ── 兼容性别名 ──
AdjustmentEngine = clean_adjustment
