import sys
import importlib.util
import os
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .state import DebateState
from .agents import FdtAgentExecutor
from typing import List, Dict, Optional

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

logger = logging.getLogger(__name__)

# 确保 FDT_LLM_API_KEY 环境变量传递到 Agent
def _ensure_llm_key():
    """确保 LLM API Key 在环境中"""
    if not os.environ.get("FDT_LLM_API_KEY"):
        # 尝试从 OPENAI_API_KEY 获取
        if os.environ.get("OPENAI_API_KEY"):
            os.environ["FDT_LLM_API_KEY"] = os.environ["OPENAI_API_KEY"]
            logger.info("[LLM] Using OPENAI_API_KEY as FDT_LLM_API_KEY")


def _import_from_skill(skill_dir: str, module_path: str, function_name: str):
    """从连字符目录名的 skill 中动态导入函数。

    Args:
        skill_dir: skill 目录名（如 'quant-daily'）
        module_path: 模块路径（如 'scripts/scan_all'）
        function_name: 要导入的函数名
    """
    full_path = _SKILLS_DIR / skill_dir / (module_path.replace("/", "\\") + ".py")
    spec = importlib.util.spec_from_file_location(module_path.replace("/", "."), full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {full_path}")
    mod = importlib.util.module_from_spec(spec)
    # 临时清除 sys.argv，防止模块级 argparse 解析 pytest 参数
    old_argv = sys.argv
    sys.argv = [str(full_path)]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return getattr(mod, function_name)


async def node_scan(state: DebateState) -> DebateState:
    import subprocess
    import sys
    import json
    from pathlib import Path

    existing_results = state.get("scan_results", {})
    if existing_results and existing_results.get("all_ranked"):
        print("[SCAN] 已有扫描结果，跳过重新扫描")
        return {**state, "current_phase": "P1", "completed_phases": ["P1"]}

    scan_script = _SKILLS_DIR / "quant-daily" / "scripts" / "scan_all.py"
    symbols = state.get("selected_symbols", [])
    cmd = [sys.executable, str(scan_script)]
    if symbols:
        cmd += ["--symbols", ",".join(symbols)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        scan_results = json.loads(result.stdout) if result.stdout else {}
    except Exception as e:
        scan_results = {"error": str(e)}
    return {**state, "scan_results": scan_results, "current_phase": "P1", "completed_phases": ["P1"]}


async def node_judge_direction(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    # 构造结构化的扫描结果摘要
    scan_summary = state.get("scan_results", {}).get("all_ranked", [])[:20]
    context = f"""基于以下扫描结果，判断当前市场趋势方向并选择值得辩论的品种：

扫描结果 TOP20（按信号强度排序）：
{scan_summary}

请以 JSON 格式返回：
1. direction: 市场整体方向 (bullish/bearish/neutral)
2. confidence: 置信度 (0-1)
3. symbols: 推荐辩论的品种列表（仅包含强烈信号的品种）
4. reason: 判断理由

返回 JSON 格式：
{{"direction": "bearish", "confidence": 0.8, "symbols": ["UR", "SA"], "reason": "多数品种空头信号强烈"}}
"""

    result = await judge.run(context, state["trace_id"])

    # 解析 LLM 输出
    output = result.get("output", "")
    import json
    try:
        # 尝试从输出中提取 JSON
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            verdict = json.loads(output[start:end])
        else:
            verdict = {"direction": "neutral", "symbols": [], "reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse judge output: {e}")
        verdict = {"direction": "neutral", "symbols": [], "reason": output}

    # 如果没有选出品种，使用触发品种
    selected_symbols = verdict.get("symbols", [])
    if not selected_symbols:
        selected_symbols = state.get("selected_symbols", [])

    dispatch_sources = verdict.get("dispatch_sources", ["chain", "technical", "fundamental"])

    new_phases = state["completed_phases"] + ["P2"]
    return {
        **state,
        "judge_direction": verdict,
        "selected_symbols": selected_symbols,
        "dispatch_sources": dispatch_sources,
        "current_phase": "P2",
        "completed_phases": new_phases
    }


async def node_chain(state: DebateState) -> dict:
    try:
        analyze_chain = _import_from_skill("commodity-chain-analysis", "scripts/chains", "analyze_chain")
        chain_data = analyze_chain(state["selected_symbols"]) if state["selected_symbols"] else {}
    except Exception as e:
        chain_data = {"error": str(e)}
    return {"chain_analysis": chain_data}


async def node_technical(state: DebateState) -> dict:
    _ensure_llm_key()
    technical = FdtAgentExecutor("technical_researcher")
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    context = f"分析品种: {state['selected_symbols']}, 方向: {direction}"
    tech_result = await technical.run(context, state["trace_id"])
    return {"technical_data": tech_result}


async def node_fundamental(state: DebateState) -> dict:
    _ensure_llm_key()
    fundamental = FdtAgentExecutor("fundamental_researcher")
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    context = f"分析品种: {state['selected_symbols']}, 方向: {direction}"
    fund_result = await fundamental.run(context, state["trace_id"])
    return {"fundamental_data": fund_result}


async def node_merge_research(state: DebateState) -> DebateState:
    merged_data = {
        "chain_analysis": state.get("chain_analysis", {}),
        "technical_data": state.get("technical_data", {}),
        "fundamental_data": state.get("fundamental_data", {}),
        "dispatch_sources": state.get("dispatch_sources", []),
    }
    new_phases = state["completed_phases"] + ["P3"]
    return {
        **state,
        "research_data": merged_data,
        "current_phase": "P3",
        "completed_phases": new_phases
    }


async def node_debate(state: DebateState) -> DebateState:
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")
    bearish = FdtAgentExecutor("bearish_analyst")

    research = state.get("research_data", {})
    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})

    context = f"""作为辩论分析师，请分析以下品种的投资机会：

品种: {symbols}
市场判断: {judge_dir}

研究数据:
- 技术面: {research.get('technical_data', {})}
- 基本面: {research.get('fundamental_data', {})}
- 产业链: {research.get('chain_analysis', {})}

请以 JSON 格式返回你的论据：
{{"arguments": ["论据1", "论据2", ...], "confidence": 0.7}}
"""

    bull_result = await bullish.run(context, state["trace_id"])
    bear_result = await bearish.run(context, state["trace_id"])

    # 解析 LLM 输出
    import json
    def parse_arguments(result):
        output = result.get("output", "")
        try:
            if "{" in output and "}" in output:
                start = output.find("{")
                end = output.rfind("}") + 1
                return json.loads(output[start:end]).get("arguments", [])
        except:
            pass
        return [output[:200]] if output else []

    bull_args = parse_arguments(bull_result)
    bear_args = parse_arguments(bear_result)

    new_phases = state["completed_phases"] + ["P4"]
    return {
        **state,
        "bullish_arguments": bull_args,
        "bearish_arguments": bear_args,
        "current_phase": "P4",
        "completed_phases": new_phases
    }


async def node_verdict(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    context = f"""作为裁决官，请基于以下辩论内容给出最终裁决：

多头论据: {state['bullish_arguments']}
空头论据: {state['bearish_arguments']}

请以 JSON 格式返回裁决：
{{"verdict": "bullish/bearish/neutral", "confidence": 0.8, "reason": "裁决理由", "action": "建议操作"}}
"""

    result = await judge.run(context, state["trace_id"])

    # 解析 LLM 输出
    import json
    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            verdict = json.loads(output[start:end])
        else:
            verdict = {"verdict": "neutral", "reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse verdict output: {e}")
        verdict = {"verdict": "neutral", "reason": output}

    new_phases = state["completed_phases"] + ["P5_verdict"]
    return {
        **state,
        "verdict": verdict,
        "current_phase": "P5_verdict",
        "completed_phases": new_phases
    }


async def node_trading_plan(state: DebateState) -> DebateState:
    _ensure_llm_key()
    strategist = FdtAgentExecutor("trading_strategist")

    context = f"""作为交易策略师，请基于以下裁决制定交易计划：

裁决: {state['verdict']}
品种: {state['selected_symbols']}

请以 JSON 格式返回交易计划：
{{"entry_price": 3100, "stop_loss": 3150, "target": 3000, "position_size": 2, "reason": "计划理由"}}
"""

    result = await strategist.run(context, state["trace_id"])

    import json
    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            plan = json.loads(output[start:end])
        else:
            plan = {"reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse trading plan: {e}")
        plan = {"reason": output}

    new_phases = state["completed_phases"] + ["P5_plan"]
    return {
        **state,
        "trading_plan": plan,
        "current_phase": "P5_plan",
        "completed_phases": new_phases
    }


async def node_risk_check(state: DebateState) -> DebateState:
    _ensure_llm_key()
    risk_manager = FdtAgentExecutor("risk_manager")

    context = f"""作为风控经理，请审核以下交易计划的风险：

交易计划: {state['trading_plan']}
裁决: {state['verdict']}

请以 JSON 格式返回风控审核结果：
{{"approved": true, "risk_level": "medium", "max_position": 2, "warnings": ["警告1", "警告2"]}}
"""

    result = await risk_manager.run(context, state["trace_id"])

    import json
    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            risk_check = json.loads(output[start:end])
        else:
            risk_check = {"approved": True, "warnings": [output]}
    except Exception as e:
        logger.warning(f"Failed to parse risk check: {e}")
        risk_check = {"approved": True, "warnings": [output]}

    new_phases = state["completed_phases"] + ["P5_risk"]
    return {
        **state,
        "risk_check": risk_check,
        "current_phase": "P5_risk",
        "completed_phases": new_phases
    }


async def node_report(state: DebateState) -> DebateState:
    import subprocess
    import sys
    import json
    import tempfile
    from pathlib import Path

    temp_dir = Path(tempfile.mkdtemp())

    scan_results = state.get("scan_results", {})
    all_ranked = scan_results.get("all_ranked", [])

    symbols_summary = []
    all_actionable = []
    BUY_top5 = []
    SELL_top5 = []
    chain_results = {}

    symbol_price_map = {}
    symbol_atr_map = {}
    symbol_direction_map = {}

    for item in all_ranked:
        symbol = item.get("symbol", item.get("pid", ""))
        if not symbol:
            continue

        raw_dir = item.get("direction", item.get("l1l4_direction", ""))
        if raw_dir in ("bull", "BUY", "buy"):
            direction = "BUY"
        elif raw_dir in ("bear", "SELL", "sell"):
            direction = "SELL"
        else:
            direction = "HOLD"

        price = item.get("price", 0)
        atr = item.get("atr", 0)
        symbol_price_map[symbol] = price
        symbol_atr_map[symbol] = atr
        symbol_direction_map[symbol] = direction

        summary_item = {
            "symbol": symbol,
            "pid": symbol.lower(),
            "name": item.get("name", symbol),
            "product_name": item.get("name", symbol),
            "direction": direction,
            "l1l4_direction": raw_dir,
            "total": item.get("total", item.get("l1l4_total", 0)),
            "l1l4_total": item.get("total", item.get("l1l4_total", 0)),
            "adx": item.get("adx", 0),
            "rsi": item.get("rsi", 50),
            "cci": item.get("cci", 0),
            "stage": item.get("stage", ""),
            "z_score": item.get("z_score", 0),
            "cons": item.get("cons", 0),
            "volume": item.get("volume", 0),
            "dc20_break": item.get("dc20_break", "none"),
            "ma_align": item.get("ma_align", "mixed"),
            "macd_cross": item.get("macd_cross", "none"),
            "factor_direction": item.get("factor_direction", "neutral"),
            "factor_total": item.get("factor_total", 0),
            "direction_conflict": item.get("direction_conflict", False),
            "last_price": price,
            "price": price,
            "confidence": abs(item.get("total", 0)) / 100 if item.get("total") else 0,
            "decision": direction,
        }
        symbols_summary.append(summary_item)

        if direction in ("BUY", "SELL") and abs(summary_item["total"]) >= 40:
            all_actionable.append(summary_item)

    all_actionable.sort(key=lambda x: x["total"], reverse=True)
    BUY_top5 = [s["pid"] for s in all_actionable if s["direction"] == "BUY"][:5]
    SELL_top5 = [s["pid"] for s in all_actionable if s["direction"] == "SELL"][:5]

    research_data = state.get("research_data") or {}
    chain_analysis = research_data.get("chain_analysis", {})
    if chain_analysis and isinstance(chain_analysis, dict):
        chain_results = chain_analysis

    intermediate_data = {
        "scan_results": scan_results,
        "symbols_summary": symbols_summary,
        "chain_results": chain_results,
        "all_actionable": all_actionable,
        "BUY_top5": BUY_top5,
        "SELL_top5": SELL_top5,
        "judge_direction": state.get("judge_direction", {}),
        "research_data": research_data,
        "bullish_arguments": state.get("bullish_arguments", []),
        "bearish_arguments": state.get("bearish_arguments", []),
        "verdict": state.get("verdict", {}),
        "trading_plan": state.get("trading_plan", {}),
        "risk_check": state.get("risk_check", {}),
    }

    verdict = state.get("verdict") or {}
    trading_plan = state.get("trading_plan") or {}
    risk_check = state.get("risk_check") or {}

    verdicts = {}
    selected_symbols = state.get("selected_symbols", [])
    for sym in selected_symbols:
        sym_key = sym.lower()
        
        if verdict and isinstance(verdict, dict):
            v_dir = verdict.get("verdict", "neutral")
            if isinstance(v_dir, str):
                direction_str = v_dir
            elif isinstance(v_dir, dict):
                direction_str = v_dir.get("status", "neutral")
            else:
                direction_str = "neutral"
        else:
            direction_str = "neutral"

        if direction_str in ("bull", "bullish", "BUY", "buy"):
            final_dir = "BUY"
        elif direction_str in ("bear", "bearish", "SELL", "sell"):
            final_dir = "SELL"
        else:
            scan_dir = symbol_direction_map.get(sym, "HOLD")
            if scan_dir in ("BUY", "SELL"):
                final_dir = scan_dir
            else:
                final_dir = "HOLD"

        price = symbol_price_map.get(sym, 0)
        atr = symbol_atr_map.get(sym, 0)

        entry_price = trading_plan.get("entry_price", trading_plan.get("price", price))
        if isinstance(entry_price, dict):
            entry_price = entry_price.get("price", price)
        if not entry_price:
            entry_price = price
        try:
            entry_price = float(entry_price)
        except (ValueError, TypeError):
            entry_price = float(price)

        target_price = trading_plan.get("target_price", trading_plan.get("target", 0))
        try:
            target_price = float(target_price)
        except (ValueError, TypeError):
            target_price = 0
        if not target_price and entry_price and atr:
            if final_dir == "BUY":
                target_price = entry_price + atr * 2
            else:
                target_price = entry_price - atr * 2

        stop_loss_price = trading_plan.get("stop_loss_price", trading_plan.get("stop_loss", 0))
        try:
            stop_loss_price = float(stop_loss_price)
        except (ValueError, TypeError):
            stop_loss_price = 0
        if not stop_loss_price and entry_price and atr:
            if final_dir == "BUY":
                stop_loss_price = entry_price - atr * 0.8
            else:
                stop_loss_price = entry_price + atr * 0.8

        position_size = trading_plan.get("position_size", trading_plan.get("position_pct", 3))
        try:
            position_size = float(position_size)
        except (ValueError, TypeError):
            position_size = 3

        risk_reward_ratio = 0
        if entry_price and stop_loss_price and target_price:
            risk = abs(entry_price - stop_loss_price)
            reward = abs(target_price - entry_price)
            if risk > 0:
                risk_reward_ratio = round(reward / risk, 2)

        verdicts[sym_key] = {
            "direction": final_dir,
            "confidence": verdict.get("confidence", 0.5),
            "judge_verdict": {
                "final_direction": final_dir,
                "confidence": verdict.get("confidence", 0.5),
                "reasoning": verdict.get("reason", ""),
            },
            "bull_args": state.get("bullish_arguments", []),
            "bear_args": state.get("bearish_arguments", []),
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss_price": stop_loss_price,
            "position_size": position_size,
            "risk_reward_ratio": risk_reward_ratio,
            "adx": symbol_atr_map.get(sym, 0),
            "rsi": 50,
            "score": 0,
            "chain": "",
        }

    debate_results = {
        "trace_id": state.get("trace_id", ""),
        "verdicts": verdicts,
        "overall": {
            "tendency": verdict.get("verdict", "neutral"),
            "core_conflict": verdict.get("reason", ""),
        },
        "bullish_arguments": state.get("bullish_arguments", []),
        "bearish_arguments": state.get("bearish_arguments", []),
        "trading_plan": trading_plan,
        "risk_check": risk_check,
    }

    for sym_key, sym_verdict in verdicts.items():
        debate_results[sym_key] = sym_verdict

    intermediate_path = temp_dir / "intermediate_data.json"
    debate_path = temp_dir / "debate_results.json"

    with open(intermediate_path, "w", encoding="utf-8") as f:
        json.dump(intermediate_data, f, ensure_ascii=False, indent=2)
    with open(debate_path, "w", encoding="utf-8") as f:
        json.dump(debate_results, f, ensure_ascii=False, indent=2)

    report_script = _SKILLS_DIR / "futures-trading-analysis" / "scripts" / "phase3_generate_report.py"

    cmd = [sys.executable, str(report_script),
           "--intermediate", str(intermediate_path),
           "--debate", str(debate_path),
           "--output", str(temp_dir)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"⚠️ 报告生成警告: {result.stderr[:200]}")
        report_files = list(temp_dir.glob("*.html"))
        if report_files:
            report_path = str(report_files[0])
        else:
            report_path = f"/tmp/report-{state['trace_id']}.html"
    except Exception as e:
        report_path = f"/tmp/report-{state['trace_id']}.html"

    new_phases = state["completed_phases"] + ["P6"]
    return {**state, "report_path": report_path, "current_phase": "P6", "completed_phases": new_phases}