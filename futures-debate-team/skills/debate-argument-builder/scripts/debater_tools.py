"""
辩手弹药构建引擎 v3.0 — 替代"中译中"，实现选择性建构叙事
========================================================
证真(多方) 和 慎思(空方) 从同一份观澜+探源+链证源数据中，
各自只挑对自己方向有利的子集，主动列弱点，预判对方攻防。

核心变化 vs v2.2:
  旧: _load_data() → 全部返回 → Agent自行决定用哪些
  新: build_ammunition() → 按偏好清单选择性建构 → 结构化输出

用法:
  from debater_tools import build_ammunition
  
  # 证真（多方）
  bull_ammo = build_ammunition("RB", role="证真", guanlan={}, tanyuan={})
  
  # 慎思（空方）
  bear_ammo = build_ammunition("RB", role="慎思", guanlan={}, tanyuan={})
"""

from typing import Dict, List, Optional, Tuple
import json, os, copy
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# 一、弹药偏好清单（决定"从同一份数据里挑什么"）
# ═══════════════════════════════════════════════════════════════

BULL_PREFERENCE = {
    "technical_pick": [
        "hard_support",           # hard支撑位
        "divergence_bull",        # 底背离
        "pattern_bull",           # 形态看涨
        "oi_up_price_up",         # OI↑价↑=真资金
        "confidence_ge_70",       # 技术Agent置信度高
        "rsi_oversold",           # RSI超卖
        "macd_golden_cross",      # MACD金叉
    ],
    "fundamental_pick": [
        "narrative_for_bull",     # 探源明确的多头叙事
        "balance_shortage",       # 平衡表短缺
        "back_structure",         # Back结构
        "low_profit",             # 利润低位
        "leading_positive",       # 领先指标正向
        "inventory_drain",        # 去库
        "basis_strong",           # 基差走强
    ],
    "neutral_interpretation": {
        # 模糊项的证多解读
        "pattern_risk_unconfirmed": "未确认=不用怕，等待右侧确认",
        "inventory_factory_down": "主动去库=产业健康出清",
        "profit_high": "纸面利润，实际受终端需求压制难释放",
        "contango": "远月升水是预期悲观，不是现实过剩，近月有基差保护",
    },
}

BEAR_PREFERENCE = {
    "technical_pick": [
        "hard_resistance",        # hard压力位
        "divergence_bear",        # 顶背离
        "pattern_bear",           # 形态看跌
        "oi_up_price_down",       # OI↑价↓=真资金做空
        "confidence_lt_60",       # 技术Agent自己都不信
        "rsi_overbought",         # RSI超买
        "pattern_risk",           # 任何反转形态预警
    ],
    "fundamental_pick": [
        "narrative_for_bear",     # 探源明确的空头叙事
        "balance_surplus",        # 平衡表过剩
        "contango_structure",     # Contango结构
        "high_profit",            # 利润高位→供给弹性
        "leading_negative",       # 领先指标负向
        "inventory_accumulation", # 累库
        "basis_weak",             # 基差走弱
    ],
    "neutral_interpretation": {
        # 模糊项的慎空解读
        "pattern_risk_unconfirmed": "雏形=预警已现，确认只是时间问题",
        "inventory_factory_down": "厂库降=贸易商不接货=被动累的前兆",
        "low_profit": "利润低位但供给还没减=还要跌到减产兑现",
        "back_structure": "Back是现货紧张但不是期货要涨，换月后基差收敛完就没故事了",
    },
}


# ═══════════════════════════════════════════════════════════════
# 二、6类交锋套路库
# ═══════════════════════════════════════════════════════════════

