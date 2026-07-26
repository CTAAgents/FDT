"""裁决阶段节点 — P5（裁决/风控/质检/品种汇聚）。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fdt_langgraph.agents import FdtAgentExecutor
from fdt_langgraph.llm_provider import parse_llm_output
from fdt_langgraph.state import DebateState
from fdt_langgraph._nodes_utils import _ensure_llm_key, _inject_memory_rules, _resolve_report_dir
from fdt_langgraph._nodes_boundary import _clamp_position, _compute_stop_target

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

async def node_verdict(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    # Build per-symbol debate context (v9.0 six-phase format)
    _all_bull_entries = []
    for _lst_key in ["bullish_arguments", "bullish_rebuttal_arguments", "bull_final_arguments"]:
        _raw = state.get(_lst_key, [])
        if isinstance(_raw, list):
            _all_bull_entries.extend(_raw)
        elif isinstance(_raw, dict):
            _all_bull_entries.append(_raw)

    _all_bear_entries = []
    for _lst_key in ["bearish_arguments", "bearish_rebuttal_arguments", "bear_final_arguments"]:
        _raw = state.get(_lst_key, [])
        if isinstance(_raw, list):
            _all_bear_entries.extend(_raw)
        elif isinstance(_raw, dict):
            _all_bear_entries.append(_raw)

    bull_args_dict = {}
    for _entry in _all_bull_entries:
        if isinstance(_entry, dict) and _entry.get("symbols"):
            bull_args_dict.update(_entry["symbols"])

    bear_args_dict = {}
    for _entry in _all_bear_entries:
        if isinstance(_entry, dict) and _entry.get("symbols"):
            bear_args_dict.update(_entry["symbols"])

    symbols = state.get("selected_symbols", [])
    scan_dir = state.get("judge_direction", {}).get("direction", "neutral")

    # ── 构建品种实际价格表（来自扫描数据，作为entry_price基准） ──
    scan_data = state.get("scan_results", {})
    all_ranked = scan_data.get("all_ranked", []) if isinstance(scan_data, dict) else []
    sym_prices = {}
    for item in all_ranked:
        sym = item.get("symbol", "").upper()
        if sym not in sym_prices:
            price = item.get("price", 0)
            atr_val = item.get("atr", 0)
            sym_prices[sym] = {"price": price, "atr": atr_val}

    debate_context_lines = []
    for sym in symbols:
        bull = bull_args_dict.get(sym, {})
        bear = bear_args_dict.get(sym, {})
        bull_text = bull.get("arguments", []) if isinstance(bull, dict) else []
        bear_text = bear.get("arguments", []) if isinstance(bear, dict) else []
        sp = sym_prices.get(sym.upper(), {})
        price_hint = f"  【实际行情】当前收盘价={sp.get('price', '?')}  ATR={sp.get('atr', '?')}" if sp.get("price") else ""
        debate_context_lines.append(
            f"\n==={sym}==={price_hint}\n"
            f"多头论据: {bull_text}\n"
            f"空头论据: {bear_text}"
        )
    debate_context = "\n".join(debate_context_lines)

    # ── 价格参考表（结构化数据，LLM无法忽略） ──
    price_table_lines = ["品种 | 当前收盘价 | ATR | 数技源方向 | 信号强度"]
    price_table_lines.append("-" * 60)
    for sym in symbols:
        sp = sym_prices.get(sym.upper(), {})
        p = sp.get("price", "N/A")
        a = sp.get("atr", "N/A")
        sdir = scan_dir
        sscore = ""
        for item in all_ranked:
            if item.get("symbol", "").upper() == sym.upper():
                sdir = item.get("direction", scan_dir)
                sscore = str(abs(item.get("total", 0)))
                break
        price_table_lines.append(f"{sym} | {p} | {a} | {sdir} | {sscore}")
    price_table = "\n".join(price_table_lines)

    # ── FDC 技术指标基准表（供闫判官数据复核用） ──
    fdc_data = state.get("fdc_data", {}) or {}
    indicator_lines = ["品种 | RSI | ADX | CCI | MACD柱 | 多空排列", "-" * 60]
    for sym in symbols:
        sym_up = sym.upper()
        sd = fdc_data.get(sym_up) or fdc_data.get(sym) or {}
        ind_vals = (sd.get("indicators") or {}).get("values", {}) if sd else {}
        def _gv(name):
            v = ind_vals.get(name)
            if isinstance(v, list) and v: return f"{v[-1]:.2f}"
            if isinstance(v, (int, float)): return f"{v:.2f}"
            return "N/A"
        rsi_v = _gv("RSI14")
        adx_v = _gv("ADX")
        cci_v = _gv("CCI20")
        macd_dif = _gv("MACD_DIF")
        macd_dea = _gv("MACD_DEA")
        macd = f"{macd_dif}/{macd_dea}" if macd_dif != "N/A" and macd_dea != "N/A" else _gv("macd_hist")
        # 均线排列检查
        closes_20 = None
        bars = (sd.get("kline") or {}).get("bars", []) if sd else []
        if len(bars) >= 20:
            c20 = [float(b.get("close", 0)) for b in bars[-20:]]
            ma5, ma20 = sum(c20[-5:])/5, sum(c20[-20:])/20
            align = "多头" if ma5 > ma20 else "空头" if ma5 < ma20 else "粘合"
        else:
            align = "N/A"
        indicator_lines.append(f"{sym_up} | {rsi_v} | {adx_v} | {cci_v} | {macd} | {align}")
    fdc_indicator_table = "\n".join(indicator_lines)

    # ── P2.5 多因子信号一致性看板注入 ──
    factor_dashboard_text = ""
    try:
        fdb = state.get("factor_dashboard")
        if fdb is not None:
            from data_adapter.factors.dashboard import format_dashboard_for_prompt
            factor_dashboard_text = format_dashboard_for_prompt(fdb)
    except Exception:
        pass

    # ── G97: 连续合约复权价差校准（连续合约 vs 具体合约） ──
    price_adjustments = state.get("price_adjustments", {}) or {}
    adjustment_lines = ["品种 | 连续合约价 | 前月合约价 | 价差（正=连续<前月）"]
    adjustment_lines.append("-" * 60)
    has_adjustment = False
    for sym in symbols:
        adj = price_adjustments.get(sym.upper(), 0.0)
        if adj != 0.0:
            has_adjustment = True
            sp = sym_prices.get(sym.upper(), {})
            cont_price = sp.get("price", "N/A")
            front_price = (float(cont_price) + adj) if isinstance(cont_price, (int, float)) else "N/A"
            adjustment_lines.append(f"{sym} | {cont_price} | {front_price} | {adj:+.2f}")
    price_adjustment_table = "\n".join(adjustment_lines) if has_adjustment else ""

    # ── Phase 3: EvoMem 补丁记忆检索（按领域注入历史规则演化） ──
    patch_context_lines = []
    try:
        from memory.manager.manager import MemoryManager
        mm = MemoryManager()
        for sym in symbols:
            sym_up = sym.upper()
            # 查品种相关补丁
            sym_patches = mm.query_patches_by_version(f"品种|{sym_up}")
            # 查通用规则补丁
            rule_patches = mm.query_patches_by_version("规则")
            merged = sym_patches + rule_patches
            if merged:
                # 去重后取最近的 3 条
                seen_ids = set()
                recent = []
                for p in merged:
                    pid = p.get("patch_id", "")
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        recent.append(p)
                recent = recent[:3]
                for p in recent:
                    patch_context_lines.append(
                        f"  · [{p.get('domain','')}] {p.get('post_state','')[:120]}"
                    )
        if patch_context_lines:
            patch_context_lines.insert(0, "【EvoMem 补丁记忆 — 相关规则演化历史】")
    except Exception:
        pass

    patch_context = "\n".join(patch_context_lines) if patch_context_lines else ""


    context = f"""作为闫判官（裁决官），请基于以下全部辩论内容对每个品种给出最终裁决。

