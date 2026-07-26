"""准备阶段节点 — P0~P2.5（扫描/新鲜度闸门/初判/数据准备/缓存）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

from fdt_langgraph.agents import FdtAgentExecutor
from fdt_langgraph.llm_provider import parse_llm_output
from fdt_langgraph.state import DebateState
from fdt_langgraph._nodes_utils import _ensure_llm_key, _inject_memory_rules, _resolve_report_dir

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

async def node_scan(state: DebateState) -> DebateState:
    import subprocess
    import sys

    existing_results = state.get("scan_results", {})
    if existing_results and existing_results.get("all_ranked"):
        print("[SCAN] 已有扫描结果，跳过重新扫描")
        scan_report_path = state.get("scan_report_path")
        if not scan_report_path and os.environ.get("FDT_GENERATE_SCAN_REPORT", "").lower() == "true":
            try:
                report_dir = _resolve_report_dir()
                scan_report_path = _write_scan_report(state["trace_id"], existing_results, report_dir)
            except Exception as e:
                logger.warning(f"[SCAN] 扫描报告生成失败: {e}")
                scan_report_path = None
        return {**state, "scan_report_path": scan_report_path, "current_phase": "P1", "completed_phases": ["P1"]}

    scan_script = _SKILLS_DIR / "quant-daily" / "scripts" / "scan_all.py"
    symbols = state.get("selected_symbols", [])
    from datetime import datetime as _dt
    _date_compact = _dt.now().strftime("%Y%m%d")
    _report_dir = _resolve_report_dir()
    cmd = [sys.executable, str(scan_script),
           "-o", str(_report_dir),
           "-p", "full_scan_summary"]
    if symbols:
        cmd += ["--symbols", ",".join(symbols)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        # scan_all writes JSON to file, not stdout. Read it afterwards.
        _summary_file = _report_dir / f"full_scan_summary_{_date_compact}.json"
        if _summary_file.exists():
            with open(str(_summary_file), "r", encoding="utf-8") as _sf:
                scan_results = json.load(_sf)
            # 清理中间文件：数据加载后删除 summary 文件
            try:
                os.remove(str(_summary_file))
                logger.debug(f"[SCAN] 已清理中间文件: {_summary_file.name}")
            except Exception:
                pass
        else:
            scan_results = {"error": "summary file not found: %s" % _summary_file}
    except Exception as e:
        scan_results = {"error": str(e)}
        try:
            _alt = _report_dir / f"full_scan_summary_{_date_compact}.json"
            if _alt.exists():
                with open(str(_alt), "r", encoding="utf-8") as _sf:
                    scan_results = json.load(_sf)
                # 清理中间文件（异常分支）
                try:
                    os.remove(str(_alt))
                except Exception:
                    pass
        except Exception:
            pass

    # v8.8.0: 生成信号扫描报告 (P1 阶段) — 仅 FDT_GENERATE_SCAN_REPORT=true 时生成
    scan_report_path = None
    if os.environ.get("FDT_GENERATE_SCAN_REPORT", "").lower() == "true":
        try:
            report_dir = _resolve_report_dir()
            scan_report_path = _write_scan_report(state["trace_id"], scan_results, report_dir)
            logger.info(f"[SCAN] 扫描报告: {scan_report_path}")
        except Exception as e:
            logger.warning(f"[SCAN] 扫描报告生成失败: {e}")
    else:
        logger.info("[SCAN] 扫描报告跳过 (FDT_GENERATE_SCAN_REPORT 未设置)")

    # v9.3.0: 标准化扫描信号输出字段（direction/total/grade/confidence 统一）
    _all_ranked = scan_results.get("all_ranked", [])
    if _all_ranked:
        # field_normalizer 已随 FDC 退役；signal_list 直接传递，数据不变
        scan_results["all_ranked"] = _all_ranked

    return {**state, "scan_results": scan_results, "scan_report_path": scan_report_path,
            "current_phase": "P1", "completed_phases": ["P1"]}




def node_freshness_gate(state: DebateState) -> DebateState:
    """P0b: 数据新鲜度闸门 — 检查 scan_results 的数据新鲜度。

    从 scan_all.py 的 freshness_report + R24 闸门结果判断数据是否可用。
    如果所有品种数据均为 STALE/UNAVAILABLE，标记 freshness_report 供 D06 降级路由决策。

    环境变量 FDT_BYPASS_FRESHNESS_GATE=true 可强制绕过（非交易时段使用）。
    """
    # ── 环境变量绕过开关（v10.1.1: 非交易时段强制辩论） ──
    if os.environ.get("FDT_BYPASS_FRESHNESS_GATE", "").lower() == "true":
        bypass_msg = "[P0b] FDT_BYPASS_FRESHNESS_GATE=true，跳过新鲜度检查"
        logger.warning(bypass_msg)
        scan_results = state.get("scan_results", {})
        all_ranked = scan_results.get("all_ranked", [])
        return {
            **state,
            "freshness_report": {
                "status": "BYPASS",
                "valid_symbols": len(all_ranked),
                "summary": bypass_msg,
            },
            "current_phase": "P0b",
            "completed_phases": state["completed_phases"] + ["P0b"],
        }

    scan_results = state.get("scan_results", {})
    if not scan_results:
        return {**state, "freshness_report": {"status": "NO_SCAN", "summary": "无扫描结果，无法验证新鲜度"}}

    # 从 scan_results 读取 freshness_report（由 scan_all.py R24 闸门输出）
    freshness = scan_results.get("freshness_report", {})
    r24_meta = scan_results.get("_meta", {})

    # 检查 R24 全局闸门是否触发
    r24_rejected = freshness.get("r24_rejected", False) or r24_meta.get("r24_rejected", False)

    # 从 all_ranked 判断实际有多少有效品种
    all_ranked = scan_results.get("all_ranked", [])
    valid_symbols = len(all_ranked)
    freshness_report = {
        "status": "PASS",
        "r24_rejected": r24_rejected,
        "total_symbols_scan": freshness.get("total_symbols", len(all_ranked)),
        "valid_symbols": valid_symbols,
        "summary": f"数据新鲜度检查通过: {valid_symbols} 品种有有效数据",
        "fail_reasons": freshness.get("fail_reasons", []),
    }

    new_phases = state["completed_phases"] + ["P0b"]

    # ── ALL_STALE: 所有品种数据均为过期/不可用 → D06 降级路由 ──
    if r24_rejected or freshness.get("status") == "ALL_STALE":
        freshness_report["status"] = "ALL_STALE"
        freshness_report["summary"] = (
            "⛔ 数据新鲜度闸门阻断: 所有品种数据源均不可靠. "
            "请检查 TQ-Local/FDC 数据源连接."
        )
        logger.warning(f"[P0b] {freshness_report['summary']}")
        for r in freshness_report["fail_reasons"][:3]:
            logger.warning(f"[P0b]   原因: {r}")
        return {
            **state,
            "freshness_report": freshness_report,
            "current_phase": "P0b",
            "completed_phases": new_phases,
        }

    # ── 部分品种过期（非全局阻塞）: 记录但继续 ──
    if valid_symbols == 0:
        freshness_report["status"] = "NO_VALID_SYMBOLS"
        freshness_report["summary"] = "扫描结果中无有效品种（all_ranked 为空），但非 R24 全局闸门阻断"
        logger.warning(f"[P0b] {freshness_report['summary']}")
        return {
            **state,
            "freshness_report": freshness_report,
            "current_phase": "P0b",
            "completed_phases": new_phases,
        }

    return {
        **state,
        "freshness_report": freshness_report,
        "current_phase": "P0b",
        "completed_phases": new_phases,
    }




async def node_judge_direction(state: DebateState) -> DebateState:
    """P2: 闫判官协调数据源调度（不做品种筛选，v9.23.1）"""
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    scan_results = state.get("scan_results", {})
    primary_from_scan = scan_results.get("primary_symbols", [])

    # ── 从 scan_all 读取预筛选品种列表 ──
    if primary_from_scan:
        selected_symbols = list(primary_from_scan)
        logger.info(f"[Judge] 接收 scan_all 去重后品种 {len(selected_symbols)} 个")
    else:
        _all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
        _candidates = sorted(
            [r for r in _all_ranked if r.get("symbol")],
            key=lambda x: abs(x.get("total", 0)), reverse=True,
        )[:5]
        selected_symbols = [c["symbol"] for c in _candidates]
        logger.warning(f"[Judge] scan_all 未提供 primary_symbols，降级取 top5: {selected_symbols}")

    # ── LLM 只决定 dispatch_sources ──
    _summary_lines = "\n".join(
        f"  {r.get('symbol','?')}: total={r.get('total',0)}, grade={r.get('grade','?')}"
        for r in (scan_results.get("all_ranked", []) or [])[:10]
    )
    context = f"""你是闫判官（FDT 辩论调度官）。以下品种已由 P1 筛选完毕准备进入辩论：

