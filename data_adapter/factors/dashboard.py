"""多因子信号一致性看板 — 汇总所有因子信号，生成闫判官终裁上下文。

接收各因子采集结果，按规则量化为方向信号（-2 ~ +2），
计算每个品种的因子一致性和分歧度。
"""

from __future__ import annotations

import math
from typing import Optional

from .types import (
    CrossSpreadResult,
    FactorDashboardResult,
    FactorSignal,
    HoldingSentimentResult,
    TermStructureResult,
    VolatilityResult,
)


def build_dashboard(
    symbols: list[str],
    term_structure: dict[str, TermStructureResult],
    volatility: dict[str, VolatilityResult],
    holding_sentiment: dict[str, HoldingSentimentResult],
    cross_spreads: list[CrossSpreadResult],
) -> FactorDashboardResult:
    """构建多因子信号一致性看板。

    从各因子采集结果中提取信号，量化为方向分，计算分歧度。

    Args:
        symbols: 品种列表
        term_structure: {symbol: TermStructureResult}
        volatility: {symbol: VolatilityResult}
        holding_sentiment: {symbol: HoldingSentimentResult}
        cross_spreads: [CrossSpreadResult, ...]

    Returns:
        FactorDashboardResult
    """
    dashboard = FactorDashboardResult(symbols=list(symbols))
    available_signals: list[str] = []

    for sym in symbols:
        bare = sym.upper()
        signals: list[FactorSignal] = []

        # ── 量价 / 技术面因子（波动率偏度信号） ──
        vol_signal = _signal_from_volatility(volatility.get(bare))
        if vol_signal:
            signals.append(vol_signal)

        # ── 期限结构信号 ──
        ts_signal = _signal_from_term_structure(term_structure.get(bare))
        if ts_signal:
            signals.append(ts_signal)

        # ── 多空持仓信号 ──
        hs_signal = _signal_from_holding_sentiment(holding_sentiment.get(bare))
        if hs_signal:
            signals.append(hs_signal)

        # ── 跨品种价差信号 ──
        spread_signals = _signals_from_cross_spreads(bare, cross_spreads)
        signals.extend(spread_signals)

        dashboard.signals[bare] = signals

        # 汇总方向
        if signals:
            total = sum(s.direction for s in signals)
            dashboard.consensus[bare] = total

            # 分歧度：方向值的标准差（归一化到 0~1）
            directions = [s.direction for s in signals]
            divergence = _compute_divergence(directions)
            dashboard.divergence[bare] = round(divergence, 2)
        else:
            dashboard.consensus[bare] = 0
            dashboard.divergence[bare] = 1.0  # 无数据时分歧度为最高

    # 如果没有任何信号，标记数据不足
    has_any_signal = any(
        len(sigs) > 0 for sigs in dashboard.signals.values()
    )
    if not has_any_signal:
        dashboard.data_grade = "NO_DATA"

    return dashboard


def _signal_from_volatility(vol: Optional[VolatilityResult]) -> Optional[FactorSignal]:
    """从波动率因子提取方向信号。

    使用偏度判断方向：
    - 偏度 > 0.3 → 上涨尾部风险 → -1（空）
    - 偏度 < -0.3 → 下跌尾部风险 → +1（多）
    """
    if vol is None or vol.data_grade != "PRIMARY" or vol.skewness is None:
        return None

    direction = 0
    if vol.skewness > 0.3:
        direction = -1
    elif vol.skewness < -0.3:
        direction = 1

    strength = min(abs(vol.skewness) * 2, 1.0) if direction != 0 else 0.3

    return FactorSignal(
        symbol=vol.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="volatility",
    )


def _signal_from_term_structure(ts: Optional[TermStructureResult]) -> Optional[FactorSignal]:
    """从期限结构因子提取方向信号。

    - 深度 backwardation（远月贴水 > 1%）→ +1（多，现货紧张）
    - 深度 contango（远月升水 > 1%）→ -1（空，供应充裕）
    """
    if ts is None or ts.data_grade != "PRIMARY" or ts.spread_ratio is None:
        return None

    direction = 0
    strength = min(abs(ts.spread_ratio) / 5, 1.0)

    if ts.curve_type == "backwardation" and ts.spread_ratio and ts.spread_ratio < -1.0:
        direction = 1
    elif ts.curve_type == "contango" and ts.spread_ratio and ts.spread_ratio > 1.0:
        direction = -1

    return FactorSignal(
        symbol=ts.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="term_structure",
    )


