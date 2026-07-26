"""辩论阶段节点 — P4（六阶段攻防）。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fdt_langgraph.agents import FdtAgentExecutor
from fdt_langgraph.state import DebateState
from fdt_langgraph._nodes_utils import _ensure_llm_key, _inject_memory_rules, _trim_arguments, _truncate_arguments_text
from fdt_langgraph._nodes_context import _build_debate_context
from fdt_langgraph._nodes_prepare import node_prepare_data

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

async def node_prepare_one_symbol(state: DebateState) -> DebateState:
    """P2.5-per-symbol: 只准备 symbol_index 指向的单个品种的 FDC 数据，合并到已积累数据中"""
    symbols = state.get("_original_symbols", state.get("selected_symbols", []))
    idx = state.get("symbol_index", 0)
    if idx < 0 or idx >= len(symbols):
        return state

    current_sym = symbols[idx]
    existing_fdc = dict(state.get("fdc_data", {}) or {})

    # 调用现有的 node_prepare_data，但只传当前品种
    mini_state = {**state, "selected_symbols": [current_sym]}
    result = await node_prepare_data(mini_state)

    # 合并新旧 fdc_data（保留已积累的其他品种数据）
    new_fdc = result.get("fdc_data", {}) or {}
    result["fdc_data"] = {**existing_fdc, **new_fdc}
    # ── 辩论论据逐品种隔离：进入新品种前清空上一品种论据 ──
    result["bullish_arguments"] = []
    result["bearish_arguments"] = []
    result["bearish_rebuttal_arguments"] = []
    result["bullish_rebuttal_arguments"] = []
    result["bear_final_arguments"] = []
    result["bull_final_arguments"] = []
    result["debate_round"] = 0
    return result




def _parse_per_symbol_debate(result: dict, symbols: list) -> dict | None:
    """从LLM输出解析逐品种论据"""
    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            parsed = json.loads(output[start:end])
            per_symbol = parsed.get("per_symbol", {})
            validated = {}
            for sym in symbols:
                sym_key = sym.upper()
                if sym_key in per_symbol and isinstance(per_symbol[sym_key], dict):
                    validated[sym] = {
                        "arguments": per_symbol[sym_key].get("arguments", []),
                        "confidence": per_symbol[sym_key].get("confidence", 0.5),
                    }
            if validated:
                return validated
    except Exception:
        pass
    return None




async def node_bullish_v1(state: DebateState) -> DebateState:
    """P3 步1: 多头立论 — 多头分析员独立寻找做多理由"""
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state, current_symbol=symbols[0] if symbols else "")

    # 根治: v1 覆盖 system_prompt（去掉冗长 schema），API 层硬约束输出长度
    bullish.system_prompt = (
        "你是期货多头分析员，代表多头利益，独立寻找做多理由。"
        "禁止自行搜索数据。\n\n"
        "## 输出格式(严格遵守)\n"
        "每条论据\u2264100字，JSON整体\u22642000字。"
        "不输出 reasoning_chain/data_date/evidence 等字段。\n"
        '格式: {"per_symbol": {"品种": {"arguments": ["[来源] 论据"], "confidence": 0.7}}, "overall_summary": "..."}'
    )
    bullish.max_tokens = min(bullish.max_tokens, 2000)

    context = f"""你是多头分析员，代表多头利益，必须只从分析师资料中寻找做多理由。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考，你完全不受扫描方向限制）

研究数据（逐品种，带来源标记）:
{research_context}

这是辩论的**多头立论阶段（v1）**——你的职责：
1. 代表多头利益，基于研究员提供的资料寻找做多理由
2. 每条论据必须标注引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源] / [chain:链证源] / [scan:数技源]）
3. 引用的**所有数值数据**（价格、RSI、ADX、成交量、持仓量等）必须在研究数据中有明确来源，禁止自行生成数字——每个具体数值须标注来自哪位分析师
4. 按照 6 维度框架（趋势结构、量价关系、期限结构、产业链验证、基本面/市场情绪、风险点）组织论证
5. 每个品种至少构建3条支持多头的论据
6. 禁止使用 WebSearch/WebFetch 自行搜集数据