选定品种: {selected_symbols}

P1 扫描摘要:
{_summary_lines}

你的职责（仅两项）：
1. dispatch_sources: 决定需要哪些数据源（从 ["chain","technical","fundamental"] 中选择）
2. reason: 简要说明选择理由

注意：你不做品种筛选。品种列表已由 scan_all.py 决定。
返回 JSON：
{{"scan_direction": "neutral", "confidence": 0.8, "dispatch_sources": ["chain", "technical"], "reason": "...", "symbols": {selected_symbols}}}
"""

    context = _inject_memory_rules("judge", context)
    result = await judge.run(context, state["trace_id"])

    output = result.get("output", "")
    parsed = parse_llm_output(output, agent_name="judge_direction",
                              default={"scan_direction": "neutral", "dispatch_sources": ["chain", "technical", "fundamental"]})
    if parsed.get("success"):
        verdict = parsed["data"]
    else:
        verdict = {"scan_direction": "neutral", "dispatch_sources": ["chain", "technical", "fundamental"],
                   "reason": output, "_parse_errors": parsed.get("errors", [])}

    dispatch_sources = verdict.get("dispatch_sources", ["chain", "technical", "fundamental"])
    scan_reason = verdict.get("reason", f"scan_all 预筛选 {len(selected_symbols)} 个品种")

    associated_groups = scan_results.get("associated_groups", {}) if isinstance(scan_results, dict) else {}
    if not isinstance(associated_groups, dict):
        associated_groups = {}

    new_phases = state["completed_phases"] + ["P2"]
    return {
        **state,
        "judge_direction": {
            "direction": "neutral",
            "confidence": verdict.get("confidence", 0.8),
            "symbols": selected_symbols,
            "reason": scan_reason,
            "audit": {},
        },
        "selected_symbols": selected_symbols,
        "_original_symbols": list(selected_symbols),
        "symbol_index": 0 if selected_symbols else -1,
        "per_symbol_results": {},
        "associated_symbols": associated_groups,
        "dispatch_sources": dispatch_sources,
        "current_phase": "P2",
        "completed_phases": new_phases,
    }




async def node_prepare_data(state: DebateState) -> DebateState:
    from fdt_langgraph._nodes_output import _write_scan_report
    """P2.5: FDC 数据准备 — 预采集所有选中品种的结构化数据供子 Agent 使用"""
    import os
    from datetime import datetime

    fdc_enabled = os.environ.get("FDT_FDC_INJECTION_ENABLED", "true").lower() == "true"
    if not fdc_enabled:
        logger.info("[FDC] 数据注入已禁用，跳过数据准备")
        return {
            **state,
            "fdc_data": {},
            "fdc_data_status": {"enabled": False, "collected": False},
            "current_phase": "P2.5",
            "completed_phases": state["completed_phases"] + ["P2.5"]
        }

    symbols = state.get("selected_symbols", [])
    if not symbols:
        logger.info("[FDC] 无选中品种，跳过数据准备")
        return {
            **state,
            "fdc_data": {},
            "fdc_data_status": {"enabled": True, "collected": False},
            "current_phase": "P2.5",
            "completed_phases": state["completed_phases"] + ["P2.5"]
        }

    # ── v10.6.0: 品种市场类型识别 ──
    if not state.get("market_type") and symbols:
        try:
            from data_adapter.instrument_classifier import classify
            # 以第一个品种为准（同批次品种通常同类型）
            primary_sym = symbols[0]
            mt = classify(primary_sym)
            state["market_type"] = mt.value
            logger.info(f"[FDC] 品种市场类型: {primary_sym} → {mt.value}")
        except Exception:
            state["market_type"] = "commodity_futures"
            logger.debug("[FDC] 品种分类失败，默认 commodity_futures")

    kline_days = int(os.environ.get("FDT_FDC_KLINE_DAYS", "120"))
    f10_enabled = os.environ.get("FDT_FDC_F10_ENABLED", "true").lower() == "true"
    position_ranking_enabled = os.environ.get("FDT_FDC_POSITION_RANKING_ENABLED", "true").lower() == "true"

    logger.info(f"[FDC] 开始为 {len(symbols)} 个品种准备数据: {symbols}")
    start_time = datetime.now()

    fdc_data: dict[str, dict] = {}
    errors: dict[str, str] = {}

    try:
        from data_adapter import get_kline as _da_get_kline
    except ImportError:
        logger.warning("[FDC] data_adapter 导入失败，降级无FDC模式")
        return {
            **state,
            "fdc_data": {},
            "fdc_data_status": {"enabled": True, "collected": False, "errors": {"import": "data_adapter not available"}},
            "current_phase": "P2.5",
            "completed_phases": state["completed_phases"] + ["P2.5"]
        }

    async def collect_symbol_data(symbol: str) -> tuple[str, dict, str | None]:
        symbol_data: dict = {}
        error: str | None = None
        data_grades: dict[str, str] = {}

        try:
            kline_payload = await _da_get_kline(symbol, period="daily", days=kline_days)
            # KlineResult.bars 是 KlineBar dataclass 列表，转为 dict 供下游兼容
            _raw_bars = [
                {"date": b.date, "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume, "open_interest": b.open_interest}
                for b in kline_payload.bars
            ]
            # 🔴 检查并反转：如果第一根 bar 的日期 > 最后一根，说明是倒序
            if _raw_bars and len(_raw_bars) > 1 and str(_raw_bars[0].get("date", "")) > str(_raw_bars[-1].get("date", "")):
                _raw_bars.reverse()

            symbol_data["kline"] = {
                "bars": _raw_bars,
                "meta": {k: v for k, v in kline_payload.meta.items() if k != "sources"},
                "summary": f"{_raw_bars[0]['date']}~{_raw_bars[-1]['date']} {len(_raw_bars)} bars" if _raw_bars else "",
            }
            data_grades["kline"] = kline_payload.meta.get("data_grade", "UNKNOWN")

            bars = _raw_bars
            bar_count = len(bars) if bars else 0
            if bars and bar_count >= 60:
                import pandas as _pd
                try:
                    # 使用 data_adapter 纯 numpy 指标，与 scan_all.py 保持一致
                    from data_adapter.indicators import compute_indicators as _compute_indicators_numpy
                    _df = _pd.DataFrame({
                        "open": [float(b.get("open", 0)) for b in bars],
                        "high": [float(b.get("high", 0)) for b in bars],
                        "low": [float(b.get("low", 0)) for b in bars],
                        "close": [float(b.get("close", 0)) for b in bars],
                        "volume": [float(b.get("volume", 0)) for b in bars],
                        "open_interest": [float(b.get("open_interest", b.get("oi", 0))) for b in bars],
                    })
                    ind_result = _compute_indicators_numpy(_df, symbol, period="daily")
                    # 统一转纯值（numpy → float/list）
                    ind_values = {}
                    for k, v in ind_result.items():
                        if isinstance(v, np.ndarray):
                            ind_values[k] = v.tolist()
                        elif hasattr(v, 'tolist'):
                            ind_values[k] = v.tolist()
                        else:
                            ind_values[k] = v
                    if ind_result:  # 仅当实际计算出了指标才标记 PRIMARY
                        symbol_data["indicators"] = {
                            "values": ind_values,
                            "available": list(ind_result.keys()),
                        }
                        data_grades["indicators"] = "PRIMARY"
                    else:
                        data_grades["indicators"] = "UNAVAILABLE"
                        logger.info(f"[FDC] {symbol} indicators.py 返回空结果(bar_count={bar_count}), 标记 UNAVAILABLE")
                except Exception as e:
                    logger.warning(f"[FDC] {symbol} 技术指标计算失败: {e}")
                    data_grades["indicators"] = "UNAVAILABLE"
            elif bars and bar_count < 60:
                data_grades["indicators"] = "UNAVAILABLE"
                logger.info(f"[FDC] {symbol} K线数量不足(bar_count={bar_count}, 需>=60), 跳过技术指标计算")
        except Exception as e:
            logger.warning(f"[FDC] {symbol} K线获取失败: {e}")
            error = f"kline_error: {e}"
            data_grades["kline"] = "UNAVAILABLE"

        if f10_enabled and not error:
            try:
                from data_adapter import get_basis, get_warrant, get_term_structure, get_spread

                # fundamental 无固定数据源，提示 agent 通过 WebSearch 获取
                async def _fundamental_websearch(_sym):
                    return {"data": {}, "summary": "利润/供需等基本面数据请通过 WebSearch 获取行业机构公开数据",
                            "data_grade": "UNAVAILABLE"}

                for name, fn in [("term_structure", get_term_structure), ("spread", get_spread),
                                 ("basis", get_basis), ("warrant", get_warrant),
                                 ("fundamental", _fundamental_websearch)]:
                    try:
                        payload = await fn(symbol)
                        _pd = payload if isinstance(payload, dict) else {"data": {}, "summary": "", "data_grade": "UNAVAILABLE"}
                        symbol_data[name] = {
                            "data": _pd.get("data", {}),
                            "summary": _pd.get("summary", ""),
                        }
                        data_grades[name] = _pd.get("data_grade", "UNKNOWN")
                    except Exception as e:
                        logger.warning(f"[FDC] {symbol} {name} 失败: {e}")
                        data_grades[name] = "UNAVAILABLE"

                f10_fields = ["term_structure", "spread", "basis", "warrant", "fundamental"]
                available_f10 = [f for f in f10_fields if f in symbol_data]
                symbol_data["f10_summary"] = {
                    "available_fields": available_f10,
                    "total_fields": len(f10_fields),
                    "coverage_pct": round(len(available_f10) / len(f10_fields) * 100, 1),
                }
            except ImportError:
                pass

        if position_ranking_enabled and not error:
            try:
                from data_adapter import get_position_ranking
                pr_payload = await get_position_ranking(symbol)
                _pr = pr_payload if isinstance(pr_payload, dict) else {"data": {}, "summary": "", "data_grade": "UNAVAILABLE"}
                symbol_data["position_ranking"] = {
                    "data": _pr.get("data", {}),
                    "summary": _pr.get("summary", ""),
                }
                data_grades["position_ranking"] = _pr.get("data_grade", "UNKNOWN")
            except Exception as e:
                logger.warning(f"[FDC] {symbol} 持仓排名失败: {e}")
                data_grades["position_ranking"] = "UNAVAILABLE"

        # ── 资金流向（探源/观澜消费） ──
        if not error:
            try:
                from data_adapter import get_fund_flow
                ff_payload = await get_fund_flow(symbol)
                _ff = ff_payload if isinstance(ff_payload, dict) else {"data": {}, "summary": "", "data_grade": "UNAVAILABLE"}
                symbol_data["fund_flow"] = {
                    "data": _ff.get("data", {}),
                    "summary": _ff.get("summary", ""),
                }
                data_grades["fund_flow"] = _ff.get("data_grade", "UNKNOWN")
            except Exception as e:
                logger.warning(f"[FDC] {symbol} 资金流向失败: {e}")
                data_grades["fund_flow"] = "UNAVAILABLE"

        # ── 外盘数据（观澜消费 — 外盘技术面参考） ──
        if not error:
            try:
                from data_adapter import get_foreign_hist
                foreign_payload = await get_foreign_hist(symbol)
                _fh = foreign_payload if isinstance(foreign_payload, dict) else {"data": {}, "summary": "", "data_grade": "UNAVAILABLE"}
                symbol_data["foreign"] = {
                    "data": _fh.get("data", {}),
                    "summary": _fh.get("summary", ""),
                }
                data_grades["foreign"] = _fh.get("data_grade", "UNKNOWN")
            except Exception as e:
                logger.warning(f"[FDC] {symbol} 外盘数据失败: {e}")
                data_grades["foreign"] = "UNAVAILABLE"

        # ── F10 数据质量评估（Data Governance Phase 2）已随 FDC 退役 ──
        symbol_data["f10_quality"] = {"available": False, "data_grade": "UNAVAILABLE", "note": "data_quality 已退役"}
        # 根据实际指标计算结果设定 indicator_quality
        ind = symbol_data.get("indicators", {})
        ind_available = bool(ind and ind.get("available"))
        symbol_data["indicator_quality"] = {
            "available": ind_available,
            "overall": "PRIMARY" if ind_available else "UNAVAILABLE",
            "completeness_pct": len(ind.get("available", [])) if ind_available else 0,
            "note": "基于 data_grades 实时评估",
        }

        symbol_data["data_grades"] = data_grades
        return symbol, symbol_data, error

    tasks = [collect_symbol_data(sym) for sym in symbols]
    # 45s 总体超时保护，防止某个品种的数据采集卡死
    results = []
    done, pending = await asyncio.wait(
        [asyncio.ensure_future(t) for t in tasks],
        timeout=45.0,
    )
    for fut in done:
        try:
            results.append(fut.result())
        except asyncio.CancelledError:
            logger.warning("[FDC] 数据采集任务被取消，跳过")
        except Exception as e:
            logger.warning(f"[FDC] 数据采集任务异常: {e}")
    if pending:
        for fut in pending:
            fut.cancel()
            logger.warning("[FDC] 数据采集超时(45s)，取消未完成的任务")

    for result in results:
        if isinstance(result, (Exception, BaseException)):
            logger.error(f"[FDC] 数据采集异常: {result}")
            continue
        symbol, data, error = result
        fdc_data[symbol] = data
        if error:
            errors[symbol] = error

    elapsed = (datetime.now() - start_time).total_seconds()
    success_count = len([s for s in symbols if s in fdc_data and fdc_data[s].get("kline", {}).get("bars")])
    logger.info(f"[FDC] 数据准备完成: {success_count}/{len(symbols)} 品种成功, 耗时 {elapsed:.1f}s")

    # 诊断：标记指标 N/A 的品种
    na_symbols = []
    for s in symbols:
        sd = fdc_data.get(s, {})
        iq = sd.get("indicator_quality", {})
        if iq.get("available") == False or iq.get("completeness_pct", 100) == 0 or iq.get("overall") == "D":
            na_symbols.append(s)
    if na_symbols:
        logger.warning(f"[FDC] 指标 N/A 或质量 D 级品种: {na_symbols} — 这些品种的裁决/分析可能依赖 FDC 回退数据")

    # ── Phase 3.3+3.7: 基本面清洗激活 ──
    try:
        from data_adapter.cleaning import clean_fundamental_data
        cleaning_enabled = os.environ.get("FDT_DATA_CLEANING_ENABLED", "true").lower() == "true"
        fdc_data = clean_fundamental_data(fdc_data, cleaning_enabled=cleaning_enabled)
    except Exception:
        pass  # cleaning layer unavailable, continue without

    # ── P2.5 多因子注入 ──
    try:
        from data_adapter.factors import FactorCollector
        fc = FactorCollector()
        factor_term_structure = await fc.collect_term_structure(symbols)
        factor_holding_sentiment = await fc.collect_holding_sentiment(symbols)
        factor_volatility = fc.compute_volatility(symbols, fdc_data)
        factor_cross_spread = fc.compute_cross_spreads(symbols, fdc_data)
        factor_dashboard = fc.build_dashboard(
            symbols, factor_term_structure, factor_volatility,
            factor_holding_sentiment, factor_cross_spread,
        )
    except Exception as e:
        logger.warning("[FDC] 多因子注入失败 (非关键): %s", e)
        factor_term_structure = {}
        factor_holding_sentiment = {}
        factor_volatility = {}
        factor_cross_spread = []
        factor_dashboard = None

    # ── 腾讯自选股特有因子采集（Equity/ETF 品种） ──
    factor_money_flow: dict = {}
    factor_north_flow: dict = {}
    try:
        from data_adapter import get_money_flow, get_north_flow
        from data_adapter.instrument_classifier import classify, MarketType
        for sym in symbols:
            mt = classify(sym)
            if mt not in (MarketType.STOCK, MarketType.ETF):
                continue
            mf = await get_money_flow(sym)
            if mf.get("data_grade") == "PRIMARY":
                factor_money_flow[sym] = mf
            nf = await get_north_flow(sym)
            if nf.get("data_grade") == "PRIMARY":
                factor_north_flow[sym] = nf
    except Exception:
        pass

    return {
        **state,
        "fdc_data": fdc_data,
        "fdc_data_status": {
            "enabled": True,
            "collected": True,
            "total_symbols": len(symbols),
            "success_symbols": success_count,
            "errors": errors,
            "elapsed_seconds": round(elapsed, 2),
            "kline_days": kline_days,
            "f10_enabled": f10_enabled,
            "position_ranking_enabled": position_ranking_enabled,
        },
        "factor_term_structure": factor_term_structure,
        "factor_holding_sentiment": factor_holding_sentiment,
        "factor_volatility": factor_volatility,
        "factor_cross_spread": factor_cross_spread,
        "factor_dashboard": factor_dashboard,
        "factor_money_flow": factor_money_flow,
        "factor_north_flow": factor_north_flow,
        "current_phase": "P2.5",
        "completed_phases": state["completed_phases"] + ["P2.5"]
    }




async def node_load_cache(state: DebateState) -> DebateState:
    """从实时数据源拉取指定品种数据，经缓存后进入辩论。

    读取 FDT_DEBATE_SYMBOLS 环境变量获取指定品种列表，
    对每个品种从 FDC 实时数据源拉取 K 线/基本面数据，
    写入本地缓存后构造 scan_results 传给下游辩论环节。
    两种模式共用此逻辑：全量模式不触发此节点，指定品种模式触发。
    """
    symbol_str = os.environ.get("FDT_DEBATE_SYMBOLS", "")
    direct_debate = os.environ.get("FDT_DIRECT_DEBATE", "").lower() == "true"

    if not symbol_str or not direct_debate:
        logger.warning("[LOAD_CACHE] FDT_DEBATE_SYMBOLS 未设置，回退到正常扫描")
        return await node_scan(state)

    symbols = [s.strip().upper() for s in symbol_str.split(",") if s.strip()]
    if not symbols:
        logger.warning("[LOAD_CACHE] FDT_DEBATE_SYMBOLS 为空，回退到正常扫描")
        return await node_scan(state)

    logger.info(f"[LOAD_CACHE] 指定品种辩论模式: {symbols}")

    # 实时拉取每个品种的 K 线数据（复用 FDC 数据引擎）
    from datetime import datetime as _dt
    _date_compact = _dt.now().strftime("%Y%m%d")
    _report_dir = _resolve_report_dir()

    # 直接调用 scan_all 的采集逻辑，但只采集指定品种
    # 方式：构造简易扫描结果，不调 scan_all 全流程
    all_ranked = []
    fdc_data = {}

    # 使用同步方式逐个拉取
    _skills_dir = str(_SKILLS_DIR)
    _qdaily_dir = str(_SKILLS_DIR / "quant-daily" / "scripts")

    try:
        # 导入 FDC 数据引擎
        if _qdaily_dir not in sys.path:
            sys.path.insert(0, _qdaily_dir)

        import asyncio as _asyncio

        from data_adapter import get_kline as _fdc_get_kline

        for sym in symbols:
            try:
                # 拉取实时 K 线数据
                payload = await _fdc_get_kline(sym.lower(), period="daily", days=120)

                meta = payload.meta
                grade = meta.get("data_grade", meta.get("data_grade_label", ""))
                # KlineResult.bars 是 KlineBar 对象列表，转为 dict 供下游兼容
                bars_raw = [
                    {"date": b.date, "open": b.open, "high": b.high, "low": b.low,
                     "close": b.close, "volume": b.volume, "open_interest": b.open_interest}
                    for b in payload.bars
                ] if hasattr(payload, "bars") else []

                if grade in ("UNAVAILABLE", "STALE") or not bars_raw:
                    logger.warning(f"[LOAD_CACHE] {sym} 数据不可用: grade={grade}")
                    all_ranked.append({
                        "symbol": sym, "direction": "neutral",
                        "total": 0, "grade": "NOISE", "price": 0,
                        "data_source": "unavailable",
                    })
                    continue

                # 格式化 K 线记录
                records = []
                for b in bars_raw:
                    records.append({
                        "date": b.get("date", ""),
                        "open": float(b.get("open", 0)),
                        "high": float(b.get("high", 0)),
                        "low": float(b.get("low", 0)),
                        "close": float(b.get("close", 0)),
                        "volume": int(b.get("volume", 0)),
                        "oi": int(b.get("oi") or b.get("open_interest", 0)),
                    })

                latest_close = records[-1]["close"] if records else 0
                source_label = meta.get("source", "fdc")

                # 存到 fdc_data 供下游使用
                fdc_data[sym] = {"kline": records, "data_source": source_label}

                # 构造条目（中性信号，下游 judge_direction 会重新判断）
                all_ranked.append({
                    "symbol": sym,
                    "direction": "neutral",
                    "signal_type": "direct_debate",
                    "strategy": "direct_debate",
                    "total": 0,
                    "abs": 0,
                    "grade": "WATCH",
                    "weight": 0,
                    "price": latest_close,
                    "change_pct": 0,
                    "volume": records[-1]["volume"] if records else 0,
                    "oi": records[-1]["oi"] if records else 0,
                    "data_source": source_label,
                })

                # 写入本地缓存
                try:
                    from fdt_cache import CacheManager
                    cache = CacheManager.get_instance()
                    cache.ensure_schema()
                    cache.update_kline_cache(sym, "daily", records)
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning(f"[LOAD_CACHE] 缓存写入失败 {sym}: {e}")

                logger.info(f"[LOAD_CACHE] {sym}: 拉取 {len(records)} 根 K 线 (最新价={latest_close}, 源={source_label})")

            except Exception as e:
                logger.warning(f"[LOAD_CACHE] {sym} 数据拉取失败: {e}")
                all_ranked.append({
                    "symbol": sym, "direction": "neutral",
                    "total": 0, "grade": "NOISE", "price": 0,
                    "data_source": "fetch_error",
                })

    except ImportError as e:
        logger.error(f"[LOAD_CACHE] 数据引擎不可用: {e}，回退到正常扫描")
        return await node_scan(state)

    # 按总信号强度排序
    all_ranked.sort(key=lambda x: abs(x.get("total", 0)), reverse=True)

    logger.info(f"[LOAD_CACHE] 完成 {len(symbols)} 个品种实时数据采集，进入辩论流程")
    return {
        **state,
        "scan_results": {"all_ranked": all_ranked, "bull_signals": [], "bear_signals": [], "per_strategy": {"direct_debate": all_ranked}},
        "fdc_data": fdc_data,
        "selected_symbols": symbols,
        "current_phase": "P1",
        "completed_phases": ["P1"],
    }




async def node_update_cache(state: DebateState) -> DebateState:
    """将本轮辩论结果写入本地缓存（P6 之后调用，不阻塞主流程）。

    将 scan_results / research_data / verdict 等写入本地缓存，
    供后续直接辩论模式复用。
    """
    try:
        from fdt_cache import CacheManager
        cache = CacheManager()

        scan_results = state.get("scan_results", {})
        research_data = state.get("research_data", {})
        verdict = state.get("verdict", {})

        cache.save_debate_results(
            trace_id=state.get("trace_id", ""),
            scan_results=scan_results,
            research_data=research_data,
            verdict=verdict,
        )
        logger.info(f"[UPDATE_CACHE] 辩论结果已写入缓存, trace_id={state.get('trace_id', '')}")
    except ImportError:
        logger.debug("[UPDATE_CACHE] fdt_cache 模块未安装，跳过缓存写入")
    except Exception as e:
        logger.warning(f"[UPDATE_CACHE] 缓存写入异常: {e}")

    # 不阻塞主流程，直接返回原 state
    return state