def _signal_from_holding_sentiment(hs: Optional[HoldingSentimentResult]) -> Optional[FactorSignal]:
    """从多空持仓因子提取方向信号。

    - 多空比 > 1.2 且多单增加 → +1（多）
    - 多空比 < 0.8 且空单增加 → -1（空）
    """
    if hs is None or hs.data_grade != "PRIMARY":
        return None

    ratio = hs.long_short_ratio
    if ratio is None:
        return None

    direction = 0
    if ratio > 1.2:
        direction = 1
    elif ratio < 0.8:
        direction = -1

    # 强度：看偏离 1.0 的程度
    strength = min(abs(ratio - 1.0) * 3, 1.0)

    return FactorSignal(
        symbol=hs.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="holding_sentiment",
    )


def _signals_from_cross_spreads(
    bare: str,
    cross_spreads: list[CrossSpreadResult],
) -> list[FactorSignal]:
    """从跨品种价差提取方向信号。

    使用 Z-Score：
    - Z > 2.0 → 价差过高 → 回归预期 → 做空该价差
    - Z < -2.0 → 价差过低 → 回归预期 → 做多该价差
    """
    signals: list[FactorSignal] = []

    for cs in cross_spreads:
        if cs.data_grade != "PRIMARY":
            continue

        # 只选择包含当前品种的配对
        if bare not in cs.pair:
            continue

        direction = 0
        if cs.zscore > 2.0:
            direction = -1  # 价差过高，预期回归
        elif cs.zscore < -2.0:
            direction = 1  # 价差过低，预期回归

        if direction != 0:
            strength = min(abs(cs.zscore) / 4, 1.0)
            source_name = f"spread_{cs.pair[0]}_{cs.pair[1]}"
            signals.append(FactorSignal(
                symbol=bare,
                direction=direction,
                strength=round(strength, 2),
                source=source_name,
            ))

    return signals


def _compute_divergence(directions: list[int]) -> float:
    """计算信号分歧度（0~1）。

    0 = 完全一致，1 = 完全分歧。
    使用归一化标准差。
    """
    if not directions:
        return 1.0

    n = len(directions)
    mean = sum(directions) / n
    variance = sum((d - mean) ** 2 for d in directions) / n
    std = math.sqrt(variance)

    # 归一化到 0~1（最大可能标准差是 2，即所有方向在 -2 和 +2 间振荡）
    max_std = 2.0
    divergence = min(std / max_std, 1.0)

    return divergence


def format_dashboard_for_prompt(dashboard: FactorDashboardResult) -> str:
    """将因子看板格式化为 LLM prompt 可读的文本表格。

    供 node_verdict() 注入闫判官终裁 prompt 使用。
    """
    if dashboard.data_grade == "NO_DATA" or not dashboard.signals:
        return "\n【多因子信号一致性看板】暂无因子数据。\n"

    # 动态构建列头（按因子源名称）
    all_sources: list[str] = []
    for sigs in dashboard.signals.values():
        for s in sigs:
            if s.source not in all_sources:
                all_sources.append(s.source)

    source_labels = {
        "volatility": "波动率",
        "term_structure": "期限结构",
        "holding_sentiment": "多空持仓",
    }
    headers = ["品种"] + [source_labels.get(s, s) for s in all_sources] + ["汇总", "分歧度"]
    col_count = len(headers)

    lines = ["\n【多因子信号一致性看板】"]
    lines.append(f"| {' | '.join(headers)} |")
    lines.append(f"|:{':' + '-' * 4 + ':'  * (col_count - 1)}")

    for bare in dashboard.symbols:
        sigs = dashboard.signals.get(bare, [])
        sig_map = {s.source: s.direction for s in sigs}

        row = [bare]
        for source in all_sources:
            d = sig_map.get(source, 0)
            if d > 0:
                row.append(f"+{d}")
            elif d < 0:
                row.append(str(d))
            else:
                row.append("0")

        consensus = dashboard.consensus.get(bare, 0)
        row.append(f"+{consensus}" if consensus > 0 else str(consensus))

        div = dashboard.divergence.get(bare, 1.0)
        row.append(f"{div:.2f}")

        lines.append(f"| {' | '.join(row)} |")

    lines.append("")
    lines.append("分歧度 < 0.2 → 因子共振，高确信度")
    lines.append("分歧度 0.2~0.5 → 因子分歧，需辩论揭示关键矛盾")
    lines.append("分歧度 > 0.5 → 极度分歧，降低置信度")
    lines.append("")

    return "\n".join(lines)