如果分析师资料中完全找不到做多理由，可以给出低置信度和"缺乏做多依据"的说明。

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["[technical:观澜] 论据1...", "[fundamental:探源] 论据2...", ...], "confidence": 0.7}},
    "CU": {{"arguments": ["[chain:链证源] 论据3...", "[scan:数技源] 论据4...", ...], "confidence": 0.6}}
  }},
  "overall_summary": "总体多头判断"
}}"""

    context = _inject_memory_rules("bullish_analyst", context)
    result = await bullish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bullish_v1"]
    return {
        **state,
        "bullish_arguments": [{"round": 1, "role": "bullish", "phase": "v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bullish_v1",
        "completed_phases": new_phases,
    }


async def node_bearish_v1(state: DebateState) -> DebateState:
    """P3 步2: 空头立论 — 空头分析员独立寻找做空理由（不再是对多头质疑）"""
    _ensure_llm_key()
    bearish = FdtAgentExecutor("bearish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state, current_symbol=symbols[0] if symbols else "")

    # 根治: v1 覆盖 system_prompt（同多头策略）
    bearish.system_prompt = (
        "你是期货空头分析员，代表空头利益，独立寻找做空理由。"
        "禁止自行搜索数据。\n\n"
        "## 输出格式(严格遵守)\n"
        "每条论据\u2264100字，JSON整体\u22642000字。"
        "不输出 reasoning_chain/data_date/evidence 等字段。\n"
        '格式: {"per_symbol": {"品种": {"arguments": ["[来源] 论据"], "confidence": 0.7}}, "overall_summary": "..."}'
    )
    bearish.max_tokens = min(bearish.max_tokens, 2000)

    context = f"""你是空头分析员，代表空头利益，独立从分析师资料中寻找做空理由。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考，你完全不受扫描方向限制）

研究数据（逐品种，带来源标记）:
{research_context}

这是辩论的**空头立论阶段（v1）**——你的职责：
1. 代表空头利益，独立从研究员提供的资料中寻找做空理由
2. 每条论据必须标注引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源] / [chain:链证源] / [scan:数技源]）
3. 引用的**所有数值数据**（价格、RSI、ADX、成交量、持仓量等）必须在研究数据中有明确来源，禁止自行生成数字——每个具体数值须标注来自哪位分析师
4. 按照 6 维度框架（趋势结构、量价关系、期限结构、产业链验证、基本面/市场情绪、风险点）组织论证
5. 每个品种至少构建3条支持空头的论据
6. 禁止引用多头论据，不做"反驳"——你与多头平级，独立产出
7. 禁止使用 WebSearch/WebFetch 自行搜集数据

如果分析师资料中完全找不到做空理由，可以给出低置信度和"缺乏做空依据"的说明。

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["[technical:观澜] 论据1...", "[fundamental:探源] 论据2...", ...], "confidence": 0.7}},
    "CU": {{"arguments": ["[chain:链证源] 论据3...", "[scan:数技源] 论据4...", ...], "confidence": 0.6}}
  }},
  "overall_summary": "总体空头判断"
}}"""

    context = _inject_memory_rules("bearish_analyst", context)
    result = await bearish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bearish_v1"]
    return {
        **state,
        "bearish_arguments": [{"round": 2, "role": "bearish", "phase": "v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bearish_v1",
        "completed_phases": new_phases,
    }



async def node_bearish_rebuttal(state: DebateState) -> DebateState:
    """P3 步3: 空头反驳多头立论 — 针对多头的做多论据进行反驳"""
    _ensure_llm_key()
    bearish = FdtAgentExecutor("bearish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state, current_symbol=symbols[0] if symbols else "")

    # 读取多头立论 bullish_arguments
    prev_bullish = state.get("bullish_arguments", [])
    bull_text = ""
    for entry in prev_bullish:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                conf = data.get("confidence", 0.5)
                args_text = '\n'.join(str(a) for a in args)
                bull_text += f"\n{sym} (置信度={conf}): {args_text}\n"

    context = f"""你是空头分析员，针对多头的做多论据进行反驳。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考）

