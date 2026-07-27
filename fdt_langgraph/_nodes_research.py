"""研究阶段节点 — P3（链证源/观澜/探源/读心/合并）。"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from fdt_langgraph.agents import FdtAgentExecutor
from fdt_langgraph.llm_provider import parse_llm_output
from fdt_langgraph.state import DebateState
from fdt_langgraph._nodes_utils import _ensure_llm_key, _import_from_skill, _import_skill_module, _normalize_per_symbol, _repair_json, _resolve_alias, _resolve_report_dir
from fdt_langgraph._nodes_context import _build_fdc_technical_context, _build_market_fundamental_context, _build_wind_context_block

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

async def node_chain(state: DebateState) -> dict:
    """链证源产业链分析节点（P3 四源之一）。
    
    导入 commodity-chain-analysis 的 analyze_chain 模块，提供产业链聚类和冗余分析。
    如分析失败，返回基于品种映射的基础产业链信息作为 fallback。

    注意 (v10.6.0): 非商品期货（股指/国债/ETF）直接跳过链证源。
    """
    # ── v10.6.0: 非商品期货跳过链证源 ──
    mt = state.get("market_type", "commodity_futures")
    if mt != "commodity_futures":
        logger.info(f"[链证源] 跳过 {mt} 品种（非商品期货）")
        return {"chain_analysis": {"skipped": True, "reason": f"非商品期货（{mt}），跳过产业链分析"}}

    try:
        # 先尝试从 analyze_chain.py 导入 run_analysis
        _chain_mod = _import_skill_module("commodity-chain-analysis", "scripts.analyze_chain")
        run_analysis = _chain_mod.run_analysis
        lookup_symbol_names = _chain_mod.lookup_symbol_names
        build_symbols_data = _chain_mod.build_symbols_data
        # lookup_symbol_names 和 build_symbols_data 都在 analyze_chain.py 中
        ac_mod = _import_skill_module("commodity-chain-analysis", "scripts.analyze_chain")
        lookup_symbol_names = ac_mod.lookup_symbol_names
        build_symbols_data = ac_mod.build_symbols_data
    except Exception:
        try:
            # fallback: 用 importlib 加载 chains.py 的映射工具
            chains_mod = _import_skill_module("commodity-chain-analysis", "scripts.chains")
            get_chain_for_symbol = chains_mod.get_chain_for_symbol
            CHAIN_PRODUCTS = chains_mod.CHAIN_PRODUCTS
            symbols = state.get("selected_symbols", [])
            fallback = {}
            for sym in symbols:
                chain = get_chain_for_symbol(sym)
                fallback[sym.upper()] = {
                    "chain": chain or "未归类",
                    "chain_members": CHAIN_PRODUCTS.get(chain, []) if chain else [],
                    "term_structure": "待计算",
                    "basis": "待计算",
                    "chain_trend": "待计算",
                    "chain_consistency": 0,
                    "redundant": False,
                    "notes": ["基础产业链映射（因 analyze_chain 未加载，分析精度受限）"],
                }
            return {"chain_analysis": fallback, "_source": "fallback_chain_mapping"}
        except Exception as e2:
            return {"chain_analysis": {"error": f"链证源加载失败: {e2}"}, "_source": "error"}
    
    # 正常导入成功：构建品种数据并执行分析
    symbols = state.get("selected_symbols", [])
    symbols_list = lookup_symbol_names(symbols)
    symbols_data = build_symbols_data(symbols_list)
    
    # 补充扫描数据中的价格信息
    scan_results = state.get("scan_results", {})
    all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
    for item in all_ranked:
        sym = item.get("symbol", "").upper()
        for sd in symbols_data:
            if sd["product_id"].upper() == sym:
                sd["last_price"] = item.get("price", 0)
                direction = item.get("direction", "neutral")
                sd["direction"] = {"bull": "BUY", "bear": "SELL"}.get(direction, "NEUTRAL")
                sd["score"] = abs(item.get("total", 0))
                break
    
    chain_data = run_analysis(symbols_data) if symbols_data else {}
    # 提取 structured chain_results
    result = chain_data.get("chain_results", {}) if isinstance(chain_data, dict) else chain_data
    result["_source"] = "analyze_chain"

    # ── P2.5 跨品种价差因子注入 ──
    try:
        factor_cs = state.get("factor_cross_spread", [])
        if factor_cs:
            cs_parts = ["【跨品种价差（P2.5 计算）】"]
            for cs in factor_cs:
                if hasattr(cs, "data_grade") and cs.data_grade == "PRIMARY":
                    pair_str = f"{cs.pair[0]}-{cs.pair[1]}" if isinstance(cs.pair, (list, tuple)) else str(cs.pair)
                    parts = [f"价差={cs.current_spread:.1f}", f"Z-Score={cs.zscore:.2f}"]
                    if cs.percentile is not None:
                        parts.append(f"百分位={cs.percentile:.0f}%")
                    if cs.trend:
                        parts.append(f"趋势={cs.trend}")
                    if cs.historical_mean is not None:
                        parts.append(f"均值={cs.historical_mean:.1f}")
                    cs_parts.append(f"  {pair_str}: {' | '.join(parts)}")
            if len(cs_parts) > 1:
                result["cross_spread_context"] = "\n".join(cs_parts)
    except Exception:
        pass

    return {"chain_analysis": result}




async def node_technical(state: DebateState) -> dict:
    from fdt_langgraph._nodes_output import _write_research_report
    _ensure_llm_key()
    technical = FdtAgentExecutor("technical_researcher")
    selected = state.get("selected_symbols", [])
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    fdc_data = state.get("fdc_data", {})
    fdc_status = state.get("fdc_data_status", {})

    scan_results = state.get("scan_results", {})
    fdc_tech_context = _build_fdc_technical_context(selected, fdc_data, scan_results)

    # ── P2.5 波动率因子注入（从 K 线计算） ──
    vol_context = ""
    try:
        factor_vol = state.get("factor_volatility", {})
        if factor_vol:
            vol_parts = ["\n【波动率因子（P2.5 计算）】"]
            for sym in selected:
                vr = factor_vol.get(sym)
                if vr and getattr(vr, "data_grade", "") == "PRIMARY":
                    parts = []
                    if vr.hv_20 is not None:
                        parts.append(f"HV20={vr.hv_20}%")
                    if vr.skewness is not None:
                        parts.append(f"偏度={vr.skewness}")
                    if vr.kurtosis is not None:
                        parts.append(f"峰度={vr.kurtosis}")
                    if vr.atr_pct is not None:
                        parts.append(f"ATR={vr.atr_pct}%")
                    if parts:
                        vol_parts.append(f"  {sym}: {' | '.join(parts)}")
            if len(vol_parts) > 1:
                vol_context = "\n".join(vol_parts)
    except Exception:
        pass

    # ── 腾讯资金流向因子注入（观澜 — 量价情绪辅助） ──
    mf_context = ""
    try:
        factor_mf = state.get("factor_money_flow", {})
        if factor_mf:
            mf_parts = ["\n【资金流向因子（腾讯自选股）】"]
            for sym in selected:
                mf = factor_mf.get(sym)
                if mf and mf.get("data_grade") == "PRIMARY":
                    parts = []
                    main_n = mf.get("main_net_inflow")
                    mid_n = mf.get("mid_net_inflow")
                    ret_n = mf.get("retail_net_inflow")
                    if main_n is not None:
                        label = "主力" if main_n > 0 else "主力"
                        parts.append(f"{label}净流入={main_n:+.0f}")
                    if mid_n is not None:
                        parts.append(f"中户净流入={mid_n:+.0f}")
                    if ret_n is not None:
                        parts.append(f"散户净流入={ret_n:+.0f}")
                    if parts:
                        mf_parts.append(f"  {sym}: {' | '.join(parts)}")
            if len(mf_parts) > 1:
                mf_context = "\n".join(mf_parts)
    except Exception:
        pass

    # ── Phase 4: 代码计算技术基准评分（L1 边界） ──
    baseline_scores: dict[str, int] = {}
    try:
        from data_adapter.factors.technical_score import compute_technical_score
        for sym in selected:
            sym_up = sym.upper()
            sd = fdc_data.get(sym_up) or fdc_data.get(sym) or {}
            ind_vals = (sd.get("indicators") or {}).get("values", {}) if sd else {}
            # 补充收盘价
            bars = (sd.get("kline") or {}).get("bars", []) if sd else []
            if bars and "close" not in ind_vals:
                ind_vals["close"] = float(bars[-1].get("close", 0)) if bars else 0
            vol_sym = state.get("factor_volatility", {}).get(sym_up, {})
            vol_dict = {}
            if hasattr(vol_sym, "hv_20"):
                vol_dict = {"hv_20": vol_sym.hv_20}
            baseline_scores[sym] = compute_technical_score(sym, ind_vals, vol_dict)
    except Exception as e:
        logger.debug(f"[TECH] 基准评分计算失败: {e}")
        baseline_scores = {}

    # 基准评分注入 prompt
    base_score_lines = ["\n【基准技术评分（代码计算）】"]
    for sym in selected:
        bs = baseline_scores.get(sym)
        if bs is not None:
            base_score_lines.append(f"  {sym}: {bs}/100")
    if len(base_score_lines) > 1:
        base_score_block = "\n".join(base_score_lines)
    else:
        base_score_block = ""

    context = f"""作为技术面研究员（观澜），请分析以下品种的技术面状态：

