"""时间轴标准化模块。

清洗逻辑：
1. 极端日期过滤（非 8 位数字 date 删除）
2. 按 date 去重（保留最后出现的那条）
3. 升序排序
4. 缺失日K标记（最多 5 个）
"""

from __future__ import annotations

from datetime import datetime, timedelta

from data_adapter.types import CleaningAction, CleaningReport


def _parse_yyyymmdd(s: str) -> datetime | None:
    """将 YYYYMMDD 字符串转为 datetime，失败返回 None。"""
    try:
        return datetime.strptime(s, "%Y%m%d")
    except (ValueError, TypeError):
        return None


def _is_valid_date(date_val) -> bool:
    """判断 date 是否为 8 位数字字符串。"""
    s = str(date_val).strip()
    return len(s) == 8 and s.isdigit()


def clean_timeline(bars: list[dict]) -> tuple[list[dict], CleaningReport]:
    """时间轴标准化。

    Args:
        bars: 原始 K 线列表（每项含 date/open/high/low/close/volume/open_interest）。

    Returns:
        (cleaned_bars, report) — 清洗后的 K 线 + 清洗报告。
    """
    actions: list[CleaningAction] = []

    # ── 1. 极端日期过滤 ──
    # valid 结构为 list[(original_index, bar)]
    valid: list[tuple[int, dict]] = []
    for i, bar in enumerate(bars):
        date_val = bar.get("date", "")
        if not _is_valid_date(date_val):
            actions.append(CleaningAction(
                action="removed",
                field="date",
                index=i,
                reason=f"invalid date format {date_val}",
            ))
        else:
            valid.append((i, bar))

    # ── 2. 去重（按 date，保留最后出现的那条）──
    seen: dict[str, tuple[int, dict]] = {}  # date -> (original_index, bar)
    for orig_idx, bar in valid:
        date = str(bar.get("date", "")).strip()
        if date in seen:
            actions.append(CleaningAction(
                action="deduped",
                field="date",
                index=orig_idx,
                reason=f"duplicate date {date}",
            ))
        seen[date] = (orig_idx, bar)

    deduped: list[tuple[int, dict]] = list(seen.values())

    # ── 3. 升序排序 ──
    deduped.sort(key=lambda entry: entry[1].get("date", ""))

    # ── 4. 缺失日K标记 ──
    result: list[dict] = []
    bars_only = [entry[1] for entry in deduped]
    missing_count = 0
    MAX_MISSING = 5

    for i in range(len(bars_only)):
        if missing_count < MAX_MISSING and i > 0:
            prev_date = str(bars_only[i - 1].get("date", ""))
            curr_date = str(bars_only[i].get("date", ""))

            prev_dt = _parse_yyyymmdd(prev_date)
            curr_dt = _parse_yyyymmdd(curr_date)

            if prev_dt is not None and curr_dt is not None:
                gap = (curr_dt - prev_dt).days
                if gap > 1:
                    max_insert = min(gap - 1, MAX_MISSING - missing_count)
                    for d in range(1, max_insert + 1):
                        missing_date = (prev_dt + timedelta(days=d)).strftime("%Y%m%d")
                        result.append({
                            "date": missing_date,
                            "_missing": True,
                            "open": 0,
                            "high": 0,
                            "low": 0,
                            "close": 0,
                            "volume": 0,
                            "open_interest": 0,
                        })
                        missing_count += 1
                        actions.append(CleaningAction(
                            action="marked",
                            field="date",
                            index=i,
                            reason=f"missing bar {missing_date} inserted",
                        ))

        result.append(bars_only[i])

    report = CleaningReport(cleaning_id="", actions=actions)
    return result, report


# 兼容性别名
TimelineCleaner = clean_timeline