研究数据（逐品种，带来源标记）:
{research_context}

【多头立论 v1 论据 — 请逐条反驳】
{_truncate_arguments_text(bull_text, "多头立论")}

这是辩论的**空头反驳阶段（bearish_rebuttal）**——
1. 对每个品种，逐条阅读多头的做多论据
2. 引用分析师资料中的数据做反证，拆解多头逻辑
3. 必须标注每条反驳引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源]）
4. 引用的**所有数值数据**必须在研究数据中有明确来源，禁止自行生成数字
5. 每个品种至少反驳2条多头论据
6. 禁止使用 WebSearch/WebFetch 自行搜集数据

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["驳[technical:观澜] 反驳1...", "驳[fundamental:探源] 反驳2..."], "confidence": 0.7}},
    "CU": {{"arguments": ["驳[chain:链证源] 反驳3...", "驳[scan:数技源] 反驳4..."], "confidence": 0.6}}
  }},
  "overall_summary": "反驳总体摘要"
}}"""

    result = await bearish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bearish_rebuttal"]
    return {
        **state,
        "bearish_rebuttal_arguments": [{"round": 3, "role": "bearish", "phase": "rebuttal_v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bearish_rebuttal",
        "completed_phases": new_phases,
    }


async def node_bullish_rebuttal(state: DebateState) -> DebateState:
    """P3 步4: 多头反驳 — 针对空头的做空论据和空头反驳进行再反驳"""
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state, current_symbol=symbols[0] if symbols else "")

    # 将空头立论和空头反驳注入上下文
    prev_bearish = state.get("bearish_arguments", [])
    bear_rebuttal = state.get("bearish_rebuttal_arguments", [])

    bear_text = ""
    for entry in prev_bearish:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                conf = data.get("confidence", 0.5)
                args_text = '\n'.join(str(a) for a in args)
                bear_text += f"\n{sym} (置信度={conf}): {args_text}\n"

    bear_rebuttal_text = ""
    for entry in bear_rebuttal:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                args_text = '\n'.join(str(a) for a in args)
                bear_rebuttal_text += f"\n{sym}: {args_text}\n"

    context = f"""你是多头分析员，针对空头的做空论据和反驳进行反驳。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考）

研究数据（逐品种，带来源标记）:
{research_context}

【空头立论 v1 论据】
{_truncate_arguments_text(bear_text, "空头立论")}

【空头反驳（对我的多头立论的质疑）】
{_truncate_arguments_text(bear_rebuttal_text, "空头反驳")}

这是辩论的**多头反驳阶段（bullish_rebuttal）**——
1. 针对空头立论中的做空论据，用研究员数据正面反驳
2. 针对空头反驳中的质疑，逐条回应
3. 每条反驳必须引用分析师资料中的数据并标注来源（如 [technical:观澜] / [fundamental:探源]）
4. 引用的**所有数值数据**必须在研究数据中有明确来源，禁止自行生成数字
5. 如果某条论据确实成立（证据不足），承认并降置信度
6. 禁止使用 WebSearch/WebFetch 自行搜集数据

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["[technical:观澜] 驳空头立论：...（反证数据）", "[fundamental:探源] 驳空头反驳：...（反证数据）"], "confidence": 0.7}},
    "CU": {{"arguments": ["[chain:链证源] 驳空头立论：...（反证数据）"], "confidence": 0.6}}
  }},
  "rebuttal_summary": "反驳总体摘要"
}}"""

    result = await bullish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bullish_rebuttal"]
    return {
        **state,
        "bullish_rebuttal_arguments": [{"round": 4, "role": "bullish", "phase": "rebuttal", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bullish_rebuttal",
        "completed_phases": new_phases,
    }





async def node_bear_final(state: DebateState) -> DebateState:
    """P3 步5: 空头最终陈述 — 整合空头立论+反驳，给出最终信心度"""
    _ensure_llm_key()
    bearish = FdtAgentExecutor("bearish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})

    # 整合空头所有论据
    bear_v1 = state.get("bearish_arguments", [])
    bear_rebuttal = state.get("bearish_rebuttal_arguments", [])

    bear_text = ""
    for entry in bear_v1:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                conf = data.get("confidence", 0.5)
                args_text = '\n'.join(str(a) for a in args)
                bear_text += f"\n{sym} (置信度={conf}): {args_text}\n"

    rebuttal_text = ""
    for entry in bear_rebuttal:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                args_text = '\n'.join(str(a) for a in args)
                rebuttal_text += f"\n{sym}: {args_text}\n"

    context = f"""你是空头分析员，做空头最终陈述。