核心原则：
- **你的裁决完全基于辩论质量，可以且应当推翻数技源的扫描方向**
- 数技源扫描参考方向: {scan_dir} — 这仅作参考，你可以推翻
- 如果空头论据更扎实 裁决空头（即使数技源方向为多头）
- 如果多头论据更扎实 裁决多头（即使数技源方向为空头）
- 双方论证均不充分 裁决 neutral / 低仓位
- 输出完整交易参数

⚠️ 数据真实性复核：辩论双方（多头/空头分析员）可能引用技术指标数值来支持论据。
**你必须以以下 FDC 实际计算指标为基准，交叉验证双方引用的数字是否准确**。
如果一方引用了严重偏离真实值的指标（如声称 RSI=50 但实际 RSI=22.6），
该方的可信度应被降低，并在裁决理由中注明"数据引用错误"。

【FDC 实际技术指标（基准事实）】
{fdc_indicator_table}

{patch_context}

【连续合约复权价差校准（G97）】仅显示有价差的品种，价差用于校正连续合约 vs 具体合约的价格偏差。
{price_adjustment_table}

⚠️ 交易参数关键约束（P0 规则，不可违反）：
- **entry_price 必须严格等于【实际行情】中的当前收盘价**，不得有任何偏离
- 严禁使用挂单价/限价单/条件单：交易指令为**市价单（market order）**，不是限价单（limit/stop order）
- **entry_price 必须在以下价格参考表中精确取值，不允许 LLM 自行计算或微调**
- **stop_loss_price 和 target_price 由系统根据 ATR 自动计算，LLM 无需输出**（只需输出 direction）
- 参考以下价格参考表（entry_price 必须从该表取值）：

{price_table}

以下为多轮攻防的全部辩论论据（多头立论空头立论空头反驳多头反驳空头最终多头最终）:

{debate_context}

【多因子信号一致性看板】
{factor_dashboard_text}

请以 JSON 格式返回逐品种裁决及交易参数，每个品种需标注"是否推翻数技源方向"。
**再次强调：entry_price 必须精确等于价格参考表中的当前收盘价，不得自行计算或微调，这是市价单，不是挂单价。**
**stop_loss_price 和 target_price 由系统根据 ATR 自动计算，LLM 无需输出这些字段。**

**新增要求（Phase B 最小关键证据集）：**
- 每个品种的 `reason` 中需包含 **核心推理路径**：明确标注哪些关键论据最终决定了裁决方向
- 在 `reason` 末尾附加 **如果-那么推理链**（If X then bull; If Y then bear; X>Y → final），格式为:
  `【推理链】如果{{条件A}}则看多；如果{{条件B}}则看空；{{条件A}}>{{条件B}}→最终方向`
- 可选输出 `key_evidence_points` 数组，列出 2-4 条对方向判断最具影响力的证据