市场方向判断: {direction}
待分析品种: {selected}

【市场技术数据（AKShare 实时源，P2.5 预采集）】
{fdc_tech_context}
{vol_context}
{mf_context}
{base_score_block}

请先以 Markdown 格式逐品种分析（趋势、关键位、量价配合、背离、形态），
然后在最后一行单独输出 JSON 代码块，格式如下：

```json
{{"per_symbol": {{
    "RB": {{"trend": "趋势判断", "key_levels": "支撑:xxx, 阻力:xxx", "volume_price": "量价配合", "divergence": "背离分析", "pattern": "技术形态", "score": 75, "disagreements": ["与数技源ADX方向不一致：ADX显示趋势疲惫，但数技源评分偏多", "MACD顶背离信号与均线多头排列矛盾"]}},
    "CU": {{"trend": "趋势判断", "key_levels": "支撑阻力位", "volume_price": "量价配合", "divergence": "背离", "pattern": "形态", "score": 60, "disagreements": []}}
  }},
  "summary": "总体技术面摘要"
}}
```

注意：
- **成交量（volume）和持仓量（OI）数据始终可用**，务必分析量价配合关系（放量/缩量、增仓/减仓方向）
- 衍生技术指标（RSI/ADX/MACD等）如标注"不可用"则基于均线和K线形态做定性分析
- 趋势判断需结合均线排列（MA5/MA10/MA20）和20日区间（支撑/阻力）
- 量价分析必须包含：成交量变化方向 vs 价格变化方向是否一致
- **score 请参考上方【基准技术评分】中的数值，在 ±10 范围内调整**（基准评分来自代码精确计算）
- **Phase C: refined_factor -- core factor: volatility. Output per-symbol refined_factor with direction(-2..+2), strength(0..1), confidence(0..1), source_factor=volatility, reasoning**
- - **Phase B: 请在 disagreement 字段标注与数技源扫描判断不一致的关键分歧点**（如有），例如"ADX显示趋势疲惫但数技源总分偏多"
- **v10.6.0 市场提示**: {_build_market_technical_suffix(state)}"""

    tech_result = await technical.run(context, state["trace_id"])
    tech_result["fdc_data_used"] = fdc_status.get("collected", False) if isinstance(fdc_status, dict) else False

    # Parse structured per-symbol data from LLM output
    output = tech_result.get("output", "")
    per_symbol_tech = {}
    llm_parse_ok = False
    parsed = parse_llm_output(output, agent_name="technical_researcher")
    if parsed.get("success") and isinstance(parsed.get("data"), dict):
        # 别名归一化（方案 B）：兼容 per_symbol / symbols / perSymbol 等变体
        raw_per_symbol = _resolve_alias(parsed["data"], "per_symbol") or {}
        if isinstance(raw_per_symbol, dict):
            raw_per_symbol = _normalize_per_symbol(raw_per_symbol)
        for sym in selected:
            sym_key = sym.upper()
            if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                per_symbol_tech[sym] = raw_per_symbol[sym_key]
        llm_parse_ok = len(per_symbol_tech) > 0
        # 评分钳制：确保 LLM score 在 baseline ±10 范围内
        if llm_parse_ok and baseline_scores:
            for sym in list(per_symbol_tech.keys()):
                sv = per_symbol_tech[sym]
                raw_score = sv.get("score", 50)
                base = baseline_scores.get(sym, 50)
                try:
                    clamped = max(base - 10, min(base + 10, int(raw_score)))
                    if clamped != int(raw_score):
                        logger.info(f"[TECH] {sym}: LLM评分{raw_score}偏离基准{base}±10，钳制为{clamped}")
                    sv["score"] = clamped
                except (TypeError, ValueError):
                    sv["score"] = base
    else:
        logger.warning(f"[TECH] parse_llm_output 失败: {parsed.get('errors', [])}")

    # If no per-symbol data extracted, try _repair_json fallback
    if not llm_parse_ok:
        logger.warning(f"[TECH] LLM 返回未解析出逐品种数据 ({len(output)} chars), 尝试 _repair_json 回退")
        try:
            repaired = _repair_json(output)
            if "{" in repaired and "}" in repaired:
                start = repaired.find("{")
                end = repaired.rfind("}") + 1
                fallback = json.loads(repaired[start:end])
                raw_per_symbol = _resolve_alias(fallback, "per_symbol") or {}
                if isinstance(raw_per_symbol, dict):
                    raw_per_symbol = _normalize_per_symbol(raw_per_symbol)
                for sym in selected:
                    sym_key = sym.upper()
                    if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                        per_symbol_tech[sym] = raw_per_symbol[sym_key]
                llm_parse_ok = len(per_symbol_tech) > 0
                # 评分钳制（fallback 路径）
                if llm_parse_ok and baseline_scores:
                    for sym in list(per_symbol_tech.keys()):
                        sv = per_symbol_tech[sym]
                        raw_score = sv.get("score", 50)
                        base = baseline_scores.get(sym, 50)
                        try:
                            clamped = max(base - 10, min(base + 10, int(raw_score)))
                            if clamped != int(raw_score):
                                logger.info(f"[TECH] {sym}(fallback): LLM评分{raw_score}偏离基准{base}±10，钳制为{clamped}")
                            sv["score"] = clamped
                        except (TypeError, ValueError):
                            sv["score"] = base
        except Exception as e:
            logger.warning(f"[TECH] _repair_json 回退失败: {e}")

    # Last-resort: regex per_symbol extraction from raw output
    if not llm_parse_ok and output:
        logger.warning("[TECH] 尝试正则提取 per_symbol 数据")
        try:
            extracted = {}
            for sym in selected:
                sk = sym.upper()
                ms = list(re.finditer(rf'"{sk}"\s*:\s*(\{{)', output))
                for m in ms:
                    depth = 0
                    start_i = m.start(1)
                    for i in range(start_i, len(output)):
                        if output[i] == "{":
                            depth += 1
                        elif output[i] == "}":
                            depth -= 1
                            if depth == 0:
                                obj_str = output[start_i:i + 1]
                                break
                    else:
                        continue
                    try:
                        obj = json.loads(obj_str)
                    except json.JSONDecodeError:
                        try:
                            obj = json.loads(_repair_json(obj_str))
                        except (json.JSONDecodeError, Exception):
                            continue
                    if isinstance(obj, dict):
                        extracted[sym] = _normalize_per_symbol({sym: obj}).get(sym, obj)
                        break
            if extracted:
                for sym_key in extracted:
                    if isinstance(extracted[sym_key], dict):
                        extracted[sym_key]["is_partial"] = True
                per_symbol_tech.update(extracted)
                llm_parse_ok = True
                logger.info(f"[TECH] 正则提取成功(partial): {list(extracted.keys())}")
                # 评分钳制（正则回退路径）
                if baseline_scores:
                    for sym in list(per_symbol_tech.keys()):
                        sv = per_symbol_tech[sym]
                        raw_score = sv.get("score", 50)
                        base = baseline_scores.get(sym, 50)
                        try:
                            clamped = max(base - 10, min(base + 10, int(raw_score)))
                            if clamped != int(raw_score):
                                logger.info(f"[TECH] {sym}(regex): LLM评分{raw_score}偏离基准{base}±10，钳制为{clamped}")
                            sv["score"] = clamped
                        except (TypeError, ValueError):
                            sv["score"] = base
        except Exception as e:
            logger.warning(f"[TECH] 正则提取失败: {e}")

    # If LLM parsing failed or returned incomplete, fill missing symbols from FDC data
    if not llm_parse_ok and fdc_data:
        for sym in selected:
            if sym in per_symbol_tech:
                continue
            sym_data = fdc_data.get(sym) or fdc_data.get(sym.upper()) or fdc_data.get(sym.lower())
            if not sym_data or not sym_data.get("kline", {}).get("bars"):
                continue
            bars = sym_data["kline"]["bars"]
            latest = bars[-1] if bars else {}
            close_val = float(latest.get("close", 0)) if latest else 0

            # Extract FDC computed indicators
            ind = (sym_data.get("indicators") or {}).get("values", {})
            def _iv(k):
                v = ind.get(k)
                if isinstance(v, (int, float)): return v
                if isinstance(v, list) and v: return v[-1]
                return None

            rsi = _iv("RSI14")
            adx = _iv("ADX")
            atr = _iv("ATR14")
            ma5 = _iv("MA5")
            ma20 = _iv("MA20")
            ma60 = _iv("MA60")
            cci = _iv("CCI20")
            macd_dif = _iv("MACD_DIF")
            macd_dea = _iv("MACD_DEA")
            supertrend_dir = _iv("SUPERTREND_DIR")
            bb_pctb = _iv("BB_PCTB")
            dc_pos = _iv("DC_POS")
            vol_ratio = _iv("VOL_RATIO")
            kama_cross = _iv("KAMA_CROSS")
            hma_cross = _iv("HMA_CROSS")
            atr_pct = _iv("volatility_pct")

            # Trend direction from MA alignment
            if ma5 and ma20 and ma60:
                if ma5 > ma20 > ma60:
                    ma_align = "多头排列"
                elif ma5 < ma20 < ma60:
                    ma_align = "空头排列"
                else:
                    ma_align = "震荡/粘合"
            elif ma5 and ma20:
                ma_align = "多头" if ma5 > ma20 else "空头" if ma5 < ma20 else "粘合"
            else:
                ma_align = "数据不足"

            # Trend strength from ADX
            if adx is not None:
                if adx >= 40:
                    adx_desc = f"极强趋势(ADX={adx:.1f})"
                elif adx >= 25:
                    adx_desc = f"趋势明确(ADX={adx:.1f})"
                else:
                    adx_desc = f"趋势不明(ADX={adx:.1f})"
            else:
                adx_desc = "ADX缺失"

            # RSI zone
            if rsi is not None:
                if rsi >= 70:
                    rsi_desc = f"超买区(RSI={rsi:.1f})"
                elif rsi <= 30:
                    rsi_desc = f"超卖区(RSI={rsi:.1f})"
                else:
                    rsi_desc = f"中性区(RSI={rsi:.1f})"
            else:
                rsi_desc = "RSI缺失"

            # DC channel position
            dc_desc = f"DC20位置={dc_pos:.2f}" if dc_pos is not None else "DC位置缺失"

            # MACD
            if macd_dif is not None and macd_dea is not None:
                macd_desc = f"MACD DIF={macd_dif:.2f} DEA={macd_dea:.2f} ({'多' if macd_dif > macd_dea else '空'})"
            else:
                macd_desc = "MACD缺失"

            # Supertrend
            st_desc = "多头" if supertrend_dir == 1 else "空头" if supertrend_dir == -1 else "无信号"
            if supertrend_dir is not None:
                st_desc = f"Supertrend {st_desc}"

            # Volume
            vol_desc = f"量比={vol_ratio:.2f}" if vol_ratio is not None else "量比缺失"

            # Score: simple heuristic from FDC indicators
            score = 50
            score_delta = 0
            if adx is not None and adx >= 25: score_delta += 10
            if ma_align == "多头排列": score_delta += 10
            elif ma_align == "空头排列": score_delta -= 10
            if rsi is not None:
                if rsi > 60: score_delta += 5
                elif rsi < 40: score_delta -= 5
            if macd_dif is not None and macd_dea is not None and macd_dif > macd_dea: score_delta += 5
            elif macd_dif is not None and macd_dea is not None and macd_dif < macd_dea: score_delta -= 5
            if supertrend_dir == 1: score_delta += 5
            elif supertrend_dir == -1: score_delta -= 5
            score = max(10, min(90, 50 + score_delta))

            trend_text = f"{ma_align}, {adx_desc}, {rsi_desc}, {st_desc}"
            kl_text = f"ATR={atr:.0f} ({atr_pct:.1f}%波动率)" if atr is not None and atr_pct is not None else "ATR缺失"
            vp_text = f"{vol_desc}, BB位置={bb_pctb:.2f}" if bb_pctb is not None else vol_desc

            per_symbol_tech[sym] = {
                "trend": trend_text,
                "key_levels": kl_text,
                "volume_price": vp_text,
                "divergence": macd_desc,
                "pattern": dc_desc,
                "score": score,
            }

    return {
        "technical_data": {
            "raw": tech_result,
            "per_symbol": per_symbol_tech,
        }
    }




async def node_fundamental(state: DebateState) -> dict:
    from fdt_langgraph._nodes_output import _write_research_report
    _ensure_llm_key()
    fundamental = FdtAgentExecutor("fundamental_researcher")
    selected = state.get("selected_symbols", [])
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    fdc_data = state.get("fdc_data", {})
    fdc_status = state.get("fdc_data_status", {})

    scan_results = state.get("scan_results", {})
    fdc_fund_context = _build_market_fundamental_context(selected, fdc_data, scan_results)

    # 通过 NewsRouter 获取实时新闻数据
    from data_adapter.news import NewsRouter
    from data_adapter.news.types import NewsQuery
    _news_router = NewsRouter()
    _news_query = NewsQuery(symbols=selected, max_age_hours=48, max_per_symbol=3)
    jin10_context = _news_router.build_prompt_context(await _news_router.fetch(_news_query))

    # ── P2.5 多空持仓因子注入 ──
    hs_context = ""
    try:
        factor_hs = state.get("factor_holding_sentiment", {})
        if factor_hs:
            hs_parts = ["\n【多空持仓因子（P2.5 采集）】"]
            for sym in selected:
                hs = factor_hs.get(sym.upper())
                if hs and getattr(hs, "data_grade", "") == "PRIMARY":
                    parts = []
                    if hs.long_short_ratio is not None:
                        parts.append(f"多空比={hs.long_short_ratio}")
                    if hs.total_long is not None:
                        parts.append(f"多单={hs.total_long}")
                    if hs.total_short is not None:
                        parts.append(f"空单={hs.total_short}")
                    if hs.top20_ratio is not None:
                        parts.append(f"前20多空比={hs.top20_ratio}")
                    if parts:
                        hs_parts.append(f"  {sym}: {' | '.join(parts)}")
            if len(hs_parts) > 1:
                hs_context = "\n".join(hs_parts)
    except Exception:
        pass

    # ── 北向资金因子注入（探源 — 外资态度指标） ──
    nf_context = ""
    try:
        factor_nf = state.get("factor_north_flow", {})
        if factor_nf:
            nf_parts = ["\n【北向资金因子（腾讯自选股）】"]
            for sym in selected:
                nf = factor_nf.get(sym.upper())
                if nf and nf.get("data_grade") == "PRIMARY":
                    parts = []
                    hold = nf.get("north_holding")
                    pct = nf.get("north_holding_pct")
                    buy = nf.get("north_net_buy")
                    if hold is not None:
                        parts.append(f"北向持仓={hold:.0f}")
                    if pct is not None:
                        parts.append(f"占比={pct:.2f}%")
                    if buy is not None:
                        parts.append(f"净买入={buy:+.0f}")
                    if parts:
                        nf_parts.append(f"  {sym}: {' | '.join(parts)}")
            if len(nf_parts) > 1:
                nf_context = "\n".join(nf_parts)
    except Exception:
        pass

    context = f"""作为基本面研究员（探源），请分析以下品种的基本面状态：