品种列表: {symbols}
数技源参考方向: {judge_dir}

【我方立论 v1 论据汇总】
{_truncate_arguments_text(bear_text, "空头立论")}

【我方反驳多头立论汇总】
{_truncate_arguments_text(rebuttal_text, "空头反驳")}

这是辩论的**空头最终陈述阶段（bear_final）**——
1. 整合空头所有论据（每条论据保持来源标注格式），给出完整的空头立场汇总
2. 调整置信度并说明理由
3. 引用的**所有数值数据**必须在研究数据中有明确来源，禁止自行生成数字
4. 包含风险提示（做空可能面临的风险）
5. 禁止使用 WebSearch/WebFetch

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["最终论据1...", "最终论据2..."], "confidence": 0.7, "risk_note": "做空风险说明"}},
    "CU": {{"arguments": ["最终论据1...", "最终论据2..."], "confidence": 0.6, "risk_note": "做空风险说明"}}
  }},
  "final_summary": "空头最终陈述摘要"
}}"""

    result = await bearish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    state = _trim_arguments(state)
    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bear_final"]
    return {
        **state,
        "bear_final_arguments": [{"round": 5, "role": "bearish", "phase": "final", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bear_final",
        "completed_phases": new_phases,
    }




async def node_bull_final(state: DebateState) -> DebateState:
    """P3 步6: 多头最终陈述 — 整合多头立论+反驳，给出最终信心度"""
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})

    # 整合多头所有论据
    bull_v1 = state.get("bullish_arguments", [])
    bull_rebuttal = state.get("bullish_rebuttal_arguments", [])

    bull_text = ""
    for entry in bull_v1:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                conf = data.get("confidence", 0.5)
                args_text = '\n'.join(str(a) for a in args)
                bull_text += f"\n{sym} (置信度={conf}): {args_text}\n"

    rebuttal_text = ""
    for entry in bull_rebuttal:
        if isinstance(entry, dict) and entry.get("symbols"):
            for sym, data in entry["symbols"].items():
                args = data.get("arguments", [])
                args_text = '\n'.join(str(a) for a in args)
                rebuttal_text += f"\n{sym}: {args_text}\n"
    context = f"""你是多头分析员，做多头最终陈述。

品种列表: {symbols}
数技源参考方向: {judge_dir}

【我方立论 v1 论据汇总】
{_truncate_arguments_text(bull_text, "多头立论")}

【我方反驳空头论据及反驳汇总】
{_truncate_arguments_text(rebuttal_text, "多头反驳")}

这是辩论的**多头最终陈述阶段（bull_final）**——
1. 整合多头所有论据（每条论据保持来源标注格式），给出完整的做多立场汇总
2. 调整置信度并说明理由
3. 引用的**所有数值数据**必须在研究数据中有明确来源，禁止自行生成数字
4. 包含风险提示（做多可能面临的风险）
5. 禁止使用 WebSearch/WebFetch

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["最终论据1...", "最终论据2..."], "confidence": 0.7, "risk_note": "做多风险说明"}},
    "CU": {{"arguments": ["最终论据1...", "最终论据2..."], "confidence": 0.6, "risk_note": "做多风险说明"}}
  }},
  "final_summary": "多头最终陈述摘要"
}}"""

    result = await bullish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    state = _trim_arguments(state)
    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P3_bull_final"]
    return {
        **state,
        "bull_final_arguments": [{"round": 6, "role": "bullish", "phase": "final", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P3_bull_final",
        "completed_phases": new_phases,
    }