ENGAGEMENT_PATTERNS = {
    "真假破": {
        "trigger": "技术位+OI数据均有",
        "bull_attack": "假破+OI不增+插针收回=洗盘",
        "bear_attack": "真破+OI增+收盘确认=方向已变",
        "key_evidence": "OI性质(套保vs投机)、收盘是否确认",
    },
    "库存幻觉": {
        "trigger": "探源输出库存结构数据",
        "bull_attack": "库存同比降=缺货逻辑，供给跟不上",
        "bear_attack": "厂库升+社库降=被动累=下游拒收，不是缺货",
        "key_evidence": "厂库vs社库结构、利润分位",
    },
    "基差修复": {
        "trigger": "基差>30或Back/Contango显著",
        "bull_attack": "基差大=期货贴水，修复方向是期货涨向现货",
        "bear_attack": "技术已破位，修复方向是现货跌向期货",
        "key_evidence": "库存周期位置(5年百分位)",
    },
    "Price_in": {
        "trigger": "宏观事件前后或数据新鲜度标记",
        "bull_attack": "预期还没走完，还有空间（引用数据新鲜度）",
        "bear_attack": "已经Price-in了（引用已有涨幅/RSI位置）",
        "key_evidence": "data_staleness_days、RSI位置",
    },
    "换月失真": {
        "trigger": "换月日±3天或技术位标注rollover状态",
        "bull_attack": "支撑位在多个合约上验证有效，不因换月失效",
        "bear_attack": "主力切换后技术位要重算，当前支撑是旧合约的",
        "key_evidence": "rollover_状态、资金切换完成度",
    },
    "盈亏比": {
        "trigger": "任何入场方案",
        "bull_attack": "目标位合理，止损距ATR容差内，R:R≥1:1",
        "bear_attack": "目标位是hard压力打不开，止损太宽R:R虚高",
        "key_evidence": "目标位hardness、驱动持续性(探源给出) ",
    },
}


# ═══════════════════════════════════════════════════════════════
# 三、弹药构建引擎
# ═══════════════════════════════════════════════════════════════

def build_ammunition(
    symbol: str,
    role: str,                       # "证真" 或 "慎思"
    guanlan: dict,                   # 观澜输出（技术分析）
    tanyuan: dict,                   # 探源输出（基本面）
    lianzhengyuan: Optional[dict] = None,  # 链证源输出
) -> dict:
    """从观澜+探源+链证源中构建结构化辩词。

    Returns: StructuredDebate 兼容格式的 dict
    """
    is_bull = role == "证真"
    pref = BULL_PREFERENCE if is_bull else BEAR_PREFERENCE
    direction = "long" if is_bull else "short"

    # ── 从观澜中挑弹药 ──
    tech_evidence = _pick_technical(guanlan, pref["technical_pick"], is_bull)

    # ── 从探源中挑弹药 ──
    fund_evidence = _pick_fundamental(tanyuan, pref["fundamental_pick"], is_bull)

    # ── 从链证源中挑弹药 ──
    chain_evidence = _pick_chain(lianzhengyuan, symbol, is_bull)

    # ── 建构论据（thesis） ──
    thesis = _build_thesis(symbol, direction, tech_evidence, fund_evidence)

    # ── 主动列弱点（counter_risks） ──
    counter_risks = _build_counter_risks(
        guanlan, tanyuan, is_bull, pref["neutral_interpretation"]
    )

    # ── 6类交锋匹配 ──
    patterns = _match_patterns(guanlan, tanyuan)

    # ── 预判对方攻击方向 ──
    rebuttal_strategy = _build_rebuttal_strategy(
        patterns, tech_evidence, fund_evidence, is_bull
    )

    # ── 方案（简化版，策执远会细化） ──
    entry_plan = _build_entry_plan(guanlan, is_bull)

    # ── 置信度 ──
    confidence = _calc_confidence(tech_evidence, fund_evidence, counter_risks)

    result = {
        "role": role,
        "variant": "bull" if is_bull else "bear",
        "symbol": symbol,
        "thesis": thesis,
        "evidence": {
            "technical": tech_evidence,
            "fundamental": fund_evidence,
            "chain": chain_evidence,
        },
        "counter_risks": counter_risks,
        "entry_plan": entry_plan,
        "rebuttal_strategy": rebuttal_strategy,
        "engagement_patterns": patterns,
        "confidence": round(confidence, 2),
        "summary_4_risk": _build_summary(thesis, counter_risks),
        "full_text": _build_full_text(role, thesis, tech_evidence, fund_evidence,
                                       counter_risks, rebuttal_strategy),
    }
    return result