市场方向判断: {direction}
待分析品种: {selected}

【市场基本面数据（AKShare 实时源，P2.5 预采集）】
{fdc_fund_context}

{jin10_context}
{hs_context}
{nf_context}
{_build_wind_context_block(state.get("wind_data"))}

请先以 Markdown 格式逐品种分析（供需平衡、库存周期、利润开工率、基差期限结构、宏观联动），
然后在最后一行单独输出 JSON 代码块，格式如下：

```json
{{"per_symbol": {{
    "RB": {{"supply_demand": "供需平衡分析", "inventory": "库存周期定位", "profit_margin": "利润与开工率", "basis_term": "基差与期限结构", "macro_external": "宏观与外盘联动", "leading_signals": ["领先信号1", "信号2"], "key_turning_points": [{{"data": "库存数据连续3周去化", "impact": "bull", "note": "关键转折：由累库转为去库"}}]}},
    "CU": {{"supply_demand": "...", "inventory": "...", "profit_margin": "...", "basis_term": "...", "macro_external": "...", "leading_signals": [...], "key_turning_points": []}}
  }},
  "summary": "总体基本面摘要"
}}
```

重要注意事项：
- 上方【市场基本面数据】区域中的数据为预采集数据，部分字段可能标记"不可用"
- **请务必使用 WebSearch 搜索以下内容补充基本面数据**：
  - 每个品种的供需/库存/开工率最新数据
  - 搜索关键词建议："{selected[0] if selected else ''} 供需 库存 2026年"
