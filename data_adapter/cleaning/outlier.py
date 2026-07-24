"""离群值（毛刺）检测清洗模块。

提供 ``clean_outliers()`` 函数，对 K 线序列执行：
1. 3σ 毛刺检测：对数收益率超过 z_threshold × 标准差时修复 close/high/low
2. 邻域滑动窗口成交量校验：单日暴增超过窗口均值 10 倍且前后未共振时平滑

所有修复记录为 CleaningAction，汇总到 CleaningReport。
"""

from __future__ import annotations

import math

from data_adapter.types import CleaningAction, CleaningReport


def clean_outliers(
    bars: list[dict],
    z_threshold: float = 3.0,
) -> tuple[list[dict], CleaningReport]:
    """离群值（毛刺）检测与修复。

    Args:
        bars: 原始 K 线列表，每项含 date/open/high/low/close/volume/open_interest。
        z_threshold: 3σ 阈值，默认 3.0。

    Returns:
        (cleaned_bars, report) — 修复后的 K 线 + 清洗报告。
    """
    actions: list[CleaningAction] = []
    result = [dict(b) for b in bars]  # 浅拷贝，不污染入参
    n = len(result)

    # ── 1. 3σ 毛刺检测 ──────────────────────────────────────────
    if n >= 3:
        log_returns: list[float] = []
        for i in range(1, n):
            prev_close = result[i - 1]["close"]
            curr_close = result[i]["close"]
            if prev_close > 0 and curr_close > 0:
                log_returns.append(math.log(curr_close / prev_close))
            else:
                log_returns.append(0.0)

        lr_mean = sum(log_returns) / len(log_returns)
        variance = sum((lr - lr_mean) ** 2 for lr in log_returns) / len(log_returns)
        lr_std = math.sqrt(variance) if variance > 0 else 0.0

        if lr_std > 0:
            # 从第 2 根 bar 开始检查，最后 1 根无下一 bar 作为邻居时跳过
            for i in range(1, n - 1):
                lr = log_returns[i - 1]
                z_score = abs(lr - lr_mean) / lr_std

                if z_score > z_threshold:
                    # ── 修复 close ──
                    median_close = (result[i - 1]["close"] + result[i + 1]["close"]) / 2.0
                    orig_close = result[i]["close"]
                    result[i]["close"] = median_close

                    actions.append(CleaningAction(
                        action="fixed",
                        field="close",
                        index=i,
                        reason=f"spike fixed z={z_score:.2f}",
                        original=str(orig_close),
                        new=str(median_close),
                    ))

                    # ── 修复 high/low（与 close 同向偏离时）──
                    spike_direction = 1 if lr > 0 else -1

                    # high：向上偏离时修复
                    median_high = (result[i - 1]["high"] + result[i + 1]["high"]) / 2.0
                    if spike_direction > 0 and result[i]["high"] > median_high:
                        orig_high = result[i]["high"]
                        result[i]["high"] = median_high
                        actions.append(CleaningAction(
                            action="fixed",
                            field="high",
                            index=i,
                            reason=f"spike fixed z={z_score:.2f}",
                            original=str(orig_high),
                            new=str(median_high),
                        ))

                    # low：向下偏离时修复
                    median_low = (result[i - 1]["low"] + result[i + 1]["low"]) / 2.0
                    if spike_direction < 0 and result[i]["low"] < median_low:
                        orig_low = result[i]["low"]
                        result[i]["low"] = median_low
                        actions.append(CleaningAction(
                            action="fixed",
                            field="low",
                            index=i,
                            reason=f"spike fixed z={z_score:.2f}",
                            original=str(orig_low),
                            new=str(median_low),
                        ))

    # ── 2. 邻域滑动窗口成交量校验 ────────────────────────────────
    if n >= 6:
        for i in range(n):
            if i < 5:
                continue  # 至少需要前 5 根 bar

            window_volumes = [result[j]["volume"] for j in range(i - 5, i)]
            window_mean = sum(window_volumes) / 5.0

            curr_volume = result[i]["volume"]
            if window_mean <= 0 or curr_volume <= 10 * window_mean:
                continue

            # 检查前一根是否有同向暴增（仅当有足够数据时）
            prev_clean = True
            if i - 1 >= 5:
                prev_window = [result[j]["volume"] for j in range(i - 6, i - 1)]
                prev_mean = sum(prev_window) / 5.0
                if prev_mean > 0 and result[i - 1]["volume"] > 10 * prev_mean:
                    prev_clean = False

            # 检查后一根是否有同向暴增（仅当有足够数据时）
            next_clean = True
            if i + 1 < n and i + 1 >= 5:
                next_window = [result[j]["volume"] for j in range(i - 4, i + 1)]
                next_mean = sum(next_window) / 5.0
                if next_mean > 0 and result[i + 1]["volume"] > 10 * next_mean:
                    next_clean = False

            if prev_clean and next_clean:
                orig_vol = result[i]["volume"]
                result[i]["volume"] = window_mean
                actions.append(CleaningAction(
                    action="fixed",
                    field="volume",
                    index=i,
                    reason="volume spike smoothed",
                    original=str(orig_vol),
                    new=str(window_mean),
                ))

    report = CleaningReport(cleaning_id="", actions=actions)
    return result, report


# 兼容性别名
OutlierDetector = clean_outliers
