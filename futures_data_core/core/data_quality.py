"""数据质量评估 — 对每笔 K 线数据附加质量元数据。

为 P1 扫描输出的每个品种附加 data_quality 块，包含：
  - source: 数据源名称
  - freshness_days: 最后 K 线距今交易日数
  - confidence: PRIMARY / FRESH / DAILY / CACHED / STALE
  - n_bars: K 线数量
  - volume_ok: 成交量有效性
  - overall: A/B/C/D 综合等级

遵循 data_sources.yaml 中的新鲜度阈值。
"""

from __future__ import annotations

from datetime import datetime, date

from futures_data_core.core.data_freshness import data_grade_from_age


# 默认评级阈值（配置加载失败时兜底）
_MIN_BARS = 30
_MIN_VOLUME_RATIO = 0.50
_MAX_STALE_DAYS = 20


def evaluate_symbol(
    symbol: str,
    kline: list[dict] | None,
    source: str = "unknown",
) -> dict:
    """评估单品种 K 线数据的质量，返回质量元数据字典。

    Args:
        symbol: 品种代码
        kline: 该品种的 K 线列表（每根包含 date/open/high/low/close/volume）
        source: 数据源名称（如 TDX / WebFallback / QMT / TqSDK）

    Returns:
        data_quality dict
    """
    if not kline or len(kline) < 2:
        return {
            "symbol": symbol,
            "source": source,
            "available": False,
            "freshness_days": -1,
            "confidence": "STALE",
            "n_bars": len(kline) if kline else 0,
            "volume_ok": False,
            "overall": "D",
            "issues": ["K线数据不足"],
        }

    # ── 基础指标 ──
    n_bars = len(kline)
    last_bar = kline[-1]
    last_date_str = str(last_bar.get("date", ""))[:10]

    # ── 新鲜度 — 最后 K 线日期距今天数 ──
    freshness_days = _calc_freshness_days(last_date_str)
    confidence = data_grade_from_age(freshness_days)

    # ── 成交量有效性 ──
    n_positive_vol = sum(
        1 for b in kline[-_MIN_BARS:] if isinstance(b, dict) and (b.get("volume", 0) or 0) > 0
    )
    volume_ok = (n_positive_vol / min(n_bars, _MIN_BARS)) >= _MIN_VOLUME_RATIO

    # ── 综合等级 ──
    issues = []
    if n_bars < _MIN_BARS:
        issues.append(f"K线数{n_bars}<{_MIN_BARS}")
    if freshness_days > _MAX_STALE_DAYS:
        issues.append(f"最后K线距今{freshness_days}天")
    if not volume_ok:
        issues.append("成交量数据异常")

    overall = _grade_overall(n_bars, freshness_days, volume_ok, bool(issues))

    return {
        "symbol": symbol,
        "source": source,
        "available": True,
        "freshness_days": freshness_days,
        "last_date": last_date_str,
        "confidence": confidence,
        "n_bars": n_bars,
        "volume_ok": volume_ok,
        "overall": overall,
        "issues": issues,
    }


def _calc_freshness_days(date_str: str) -> int:
    """计算最后 K 线日期距今天数（交易日近似 = 自然日 * 0.7）。"""
    if not date_str:
        return 999
    try:
        last = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        delta = (date.today() - last).days
        # 粗略近似交易日数
        return max(0, int(delta * 0.7))
    except (ValueError, TypeError):
        return 999


def _grade_overall(
    n_bars: int,
    freshness_days: int,
    volume_ok: bool,
    has_issues: bool,
) -> str:
    """综合质量等级。

    A = 数据充足 + 新鲜 + 成交量正常 + 无问题
    B = 有 1 个小问题
    C = 有 2 个问题
    D = 严重不足
    """
    if n_bars >= _MIN_BARS and freshness_days <= 5 and volume_ok and not has_issues:
        return "A"
    if n_bars >= 20 and freshness_days <= 10 and volume_ok:
        return "B"
    if n_bars >= 10 and freshness_days <= _MAX_STALE_DAYS:
        return "C"
    return "D"
