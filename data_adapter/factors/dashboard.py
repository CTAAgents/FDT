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
    MomentumResult,
    QualityResult,
    TermStructureResult,
    ValueResult,
    VolatilityResult,
)
from data_adapter.instrument_classifier import MarketType


# 类型感知看板：每种市场类型对应的因子列
# key=MarketType, value=[(source_name, 中文标签), ...]
_TYPE_FACTOR_MAP: dict[MarketType, list[tuple[str, str]]] = {
    MarketType.COMMODITY_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("cross_spread", "价差"),
        ("basis", "基差"), ("warrant", "仓单"),
        ("inventory", "库存"), ("calendar_spread", "跨期价差"),
        ("profit", "利润"), ("momentum", "动量"),
    ],
    MarketType.INDEX_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("momentum", "动量"),
    ],
    MarketType.BOND_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("momentum", "动量"),
    ],
    MarketType.STOCK: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"), ("value", "价值"),
        ("quality", "质量"), ("momentum", "动量"),
    ],
    MarketType.ETF: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"), ("etf_premium", "ETF溢价"),
        ("value", "价值"), ("quality", "质量"),
        ("momentum", "动量"),
    ],
    MarketType.CONVERTIBLE_BOND: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("momentum", "动量"),
    ],
    MarketType.REIT: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("quality", "质量"), ("momentum", "动量"),
    ],
}


