"""数据质量评估 — K线 / F10 基本面 / 技术指标 多维度质量元数据。

K线评估:
  - source: 数据源名称
  - freshness_days: 最后 K 线距今交易日数
  - confidence: PRIMARY / FRESH / DAILY / CACHED / STALE
  - n_bars: K 线数量
  - volume_ok: 成交量有效性
  - overall: A/B/C/D 综合等级

F10 数据评估:
  - 基差 (basis): 数值合理性、缺失检测
  - 期限结构 (term_structure): 结构完整性、合约覆盖
  - 仓单 (warrant): 数据有效性
  - 持仓排名 (position_ranking): 数据可用性
  - 基本面 (fundamental): 数据完整性

技术指标评估:
  - NaN/Inf 检测
  - 数值范围合理性
  - 关键指标完整性

遵循 data_sources.yaml 中的新鲜度阈值。
"""

from __future__ import annotations

import math
from datetime import datetime, date

from futures_data_core.core.data_freshness import data_grade_from_age


# ── K线评估阈值 ──
_MIN_BARS = 30
_MIN_VOLUME_RATIO = 0.50
_MAX_STALE_DAYS = 20

# ── 技术指标合理性范围 ──
_INDICATOR_RANGES = {
    "RSI14": (0, 100),
    "RSI": (0, 100),
    "ADX14": (0, 100),
    "ADX": (0, 100),
    "CCI20": (-300, 300),
    "CCI": (-300, 300),
    "ATR14": (0, None),      # 正数即可
    "ATR": (0, None),
}

# 必须存在的关键指标
_REQUIRED_INDICATORS = {"MA10", "MA20", "MA60", "RSI14", "ADX14", "ATR14", "EMA12", "EMA26"}