# ═══════════════════════════════════════════════════════════════
# 四、子函数实现
# ═══════════════════════════════════════════════════════════════

def _pick_technical(guanlan: dict, picks: List[str], is_bull: bool) -> List[dict]:
    """按偏好清单从观澜输出中挑技术证据。"""
    evidence = []
    guanlan = guanlan or {}

    # 支撑/阻力位
    supports = guanlan.get("supports", [])
    resistances = guanlan.get("resistances", [])

    if is_bull:
        # 多方只挑支撑位
        for s in supports[:3]:  # 最多挑3个
            if "hard" in s.get("hardness", ""):
                evidence.append({
                    "point": f"{s.get('price','?')}是{s.get('source','?')}，hard支撑，触碰{s.get('touch_count','?')}次",
                    "source": "观澜",
                    "weight": 0.9,
                })
        # 底背离
        if guanlan.get("divergence") == "bullish":
            evidence.append({
                "point": "价格新低但RSI/OSC未新低，底背离，下跌动能衰竭",
                "source": "观澜",
                "weight": 0.85,
            })
    else:
        # 空方只挑压力位
        for r in resistances[:3]:
            if "hard" in r.get("hardness", ""):
                evidence.append({
                    "point": f"{r.get('price','?')}是{r.get('source','?')}，hard压力，测试{r.get('touch_count','?')}次未过",
                    "source": "观澜",
                    "weight": 0.9,
                })
        # 顶背离
        if guanlan.get("divergence") == "bearish":
            evidence.append({
                "point": "价格新高但RSI/OSC未新高，顶背离，上涨动能衰竭",
                "source": "观澜",
                "weight": 0.85,
            })

    # OI配合
    oi = guanlan.get("oi", {})
    if oi:
        if is_bull and oi.get("trend") == "up" and guanlan.get("price_trend") == "up":
            evidence.append({
                "point": f"OI↑价↑，真资金进场（OI{oi.get('change_pct','?')}%）",
                "source": "观澜",
                "weight": 0.8,
            })
        elif not is_bull and oi.get("trend") == "up" and guanlan.get("price_trend") == "down":
            evidence.append({
                "point": f"OI↑价↓，真资金在做空（OI{oi.get('change_pct','?')}%）",
                "source": "观澜",
                "weight": 0.8,
            })

    # RSI极端
    rsi = guanlan.get("rsi", 50)
    if is_bull and rsi < 35:
        evidence.append({
            "point": f"RSI {rsi}，超卖区域，反弹动能积累",
            "source": "观澜",
            "weight": 0.7,
        })
    elif not is_bull and rsi > 65:
        evidence.append({
            "point": f"RSI {rsi}，超买区域，回调风险加大",
            "source": "观澜",
            "weight": 0.7,
        })

    return evidence