- 金十快讯区域（如可用）可作为实时素材，引用时标注 [jin10]
- WebSearch 获取的数据引用时标注 [fundamental:web]
- 每个品种的 leading_signals 为数组，包含1-3个关键信号
- **Phase B: `key_turning_points` 字段标注对方向具有边际影响的关键转折数据**，包含数据描述、影响方向和说明（如"库存由累库转去库"）
- **Phase C: refined_factors -- core factors: holding_sentiment+term_structure. Output per-symbol refined_factors with direction/strength/confidence/source_factor/reasoning**
- **v10.6.0: 市场类型感知** — 以下指令根据品种市场类型动态注入：

{_build_market_fundamental_suffix(state)}"""

    fund_result = await fundamental.run(context, state["trace_id"])
    fund_result["fdc_data_used"] = fdc_status.get("collected", False) if isinstance(fdc_status, dict) else False

    # Parse structured per-symbol data from LLM output
    output = fund_result.get("output", "")
    per_symbol_fund = {}
    llm_parse_ok = False
    parsed = parse_llm_output(output, agent_name="fundamental_researcher")
    if parsed.get("success") and isinstance(parsed.get("data"), dict):
        # 别名归一化（方案 B）：兼容 per_symbol / symbols / perSymbol 等变体
        raw_per_symbol = _resolve_alias(parsed["data"], "per_symbol") or {}
        if isinstance(raw_per_symbol, dict):
            raw_per_symbol = _normalize_per_symbol(raw_per_symbol)
        for sym in selected:
            sym_key = sym.upper()
            if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                per_symbol_fund[sym] = raw_per_symbol[sym_key]
        llm_parse_ok = len(per_symbol_fund) > 0
    else:
        logger.warning(f"[FUND] parse_llm_output 失败: {parsed.get('errors', [])}")

    # If no per-symbol data, try _repair_json fallback
    if not llm_parse_ok:
        logger.warning(f"[FUND] LLM 返回未解析出逐品种数据 ({len(output)} chars), 尝试 _repair_json 回退")
        try:
            repaired = _repair_json(output)
            if "{" in repaired and "}" in repaired:
                start = repaired.find("{")
                end = repaired.rfind("}") + 1
                fallback = json.loads(repaired[start:end])
                raw_per_symbol = _resolve_alias(fallback, "per_symbol") or {}
                if isinstance(raw_per_symbol, dict):
                    raw_per_symbol = _normalize_per_symbol(raw_per_symbol)
                for sym in selected:
                    sym_key = sym.upper()
                    if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                        per_symbol_fund[sym] = raw_per_symbol[sym_key]
                llm_parse_ok = len(per_symbol_fund) > 0
        except Exception as e:
            logger.warning(f"[FUND] _repair_json 回退失败: {e}")

    # Last-resort: regex per_symbol extraction from raw output
    if not llm_parse_ok and output:
        logger.warning("[FUND] 尝试正则提取 per_symbol 数据")
        try:
            extracted = {}
            for sym in selected:
                sk = sym.upper()
                # 匹配 "SYM": { 后找到匹配的闭合大括号
                ms = list(re.finditer(rf'"{sk}"\s*:\s*(\{{)', output))
                for m in ms:
                    depth = 0
                    start_i = m.start(1)
                    for i in range(start_i, len(output)):
                        if output[i] == "{":
                            depth += 1
                        elif output[i] == "}":
                            depth -= 1
                            if depth == 0:
                                obj_str = output[start_i:i + 1]
                                break
                    else:
                        continue
                    try:
                        obj = json.loads(obj_str)
                    except json.JSONDecodeError:
                        try:
                            obj = json.loads(_repair_json(obj_str))
                        except (json.JSONDecodeError, Exception):
                            continue
                    if isinstance(obj, dict):
                        extracted[sym] = _normalize_per_symbol({sym: obj}).get(sym, obj)
                        break
            if extracted:
                for sym_key in extracted:
                    if isinstance(extracted[sym_key], dict):
                        extracted[sym_key]["is_partial"] = True
                per_symbol_fund.update(extracted)
                llm_parse_ok = True
                logger.info(f"[FUND] 正则提取成功(partial): {list(extracted.keys())}")
        except Exception as e:
            logger.warning(f"[FUND] 正则提取失败: {e}")

    # If LLM parsing failed or returned incomplete, fill missing symbols from FDC data
    if not llm_parse_ok and fdc_data:
        for sym in selected:
            if sym in per_symbol_fund:
                continue
            sym_data = fdc_data.get(sym) or fdc_data.get(sym.upper()) or fdc_data.get(sym.lower())
            if not sym_data:
                per_symbol_fund[sym] = {"supply_demand":"基本面数据暂缺","inventory":"无数据","profit_margin":"无数据","basis_term":"无数据","leading_signals":[]}
                continue
            def _f10s(fn):
                entry = sym_data.get(fn)
                if not entry or "error" in (entry if isinstance(entry, dict) else {}):
                    return None
                summary = entry.get("summary") if isinstance(entry, dict) else None
                if summary and isinstance(summary, str) and len(summary) > 5:
                    s = summary.strip()
                    if not re.search(r'(independent|暂缺|待[核实查计算]|占位|placeholder)', s, re.I) and not re.match(r'^[a-zA-Z]{1,4}\s*基本面', s):
                        return s[:120]
                data = entry.get("data") if isinstance(entry, dict) else None
                if isinstance(data, dict) and data:
                    skip_k = {"symbol","structure","exchange","product_id"}
                    skip_v = {"UNKNOWN","unknown","N/A","","None","none"}
                    parts = []
                    for k, v in list(data.items())[:6]:
                        if k not in skip_k and isinstance(v,(int,float,str)) and str(v).strip() and str(v).strip() not in skip_v:
                            parts.append(f"{k}={v}")
                    return ", ".join(parts)[:120] if parts else None
                return None
            ts=_f10s("term_structure"); sp=_f10s("spread"); ba=_f10s("basis"); fu=_f10s("fundamental"); wa=_f10s("warrant"); ff=_f10s("fund_flow")
            available = [fn for fn in ["term_structure","spread","basis","warrant","fundamental","fund_flow"] if sym_data.get(fn) and "error" not in (sym_data.get(fn) if isinstance(sym_data.get(fn),dict) else {})]
            sd_parts = []
            if ts: sd_parts.append(f"期限结构: {ts}")
            if sp: sd_parts.append(f"价差: {sp}")
            if fu: sd_parts.append(f"基本面: {fu}")
            ind = (sym_data.get("indicators") or {}).get("values", {})
            def _iv(k):
                v = ind.get(k)
                return v if isinstance(v,(int,float)) else (v[-1] if isinstance(v,list) and v else None)
            rsi=_iv("RSI14"); adx=_iv("ADX")
            supply_demand = "; ".join(sd_parts) if sd_parts else (f"技术面偏弱(RSI={rsi:.1f}, ADX={adx:.1f})，供需可能宽松" if rsi and adx and adx>25 and rsi<40 else f"技术面偏强(RSI={rsi:.1f}, ADX={adx:.1f})，供需可能偏紧" if rsi and adx and adx>25 and rsi>60 else f"趋势不明(ADX={adx:.1f})，供需均衡" if adx else "基本面数据暂缺")
            inventory = "无数据"
            if fu and ("库存" in fu or "仓单" in fu): inventory = fu[:150]
            elif wa and "仓单" in str(wa): inventory = str(wa)[:150]
            bt_parts = []
            if ba: bt_parts.append(f"基差: {ba}")
            if ts: bt_parts.append(f"期限: {ts}")
            basis_term = "; ".join(bt_parts) if bt_parts else "期限结构与基差待计算"
            leading = []
            pr = sym_data.get("position_ranking")
            if pr and isinstance(pr,dict):
                prd = pr.get("data")
                if isinstance(prd,dict):
                    t = prd.get("top1_name","")
                    c = prd.get("top1_change","")
                    if t: leading.append(f"持仓第一: {t}")
                    if c and str(c)!="0": leading.append(f"持仓变化: {c}")
            ffd = sym_data.get("fund_flow")
            if ffd and isinstance(ffd,dict):
                ffd_data = ffd.get("data")
                if isinstance(ffd_data,dict):
                    lr = ffd_data.get("long_short_ratio")
                    if lr is not None: leading.append(f"多空比: {lr}")
            if not leading: leading = ["持仓数据暂缺"]
            per_symbol_fund[sym] = {"supply_demand":supply_demand,"inventory":inventory,"profit_margin":fu if fu else "利润和开工率数据待查","basis_term":basis_term,"leading_signals":leading}

    return {
        "fundamental_data": {
            "raw": fund_result,
            "per_symbol": per_symbol_fund,
        }
    }




async def node_sentiment(state: DebateState) -> dict:
    """新闻情绪分析（P3）— 与链证源/观澜/探源并行。

    从 NewsRouter（多源聚合）获取新闻数据，由读心 Agent 加工为 SentimentStateVector。
    Agent 只分析不搜索，数据已在适配层完成采集。
    """
    _ensure_llm_key()
    sentiment_agent = FdtAgentExecutor("news_sentiment_analyst")
    selected = state.get("selected_symbols", [])

    # ── 通过 NewsRouter 获取聚合新闻数据（替换 _build_jin10_context） ──
    from data_adapter.news import NewsRouter
    from data_adapter.news.types import NewsQuery
    router = NewsRouter()
    query = NewsQuery(symbols=selected, max_age_hours=48, max_per_symbol=5)
    news_result = await router.fetch(query)
    news_context = router.build_prompt_context(news_result)

    # ── 逐品种新闻质量评估（通过 NewsRouter） ──
    # HARNESS FIX: news empty -> FDC data for sentiment
    news_quality = router.build_quality_report(news_result, selected)
    _all_news_empty = "No" in news_context or not getattr(news_result, "items", [])
    if _all_news_empty:
        _fdc = state.get("fdc_data", state.get("fundamental_data", {}))
        _chain = state.get("chain_analysis") or {}
        _extra = ["\n\n(Market snapshot from FDC, for sentiment inference)"]
        for _s in selected:
            _fs = _fdc.get(_s, _fdc.get(_s.upper(), {}))
            _cs = _chain.get(_s, _chain.get(_s.upper(), {}))
            _fund = {}
            _ff = _fs.get("fundamental", {}) if isinstance(_fs, dict) else {}
            if isinstance(_ff, dict):
                _fund = _ff.get("data", _ff)
            if isinstance(_fund, dict) and _fund:
                _extra.append(f"  [_s] opr:{_fund.get('operating_rate','?')}% inv:{_fund.get('inventory','?')}kt fee:{_fund.get('processing_fee','?')}")
                ns = _fund.get("notes","")
                if ns: _extra.append(f"    note: {str(ns)[:200]}")
            if isinstance(_cs, dict) and _cs.get("chain"):
                _extra.append(f"  [_s] chain:{_cs.get('chain','')} trend:{_cs.get('chain_trend','')}")
        _extra.append("(Infer market sentiment from above, tag [fdc])")
        news_context += "\n".join(_extra)

    context = f"""作为新闻情绪分析师（读心），请分析以下品种的新闻情绪状态。