{{"per_symbol": {{
    "RB": {{"direction": "bearish", "confidence": 0.8, "reason": "裁决理由（引用辩论中的关键论据）。【推理链】如果需求走弱则看空；如果库存去化则看多；需求走弱>库存去化→看空",
            "overturn_scan": true, "overturn_reason": "推翻数技源方向的理由",
            "entry_price": <从价格参考表取当前收盘价>,
            "position_pct": 5, "contract": "RB2410", "risk_reward_ratio": 3.0,
            "key_evidence_points": ["需求数据连续3周回落（探源）", "空头立论引用库存高位（空头分析员）"]}}
  }},
  "overall_direction": "bearish/neutral/bullish",
  "overall_confidence": 0.75,
  "overall_reason": "总体摘要（总结哪方论证更优，是否推翻扫描方向）",
  "scan_overturned": true/false
}}"""

    context = _inject_memory_rules("judge", context)
    result = await judge.run(context, state["trace_id"])

    output = result.get("output", "")
    parsed = parse_llm_output(output, agent_name="judge")
    if parsed.get("success"):
        parsed_data = parsed["data"]
        per_symbol = parsed_data.get("per_symbol", {}) if isinstance(parsed_data, dict) else {}
    else:
        parsed_data = {}
        per_symbol = {}
        logger.warning(f"[VERDICT] parse_llm_output 失败: {parsed.get('errors', [])}")

    if per_symbol:
            validated_symbols = {}
            for sym in symbols:
                sym_key = sym.upper()
                sv = per_symbol.get(sym_key, per_symbol.get(sym, {}))
                if isinstance(sv, dict) and sv.get("direction"):
                    sv.setdefault("entry_price", sv.get("price", 0))
                    sv.setdefault("stop_loss_price", sv.get("stop_loss", 0))
                    sv.setdefault("target_price", sv.get("target", 0))
                    sv.setdefault("position_pct", sv.get("position_pct", 3))
                    sv.setdefault("contract", sv.get("contract", ""))
                    sv.setdefault("risk_reward_ratio", sv.get("risk_reward_ratio", 0))
                    sv.setdefault("confidence", sv.get("confidence", 0.5))
                    # 强制 entry_price = 实际扫描价格（杜绝挂单价）
                    sp = sym_prices.get(sym_key, {})
                    scan_price = sp.get("price", 0)
                    if scan_price > 0:
                        sv["entry_price"] = scan_price
                    # G97: 连续合约复权价差校准 — 调整 entry_price 至具体合约价格
                    price_adjustments = state.get("price_adjustments", {}) or {}
                    adjustment = price_adjustments.get(sym_key, 0.0)
                    if adjustment != 0.0 and scan_price > 0:
                        adjusted_price = round(scan_price + adjustment, 2)
                        sv["entry_price"] = adjusted_price
                        logger.info("[G97] %s 价差校准: %s + %s = %s", sym_key, scan_price, adjustment, adjusted_price)
                    # 代码计算 stop_loss/target（L0 硬约束，覆写 LLM 输出）
                    direction = sv.get("direction", "neutral")
                    atr_val = sp.get("atr", 0)
                    entry_for_st = sv.get("entry_price", scan_price) or scan_price
                    stop_loss, target = _compute_stop_target(direction, entry_for_st, atr_val)
                    sv["stop_loss_price"] = stop_loss
                    sv["target_price"] = target
                    # 仓位代码硬校验（L0 硬约束）
                    sv["position_pct"] = _clamp_position(sym_key, sv.get("position_pct", 3))
                    validated_symbols[sym] = sv

            # 计算 overall confidence：优先用 LLM 的 overall_confidence，回退到 per_symbol 均值
            overall_conf = parsed_data.get("overall_confidence", None) if isinstance(parsed_data, dict) else None
            if overall_conf is None and validated_symbols:
                confs = [sv.get("confidence", 0.5) for sv in validated_symbols.values() if isinstance(sv, dict)]
                overall_conf = sum(confs) / len(confs) if confs else 0.5
            elif overall_conf is None:
                overall_conf = 0.5
            overall = {
                "direction": parsed.get("overall_direction", "neutral"),
                "confidence": overall_conf,
                "reason": parsed.get("overall_reason", output[:200]),
                "per_symbol": validated_symbols,
            }
            if validated_symbols:
                new_phases = state["completed_phases"] + ["P4_verdict"]
                return {
                    **state,
                    "verdict": overall,
                    "current_phase": "P4_verdict",
                    "completed_phases": new_phases
                }

    # Fallback: single verdict (enforce_structured_output 失败或无品种数据时)
    # v9.20.3+: 使用 auto_fix_json 处理 markdown 代码块等格式，并尝试提取 per_symbol
    try:
        if "{" in output and "}" in output:
            from scripts.enforce_structured_output import auto_fix_json
            fixed = auto_fix_json(output)
            verdict_raw = json.loads(fixed)
            verdict_raw.setdefault("entry_price", verdict_raw.get("price", 0))
            verdict_raw.setdefault("stop_loss_price", verdict_raw.get("stop_loss", 0))
            verdict_raw.setdefault("target_price", verdict_raw.get("target", 0))
            verdict_raw.setdefault("position_pct", verdict_raw.get("position_pct", 3))
            verdict_raw.setdefault("contract", verdict_raw.get("contract", ""))
            verdict_raw.setdefault("risk_reward_ratio", verdict_raw.get("risk_reward_ratio", 0))
            verdict_raw.setdefault("direction", verdict_raw.get("verdict", verdict_raw.get("direction", "neutral")))
            # 尝试从 fallback JSON 提取 per_symbol 数据
            fb_per_symbol = verdict_raw.get("per_symbol", {})
            if isinstance(fb_per_symbol, dict) and fb_per_symbol:
                validated = {}
                for sym in symbols:
                    sym_key = sym.upper()
                    sv = fb_per_symbol.get(sym_key, fb_per_symbol.get(sym, {}))
                    if isinstance(sv, dict) and sv.get("direction"):
                        sv.setdefault("entry_price", sv.get("price", 0))
                        sv.setdefault("stop_loss_price", sv.get("stop_loss", 0))
                        sv.setdefault("target_price", sv.get("target", 0))
                        sv.setdefault("position_pct", sv.get("position_pct", 3))
                        sv.setdefault("contract", sv.get("contract", ""))
                        sv.setdefault("risk_reward_ratio", sv.get("risk_reward_ratio", 0))
                        sv.setdefault("confidence", sv.get("confidence", 0.5))
                        sp = sym_prices.get(sym_key, {})
                        scan_price = sp.get("price", 0)
                        if scan_price > 0:
                            sv["entry_price"] = scan_price
                        # G97: 连续合约复权价差校准 — 调整 entry_price 至具体合约价格
                        fb_price_adjustments = state.get("price_adjustments", {}) or {}
                        fb_adjustment = fb_price_adjustments.get(sym_key, 0.0)
                        if fb_adjustment != 0.0 and scan_price > 0:
                            adjusted_price = round(scan_price + fb_adjustment, 2)
                            sv["entry_price"] = adjusted_price
                            logger.info("[G97-fallback] %s 价差校准: %s + %s = %s", sym_key, scan_price, fb_adjustment, adjusted_price)
                        # 代码计算 stop_loss/target（L0 硬约束，覆写 LLM 输出）
                        direction = sv.get("direction", "neutral")
                        atr_val = sp.get("atr", 0)
                        fb_entry = sv.get("entry_price", scan_price) or scan_price
                        stop_loss, target = _compute_stop_target(direction, fb_entry, atr_val)
                        sv["stop_loss_price"] = stop_loss
                        sv["target_price"] = target
                        # 仓位代码硬校验（L0 硬约束）
                        sv["position_pct"] = _clamp_position(sym_key, sv.get("position_pct", 3))
                        validated[sym] = sv
                if validated:
                    # 计算 fallback 路径的 overall confidence
                    fb_conf = verdict_raw.get("overall_confidence", verdict_raw.get("confidence", None))
                    if fb_conf is None and validated:
                        fb_confs = [sv.get("confidence", 0.5) for sv in validated.values() if isinstance(sv, dict)]
                        fb_conf = sum(fb_confs) / len(fb_confs) if fb_confs else 0.5
                    elif fb_conf is None:
                        fb_conf = 0.5
                    return {
                        **state,
                        "verdict": {
                            "direction": verdict_raw.get("direction", "neutral"),
                            "confidence": fb_conf,
                            "reason": verdict_raw.get("reason", output[:200]),
                            "per_symbol": validated,
                        },
                        "current_phase": "P4_verdict",
                        "completed_phases": state["completed_phases"] + ["P4_verdict"],
                    }
        else:
            verdict_raw = {"direction": "neutral", "reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse verdict output: {e}")
        verdict_raw = {"direction": "neutral", "reason": output}

    verdict = {
        "direction": verdict_raw.get("direction", "neutral"),
        "reason": verdict_raw.get("reason", output[:200]),
        "per_symbol": {},
    }

    # v9.3.0: 标准化裁决字段（field_normalizer 已随 FDC 退役，直接传递）

    new_phases = state["completed_phases"] + ["P4_verdict"]
    return {
        **state,
        "verdict": verdict,
        "current_phase": "P4_verdict",
        "completed_phases": new_phases
    }




async def node_right_side_check(state: DebateState) -> DebateState:
    """G98: 右侧交易校验 — 反趋势方向且趋势结构未破坏时降级为INFO。

    如果裁决方向与短期趋势相反，且趋势结构未被破坏，
    则将方向降级为 neutral（观望），清空入场/目标/止损参数。

    Returns:
        DebateState，verdict 中的 per_symbol 可能被降级。
    """
    verdict = state.get("verdict", {})
    per_symbol = (verdict or {}).get("per_symbol", {})
    fdc_data = state.get("fdc_data", {}) or {}
    downgraded_symbols = []

    for sym_key, sv in per_symbol.items():
        if not isinstance(sv, dict):
            continue
        direction = sv.get("direction", "neutral")
        if direction in ("neutral", None, ""):
            continue  # neutral 方向不检查

        # ── 从 FDC 数据确定短期趋势 ──
        sym_up = sym_key.upper()
        sd = fdc_data.get(sym_up) or fdc_data.get(sym_key) or {}
        bars = (sd.get("kline") or {}).get("bars", []) if sd else []

        if len(bars) < 20:
            continue  # 数据不足，跳过检查

        closes = [float(b.get("close", 0)) for b in bars[-20:]]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20

        # ── 判断短期趋势方向 ──
        if ma5 > ma20 * 1.005:
            trend = "bullish"  # 多头排列
        elif ma5 < ma20 * 0.995:
            trend = "downtrend"  # 空头排列
        else:
            continue  # 粘合无趋势，跳过

        # ── 检查是否反趋势 ──
        is_counter_trend = (direction == "bearish" and trend == "bullish") or \
                           (direction == "bullish" and trend == "downtrend")

        if not is_counter_trend:
            continue  # 顺趋势或横盘，通过

        # ── 检查趋势结构是否被破坏 ──
        # 趋势未破坏 = 最近 N 根 K 线未突破趋势线
        # 多头趋势: 无收盘价 < MA20
        # 空头趋势: 无收盘价 > MA20
        structure_broken = False
        for b in bars[-3:]:
            c = float(b.get("close", 0))
            if trend == "bullish" and c < ma20 * 0.99:
                structure_broken = True
                break
            if trend == "downtrend" and c > ma20 * 1.01:
                structure_broken = True
                break

        if structure_broken:
            continue  # 趋势结构已破坏，放行

        # ── 趋势结构未破坏 + 反趋势 → 降级为 INFO ──
        sv["direction"] = "neutral"
        sv["grade"] = "INFO"
        sv["entry_price"] = None
        sv["stop_loss_price"] = None
        sv["target_price"] = None
        sv["position_pct"] = 0
        sv["right_side_downgraded"] = True
        sv["right_side_reason"] = (
            f"反趋势方向被右侧交易铁律降级：裁决方向={direction}，"
            f"短期趋势={'多头' if trend == 'bullish' else '空头'}（MA5={ma5:.2f}, MA20={ma20:.2f}），"
            f"趋势结构未破坏，仅允许 INFO（仅供关注）。"
        )
        downgraded_symbols.append(sym_key)
        logger.info(
            "[G98] %s 右侧交易降级: %s → neutral (趋势=%s, MA5=%.2f, MA20=%.2f)",
            sym_key, direction, trend, ma5, ma20,
        )

    if downgraded_symbols:
        logger.warning("[G98] 右侧交易降级品种: %s", downgraded_symbols)

    # 如果整体方向由被降级品种主导，调整 overall
    if verdict and downgraded_symbols:
        remaining_directions = [
            v.get("direction", "neutral") for v in per_symbol.values()
            if isinstance(v, dict) and not v.get("right_side_downgraded", False)
        ]
        if remaining_directions:
            bull_count = sum(1 for d in remaining_directions if d == "bullish")
            bear_count = sum(1 for d in remaining_directions if d == "bearish")
            if bull_count > bear_count:
                verdict["direction"] = "bullish"
            elif bear_count > bull_count:
                verdict["direction"] = "bearish"
            else:
                verdict["direction"] = "neutral"
        else:
            verdict["direction"] = "neutral"

    new_phases = state["completed_phases"] + ["P4_right_side_check"]
    return {
        **state,
        "verdict": verdict,
        "current_phase": "P4_right_side_check",
        "completed_phases": new_phases,
    }


async def node_risk_check(state: DebateState) -> DebateState:
    from fdt_langgraph._nodes_output import _write_signal_report
    _ensure_llm_key()
    risk_manager = FdtAgentExecutor("risk_manager")

    verdict = state.get("verdict", {})
    fdc_data = state.get("fdc_data", {}) or {}
    symbols = state.get("selected_symbols", [])
    # FDC技术指标基准表
    ind_lines = ["品种 | RSI | ADX | CCI | 均线排列", "-" * 60]
    for sym in symbols:
        sym_up = sym.upper()
        sd = fdc_data.get(sym_up) or fdc_data.get(sym) or {}
        iv = (sd.get("indicators") or {}).get("values", {}) if sd else {}
        def _gv(n):
            v = iv.get(n)
            if isinstance(v, list) and v:
                return f"{v[-1]:.2f}"
            if isinstance(v, (int, float)):
                return f"{v:.2f}"
            return "N/A"
        bars = (sd.get("kline") or {}).get("bars", []) if sd else []
        if len(bars) >= 20:
            c20 = [float(b.get("close", 0)) for b in bars[-20:]]
            ma5 = sum(c20[-5:]) / 5
            ma20 = sum(c20[-20:]) / 20
            align = "多头" if ma5 > ma20 else "空头" if ma5 < ma20 else "粘合"
        else:
            align = "N/A"
        ind_lines.append(f"{sym_up} | {_gv('rsi')} | {_gv('adx')} | {_gv('cci')} | {align}")
    fdc_ind_table = "\n".join(ind_lines)
    context = f"""作为风控经理（风控明），请基于以下裁决和实际市场数据审核风险。