# ═══════════════════════════════════════════════════════════════
#  K线质量评估
# ═══════════════════════════════════════════════════════════════


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

    # ── OHLC 完整性检查 ──
    bad_ohlc = 0
    for b in kline:
        try:
            o, h, l, c = float(b.get("open", 0)), float(b.get("high", 0)), float(b.get("low", 0)), float(b.get("close", 0))
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                bad_ohlc += 1
            elif l > h or o > h or c > h:
                bad_ohlc += 1
        except (TypeError, ValueError):
            bad_ohlc += 1
    ohlc_ok = bad_ohlc == 0

    # ── 综合等级 ──
    issues = []
    if n_bars < _MIN_BARS:
        issues.append(f"K线数{n_bars}<{_MIN_BARS}")
    if freshness_days > _MAX_STALE_DAYS:
        issues.append(f"最后K线距今{freshness_days}天")
    if not volume_ok:
        issues.append("成交量数据异常")
    if not ohlc_ok:
        issues.append(f"{bad_ohlc}根K线OHLC异常")

    overall = _grade_overall(n_bars, freshness_days, volume_ok and ohlc_ok, bool(issues))

    return {
        "symbol": symbol,
        "source": source,
        "available": True,
        "freshness_days": freshness_days,
        "last_date": last_date_str,
        "confidence": confidence,
        "n_bars": n_bars,
        "volume_ok": volume_ok,
        "ohlc_ok": ohlc_ok,
        "overall": overall,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════
#  F10 数据质量评估
# ═══════════════════════════════════════════════════════════════


def evaluate_f10_data(symbol: str, f10_data: dict) -> dict:
    """评估单品种 F10 数据的质量，返回 {field: quality} 字典。

    检查维度:
      - 基础: A2A grade (PRIMARY/FRESH/DAILY/STALE/UNAVAILABLE)
      - 完整性: 数据非 None、含必要字段
      - 数值合理: 基差/期限结构斜率等在正常范围

    Args:
        symbol: 品种代码
        f10_data: symbol_data dict (含 term_structure / basis / spread / warrant / fundamental 等 key)

    Returns:
        {field: {available, grade, issues, summary}, ...} + f10_overall / f10_pct / f10_issues
    """
    fields_map = [
        ("basis", "基差", _check_basis),
        ("term_structure", "期限结构", _check_term_structure),
        ("spread", "价差", _check_spread),
        ("warrant", "仓单", _check_warrant),
        ("fundamental", "基本面", _check_fundamental),
        ("position_ranking", "持仓排名", _check_position_ranking),
    ]

    results = {}
    total_available = 0
    total_issues = 0
    all_issues = []

    for field_key, field_label, checker in fields_map:
        raw = f10_data.get(field_key, {})
        data_grade = raw.get("summary", "UNAVAILABLE") if isinstance(raw, dict) else "UNAVAILABLE"
        issues = []
        available = False

        if raw and isinstance(raw, dict) and "error" not in str(raw.get("data", {})):
            try:
                payload_data = raw.get("data", {})
                if payload_data and isinstance(payload_data, dict) and not payload_data.get("error"):
                    available = True
                    # 数值级检查
                    checker(payload_data, issues)
            except Exception:
                issues.append("解析异常")

        if available:
            total_available += 1

        if not available:
            issues.append("数据不可用")

        total_issues += len(issues)
        all_issues.extend(f"{field_label}: {i}" for i in issues)

        results[field_key] = {
            "available": available,
            "grade": data_grade,
            "issues": issues,
        }

    total_fields = len(fields_map)
    f10_pct = round(total_available / total_fields * 100, 1)
    if total_issues == 0:
        f10_overall = "A" if f10_pct >= 80 else "B"
    elif total_issues <= 2:
        f10_overall = "B" if f10_pct >= 50 else "C"
    else:
        f10_overall = "C" if f10_pct >= 50 else "D"

    return {
        "symbol": symbol,
        "fields": results,
        "f10_available": total_available,
        "f10_total": total_fields,
        "f10_pct": f10_pct,
        "f10_overall": f10_overall,
        "f10_issues": all_issues,
    }


def _check_basis(data: dict, issues: list) -> None:
    basis_pct = data.get("basis_pct")
    if basis_pct is None:
        issues.append("basis_pct缺失")
        return
    try:
        bp = float(basis_pct)
        if abs(bp) > 50:
            issues.append(f"基差率异常({bp:+.1f}%)")
    except (TypeError, ValueError):
        issues.append("基差率非数值")


def _check_term_structure(data: dict, issues: list) -> None:
    structure = data.get("structure")
    if structure not in ("BACK", "CONTANGO", "FLAT"):
        issues.append(f"期限结构判定异常({structure})")
    slope = data.get("slope_pct")
    if slope is not None:
        try:
            s = float(slope)
            if abs(s) > 20:
                issues.append(f"期限斜率异常({s:+.2f}%)")
        except (TypeError, ValueError):
            issues.append("斜率非数值")
    contracts = data.get("contracts", [])
    if len(contracts) < 2:
        issues.append(f"合约数不足({len(contracts)}<2)")


def _check_spread(data: dict, issues: list) -> None:
    if not data or (isinstance(data, dict) and "error" in data):
        issues.append("价差数据为空")
    spread = data.get("spread")
    if spread is not None and isinstance(spread, (int, float)):
        if abs(spread) > 10000:
            issues.append(f"价差异常({spread})")


def _check_warrant(data: dict, issues: list) -> None:
    if not data or (isinstance(data, dict) and not data.get("data") and "error" not in data):
        return  # 仓单无可用的数据时不视为问题（部分品种无仓单发布）
    if isinstance(data, dict) and "error" in data:
        issues.append("仓单获取失败")


def _check_fundamental(data: dict, issues: list) -> None:
    if isinstance(data, dict) and "error" in data:
        issues.append("基本面获取失败")


def _check_position_ranking(data: dict, issues: list) -> None:
    if isinstance(data, dict) and "error" in data:
        issues.append("持仓排名获取失败")


# ═══════════════════════════════════════════════════════════════
#  技术指标质量评估
# ═══════════════════════════════════════════════════════════════


def evaluate_indicators(symbol: str, indicators: dict | None) -> dict:
    """评估技术指标计算质量。

    检查:
      - NaN/Inf 数量
      - 关键指标完整性
      - 数值范围合理性

    Args:
        symbol: 品种代码
        indicators: symbol_data["indicators"] dict (含 values / available)

    Returns:
        质量元数据 dict
    """
    if not indicators:
        return {
            "symbol": symbol,
            "available": False,
            "n_nan": -1,
            "n_inf": -1,
            "completeness_pct": 0,
            "range_issues": ["指标数据为空"],
            "overall": "D",
        }

    values = indicators.get("values", {})
    available_keys = indicators.get("available", [])

    nan_count = 0
    inf_count = 0
    zero_count = 0
    range_issues = []

    for key, val in values.items():
        if val is None:
            nan_count += 1
            continue

        # 列表值（如 MA 系列）
        if isinstance(val, list):
            for v in val:
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    nan_count += 1
                elif isinstance(v, float) and math.isinf(v):
                    inf_count += 1
                elif isinstance(v, (int, float)) and v == 0 and key.startswith("MA"):
                    zero_count += 1
            continue

        # 标量值
        if isinstance(val, float):
            if math.isnan(val):
                nan_count += 1
            elif math.isinf(val):
                inf_count += 1

        # 范围检查
        if isinstance(val, (int, float)) and not math.isnan(val) and not math.isinf(val):
            _check_indicator_range(key, val, range_issues)

    # 完整性
    present = len([k for k in _REQUIRED_INDICATORS if k in available_keys or k in values])
    completeness_pct = round(present / len(_REQUIRED_INDICATORS) * 100, 1)

    # 综合等级
    issues = []
    if completeness_pct < 50:
        issues.append(f"关键指标缺失({present}/{len(_REQUIRED_INDICATORS)})")
    if nan_count > 0:
        issues.append(f"{nan_count}个NaN值")
    if inf_count > 0:
        issues.append(f"{inf_count}个Inf值")
    issues.extend(range_issues)

    if completeness_pct >= 80 and nan_count == 0 and inf_count == 0 and not range_issues:
        overall = "A"
    elif completeness_pct >= 50 and nan_count <= 3 and inf_count == 0:
        overall = "B"
    elif completeness_pct >= 30:
        overall = "C"
    else:
        overall = "D"

    return {
        "symbol": symbol,
        "available": True,
        "n_nan": nan_count,
        "n_inf": inf_count,
        "completeness_pct": completeness_pct,
        "completeness": f"{present}/{len(_REQUIRED_INDICATORS)}",
        "range_issues": range_issues,
        "overall": overall,
        "issues": issues,
    }


def _check_indicator_range(key: str, val: float, issues: list) -> None:
    """检查单个指标值是否在合理范围内。"""
    for prefix, (lo, hi) in _INDICATOR_RANGES.items():
        if key.upper() == prefix or key.upper().startswith(prefix):
            if lo is not None and val < lo:
                issues.append(f"{key}={val:.1f}<{lo}")
            if hi is not None and val > hi:
                issues.append(f"{key}={val:.1f}>{hi}")
            break


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════


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
    basic_ok: bool,
    has_issues: bool,
) -> str:
    """综合质量等级。

    A = 数据充足 + 新鲜 + 基础正常 + 无问题
    B = 有 1 个小问题
    C = 有 2 个问题
    D = 严重不足
    """
    if n_bars >= _MIN_BARS and freshness_days <= 5 and basic_ok and not has_issues:
        return "A"
    if n_bars >= 20 and freshness_days <= 10 and basic_ok:
        return "B"
    if n_bars >= 10 and freshness_days <= _MAX_STALE_DAYS:
        return "C"
    return "D"