def _pick_fundamental(tanyuan: dict, picks: List[str], is_bull: bool) -> List[dict]:
    """按偏好清单从探源输出中挑基本面证据。"""
    evidence = []
    tanyuan = tanyuan or {}

    # 叙事
    narratives = tanyuan.get("narratives", tanyuan.get("narrative_for_bull" if is_bull else "narrative_for_bear", []))
    if isinstance(narratives, list):
        for n in narratives[:2]:
            evidence.append({"point": str(n), "source": "探源", "weight": 0.85})

    # 库存
    inv = tanyuan.get("inventory", {})
    if inv:
        if is_bull:
            pct = inv.get("percentile_5y", 50)
            if pct < 40:
                evidence.append({
                    "point": f"库存5年百分位{pct}%，偏低，有补库驱动",
                    "source": "探源",
                    "weight": 0.8,
                })
            # 库存结构：厂库降=主动去库（利好）
            structure = inv.get("structure", "")
            if "厂库降" in structure and "社库降" in structure:
                evidence.append({
                    "point": f"厂库+社库双降=主动去库，产业健康出清",
                    "source": "探源",
                    "weight": 0.75,
                })
        else:
            pct = inv.get("percentile_5y", 50)
            if pct > 60:
                evidence.append({
                    "point": f"库存5年百分位{pct}%，偏高，去库压力大",
                    "source": "探源",
                    "weight": 0.8,
                })
            structure = inv.get("structure", "")
            if "厂库升" in structure and "社库降" in structure:
                evidence.append({
                    "point": f"厂库升+社库降=被动累库，下游不接货",
                    "source": "探源",
                    "weight": 0.85,
                })

    # 利润
    profit = tanyuan.get("profit", {})
    if profit:
        pct = profit.get("percentile_5y", 50)
        value = profit.get("value", 0)
        if is_bull and pct < 30:
            evidence.append({
                "point": f"利润{value}，百分位{pct}%，低位→减产预期，供给收缩",
                "source": "探源",
                "weight": 0.85,
            })
        elif not is_bull and pct > 60:
            evidence.append({
                "point": f"利润{value}，百分位{pct}%，高位→供给弹性大，随时放量",
                "source": "探源",
                "weight": 0.85,
            })
        elif not is_bull and pct < 20:
            # 低利润对空方也是弹药：利润低但供给还没减=还要跌
            evidence.append({
                "point": f"利润{value}，百分位{pct}%，已经亏损但产量未减=减产还没兑现，价格还要跌到真正减产",
                "source": "探源",
                "weight": 0.7,
            })

    # 期限结构
    ts = tanyuan.get("term_structure", tanyuan.get("ts_type", ""))
    if ts:
        if is_bull and "back" in str(ts).lower():
            evidence.append({
                "point": f"期限结构{ts}，Back=近月偏紧，利于做多近月",
                "source": "探源",
                "weight": 0.8,
            })
        elif not is_bull and "contango" in str(ts).lower():
            evidence.append({
                "point": f"期限结构{ts}，Contango=远月升水，利于做空近月",
                "source": "探源",
                "weight": 0.8,
            })

    # 领先指标
    leading = tanyuan.get("leading_indicators", {})
    if leading:
        for key, val in leading.items():
            if isinstance(val, (int, float)):
                if is_bull and val > 0:
                    evidence.append({
                        "point": f"领先指标{key}: {val}，正向，预示需求改善",
                        "source": "探源",
                        "weight": 0.6,
                    })
                elif not is_bull and val < 0:
                    evidence.append({
                        "point": f"领先指标{key}: {val}%，负向，预示需求走弱",
                        "source": "探源",
                        "weight": 0.6,
                    })

    return evidence


def _pick_chain(lianzhengyuan: Optional[dict], symbol: str, is_bull: bool) -> List[dict]:
    """从链证源输出中挑产业链证据。"""
    if not lianzhengyuan:
        return []
    evidence = []

    chain = lianzhengyuan.get("chain_results", {}).get(symbol, {})
    chain_name = chain.get("chain", "")
    if chain_name:
        trend = chain.get("chain_trend", "")
        consistency = chain.get("chain_consistency", 0)
        if is_bull and "多" in str(trend):
            evidence.append({
                "point": f"产业链{chain_name}趋势{trend}，链内一致性{consistency}%，方向有利",
                "source": "链证源",
                "weight": 0.7,
            })
        elif not is_bull and "空" in str(trend):
            evidence.append({
                "point": f"产业链{chain_name}趋势{trend}，链内一致性{consistency}%，方向有利",
                "source": "链证源",
                "weight": 0.7,
            })

    return evidence


def _build_thesis(symbol: str, direction: str,
                  tech: List[dict], fund: List[dict]) -> str:
    """建构一句话论点（不是复述数据，是叙事）。"""
    tech_points = [e["point"] for e in tech[:2]]
    fund_points = [e["point"] for e in fund[:2]]
    all_points = tech_points + fund_points
    if all_points:
        return f"{symbol} {'做多' if direction == 'long' else '做空'}，{' + '.join(all_points[:3])}，三重共振"
    return f"{symbol} {'做多' if direction == 'long' else '做空'}，基本面+技术面信号共振"