def build_dashboard(
    symbols: list[str],
    term_structure: dict[str, TermStructureResult],
    volatility: dict[str, VolatilityResult],
    holding_sentiment: dict[str, HoldingSentimentResult],
    cross_spreads: list[CrossSpreadResult],
    # ── 腾讯特有因子（dict 降级友好） ──
    money_flow: dict[str, dict] | None = None,
    north_flow: dict[str, dict] | None = None,
    etf_premium: dict[str, dict] | None = None,
    # ── 期货特有因子（dict 降级友好） ──
    basis: dict[str, dict] | None = None,
    warrant: dict[str, dict] | None = None,
    inventory: dict[str, dict] | None = None,
    calendar_spread: dict[str, dict] | None = None,
    profit: dict[str, dict] | None = None,
    # ── G23 因子（TypedResult 降级友好） ──
    momentum: dict[str, MomentumResult] | None = None,
    value: dict[str, ValueResult] | None = None,
    quality: dict[str, QualityResult] | None = None,
) -> FactorDashboardResult:
    """构建多因子信号一致性看板。

    从各因子采集结果中提取信号，量化为方向分，计算分歧度。

    Args:
        symbols: 品种列表
        term_structure: {symbol: TermStructureResult}
        volatility: {symbol: VolatilityResult}
        holding_sentiment: {symbol: HoldingSentimentResult}
        cross_spreads: [CrossSpreadResult, ...]
        money_flow: {symbol: dict} — 资金流向因子
        north_flow: {symbol: dict} — 北向资金因子
        etf_premium: {symbol: dict} — ETF 溢价因子
        basis: {symbol: dict} — 基差因子
        warrant: {symbol: dict} — 仓单因子
        inventory: {symbol: dict} — 库存因子
        calendar_spread: {symbol: dict} — 跨期价差因子
        profit: {symbol: dict} — 产业链利润因子
        momentum: {symbol: MomentumResult} — 动量因子
        value: {symbol: ValueResult} — 价值因子
        quality: {symbol: QualityResult} — 质量因子

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

        # ── 基差信号（期货特有） ──
        basis_data = (basis or {}).get(bare)
        basis_signal = _signal_from_basis(basis_data)
        if basis_signal:
            signals.append(basis_signal)

        # ── 仓单信号（期货特有） ──
        warrant_data = (warrant or {}).get(bare)
        warrant_signal = _signal_from_warrant(warrant_data)
        if warrant_signal:
            signals.append(warrant_signal)

        # ── 库存信号（期货特有） ──
        inv_data = (inventory or {}).get(bare)
        inv_signal = _signal_from_inventory(inv_data)
        if inv_signal:
            signals.append(inv_signal)

        # ── 跨期价差信号（期货特有） ──
        cs_data = (calendar_spread or {}).get(bare)
        cs_signal = _signal_from_calendar_spread(cs_data)
        if cs_signal:
            signals.append(cs_signal)

        # ── 产业链利润信号（期货特有） ──
        profit_data = (profit or {}).get(bare)
        profit_signal = _signal_from_profit(profit_data)
        if profit_signal:
            signals.append(profit_signal)

        # ── 动量信号（G23） ──
        mom_result = (momentum or {}).get(bare)
        mom_signal = _signal_from_momentum(mom_result)
        if mom_signal:
            signals.append(mom_signal)

        # ── 价值信号（G23 — 股票/ETF） ──
        val_result = (value or {}).get(bare)
        val_signal = _signal_from_value(val_result)
        if val_signal:
            signals.append(val_signal)

        # ── 质量信号（G23 — 股票/ETF） ──
        qual_result = (quality or {}).get(bare)
        qual_signal = _signal_from_quality(qual_result)
        if qual_signal:
            signals.append(qual_signal)

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
    if not mf or mf.get("data_grade") not in ("PRIMARY", "DERIVED"):
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
    if not nf or nf.get("data_grade") not in ("PRIMARY", "DERIVED"):
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
    if not ep or ep.get("data_grade") not in ("PRIMARY", "DERIVED"):
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


def _signal_from_basis(basis_data: dict | None) -> Optional[FactorSignal]:
    """从基差因子提取方向信号。

    基差 = 现货价 - 期货价：
    - 基差 > 0 → 现货溢价 → 现货紧张 → +1（看多）
    - 基差 < 0 → 期货溢价 → 供应充裕 → -1（看空）
    """
    if not basis_data:
        return None
    # 支持 data_adapter wrapper 格式和 flat 格式
    raw = basis_data.get("data", basis_data)
    grade = basis_data.get("data_grade", raw.get("data_grade", ""))
    if grade not in ("PRIMARY", "DERIVED"):
        return None

    basis_val = raw.get("basis")
    basis_pct = raw.get("basis_pct")
    symbol = raw.get("symbol", "?")

    if basis_val is None:
        # 只有现货价时无法计算基差方向
        return None

    direction = 0
    if basis_val > 0:
        direction = 1
    elif basis_val < 0:
        direction = -1

    if direction == 0:
        return None

    strength = min(abs(basis_pct or 0) * 5, 1.0) if basis_pct else 0.3

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="basis",
    )


def _signal_from_warrant(warrant_data: dict | None) -> Optional[FactorSignal]:
    """从仓单因子提取方向信号。

    仓单增加 → 供应增加 → 看空
    仓单减少 → 供应减少 → 看多
    强度 = |daily_change| / total 归一化
    """
    if not warrant_data:
        return None
    raw = warrant_data.get("data", warrant_data)
    grade = warrant_data.get("data_grade", raw.get("data_grade", ""))
    if grade not in ("PRIMARY", "DERIVED"):
        return None

    total = raw.get("total")
    daily_change = raw.get("daily_change")
    symbol = raw.get("symbol", "?")

    if total is None or daily_change is None:
        return None

    direction = 0
    if daily_change > 0:
        direction = -1  # 仓单增加 → 看空
    elif daily_change < 0:
        direction = 1   # 仓单减少 → 看多

    if direction == 0:
        return None

    strength = min(abs(daily_change) / max(total, 1), 1.0)

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="warrant",
    )


def _signal_from_inventory(inv_data: dict | None) -> Optional[FactorSignal]:
    """从库存因子提取方向信号。

    库存增加 → 供应过剩 → 看空
    库存减少 → 供应紧张 → 看多
    """
    if not inv_data:
        return None
    raw = inv_data.get("data", inv_data)
    grade = inv_data.get("data_grade", raw.get("data_grade", ""))
    if grade not in ("PRIMARY", "DERIVED"):
        return None

    inventory_val = raw.get("inventory")
    change = raw.get("change")
    symbol = raw.get("symbol", "?")

    if inventory_val is None or change is None:
        return None

    direction = 0
    if change > 0:
        direction = -1  # 累库 → 看空
    elif change < 0:
        direction = 1   # 去库 → 看多

    if direction == 0:
        return None

    strength = min(abs(change) / max(inventory_val, 1), 1.0)

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="inventory",
    )


def _signal_from_calendar_spread(cs_data: dict | None) -> Optional[FactorSignal]:
    """从跨期价差因子提取方向信号。

    使用第一个近远月价差：
    - 价差 > 0 → contango → 看空（远月更贵）
    - 价差 < 0 → backwardation → 看多（近月更贵）
    """
    if not cs_data:
        return None
    raw = cs_data.get("data", cs_data)
    grade = cs_data.get("data_grade", raw.get("data_grade", ""))
    if grade not in ("PRIMARY", "DERIVED"):
        return None

    spreads = raw.get("spreads", [])
    symbol = raw.get("symbol", "?")

    if not spreads:
        return None

    first_spread = spreads[0].get("spread", 0) if isinstance(spreads[0], dict) else 0

    direction = 0
    if first_spread > 0:
        direction = -1  # contango → 看空
    elif first_spread < 0:
        direction = 1   # backwardation → 看多

    if direction == 0:
        return None

    strength = min(abs(first_spread) / 100, 1.0)

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="calendar_spread",
    )


def _signal_from_profit(profit_data: dict | None) -> Optional[FactorSignal]:
    """从产业链利润因子提取方向信号。

    利润 = 成品价 - 原料成本：
    - 利润偏高 (>历史80分位) → 供给将增加 → 看空
    - 利润偏低 (<历史20分位) → 供给将减少 → 看多
    """
    if not profit_data:
        return None
    raw = profit_data.get("data", profit_data)
    grade = profit_data.get("data_grade", raw.get("data_grade", ""))
    if grade not in ("PRIMARY", "DERIVED"):
        return None

    profit_val = raw.get("profit")
    percentile = raw.get("percentile")
    symbol = raw.get("symbol", "?")

    if profit_val is None:
        return None

    direction = 0
    if percentile is not None:
        if percentile > 80:
            direction = -1  # 利润过高 → 看空
        elif percentile < 20:
            direction = 1   # 利润过低 → 看多
    else:
        # 无百分位时使用利润本身的符号
        if profit_val > 0:
            direction = -1
        elif profit_val < 0:
            direction = 1

    if direction == 0:
        return None

    strength = min(abs(profit_val) / 500, 1.0) if abs(profit_val) > 0 else 0.3

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="profit",
    )


def _signal_from_momentum(mom: Optional[MomentumResult]) -> Optional[FactorSignal]:
    """从动量因子提取方向信号。

    使用时序动量 12-1M：
    - 动量 > 5% → 趋势强劲 → +1（多）
    - 动量 < -5% → 趋势向下 → -1（空）
    """
    if mom is None or mom.data_grade != "PRIMARY":
        return None

    m12 = mom.momentum_12m1m
    if m12 is None:
        return None

    direction = 0
    if m12 > 5.0:
        direction = 1
    elif m12 < -5.0:
        direction = -1

    if direction == 0:
        return None

    strength = min(abs(m12) / 20, 1.0)

    return FactorSignal(
        symbol=mom.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="momentum",
    )


def _signal_from_value(val: Optional[ValueResult]) -> Optional[FactorSignal]:
    """从价值因子提取方向信号。

    使用 composite_zscore：
    - z < -1.0 → 低估 → +1（看多）
    - z > 1.0 → 高估 → -1（看空）
    """
    if val is None or val.data_grade != "PRIMARY":
        return None

    z = val.composite_zscore
    if z is None:
        return None

    direction = 0
    if z < -1.0:
        direction = 1
    elif z > 1.0:
        direction = -1

    if direction == 0:
        return None

    strength = min(abs(z) / 3, 1.0)

    return FactorSignal(
        symbol=val.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="value",
    )


def _signal_from_quality(qual: Optional[QualityResult]) -> Optional[FactorSignal]:
    """从质量因子提取方向信号。

    使用 composite_score：
    - score > 0.7 → 高质量 → +1（看多）
    - score < 0.3 → 低质量 → -1（看空）
    """
    if qual is None or qual.data_grade != "PRIMARY":
        return None

    score = qual.composite_score
    if score is None:
        return None

    direction = 0
    if score > 0.7:
        direction = 1
    elif score < 0.3:
        direction = -1

    if direction == 0:
        return None

    strength = score if direction > 0 else (1.0 - score)

    return FactorSignal(
        symbol=qual.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="quality",
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