待分析品种: {selected}

【实时新闻（多源聚合，已预采集，引用时标注来源标签）】
{news_context}

注意：新闻数据已由系统预采集完毕，你只需分析即可，无需自行搜索。

输出格式要求（JSON，顶级字段必须包含 per_symbol 和 summary）：

```json
{{
  "per_symbol": {{
    "品种代码1": {{
      "overall_sentiment": -0.3,
      "sentiment_breakdown": {{"policy": 0.0, "supply_demand": -0.5, "macro": 0.0, "geopolitics": 0.0, "other": 0.0}},
      "hot_volume": 1500,
      "key_events": [
        {{"type": "supply_demand", "content": "事件描述", "score": -0.5, "time": "2026-07-25", "source": "jin10", "confidence": 0.8}}
      ],
      "divergence": 0.15
    }},
    "品种代码2": {{...}}
  }},
  "summary": "整体情绪总结",
  "composite_score": -0.2
}}
```

注意：
- 不下多空结论，只输出情绪评分
- 事件类型：policy / supply_demand / macro / geopolitics / other
- 越近的快讯权重越高（<1h:1.0, 1-4h:0.7, 4-24h:0.4, >24h:0.1）
- 情绪偏离度 > 0.3 时标注（这是辩论最有价值的素材）
- **Phase C: refined_factor -- core factor: sentiment. Output per-symbol refined_factor with direction/strength/confidence/source_factor=sentiment/reasoning**
{_build_wind_context_block(state.get("wind_data"))}"""

    result = await sentiment_agent.run(context, state["trace_id"])

    # ── 解析 LLM 结构化输出（v9.26.0 修复：此前缺失 parse_llm_output 调用） ──
    output_raw = result.get("output", "") if isinstance(result, dict) else ""
    parsed = parse_llm_output(output_raw, agent_name="news_sentiment_analyst")
    per_symbol_sentiment = {}
    overall_score = 0.0
    summary_text = ""
    if parsed.get("success") and isinstance(parsed.get("data"), dict):
        data = parsed["data"]
        per_symbol_sentiment = data.get("per_symbol", {})
        # v10.7.0 fix: 从 per_symbol 的 overall_sentiment 计算均值，
        # 不依赖可选的顶级 composite_score 字段（LLM 可能省略）。
        # 每品种 overall_sentiment 是 prompt 示例中的必含字段，更可靠。
        sym_scores = [
            s.get("overall_sentiment", 0)
            for s in per_symbol_sentiment.values()
            if isinstance(s, dict) and s.get("overall_sentiment") is not None
        ]
        if sym_scores:
            overall_score = sum(sym_scores) / len(sym_scores)
        else:
            # 回退到 composite_score（如 LLM 同时省略了二者）
            overall_score = data.get("composite_score", 0) or 0
        summary_text = data.get("summary", "")
        if isinstance(overall_score, dict):
            overall_score = sum(overall_score.values()) / max(len(overall_score), 1)
        overall_score = round(float(overall_score), 2)
    else:
        # fallback: 从原始 LLM 输出文本尝试二次解析
        per_symbol_sentiment = {}
        overall_score = 0.0
        summary_text = ""
        if output_raw:
            try:
                from scripts.enforce_structured_output import auto_fix_json
                fb_parsed = json.loads(auto_fix_json(output_raw))
                if isinstance(fb_parsed, dict):
                    per_symbol_sentiment = fb_parsed.get("per_symbol", {})
                    fb_scores = [
                        s.get("overall_sentiment", 0)
                        for s in per_symbol_sentiment.values()
                        if isinstance(s, dict) and s.get("overall_sentiment") is not None
                    ]
                    overall_score = sum(fb_scores) / len(fb_scores) if fb_scores else (fb_parsed.get("composite_score", 0) or 0)
                    summary_text = fb_parsed.get("summary", "")
            except Exception:
                pass
        if not overall_score:
            overall_score = 0.0
        if isinstance(overall_score, dict):
            overall_score = sum(overall_score.values()) / max(len(overall_score), 1)
        overall_score = round(float(overall_score), 2)

    return {
        "sentiment_data": {
            "raw": result,
            "news_quality": news_quality,
            "overall_score": overall_score,
            "summary": summary_text,
            "per_symbol": per_symbol_sentiment,
        }
    }


# ── v10.6.0: 市场类型感知辅助函数 ──────────────────────


def _build_market_fundamental_suffix(state: DebateState) -> str:
    """根据品种市场类型返回基本面分析的额外指令"""
    mt = state.get("market_type", "commodity_futures")
    instructions = {
        "index_futures": (
            "【股指期货特别说明】\n"
            "- 基本面分析重心：宏观经济（PMI/GDP/CPI）、货币政策（利率/准备金）、\n"
            "  财政政策、市场估值（PE/PB）、资金面（北向/两融）\n"
            "- 不做供需平衡分析，不做库存周期分析\n"
            "- 关注成分股结构、权重股表现、行业轮动\n"
            "- leading_signals 应为宏观领先指标（社融/信贷/PMI 新订单）"
        ),
        "bond_futures": (
            "【国债期货特别说明】\n"
            "- 基本面分析重心：货币政策（OMO/MLF/LPR）、通胀（CPI/PPI）、\n"
            "  经济增长预期、财政赤字、信用利差、收益率曲线形态\n"
            "- 不做供需平衡分析，不做库存周期分析\n"
            "- 关注期限利差（10-2Y）、中美利差、银行间流动性\n"
            "- leading_signals 应为利率领先指标（CPI/PPI/社融）"
        ),
        "etf": (
            "【ETF 特别说明】\n"
            "- 基本面分析重心：标的指数估值（PE/PB）、成分股结构、权重集中度、\n"
            "  行业分布、溢价率/折价率、份额变化趋势\n"
            "- 分析跟踪误差、流动性（日均成交额）\n"
            "- 不做供需/库存/基差分析\n"
            "- leading_signals 应为指数驱动因素"
        ),
    }
    return instructions.get(mt, "")


def _build_market_technical_suffix(state: DebateState) -> str:
    """根据品种市场类型返回技术分析的额外提示"""
    mt = state.get("market_type", "commodity_futures")
    hints = {
        "index_futures": "注意：趋势判断应结合成分股指数结构",
        "bond_futures": "注意：国债期货需关注 CTD 券转换和交割月效应",
        "etf": "注意：折溢价可能对技术指标产生干扰，分析时应结合净值参考",
    }
    hint = hints.get(mt, "")
    return f"\n- **v10.6.0 市场提示**: {hint}" if hint else ""


# ==================== 逐品种循环节点 (v9.13.0) ====================



async def node_merge_research(state: DebateState) -> DebateState:
    merged_data = {
        "chain_analysis": state.get("chain_analysis", {}),
        "technical_data": state.get("technical_data", {}),
        "fundamental_data": state.get("fundamental_data", {}),
        "sentiment_data": state.get("sentiment_data", {}),
        "dispatch_sources": state.get("dispatch_sources", []),
    }
    new_phases = state["completed_phases"] + ["P2"]

    # v9.12.0: 研究报告 (P2 阶段) — 仅 FDT_GENERATE_INTERMEDIATE_REPORTS=true 时生成
    research_report_path = None
    if os.environ.get("FDT_GENERATE_INTERMEDIATE_REPORTS", "").lower() == "true":
        try:
            report_dir = _resolve_report_dir()
            research_report_path = _write_research_report(state["trace_id"], merged_data, report_dir)
            logger.info(f"[MERGE] 研究报告: {research_report_path}")
        except Exception as e:
            logger.warning(f"[MERGE] 研究报告生成失败: {e}")
    else:
        logger.debug("[MERGE] 研究报告跳过 (FDT_GENERATE_INTERMEDIATE_REPORTS 未设置)")

    return {
        **state,
        "research_data": merged_data,
        "research_report_path": research_report_path,
        "current_phase": "P2",
        "completed_phases": new_phases
    }