def _build_counter_risks(guanlan: dict, tanyuan: dict,
                          is_bull: bool, interpretations: dict) -> List[dict]:
    """主动列己方弱点。"""
    risks = []

    # 观澜的反转形态预警（如果是己方不利的）
    pattern_risk = guanlan.get("pattern_risk", "")
    if pattern_risk:
        interpretation = interpretations.get("pattern_risk_unconfirmed", "待观察")
        risks.append({
            "risk": f"观澜标注{pattern_risk}",
            "mitigation": interpretation,
            "severity": "medium",
        })

    # 利润高位（如果对己方不利）
    profit = tanyuan.get("profit", {})
    pct = profit.get("percentile_5y", 50)
    if is_bull and pct > 60:
        risks.append({
            "risk": f"利润百分位{pct}%，供给释放压力",
            "mitigation": interpretations.get("profit_high", "纸面利润，需求压制"),
            "severity": "medium",
        })
    elif not is_bull and pct < 30:
        risks.append({
            "risk": f"利润百分位{pct}%，成本支撑，下行空间有限",
            "mitigation": interpretations.get("low_profit", "利润低位但减产未兑现"),
            "severity": "high",
        })

    # 库存结构
    inv = tanyuan.get("inventory", {})
    structure = inv.get("structure", "")
    if is_bull and "厂库升" in structure:
        risks.append({
            "risk": "厂库升→供给压力",
            "mitigation": "社库也在降，中游去库会向上游传导，厂库升是短期滞后",
            "severity": "medium",
        })

    # 换月
    if guanlan.get("rollover_near"):
        risks.append({
            "risk": "临近换月，技术位可能失真",
            "mitigation": "已在止损中考虑了ATR缓冲，换月跳空风险可控",
            "severity": "high",
        })

    return risks


def _match_patterns(guanlan: dict, tanyuan: dict) -> List[str]:
    """匹配适用的6类交锋套路。"""
    matched = []
    guanlan = guanlan or {}
    tanyuan = tanyuan or {}

    # 真假破：有技术位+OI数据
    if guanlan.get("supports") or guanlan.get("resistances"):
        if guanlan.get("oi", {}).get("change_pct"):
            matched.append("真假破")

    # 库存幻觉：有库存结构
    inv = tanyuan.get("inventory", {})
    if inv.get("structure") or inv.get("percentile_5y"):
        matched.append("库存幻觉")

    # 基差修复：基差或期限结构显著
    if tanyuan.get("basis", 0) > 30 or tanyuan.get("term_structure"):
        matched.append("基差修复")

    # Price-in：有宏观事件标记或RSI极端
    if guanlan.get("rsi", 50) > 65 or guanlan.get("rsi", 50) < 35:
        if tanyuan.get("event_near"):
            matched.append("Price_in")

    # 换月失真
    if guanlan.get("rollover_near"):
        matched.append("换月失真")

    # 盈亏比：总是适用
    matched.append("盈亏比")

    return matched


def _build_rebuttal_strategy(
    patterns: List[str],
    tech: List[dict],
    fund: List[dict],
    is_bull: bool,
) -> List[dict]:
    """预判对方攻击方向+己方防守方案。"""
    strategy = []
    for p in patterns[:4]:  # 最多4个
        pattern_info = ENGAGEMENT_PATTERNS.get(p, {})
        if is_bull:
            attack = pattern_info.get("bear_attack", "")
            defense = pattern_info.get("bull_attack", "")
        else:
            attack = pattern_info.get("bull_attack", "")
            defense = pattern_info.get("bear_attack", "")
        if attack and defense:
            strategy.append({
                "pattern": p,
                "predicted_attack": f"对方可能用: {attack}",
                "defense": f"己方防守: {defense}",
                "key_evidence": pattern_info.get("key_evidence", ""),
            })
    return strategy


