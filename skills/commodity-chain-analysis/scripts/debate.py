#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多Agent辩论引擎 v3.0 — 数据驱动版本
=====================================
基于 futures-data-search 的全维度多空辩论。

数据来源（由上游管线注入）：
  fund_data = {
      'oi_ranking': DuckDBStore.get_latest_oi(variety)
          → 前20会员多空持仓 + 净头寸 + 集中度
      'warehouse': DuckDBStore.get_latest_warehouse(variety)
          → 仓单注册/注销量 + 日净变化
      'news': DuckDBStore.get_latest_news(variety)
          → 产业新闻 + 情绪标签(bullish/bearish)
      'spread': DuckDBStore.get_term_structure(variety)
          → 期限结构 + Back/Contango状态
      'oi_trend': DuckDBStore.get_oi_net_position(variety, days=10)
          → 主力席位10日净持仓趋势
  }

辩论流程：
  1. 多头Agent：fund_data → 构建多头论点（资金面+供应面+催化剂+结构面）
  2. 空头Agent：fund_data → 构建空头论点
  3. 研究主管：综合技术面+资金面+基本面 → 裁决
"""

from .config import get_chain_debate_weight

# ═══════════════════════════════════════════════════════════════
# 数据解读层 — 将原始数据转为结构化论点证据
# ═══════════════════════════════════════════════════════════════


def _analyze_oi_bullish(oi_data) -> list:
    """分析持仓排名数据，提取多头论据"""
    args = []
    if not oi_data:
        return args

    long_lots = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "long")
    short_lots = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "short")
    net = long_lots - short_lots

    # 净持仓方向
    if net > 0:
        args.append(
            {
                "type": "fund_flow",
                "point": f"前20会员净多头{net:,}手，主力席位整体看多",
                "data": {"net_position": net, "long_lots": long_lots, "short_lots": short_lots},
            }
        )
    elif net < 0:
        args.append(
            {
                "type": "fund_flow",
                "point": f"前20会员净空头{abs(net):,}手，主力席位整体看空（多头不利）",
                "data": {"net_position": net},
            }
        )

    # 前5集中度
    top5_long = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "long" and r.get("rank", 99) <= 5)
    top5_short = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "short" and r.get("rank", 99) <= 5)
    total = long_lots + short_lots
    if total > 0:
        concen = (top5_long + top5_short) / total
        if concen > 0.35:
            args.append(
                {
                    "type": "fund_flow",
                    "point": f"前5会员持仓集中度{concen:.1%}，资金高度集中，趋势延续概率大",
                    "data": {"concentration": concen},
                }
            )

    return args


def _analyze_oi_bearish(oi_data) -> list:
    """分析持仓排名数据，提取空头论据"""
    args = []
    if not oi_data:
        return args

    long_lots = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "long")
    short_lots = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "short")
    net = long_lots - short_lots

    if net < 0:
        args.append(
            {
                "type": "fund_flow",
                "point": f"前20会员净空头{abs(net):,}手，主力席位整体看空",
                "data": {"net_position": net},
            }
        )
    elif net > 0:
        args.append(
            {
                "type": "fund_flow",
                "point": f"前20会员净多头{net:,}手，主力席位看多（空头不利）",
                "data": {"net_position": net},
            }
        )

    top5_long = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "long" and r.get("rank", 99) <= 5)
    top5_short = sum(r.get("lots", 0) for r in oi_data if r.get("direction") == "short" and r.get("rank", 99) <= 5)
    total = long_lots + short_lots
    if total > 0:
        bear_concen = top5_short / total
        if bear_concen > 0.20:
            args.append(
                {
                    "type": "fund_flow",
                    "point": f"空头前5会员占比{bear_concen:.1%}，空头力量集中",
                    "data": {"short_concentration": bear_concen},
                }
            )

    return args


def _analyze_warehouse_bullish(wh_data) -> list:
    """分析仓单数据，提取多头论据（仓单减少=多头利好）"""
    args = []
    if not wh_data:
        return args

    total_registered = sum(r.get("registered_lots", 0) for r in wh_data)
    total_net = sum(r.get("net_change", 0) for r in wh_data)

    if total_net < 0:
        args.append(
            {
                "type": "supply",
                "point": f"仓单净减少{abs(total_net):,}张，现货供应趋紧",
                "data": {"registered": total_registered, "net_change": total_net},
            }
        )

    # 注销仓单率（注销/注册比例高=潜在需求强）
    total_cancelled = sum(r.get("cancelled_lots", 0) for r in wh_data)
    if total_registered > 0:
        cancel_rate = total_cancelled / total_registered
        if cancel_rate > 0.15:
            args.append(
                {
                    "type": "supply",
                    "point": f"注销仓单率{cancel_rate:.1%}，潜在交割需求旺盛",
                    "data": {"cancel_rate": cancel_rate},
                }
            )

    return args


def _analyze_warehouse_bearish(wh_data) -> list:
    """分析仓单数据，提取空头论据（仓单增加=空头利好）"""
    args = []
    if not wh_data:
        return args

    total_registered = sum(r.get("registered_lots", 0) for r in wh_data)
    total_net = sum(r.get("net_change", 0) for r in wh_data)

    if total_net > 0:
        args.append(
            {
                "type": "supply",
                "point": f"仓单净增加{total_net:,}张，现货供应充裕",
                "data": {"registered": total_registered, "net_change": total_net},
            }
        )

    return args


def _analyze_news(news_data, sentiment_filter=None) -> list:
    """分析新闻数据，提取催化事件"""
    args = []
    if not news_data:
        return args

    for item in news_data[:5]:
        sentiment = item.get("sentiment", "neutral")
        if sentiment_filter and sentiment != sentiment_filter:
            continue
        title = item.get("title", "")
        if not title:
            continue

        sentiment_label = {"bullish": "利好", "bearish": "利空", "neutral": "中性"}.get(sentiment, "中性")

        args.append(
            {
                "type": "catalyst",
                "point": f"【{sentiment_label}】{title}",
                "data": {"title": title, "source": item.get("source", ""), "sentiment": sentiment},
            }
        )

    return args


def _analyze_spread_bullish(spread_data) -> list:
    """分析期限结构，提取多头论据（Back=多头利好）"""
    args = []
    if not spread_data or len(spread_data) < 2:
        return args

    prices = [r.get("price", 0) for r in spread_data if r.get("price")]
    if len(prices) >= 2:
        if prices[0] > prices[1]:
            args.append(
                {
                    "type": "structure",
                    "point": f"期限结构Back(近月{prices[0]:.0f}>远月{prices[1]:.0f})，现货偏紧",
                    "data": {"near_month": prices[0], "far_month": prices[1], "structure": "back"},
                }
            )

    return args


def _analyze_spread_bearish(spread_data) -> list:
    """分析期限结构，提取空头论据（Contango=空头利好）"""
    args = []
    if not spread_data or len(spread_data) < 2:
        return args

    prices = [r.get("price", 0) for r in spread_data if r.get("price")]
    if len(prices) >= 2:
        if prices[0] < prices[1]:
            args.append(
                {
                    "type": "structure",
                    "point": f"期限结构Contango(近月{prices[0]:.0f}<远月{prices[1]:.0f})，现货宽松",
                    "data": {"near_month": prices[0], "far_month": prices[1], "structure": "contango"},
                }
            )

    return args


def _count_sentiment(news_data) -> dict:
    """统计新闻情绪分布"""
    result = {"bullish": 0, "bearish": 0, "neutral": 0}
    if not news_data:
        return result
    for item in news_data:
        s = item.get("sentiment", "neutral")
        if s in result:
            result[s] += 1
    return result


# ═══════════════════════════════════════════════════════════════
# 多头Agent — 构建多头论据
# ═══════════════════════════════════════════════════════════════


def bull_argument(chain_name: str, chain_data: dict, fund_data: dict = None) -> dict:
    """多头Agent：构建做多论据（信号BUY时为正，SELL时为反方）

    Parameters
    ----------
    fund_data : dict
        由 futures-data-search 提供的数据，包含：
        - oi_ranking : list[dict]  — 前20会员持仓
        - warehouse  : list[dict]  — 仓单日报
        - news       : list[dict]  — 产业新闻（带sentiment）
        - spread     : list[dict]  — 期限结构
        - oi_trend   : list[dict]  — 净持仓趋势
    """
    weights = get_chain_debate_weight(chain_name)
    bull_case = {"chain": chain_name, "arguments": [], "strength": 0}

    score = chain_data.get("avg_score", 0)
    direction = chain_data.get("overall_trend", "HOLD")
    member = chain_data["members"][0] if chain_data.get("members") else {}
    is_buy_signal = direction == "BUY"

    # ── 1. 技术面论证（40%权重） ──
    if is_buy_signal:
        tech_weight = int(10 * weights.get("technical_weight", 1.0))
        if score >= 60:
            bull_case["arguments"].append(
                {
                    "type": "technical",
                    "point": f"多头信号（总分{score:.0f}），多层级共振，趋势明确",
                    "weight": tech_weight,
                    "source": "commodity-trend-signal",
                }
            )
            bull_case["strength"] += tech_weight
        elif score >= 40:
            bull_case["arguments"].append(
                {
                    "type": "technical",
                    "point": f"多头信号（总分{score:.0f}），有一定技术支撑",
                    "weight": int(6 * weights["technical_weight"]),
                    "source": "commodity-trend-signal",
                }
            )
            bull_case["strength"] += int(6 * weights["technical_weight"])
    else:
        # 信号是SELL：多头为反方，论证空头信号可能失败
        tech_weight = int(4 * weights.get("technical_weight", 1.0))
        bull_case["arguments"].append(
            {
                "type": "technical",
                "point": f"空头信号得分{score:.0f}，需警惕超卖后的技术性反弹",
                "weight": tech_weight,
                "source": "commodity-trend-signal",
            }
        )
        bull_case["strength"] += tech_weight

    # ── 2. 资金面论证（25%权重）—— 来自futures-data-search oi_ranking ──
    oi_data = (fund_data or {}).get("oi_ranking")
    oi_args = _analyze_oi_bullish(oi_data)
    for arg in oi_args:
        w = int(6 * weights.get("fundamental_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(oi_ranking)"
        bull_case["arguments"].append(arg)
        bull_case["strength"] += w

    # ── 3. 供应面论证（15%权重）—— 来自futures-data-search warehouse ──
    wh_data = (fund_data or {}).get("warehouse")
    wh_args = _analyze_warehouse_bullish(wh_data)
    for arg in wh_args:
        w = int(4 * weights.get("fundamental_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(warehouse)"
        bull_case["arguments"].append(arg)
        bull_case["strength"] += w

    # ── 4. 催化事件（10%权重）—— 来自futures-data-search news ──
    news_data = (fund_data or {}).get("news")
    news_args = _analyze_news(news_data, sentiment_filter="bullish")
    for arg in news_args:
        w = int(3 * weights.get("macro_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(news)"
        bull_case["arguments"].append(arg)
        bull_case["strength"] += w

    # ── 5. 期限结构论证（10%权重）—— 来自futures-data-search spread ──
    spread_data = (fund_data or {}).get("spread")
    spread_args = _analyze_spread_bullish(spread_data)
    for arg in spread_args:
        w = int(3 * weights.get("chain_logic_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(spread)"
        bull_case["arguments"].append(arg)
        bull_case["strength"] += w

    return bull_case


# ═══════════════════════════════════════════════════════════════
# 空头Agent — 构建空头论据
# ═══════════════════════════════════════════════════════════════


def bear_argument(chain_name: str, chain_data: dict, fund_data: dict = None) -> dict:
    """空头Agent：构建做空论据

    与bull_argument对称，从空头角度解读相同数据源。
    """
    weights = get_chain_debate_weight(chain_name)
    bear_case = {"chain": chain_name, "arguments": [], "strength": 0}

    score = chain_data.get("avg_score", 0)
    direction = chain_data.get("overall_trend", "HOLD")
    member = chain_data["members"][0] if chain_data.get("members") else {}
    is_sell_signal = direction == "SELL"

    # ── 1. 技术面论证（40%权重） ──
    if is_sell_signal:
        tech_weight = int(10 * weights.get("technical_weight", 1.0))
        if score >= 60:
            bear_case["arguments"].append(
                {
                    "type": "technical",
                    "point": f"空头信号（总分{score:.0f}），多层级共振，下行趋势明确",
                    "weight": tech_weight,
                    "source": "commodity-trend-signal",
                }
            )
            bear_case["strength"] += tech_weight
        elif score >= 40:
            bear_case["arguments"].append(
                {
                    "type": "technical",
                    "point": f"空头信号（总分{score:.0f}），有一定下行压力",
                    "weight": int(6 * weights["technical_weight"]),
                    "source": "commodity-trend-signal",
                }
            )
            bear_case["strength"] += int(6 * weights["technical_weight"])
    else:
        # 信号是BUY：空头为反方，论证多头信号可能失败
        tech_weight = int(4 * weights.get("technical_weight", 1.0))
        bear_case["arguments"].append(
            {
                "type": "technical",
                "point": f"多头信号得分{score:.0f}，需警惕超买后的回调风险",
                "weight": tech_weight,
                "source": "commodity-trend-signal",
            }
        )
        bear_case["strength"] += tech_weight

    # ── 2. 资金面论证（25%权重）—— 来自futures-data-search oi_ranking ──
    oi_data = (fund_data or {}).get("oi_ranking")
    oi_args = _analyze_oi_bearish(oi_data)
    for arg in oi_args:
        w = int(6 * weights.get("fundamental_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(oi_ranking)"
        bear_case["arguments"].append(arg)
        bear_case["strength"] += w

    # ── 3. 供应面论证（15%权重）—— 来自futures-data-search warehouse ──
    wh_data = (fund_data or {}).get("warehouse")
    wh_args = _analyze_warehouse_bearish(wh_data)
    for arg in wh_args:
        w = int(4 * weights.get("fundamental_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(warehouse)"
        bear_case["arguments"].append(arg)
        bear_case["strength"] += w

    # ── 4. 催化事件（10%权重）—— 来自futures-data-search news ──
    news_data = (fund_data or {}).get("news")
    news_args = _analyze_news(news_data, sentiment_filter="bearish")
    for arg in news_args:
        w = int(3 * weights.get("macro_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(news)"
        bear_case["arguments"].append(arg)
        bear_case["strength"] += w

    # ── 5. 期限结构论证（10%权重）—— 来自futures-data-search spread ──
    spread_data = (fund_data or {}).get("spread")
    spread_args = _analyze_spread_bearish(spread_data)
    for arg in spread_args:
        w = int(3 * weights.get("chain_logic_weight", 1.0))
        arg["weight"] = w
        arg["source"] = "futures-data-search(spread)"
        bear_case["arguments"].append(arg)
        bear_case["strength"] += w

    return bear_case


# ═══════════════════════════════════════════════════════════════
# 研究主管Agent — 综合多维度证据裁决
# ═══════════════════════════════════════════════════════════════


def research_manager_decision(
    bull_case: dict, bear_case: dict, signal_direction: str = "", fund_data: dict = None
) -> dict:
    """研究主管：多维度证据加权裁决

    不再仅凭bull-bear分差做决定，而是检查各维度的证据一致性：
    - 技术面得分：40%
    - 资金面（oi_ranking）：25%
    - 供应面（warehouse）：15%
    - 催化事件（news）：10%
    - 期限结构（spread）：10%

    只有当技术面+资金面+基本面三者方向一致时，verdict才有效。
    """
    bull = bull_case["strength"]
    bear = bear_case["strength"]
    diff = bull - bear

    # 提取各维度证据方向
    evidence = {"technical": 0, "fund_flow": 0, "supply": 0, "structure": 0}

    for arg in bull_case.get("arguments", []):
        t = arg.get("type", "")
        if t in evidence:
            evidence[t] += arg.get("weight", 0)
    for arg in bear_case.get("arguments", []):
        t = arg.get("type", "")
        if t in evidence:
            evidence[t] -= arg.get("weight", 0)

    # 新闻情绪统计
    news_data = (fund_data or {}).get("news", [])
    sentiment = _count_sentiment(news_data)

    # 判断各维度方向一致性
    tech_dir = "bullish" if evidence.get("technical", 0) > 0 else "bearish"
    fund_dir = "bullish" if evidence.get("fund_flow", 0) > 0 else "bearish"
    supply_dir = "bullish" if evidence.get("supply", 0) > 0 else "bearish"
    struct_dir = "bullish" if evidence.get("structure", 0) > 0 else "bearish"

    # 一致性检验：技术面+资金面+基本面是否同向
    dimensions = [tech_dir, fund_dir, supply_dir, struct_dir]
    bullish_count = dimensions.count("bullish")
    bearish_count = dimensions.count("bearish")

    # 裁决逻辑
    verdict_map = {
        "BUY": {"for_condition": diff > 3, "against_condition": diff < -3},
        "SELL": {"for_condition": diff < -3, "against_condition": diff > 3},
    }

    verdict = "HOLD"
    consensus = ""
    plan_parts = []

    if signal_direction in verdict_map:
        rule = verdict_map[signal_direction]

        if rule["for_condition"] and bullish_count >= bearish_count:
            verdict = signal_direction
            consensus = f"{'多头' if signal_direction == 'BUY' else '空头'}证据占优"
        elif rule["against_condition"] and bearish_count > bullish_count:
            verdict = "HOLD"
            consensus = "信号方向与基本面证据不一致"
        else:
            verdict = "HOLD" if abs(diff) < 5 else signal_direction
            if abs(diff) >= 5:
                consensus = f"强度足够但维度一致性不足(bull={bullish_count}/bear={bearish_count})"
            else:
                consensus = "多空证据强度接近，无明显倾向"

    plan_parts.append(f"技术面:{tech_dir}")
    plan_parts.append(f"资金面:{fund_dir}")
    plan_parts.append(f"供应面:{supply_dir}")
    plan_parts.append(f"结构面:{struct_dir}")

    if sentiment.get("bullish") or sentiment.get("bearish"):
        plan_parts.append(f"新闻:{sentiment}")

    return {
        "chain": bull_case.get("chain", ""),
        "bull_strength": bull,
        "bear_strength": bear,
        "signal_direction": signal_direction,
        "verdict": verdict,
        "plan": f"{consensus} | {'|'.join(plan_parts)}",
        "evidence": evidence,
        "dimension_consensus": {
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "technical": tech_dir,
            "fund_flow": fund_dir,
            "supply": supply_dir,
            "structure": struct_dir,
        },
    }