核心职责包括：
1. **数据真实性复核** — 以下方FDC实际技术指标为基准，验证裁决中的方向判断是否与客观指标一致
2. 标准风控检查 — 杠杆、保证金占用、止损比例、仓位
3. 市场状态校验 — 如果RSI极高/极低但裁决方向与之矛盾，应标注警告

【FDC实际技术指标（基准事实）】
{fdc_ind_table}

裁决: {verdict}

请以JSON格式返回风控审核结果，含风险等级判断和定性点评：
{{"approved": true, "risk_level": "low/medium/high", "risk_color": "green/yellow/red",
  "max_position": 2, "warnings": ["警告1", "警告2"],
  "entry_price_check": true, "stop_loss_check": true, "position_pct_check": true,
  "risk_commentary": "定性点评（100-300字，说明为什么给这个风险评级、最关注什么矛盾、裁决是否合理）",
  "key_concerns": ["最关注的风险点1", "风险点2", "风险点3"]}}"""
    # ── 调用风险经理 LLM ──
    context = _inject_memory_rules("risk_manager", context)
    try:
        result = await risk_manager.run(context, state["trace_id"])
        output = result.get("output", "")
        # v9.22.2: 使用 parse_llm_output 统一入口
        parsed = parse_llm_output(output, agent_name="risk_manager",
                                  default={"approved": True, "risk_level": "low", "risk_color": "yellow"})
        if parsed.get("success"):
            risk_check = parsed["data"]
        else:
            risk_check = {"approved": True, "risk_level": "low", "risk_color": "yellow", "warnings": [f"LLM解析失败: {parsed.get('errors', [])}"]}
    except Exception as e:
        logger.warning(f"[RISK] 风控LLM解析失败: {e}, 使用默认yellow")
        risk_check = {"approved": True, "risk_level": "low", "risk_color": "yellow", "warnings": [f"LLM解析异常: {e}"]}
    """P6a: CTP 信号输出"""
    verdict = state.get("verdict", {})

    risk_color = risk_check.get("risk_color", "red")

    # Build per-symbol signals from scan data's all_actionable items
    scan_results = state.get("scan_results", {})
    all_ranked = scan_results.get("all_ranked", [])
    actionable_signals = []
    for item in all_ranked:
        raw_dir = item.get("direction", "")
        total = item.get("total", 0)
        if raw_dir in ("bull", "BUY", "buy") and abs(total) >= 60:
            actionable_signals.append({
                "symbol": item.get("symbol", item.get("pid", "")),
                "direction": "BUY",
                "entry_price": item.get("price", 0),
                "order_type": "market",
                "score": abs(total),
            })
        elif raw_dir in ("bear", "SELL", "sell") and abs(total) >= 60:
            actionable_signals.append({
                "symbol": item.get("symbol", item.get("pid", "")),
                "direction": "SELL",
                "entry_price": item.get("price", 0),
                "order_type": "market",
                "score": abs(total),
            })
    actionable_signals.sort(key=lambda x: x["score"], reverse=True)

    # v9.23.1: CTP信号关联selected_symbols
    # - selected_symbols非空时，仅输出已辩论品种的信号
    # - selected_symbols为空时（无品种通过初选），清空信号
    selected_syms = state.get("selected_symbols", [])
    if selected_syms:
        selected_lower = set(s.lower() for s in selected_syms)
        actionable_signals = [s for s in actionable_signals if s.get("symbol", "").lower() in selected_lower]
    else:
        actionable_signals = []

    best_buy = next((s for s in actionable_signals if s["direction"] == "BUY"), None)
    best_sell = next((s for s in actionable_signals if s["direction"] == "SELL"), None)

    signal_output = {
        "trace_id": state.get("trace_id", ""),
        "risk_color": risk_color,
        "risk_check": risk_check,
        "status": "blocked" if risk_color == "red" else "sent",
        "message": "",
        "signals": actionable_signals[:10],  # top 10 signals
    }

    risk_colors_order = {"green": 0, "yellow": 1, "red": 2}
    threshold = os.environ.get("FDT_RISK_THRESHOLD", "yellow")
    current_level = risk_colors_order.get(risk_color, 2)
    threshold_level = risk_colors_order.get(threshold, 1)

    if current_level > threshold_level:
        signal_output["message"] = f"风控{risk_color}未通过阈值{threshold}，{len(actionable_signals)}个潜在信号已阻断"
    else:
        signal_output["status"] = "sent"
        if best_buy or best_sell:
            signal_output["message"] = (
                f"风控{risk_color}通过阈值{threshold}，共{len(actionable_signals)}个可执行信号"
                f"{'，最强做多:' + best_buy['symbol'] if best_buy else ''}"
                f"{'，最强做空:' + best_sell['symbol'] if best_sell else ''}"
            )
        else:
            signal_output["message"] = f"风控{risk_color}通过阈值{threshold}，无评分≥60的强信号"
        if best_buy:
            signal_output["signal"] = {
                "direction": "BUY",
                "symbol": best_buy["symbol"],
                "entry_price": best_buy["entry_price"],
                "order_type": "market",
                "stop_loss_price": best_buy["entry_price"] * 0.97,
                "target_price": best_buy["entry_price"] * 1.05,
                "position_pct": 3,
                "contract": "",
                "risk_reward_ratio": 2.0,
                "confidence": min(1.0, best_buy["score"] / 100),
            }
        elif best_sell:
            signal_output["signal"] = {
                "direction": "SELL",
                "symbol": best_sell["symbol"],
                "entry_price": best_sell["entry_price"],
                "order_type": "market",
                "stop_loss_price": best_sell["entry_price"] * 1.03,
                "target_price": best_sell["entry_price"] * 0.95,
                "position_pct": 3,
                "contract": "",
                "risk_reward_ratio": 2.0,
                "confidence": min(1.0, best_sell["score"] / 100),
            }

    new_phases = state["completed_phases"] + ["P6a"]

    # v9.12.0: CTP 信号扫描报告 (P6a 阶段) — 仅 FDT_GENERATE_INTERMEDIATE_REPORTS=true 时生成
    signal_report_path = None
    if os.environ.get("FDT_GENERATE_INTERMEDIATE_REPORTS", "").lower() == "true":
        try:
            report_dir = _resolve_report_dir()
            _signals_list_ = signal_output.get("signals", [])
            signal_report_path = _write_signal_report(state["trace_id"], signal_output, report_dir, signals_list=_signals_list_)
            logger.info(f"[SIGNAL] CTP 信号扫描报告: {signal_report_path}")
        except Exception as e:
            logger.warning(f"[SIGNAL] CTP 信号扫描报告生成失败: {e}")
    else:
        logger.debug("[SIGNAL] CTP 信号扫描报告跳过 (FDT_GENERATE_INTERMEDIATE_REPORTS 未设置)")

    return {
        **state,
        "signal_output": signal_output,
        "signal_report_path": signal_report_path,
        "current_phase": "P6a",
        "completed_phases": new_phases
    }




async def node_quality_inspect(state: DebateState) -> DebateState:
    """品藻质检节点（Phase 3 Data Governance）。

    校验当前品种的 P4 裁决 + P5 风控数据质量。
    不合格 + 重试未超限 → 退回重修；通过或超限 → 存入结果。
    品藻仅输出 PASS/FAIL，退回/跳过由 LangGraph 条件边决定。
    """
    from fdt_langgraph.quality_inspector import validate_risk, validate_verdict

    # 使用 _original_symbols 而非 selected_symbols 定位当前品种（修复: per-symbol循环symbol丢失）
    symbols = state.get("_original_symbols", state.get("selected_symbols", []))
    idx = state.get("symbol_index", -1)
    current_sym = symbols[idx] if 0 <= idx < len(symbols) else ""
    counters = dict(state.get("rework_counters", {}))
    timings = list(state.get("phase_timings", []))
    retries = counters.get(current_sym, 0)

    # G19: 无选定品种时跳过质检（不制造 FAIL 噪音）
    if not current_sym or not symbols:
        quality_report = {
            "symbol": current_sym,
            "status": "SKIP",
            "issues": [],
            "verdict_report": {"status": "SKIP", "issues": [], "passed": 0, "failed": 0, "skipped": 1},
            "risk_report": {"status": "SKIP", "issues": [], "passed": 0, "failed": 0, "skipped": 1},
            "retry_count": retries,
        }
        timings.append({
            "phase": "quality_inspect",
            "symbol": current_sym,
            "elapsed_seconds": 0.0,
            "retry_count": retries,
            "status": "SKIP",
        })
        logger.info(f"[质检] 无选定品种，跳过质检 (symbol={current_sym!r}, symbols={symbols})")
        return {
            **state,
            "quality_report": quality_report,
            "rework_counters": counters,
            "phase_timings": timings,
            "current_phase": "P3.5",
            "completed_phases": state["completed_phases"] + ["P3.5"],
        }

    # ── 质检裁决 ──
    verdict = state.get("verdict")
    if verdict and isinstance(verdict, dict) and verdict.get("direction"):
        vr_report = validate_verdict(verdict)
    else:
        vr_report = {"status": "SKIP", "issues": [], "passed": 0, "failed": 0, "skipped": 1}

    # ── 质检风控 ──
    risk = state.get("risk_check")
    if risk and isinstance(risk, dict) and (risk.get("risk_level") or risk.get("risk_color")):
        rr_report = validate_risk(risk)
    else:
        rr_report = {"status": "SKIP", "issues": [], "passed": 0, "failed": 0, "skipped": 1}

    # ── 合并结果 ──
    all_issues = (vr_report.get("issues", []) if isinstance(vr_report, dict) else []) \
                 + (rr_report.get("issues", []) if isinstance(rr_report, dict) else [])
    total_failed = (vr_report.get("failed", 0) if isinstance(vr_report, dict) else 0) \
                   + (rr_report.get("failed", 0) if isinstance(rr_report, dict) else 0)
    overall_status = "FAIL" if total_failed > 0 else "PASS"

    quality_report = {
        "symbol": current_sym,
        "status": overall_status,
        "issues": all_issues,
        "verdict_report": vr_report,
        "risk_report": rr_report,
        "retry_count": retries,
    }

    # ── 更新重试计数器 ──
    if overall_status == "FAIL":
        counters[current_sym] = retries + 1
        logger.warning(f"[质检] {current_sym} 裁决/风控质检 FAIL (重试 {retries + 1}/2): {[i['message'] for i in all_issues[:3]]}")
    else:
        logger.info(f"[质检] {current_sym} 裁决/风控质检 PASS")

    # ── D6 Output: 审计日志 ──
    try:
        from scripts.output_audit import OutputAudit
        audit = OutputAudit()
        audit.log_output(
            agent_name="quality_assurance",
            action="review",
            output={"symbol": current_sym or "unknown", "status": overall_status,
                    "retry_count": retries, "issues_count": len(all_issues)},
        )
    except Exception:
        pass

    # ── 记录耗时 ──
    timings.append({
        "phase": "quality_inspect",
        "symbol": current_sym,
        "elapsed_seconds": 0.0,
        "retry_count": retries,
        "status": overall_status,
    })

    return {
        **state,
        "quality_report": quality_report,
        "rework_counters": counters,
        "phase_timings": timings,
        "current_phase": "P3.5",
        "completed_phases": state["completed_phases"] + ["P3.5"],
    }




async def node_store_per_symbol_result(state: DebateState) -> DebateState:
    """P4-per-symbol: 将当前品种的裁决/风控结果存入 per_symbol_results，递增索引"""
    symbols = state.get("_original_symbols", [])
    current_sym_idx = state.get("symbol_index", 0)

    # G19 修复: 使用 _original_symbols[idx] 替代 selected_symbols[0]，避免空列表越界
    if not symbols or current_sym_idx < 0 or current_sym_idx >= len(symbols):
        logger.warning("G19 修复: node_store_per_symbol_result 无有效品种(symbols=%s, idx=%s)，跳过存储", symbols, current_sym_idx)
        return {
            **state,
            "symbol_index": current_sym_idx + 1,
            "current_phase": "P4_skip_no_symbol",
            "completed_phases": state["completed_phases"] + ["P4_skip_no_symbol"],
        }

    current_sym = symbols[current_sym_idx]

    # 收集本品种的关键数据
    per_symbol = dict(state.get("per_symbol_results", {}))

    sym_result = {
        "fdc_data": {current_sym: state.get("fdc_data", {}).get(current_sym, {})},
        "research_data": state.get("research_data"),
        "chain_analysis": state.get("chain_analysis"),
        "technical_data": state.get("technical_data"),
        "fundamental_data": state.get("fundamental_data"),
        "sentiment_data": state.get("sentiment_data"),
        "bullish_arguments": state.get("bullish_arguments"),
        "bearish_arguments": state.get("bearish_arguments"),
        "bearish_rebuttal_arguments": state.get("bearish_rebuttal_arguments"),
        "bullish_rebuttal_arguments": state.get("bullish_rebuttal_arguments"),
        "bear_final_arguments": state.get("bear_final_arguments"),
        "bull_final_arguments": state.get("bull_final_arguments"),
        "verdict": state.get("verdict"),
        "risk_check": state.get("risk_check"),
        "signal_output": state.get("signal_output"),
    }
    per_symbol[current_sym] = sym_result

    next_idx = current_sym_idx + 1
    return {
        **state,
        "per_symbol_results": per_symbol,
        "symbol_index": next_idx,
        "current_phase": f"P4_{current_sym}_stored",
        "completed_phases": state["completed_phases"] + [f"P4_{current_sym}_stored"],
    }




def node_route_next_symbol(state: DebateState) -> str:
    """路由：还有品种未处理 → 回到 prepare_one_symbol；全部完成 → aggregate_results"""
    symbols = state.get("_original_symbols", [])
    idx = state.get("symbol_index", 0)
    if idx < len(symbols):
        return "prepare_one_symbol"
    return "aggregate_results"




async def node_aggregate_results(state: DebateState) -> DebateState:
    """P5-per-symbol: 恢复完整品种列表，从 per_symbol_results 重建最终状态"""
    original_symbols = list(state.get("_original_symbols", []))
    per_symbol = state.get("per_symbol_results", {})

    # 从第一个有数据的品种恢复 research_data
    research_data = None
    for sym in original_symbols:
        sr = per_symbol.get(sym, {})
        if sr.get("research_data"):
            research_data = sr["research_data"]
            break

    # 合并各品种的裁决/风控
    combined_verdict = {"direction": "neutral", "per_symbol": {}, "reason": ""}
    combined_risk = {"approved": True, "risk_level": "low", "risk_color": "green", "warnings": []}
    reasons = []

    for sym in original_symbols:
        sr = per_symbol.get(sym, {})
        v = sr.get("verdict", {})
        r = sr.get("risk_check", {})
        if v and isinstance(v, dict):
            ps = v.get("per_symbol", {})
            combined_verdict["per_symbol"].update(ps)
        if r:
            combined_risk = r

    # 从 per_symbol_results 重建完整的 research_data，包含所有品种的技术/基本面/情绪数据
    combined_tech = {}
    combined_fund = {}
    combined_sent = {}
    combined_chain = None
    combined_fdc = {}  # v9.23.1: 合并所有品种的 fdc_data，确保报告能提取 indicators
    for sym in original_symbols:
        sr = per_symbol.get(sym, {})
        rd = sr.get("research_data") or {}
        # 合并每个品种的 fdc_data（用于报告的 indicators 提取）
        sym_fdc = sr.get("fdc_data", {}) or {}
        if isinstance(sym_fdc, dict):
            combined_fdc.update(sym_fdc)
        if rd:
            t = rd.get("technical_data", {})
            if isinstance(t, dict):
                ts = t.get("per_symbol", {})
                if sym in ts or any(k.upper() == sym.upper() for k in ts):
                    combined_tech.update(ts)
                elif t.get("output"):
                    combined_tech[sym] = t
            f = rd.get("fundamental_data", {})
            if isinstance(f, dict):
                fs = f.get("per_symbol", {})
                if sym in fs or any(k.upper() == sym.upper() for k in fs):
                    combined_fund.update(fs)
            s = rd.get("sentiment_data", {})
            if s and isinstance(s, dict):
                combined_sent[sym] = s
            if not combined_chain:
                ch = rd.get("chain_analysis", {})
                if ch:
                    combined_chain = ch

    # 判断整体方向
    directions = set()
    for sym in original_symbols:
        ps = combined_verdict["per_symbol"].get(sym, {})
        if isinstance(ps, dict) and ps.get("direction"):
            directions.add(ps["direction"])
    combined_verdict["direction"] = "neutral" if len(directions) != 1 else directions.pop()

    # 重建含所有品种数据的 research_data
    rebuilt_research = {}
    if research_data:
        rebuilt_research = dict(research_data)
    if combined_tech:
        rebuilt_research["technical_data"] = {"per_symbol": combined_tech}
    if combined_fund:
        rebuilt_research["fundamental_data"] = {"per_symbol": combined_fund}
    if combined_sent:
        rebuilt_research["sentiment_data"] = combined_sent
    if combined_chain:
        rebuilt_research["chain_analysis"] = combined_chain

    return {
        **state,
        "selected_symbols": original_symbols,
        "research_data": rebuilt_research,
        "fdc_data": combined_fdc,  # v9.23.1: 保留所有品种的 fdc_data
        "technical_data": {"per_symbol": combined_tech} if combined_tech else {},
        "fundamental_data": {"per_symbol": combined_fund} if combined_fund else {},
        "verdict": combined_verdict,
        "risk_check": combined_risk,
        "current_phase": "P5_aggregate",
        "completed_phases": state["completed_phases"] + ["P5_aggregate"],
    }



