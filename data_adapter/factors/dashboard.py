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
    FactorMatrixResult,
    FactorSignal,
    HoldingSentimentResult,
    TermStructureResult,
    VolatilityResult,
)
from data_adapter.instrument_classifier import MarketType


# 类型感知看板：每种市场类型对应的因子列
# key=MarketType, value=[(source_name, 中文标签), ...]
_TYPE_FACTOR_MAP: dict[MarketType, list[tuple[str, str]]] = {
    MarketType.COMMODITY_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("cross_spread", "价差"),
    ],
    MarketType.INDEX_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.BOND_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.STOCK: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"),
    ],
    MarketType.ETF: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"), ("etf_premium", "ETF溢价"),
    ],
    MarketType.CONVERTIBLE_BOND: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
    MarketType.REIT: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
}


def build_dashboard(
    symbols: list[str],
    term_structure: dict[str, TermStructureResult],
    volatility: dict[str, VolatilityResult],
    holding_sentiment: dict[str, HoldingSentimentResult],
    cross_spreads: list[CrossSpreadResult],
    # ── 新增参数（腾讯特有，dict 降级友好） ──
    money_flow: dict[str, dict] | None = None,
    north_flow: dict[str, dict] | None = None,
    etf_premium: dict[str, dict] | None = None,
) -> FactorDashboardResult:
    """构建多因子信号一致性看板。

    从各因子采集结果中提取信号，量化为方向分，计算分歧度。

    Args:
        symbols: 品种列表
        term_structure: {symbol: TermStructureResult}
        volatility: {symbol: VolatilityResult}
        holding_sentiment: {symbol: HoldingSentimentResult}
        cross_spreads: [CrossSpreadResult, ...]
        money_flow: {symbol: dict} — 资金流向因子（腾讯特有）
        north_flow: {symbol: dict} — 北向资金因子（腾讯特有）
        etf_premium: {symbol: dict} — ETF 溢价因子（腾讯特有）

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

        # ── 资金流向信号（腾讯特有） ──
        mf_data = (money_flow or {}).get(bare)
        mf_signal = _signal_from_money_flow(mf_data)
        if mf_signal:
            signals.append(mf_signal)

        # ── 北向资金信号（腾讯特有） ──
        nf_data = (north_flow or {}).get(bare)
        nf_signal = _signal_from_north_flow(nf_data)
        if nf_signal:
            signals.append(nf_signal)

        # ── ETF 溢价信号（腾讯特有） ──
        ep_data = (etf_premium or {}).get(bare)
        ep_signal = _signal_from_etf_premium(ep_data)
        if ep_signal:
            signals.append(ep_signal)

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


def _signal_from_money_flow(mf: dict | None) -> Optional[FactorSignal]:
    """从资金流向因子提取方向信号。

    主力净流入 > 0 → 看多（机构看好）
    主力净流入 < 0 → 看空（机构撤离）
    强度 = 主力净流入 / max(|中户|+|散户|, 1) 归一化
    """
    if not mf or mf.get("data_grade") != "PRIMARY":
        return None

    main_n = mf.get("main_net_inflow")
    if main_n is None:
        return None

    symbol = mf.get("symbol", "?")
    direction = 0
    if main_n > 0:
        direction = 1
    elif main_n < 0:
        direction = -1

    # 强度：主力净流入相对散户+中户的比例
    retail_n = abs(mf.get("retail_net_inflow", 0) or 0)
    mid_n = abs(mf.get("mid_net_inflow", 0) or 0)
    denominator = retail_n + mid_n
    if denominator > 0 and direction != 0:
        strength = min(abs(main_n) / denominator, 1.0)
    else:
        strength = 0.3 if direction != 0 else 0.0

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="money_flow",
    )


def _signal_from_north_flow(nf: dict | None) -> Optional[FactorSignal]:
    """从北向资金因子提取方向信号。

    北向净买入 > 0 → +1（外资加仓，看多）
    北向净买入 < 0 → -1（外资减仓，看空）
    """
    if not nf or nf.get("data_grade") != "PRIMARY":
        return None

    net_buy = nf.get("north_net_buy")
    if net_buy is None:
        return None

    symbol = nf.get("symbol", "?")
    direction = 0
    if net_buy > 0:
        direction = 1
    elif net_buy < 0:
        direction = -1

    # 强度：持股占比越高，信号越强
    pct = nf.get("north_holding_pct")
    strength = min(abs(pct or 0) / 10, 1.0) if pct else 0.3
    if direction == 0:
        strength = 0.0

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="north_flow",
    )


def _signal_from_etf_premium(ep: dict | None) -> Optional[FactorSignal]:
    """从 ETF 溢价因子提取方向信号。

    溢价 > 1% → 市场情绪过热，短期回调风险 → -1（看空）
    折价 > 1% → 市场情绪低迷，短期反弹机会 → +1（看多）
    """
    if not ep or ep.get("data_grade") != "PRIMARY":
        return None

    premium = ep.get("premium_pct")
    if premium is None:
        return None

    symbol = ep.get("symbol", "?")
    direction = 0
    if premium > 1.0:
        direction = -1  # 溢价过高，看空
    elif premium < -1.0:
        direction = 1   # 折价过大，看多

    if direction == 0:
        return None

    strength = min(abs(premium) / 5, 1.0)

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="etf_premium",
    )


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


def format_dashboard_for_prompt(
    dashboard: FactorDashboardResult,
    market_types: dict[str, MarketType] | None = None,
) -> str:
    """将因子看板格式化为 LLM prompt 可读的文本表格。

    按市场类型分组渲染子表格，每种类型只展示相关因子列。
    可通过 market_types 参数传入 {symbol: MarketType} 映射；
    未传入时使用 classify() 自动判断。

    Args:
        dashboard: 因子看板数据
        market_types: {symbol: MarketType} 映射（可选）

    Returns:
        格式化后的文本表格。
    """
    if dashboard.data_grade == "NO_DATA" or not dashboard.signals:
        return "\n【多因子信号一致性看板】暂无因子数据。\n"

    from data_adapter.instrument_classifier import classify, get_market_label

    lines = ["\n【多因子信号一致性看板】"]
    added_separator = False

    # 按市场类型分组
    type_groups: dict[str, list[str]] = {}
    for bare in dashboard.symbols:
        if market_types and bare in market_types:
            mt = market_types[bare]
        else:
            mt = classify(bare)
        type_name = mt.value
        if type_name not in type_groups:
            type_groups[type_name] = []
        type_groups[type_name].append(bare)

    for type_name, symbols_group in type_groups.items():
        mt_enum = MarketType(type_name) if type_name in {m.value for m in MarketType} else None
        if mt_enum is None or mt_enum not in _TYPE_FACTOR_MAP:
            continue

        factors = _TYPE_FACTOR_MAP[mt_enum]
        label = get_market_label(mt_enum)
        lines.append(f"\n── {label} ──")

        # 表头
        headers = ["品种"] + [f[1] for f in factors] + ["汇总", "分歧度"]
        lines.append(f"| {' | '.join(headers)} |")
        lines.append(f"|:{':' + '-' * 4 + ':' * (len(headers) - 1)}")

        for bare in symbols_group:
            sigs = dashboard.signals.get(bare, [])
            sig_map = {s.source: s.direction for s in sigs}

            row = [bare]
            for source, _ in factors:
                d = sig_map.get(source)
                if d is None:
                    row.append("—")  # 数据不可用
                elif d > 0:
                    row.append(f"+{d}")
                elif d < 0:
                    row.append(str(d))
                else:
                    row.append("0")  # 方向中性

            consensus = dashboard.consensus.get(bare, 0)
            row.append(f"+{consensus}" if consensus > 0 else str(consensus))

            div = dashboard.divergence.get(bare, 1.0)
            row.append(f"{div:.2f}")

            lines.append(f"| {' | '.join(row)} |")

        added_separator = True

    if not added_separator:
        return "\n【多因子信号一致性看板】暂无因子数据。\n"

    lines.append("")
    lines.append("分歧度 < 0.2 → 因子共振，高确信度")
    lines.append("分歧度 0.2~0.5 → 因子分歧，需辩论揭示关键矛盾")
    lines.append("分歧度 > 0.5 → 极度分歧，降低置信度")
    lines.append("")

    return "\n".join(lines)


def build_matrix(dashboard: FactorDashboardResult) -> FactorMatrixResult:
    """将 FactorDashboardResult 升级为 FactorMatrixResult（G23 §3.4）。

    转换逻辑：
      - matrix: {symbol: {factor_name: FactorSignal}}
      - factor_ic: 从信号强度估算（简化：strength × sign(direction)）
    """
    if dashboard.data_grade == "NO_DATA" or not dashboard.signals:
        return FactorMatrixResult(data_grade="NO_DATA")

    # 收集所有因子名称
    all_sources: list[str] = []
    for sigs in dashboard.signals.values():
        for s in sigs:
            if s.source not in all_sources:
                all_sources.append(s.source)

    matrix: dict[str, dict[str, FactorSignal]] = {}
    factor_signals: dict[str, list[int]] = {src: [] for src in all_sources}

    for bare in dashboard.symbols:
        sigs = dashboard.signals.get(bare, [])
        sym_matrix: dict[str, FactorSignal] = {}
        for s in sigs:
            sym_matrix[s.source] = s
            # 收集因子方向用于 IC 估算
            if s.source in factor_signals:
                factor_signals[s.source].append(s.direction)
        matrix[bare] = sym_matrix

    # 简化 IC 估算：因子方向与共识方向的秩相关代理
    factor_ic: dict[str, float] = {}
    for src, dirs in factor_signals.items():
        if len(dirs) < 3:
            factor_ic[src] = 0.0
            continue
        consensus = sum(dirs) / len(dirs)
        # 正相关 = 该因子与共识同向
        aligned = sum(1 for d in dirs if d * consensus > 0)
        ic = (aligned / len(dirs)) * 2 - 1  # -1~+1
        factor_ic[src] = round(ic, 3)

    return FactorMatrixResult(
        symbols=list(dashboard.symbols),
        factors=all_sources,
        matrix=matrix,
        factor_ic=factor_ic,
        data_grade="PRIMARY",
    )