def _build_entry_plan(guanlan: dict, is_bull: bool) -> Optional[dict]:
    """构建入场方案（简化版，策执远会细化）。"""
    guanlan = guanlan or {}
    price = guanlan.get("last_price", 0)
    if not price:
        return None

    atr = guanlan.get("atr", price * 0.01)
    supports = guanlan.get("supports", [])
    resistances = guanlan.get("resistances", [])

    if is_bull and supports:
        nearest = min(supports, key=lambda s: abs(s.get("price", 0) - price))
        stop = nearest.get("price", price - 2 * atr)
        target = price + 2 * atr
        return {
            "price_zone": f"{price-0.3*atr:.0f}-{price:.0f}",
            "stop": f"{stop:.0f}（观澜锚{nearest.get('price', stop):.0f}-0.4ATR={0.4*atr:.0f}）",
            "target": f"{target:.0f}（{2}ATR）",
            "risk_reward": f"1:{abs(target-price)/max(abs(price-stop),1):.1f}",
        }
    elif not is_bull and resistances:
        nearest = min(resistances, key=lambda s: abs(s.get("price", 0) - price))
        stop = nearest.get("price", price + 2 * atr)
        target = price - 2 * atr
        return {
            "price_zone": f"{price:.0f}-{price+0.3*atr:.0f}",
            "stop": f"{stop:.0f}（观澜锚{nearest.get('price', stop):.0f}+0.4ATR）",
            "target": f"{target:.0f}（{2}ATR）",
            "risk_reward": f"1:{abs(price-target)/max(abs(stop-price),1):.1f}",
        }

    return None


def _calc_confidence(tech: List[dict], fund: List[dict],
                      risks: List[dict]) -> float:
    """根据证据质量和弱点数量计算置信度。"""
    base = 0.6
    tech_weight = min(len(tech) * 0.05, 0.2)
    fund_weight = min(len(fund) * 0.05, 0.2)
    risk_penalty = min(len(risks) * 0.05, 0.2)
    return max(0.1, min(0.95, base + tech_weight + fund_weight - risk_penalty))


def _build_summary(thesis: str, risks: List[dict]) -> str:
    """精简版摘要（给风控明）。"""
    risk_summary = "; ".join([r["risk"] for r in risks[:2]]) if risks else "无"
    return f"{thesis} | 风险: {risk_summary}"


def _build_full_text(role: str, thesis: str,
                      tech: List[dict], fund: List[dict],
                      risks: List[dict], rebuttal: List[dict]) -> str:
    """完整论证文本（给HTML报告）。"""
    lines = [f"## {role}论据", "", f"**核心论点**: {thesis}", ""]

    lines.append("### 技术面证据")
    for e in tech:
        lines.append(f"- {e['point']} (来源:{e['source']})")

    lines.append("")
    lines.append("### 基本面证据")
    for e in fund:
        lines.append(f"- {e['point']} (来源:{e['source']})")

    if risks:
        lines.append("")
        lines.append("### 承认的风险")
        for r in risks:
            lines.append(f"- ⚠️ {r['risk']} → {r['mitigation']}")

    if rebuttal:
        lines.append("")
        lines.append("### 预判对方攻击")
        for r in rebuttal:
            lines.append(f"- {r['predicted_attack']}")
            lines.append(f"  → {r['defense']}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 五、向后兼容
# ═══════════════════════════════════════════════════════════════

def get_factor_decomp(symbol: str) -> dict:
    """(向后兼容) 获取品种的7因子分解数据。"""
    return {"symbol": symbol, "note": "v3.0使用build_ammunition替代", "error": "功能已迁移"}


def get_chain_context(symbol: str) -> dict:
    """(向后兼容) 获取品种所在产业链的上下文信息。"""
    return {"symbol": symbol, "note": "v3.0使用build_ammunition替代", "error": "功能已迁移"}


def get_price_action(symbol: str, days: int = 20) -> dict:
    """(向后兼容) 获取品种近期价格走势摘要。"""
    return {"symbol": symbol, "note": "v3.0使用build_ammunition替代", "error": "功能已迁移"}
