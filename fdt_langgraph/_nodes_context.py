"""上下文构建函数 — 为 LLM prompt 构建结构化上下文。

依赖 _nodes_utils。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

def _build_scan_signal_table(all_ranked: list, symbols: list, header_suffix: str = "") -> list:
    """生成数技源扫描信号对照表的格式化行列表。"""
    lines: list[str] = []
    lines.append(f"\n\n【数技源扫描信号对照（TDX数据源）{header_suffix}】")
    lines.append("品种 | 方向 | 总分 | 等级 | RSI | ADX | 均线排列 | 子策略一致性")
    lines.append("-" * 80)
    for item in all_ranked:
        sym = item.get("symbol", "").upper()
        if sym not in [s.upper() for s in symbols]:
            continue
        dir_map = {"bull": "多头", "bear": "空头", "neutral": "中性"}
        dir_str = dir_map.get(item.get("direction", ""), item.get("direction", ""))
        total = item.get("total", 0)
        grade = item.get("grade", "N/A")
        rsi = item.get("rsi", "N/A")
        adx = item.get("adx", "N/A")
        ma = item.get("ma_align", "N/A")
        sub_sigs = item.get("sub_signals", [])
        sub_bear = sum(1 for s in sub_sigs if s.get("direction") in ("bear", "SELL"))
        sub_bull = sum(1 for s in sub_sigs if s.get("direction") in ("bull", "BUY"))
        sub_total = len(sub_sigs)
        consistency = f"空{sub_bear}/多{sub_bull}/共{sub_total}" if sub_total else "N/A"
        lines.append(f"{sym} | {dir_str} | {total} | {grade} | {rsi} | {adx} | {ma} | {consistency}")
    return lines




def _build_fdc_technical_context(symbols: list[str], fdc_data: dict, scan_results: dict | None = None) -> str:
    """[别名] 同 _build_market_technical_context"""
    return _build_market_technical_context(symbols, fdc_data, scan_results)




def _build_market_technical_context(symbols: list[str], market_data: dict, scan_results: dict | None = None) -> str:
    if not market_data:
        return "（市场技术数据暂不可用，基于扫描数据进行分析）"
    lines = []
    for symbol in symbols:
        sym_data = market_data.get(symbol) or market_data.get(symbol.upper()) or market_data.get(symbol.lower())
        if not sym_data:
            lines.append(f"\n【{symbol}】无 FDC 数据")
            continue
        lines.append(f"\n【{symbol}】市场技术数据")
        kline = sym_data.get("kline", {})
        if kline and kline.get("bars"):
            bars = kline["bars"]
            latest = bars[-1] if bars else {}
            prev = bars[-2] if len(bars) >= 2 else {}
            change_pct = 0.0
            if latest and prev and float(prev.get("close", 1)) != 0:
                change_pct = (float(latest.get("close", 0)) - float(prev.get("close", 0))) / float(prev.get("close", 1)) * 100
            lines.append(f"  最新价: {latest.get('close')} ({change_pct:+.2f}%)")
            lines.append(f"  最高/最低: {latest.get('high')} / {latest.get('low')}")
            vol = latest.get('volume', 0) or 0
            oi = latest.get('open_interest') or latest.get('oi') or 0
            lines.append(f"  成交量: {float(vol):.0f}, 持仓量: {float(oi):.0f}")
            lines.append(f"  K线数量: {len(bars)}根")
            if len(bars) >= 20:
                recent_closes = [float(b.get("close", 0)) for b in bars[-20:]]
                ma5 = sum(recent_closes[-5:]) / 5 if len(recent_closes) >= 5 else 0
                ma10 = sum(recent_closes[-10:]) / 10 if len(recent_closes) >= 10 else 0
                ma20 = sum(recent_closes[-20:]) / 20 if len(recent_closes) >= 20 else 0
                lines.append(f"  均线: MA5={ma5:.2f}, MA10={ma10:.2f}, MA20={ma20:.2f}")
                highs = [float(b.get("high", 0)) for b in bars[-20:]]
                lows = [float(b.get("low", 0)) for b in bars[-20:]]
                lines.append(f"  20日区间: 支撑={min(lows):.2f}, 阻力={max(highs):.2f}")
            # 量价数据可用标识（即便无衍生指标）
            lines.append("  量价数据状态: ✅ 可用（含成交量、持仓量、K线形态）")
        else:
            lines.append("  K线数据: 不可用")
        indicators = sym_data.get("indicators", {})
        if indicators and indicators.get("available"):
            avail = indicators["available"]
            lines.append(f"  技术指标状态: ✅ {len(avail)}组可用")
            values = indicators.get("values", {})
            if values:
                latest_ind = {}
                for name, val in values.items():
                    if isinstance(val, list) and val:
                        latest_ind[name] = val[-1]
                    elif isinstance(val, (int, float)):
                        latest_ind[name] = val
                if latest_ind:
                    lines.append("  关键指标最新值:")
                    for name, val in list(latest_ind.items())[:8]:
                        if isinstance(val, float):
                            lines.append(f"    - {name}: {val:.4f}")
                        else:
                            lines.append(f"    - {name}: {val}")
        else:
            lines.append("  技术指标状态: ⚠️ 衍生指标暂不可用（K线/量价数据仍然可用）")
        grades = sym_data.get("data_grades", {})
        if grades:
            lines.append(f"  数据质量: K线={grades.get('kline','?')}, 指标={grades.get('indicators','?')}")

        # ── 持仓排名（观澜消费 — 持仓结构/前20席位） ──
        pr = sym_data.get("position_ranking", {})
        pr_data = pr.get("data") if isinstance(pr, dict) and "error" not in str(pr.get("data", {})) else None
        if pr_data and isinstance(pr_data, dict):
            nl = pr_data.get("net_long", "")
            t5l = pr_data.get("top5_long", "")
            t5s = pr_data.get("top5_short", "")
            parts = []
            if nl != "" and nl is not None: parts.append(f"净多:{nl}")
            if t5l: parts.append(f"前5多:{t5l}")
            if t5s: parts.append(f"前5空:{t5s}")
            if parts: lines.append(f"  持仓排名: {' | '.join(parts)}")

        # ── 资金流向（观澜消费 — 多空比） ──
        ff = sym_data.get("fund_flow", {})
        ff_data = ff.get("data") if isinstance(ff, dict) and "error" not in str(ff.get("data", {})) else None
        if ff_data and isinstance(ff_data, dict):
            lr = ff_data.get("long_short_ratio")
            oi = ff_data.get("total_oi")
            lv = ff_data.get("long_volume")
            sv = ff_data.get("short_volume")
            ff_parts = []
            if oi is not None: ff_parts.append(f"总持仓:{oi}")
            if lv is not None: ff_parts.append(f"多头:{lv}")
            if sv is not None: ff_parts.append(f"空头:{sv}")
            if lr is not None: ff_parts.append(f"多空比:{lr}")
            if ff_parts: lines.append(f"  资金流向: {' | '.join(ff_parts)}")

        # ── 外盘数据（观澜消费 — 外盘技术面参考） ──
        foreign = sym_data.get("foreign", {})
        foreign_data = foreign.get("data") if isinstance(foreign, dict) and "error" not in str(foreign.get("data", {})) else None
        if foreign_data and isinstance(foreign_data, dict):
            fsym = foreign_data.get("foreign_symbol", "")
            fclose = foreign_data.get("close", "")
            fcp = foreign_data.get("change_pct", "")
            if fsym:
                fp = f"{fsym} {fclose}"
                if fcp is not None: fp += f" ({fcp:+.2f}%)" if isinstance(fcp, (int, float)) else f" ({fcp})"
                lines.append(f"  外盘: {fp}")

    # ── P1角色矫正：注入 stats 纯统计特征（观澜主要参考依据） ──
    if scan_results:
        all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
        stats_items = [r for r in all_ranked if r.get("symbol", "").upper() in [s.upper() for s in symbols] and r.get("stats")]
        if stats_items:
            lines.append("\n\n【数技源统计特征（P1 stats，纯定量事实）】")
            lines.append("品种 | 收盘 | 涨跌% | MA20 | MA60 | 排列 | ATR | RSI | ADX | +DI | -DI | 量能比 | 持仓增 | 20日位%")
            lines.append("-" * 120)
            for item in stats_items:
                st = item["stats"]
                sym = item.get("symbol", "").upper()
                lines.append(
                    f"{sym} | {st.get('latest_close',0)} | {st.get('change_pct',0):+.2f} | "
                    f"{st.get('ma_20',0):.0f} | {st.get('ma_60',0):.0f} | {st.get('ma_align','?')} | "
                    f"{st.get('atr_14',0):.0f} | {st.get('rsi_14',50):.1f} | {st.get('adx_14',25):.1f} | "
                    f"{st.get('di_plus',0):.1f} | {st.get('di_minus',0):.1f} | "
                    f"{st.get('volume_ma20_ratio',0):.2f}x | {st.get('oi_change',0)} | "
                    f"{st.get('price_position_pct',50):.1f}"
                )

    # ── 追加数技源扫描对照（让观澜同时看到两套数据，做交叉验证） ──
    if scan_results:
        all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
        if all_ranked:
            lines.extend(_build_scan_signal_table(all_ranked, symbols, "— 仅供参考"))

    # v9.22.4: 追加 Vector Memory 历史模式（通过 MemoryManager）
    try:
        from memory.manager import get_memory
        memory = get_memory()
        memory_sections = []
        for sym in symbols[:3]:  # 最多 3 个品种
            records = memory.retrieve_similar(sym, top_k=3)
            if records:
                mem_lines = [f"品种: {sym}"]
                for i, rec in enumerate(records, 1):
                    mem_lines.append(
                        f"  {i}. 方向={rec.get('direction', 'N/A')} | "
                        f"置信度={rec.get('confidence', 'N/A')} | "
                        f"理由={str(rec.get('reason', ''))[:80]}"
                    )
                memory_sections.append("\n".join(mem_lines))
        if memory_sections:
            lines.append("\n\n【品种历史模式】\n" + "\n---\n".join(memory_sections))
    except Exception as e:
        logger.debug(f"[FUND] VectorMemory 查询失败 (非关键): {e}")

    return "\n".join(lines)




def _build_fdc_fundamental_context(symbols: list[str], fdc_data: dict, scan_results: dict | None = None) -> str:
    """[别名] 同 _build_market_fundamental_context"""
    return _build_market_fundamental_context(symbols, fdc_data, scan_results)




def _build_market_fundamental_context(symbols: list[str], market_data: dict, scan_results: dict | None = None) -> str:
    if not market_data:
        return "（市场基本面数据暂不可用）"
    lines = []
    for symbol in symbols:
        sym_data = market_data.get(symbol) or market_data.get(symbol.upper()) or market_data.get(symbol.lower())
        if not sym_data:
            lines.append(f"\n【{symbol}】无市场数据")
            continue
        lines.append(f"\n【{symbol}】市场基本面数据")
        for field_name, label in [("term_structure", "期限结构"), ("basis", "基差"),
                                   ("spread", "价差"), ("warrant", "仓单"),
                                   ("position_ranking", "持仓排名"), ("fund_flow", "资金流向"),
                                   ("fundamental", "基本面")]:
            field = sym_data.get(field_name, {})
            if field and "error" not in field and field.get("data_grade") != "UNAVAILABLE":
                lines.append(f"  {label}:")
                f_data = field.get("data", {})
                if isinstance(f_data, dict):
                    for key in list(f_data.keys())[:5]:
                        val = f_data[key]
                        lines.append(f"    {key}: {val}")
                if field.get("summary"):
                    lines.append(f"    摘要: {field['summary']}")
            elif field_name == "position_ranking":
                lines.append(f"  {label}: AKShare 数据不可用，请通过 WebSearch 搜索该品种的持仓排名数据（交易所官网或行业网站）")
            elif field_name == "fundamental":
                lines.append(f"  {label}: 无固定数据源，请通过 WebSearch/WebFetch 获取行业机构公开数据（供需/库存/利润/政策等）")
            else:
                lines.append(f"  {label}: 不可用")
        f10_summary = sym_data.get("f10_summary", {})
        if f10_summary:
            lines.append(f"  F10覆盖率: {f10_summary.get('coverage_pct',0)}%")
        grades = sym_data.get("data_grades", {})
        if grades:
            f10_grades = {k: v for k, v in grades.items() if k in
                          ["term_structure", "basis", "spread", "warrant", "position_ranking", "fund_flow", "fundamental"]}
            if f10_grades:
                lines.append(f"  数据质量: {json.dumps(f10_grades, ensure_ascii=False)}")
        # ── Data Governance Phase 2: F10 质量详情 ──
        f10_q = sym_data.get("f10_quality", {})
        if f10_q and f10_q.get("f10_issues"):
            lines.append(f"  ⚠️ F10质量: {f10_q.get('f10_overall','?')}级 | "
                         f"可用{f10_q.get('f10_available',0)}/{f10_q.get('f10_total',0)} | "
                         f"问题: {'; '.join(f10_q['f10_issues'][:3])}")
        ind_q = sym_data.get("indicator_quality", {})
        if ind_q:
            qual_parts = []
            if ind_q.get("overall"):
                qual_parts.append(f"{ind_q['overall']}级")
            if ind_q.get("n_nan", 0) > 0:
                qual_parts.append(f"NaN={ind_q['n_nan']}")
            if ind_q.get("n_inf", 0) > 0:
                qual_parts.append(f"Inf={ind_q['n_inf']}")
            qual_parts.append(f"指标{ind_q.get('completeness', '?/8')}")
            lines.append(f"  技术指标质量: {' | '.join(qual_parts)}")

    # ── 追加数技源扫描对照 ──
    if scan_results:
        all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
        if all_ranked:
            lines.extend(_build_scan_signal_table(all_ranked, symbols))

    # ── Phase 3.7: 清洗质量警告注入（探源 Agent 数据质量感知） ──
    for symbol in symbols:
        sym_data = market_data.get(symbol) or market_data.get(symbol.upper()) or market_data.get(symbol.lower())
        if not sym_data:
            continue
        quality_warnings = []
        for dtype in ("basis", "warrant", "position_ranking", "fund_flow"):
            field = sym_data.get(dtype, {})
            cleaning = field.get("_cleaning") if isinstance(field, dict) else None
            if cleaning and cleaning.get("total_actions", 0) > 0:
                for act in cleaning.get("actions", []):
                    if act.get("action") == "marked" and "stale" in act.get("reason", ""):
                        quality_warnings.append(f"  ⏳ {dtype} 数据过期: {act['reason']}")
                    if act.get("action") == "marked" and "caliber" in act.get("reason", ""):
                        quality_warnings.append(f"  🔧 {dtype} 口径变更: {act['reason']}")
                    if act.get("action") == "marked" and "missing" in act.get("reason", ""):
                        quality_warnings.append(f"  ⚠️ {dtype} 字段缺失: {act['reason']}")
        if quality_warnings:
            lines.append(f"\n【{symbol}】数据质量提示")
            lines.extend(quality_warnings[:4])  # 最多 4 条

    # ── G-6D-06: vector_memory 历史记忆注入 ──
    try:
        from scripts.vector_memory import VectorMemory
        vm = VectorMemory()
        for symbol in symbols:
            memories = vm.query(symbol, top_k=3)
            if memories:
                lines.append(f"\n📜【{symbol}】历史记忆")
                for m in memories:
                    rec = m["record"]
                    ts = rec.get("timestamp", "")[:10]
                    direction = {"long": "多头", "short": "空头"}.get(rec.get("direction", ""), rec.get("direction", ""))
                    pnl = rec.get("pnl", 0)
                    pnl_label = f"盈利{pnl}" if pnl >= 0 else f"亏损{abs(pnl)}"
                    regime = rec.get("regime", "")
                    lines.append(f"  [{ts}] {direction} | {pnl_label} | 区制:{regime} | 置信:{m['similarity_score']:.0%}")
    except Exception:
        pass

    # ── Phase A: 历史准确率注入（P4/P5 context） ──
    try:
        from memory.manager import get_memory
        memory = get_memory()
        for symbol in symbols:
            acc = memory.retrieve_accuracy(symbol=symbol)
            if acc.get("with_outcome", 0) >= 3:
                lines.append(f"\n📊【{symbol}】系统历史判断准确率")
                lines.append(f"  总裁决: {acc['total_verdicts']}次 | 已跟踪: {acc['with_outcome']}次 | "
                             f"正确: {acc['correct']}次 | 准确率: {acc['accuracy']:.1%}")
                cal = acc.get("calibration")
                if cal and cal.get("buckets"):
                    lines.append("  置信度校准:")
                    for b in cal["buckets"]:
                        if b["count"] > 0:
                            lines.append(f"    置信度{b['bucket_label']}%: {b['count']}次 → 准确率{b['accuracy']:.0%}")
    except Exception:
        pass

    return "\n".join(lines)




def _build_debate_context(state: DebateState, current_symbol: str = "") -> str:
    """构建辩论上下文：扫描指标 + 研究员快照（技术面+基本面+产业链），带来源标记

    Args:
        state: 辩论状态 (DebateState)
        current_symbol: 当前辩论品种，非空时只包含该品种数据
    """
    research = state.get("research_data", {})
    symbols = state.get("selected_symbols", [])
    # v9.22.3: 按品种过滤 — 仅保留当前品种数据
    if current_symbol:
        symbols = [s for s in symbols if s.upper() == current_symbol.upper()] or symbols[:1]
    scan_data = state.get("scan_results", {})
    all_ranked = scan_data.get("all_ranked", []) if isinstance(scan_data, dict) else []

    sym_indicators = {}
    for item in all_ranked:
        sym = item.get("symbol", item.get("pid", "")).upper()
        if sym not in sym_indicators:
            sym_indicators[sym] = {
                "price": item.get("price", 0),
                "adx": item.get("adx", 0),
                "rsi": item.get("rsi", 50),
                "volume": item.get("volume", 0),
                "total": item.get("total", 0),
                "grade": item.get("grade", ""),
                "direction": item.get("direction", ""),
                "change_pct": item.get("change_pct", 0),
            }

    chain = research.get("chain_analysis", {}) or {}
    tech = research.get("technical_data", {}) or {}
    fund = research.get("fundamental_data", {}) or {}

    lines = []
    for sym in symbols:
        lines.append(f"\n==={sym}===")
        ind = sym_indicators.get(sym.upper(), sym_indicators.get(sym, {}))
        if ind:
            lines.append(
                f"[scan:数技源] ADX={ind['adx']:.1f} RSI={ind['rsi']:.1f} "
                f"\u4ef7\u683c={ind['price']} \u4fe1\u53f7\u603b\u5206={ind['total']} \u65b9\u5411={ind['direction']}"
            )

        # \u6280\u672f\u9762\uff08\u89c2\u6f9c\uff09
        tech_per_sym = tech.get("per_symbol", {}) if isinstance(tech, dict) else {}
        if sym in tech_per_sym:
            td = tech_per_sym[sym]
            trend = td.get("trend", "")
            score = td.get("score", "")
            lines.append(f"[technical:\u89c2\u6f9c] \u8d8b\u52bf={trend} \u8bc4\u5206={score}")
        elif isinstance(tech, dict) and tech.get("output"):
            lines.append(f"[technical:\u89c2\u6f9c] {tech['output'][:200]}")

        # \u57fa\u672c\u9762\uff08\u63a2\u6e90\uff09
        fund_per_sym = fund.get("per_symbol", {}) if isinstance(fund, dict) else {}
        if sym in fund_per_sym:
            fd = fund_per_sym[sym]
            sd = fd.get("supply_demand", "")
            inv = fd.get("inventory", "")
            basis = fd.get("basis_term", "")
            lines.append(f"[fundamental:\u63a2\u6e90] \u4f9b\u9700={sd} \u5e93\u5b58={inv} \u57fa\u5dee/\u671f\u9650={basis}")
        elif isinstance(fund, dict) and fund.get("output"):
            lines.append(f"[fundamental:\u63a2\u6e90] {fund['output'][:200]}")

        # \u4ea7\u4e1a\u94fe\uff08\u94fe\u8bc1\u6e90\uff09
        if chain and isinstance(chain, dict) and len(str(chain)) > 50:
            lines.append(f"[chain:\u94fe\u8bc1\u6e90] {str(chain)[:200]}")

        # \u65b0\u95fb\u60c5\u7eea\uff08\u8bfb\u5fc3\uff09
        sent = research.get("sentiment_data", {}) or {}
        if sent and isinstance(sent, dict):
            sent_raw = sent.get("raw", {})
            sent_output = sent_raw.get("output", "") if isinstance(sent_raw, dict) else ""
            if sent_output:
                lines.append(f"[sentiment:\u8bfb\u5fc3] {sent_output[:200]}")

    # v9.23.0: Token 预算控制
    import os
    _MAX_CONTEXT_TOKENS = int(os.environ.get("FDT_CONTEXT_MAX_TOKENS", "8000"))
    raw_context = "\n".join(lines)
    try:
        try:
            from scripts.llm.token_budget import TokenBudget  # type: ignore
            estimated = TokenBudget.estimate(raw_context)
        except ImportError:
            estimated = len(raw_context) // 2  # fallback: 粗略估计
        if estimated > _MAX_CONTEXT_TOKENS:
            ratio = _MAX_CONTEXT_TOKENS / max(estimated, 1)
            cutoff = int(len(raw_context) * ratio)
            raw_context = raw_context[:cutoff]
            raw_context += f"\n\n[系统截断: context 预估 {estimated} tokens > 上限 {_MAX_CONTEXT_TOKENS}, 已截断至约 {_MAX_CONTEXT_TOKENS} tokens]"
            logger.warning(f"[Context] context token 预算超限: {estimated} > {_MAX_CONTEXT_TOKENS}, 已截断")
    except Exception:
        pass

    return raw_context




def _build_signal_summary_html(verdicts: dict, risk_check: dict) -> str:
    """构建交易信号汇总 HTML（追加在品种辨析段之后）。

    Args:
        verdicts: 逐品种裁决 dict（key 为品种代码，value 含 direction/confidence/entry_price 等）
        risk_check: 风控审核数据

    Returns:
        信号汇总 HTML 片段，无可执行信号时返回空字符串。
    """
    # 筛选可执行信号
    actionable = []
    for sym, v in verdicts.items():
        if v.get("direction") in ("BUY", "SELL"):
            actionable.append({
                "symbol": sym.upper(),
                "direction": "做多" if v["direction"] == "BUY" else "做空",
                "dir_cls": "bull" if v["direction"] == "BUY" else "bear",
                "confidence": v.get("confidence", 0),
                "entry": v.get("entry_price", 0),
                "target": v.get("target_price", 0),
                "stop": v.get("stop_loss_price", 0),
                "position": v.get("position_size", 0),
                "rr": v.get("risk_reward_ratio", 0),
            })
    if not actionable:
        return ""

    # 排序：置信度降序
    actionable.sort(key=lambda x: x["confidence"], reverse=True)

    # 风险汇总
    rc = risk_check or {}
    risk_color = rc.get("risk_color", "unknown")
    risk_label = {"green": "绿灯", "yellow": "黄灯", "red": "红灯"}.get(risk_color, risk_color)
    rows_html = ""
    for s in actionable:
        pct_display = f"{s['position']:.1f}%" if s['position'] > 0 else "—"
        rr_display = f"{s['rr']:.2f}:1" if s['rr'] > 0 else "—"
        rows_html += (
            f'<tr>'
            f'<td><strong>{s["symbol"]}</strong></td>'
            f'<td><span class="tag tag-{s["dir_cls"]}">{s["direction"]}</span></td>'
            f'<td>{s["confidence"]:.0%}</td>'
            f'<td>{s["entry"]:.1f}</td>'
            f'<td>{s["target"]:.1f}</td>'
            f'<td style="color:var(--red);">{s["stop"]:.1f}</td>'
            f'<td>{pct_display}</td>'
            f'<td>{rr_display}</td>'
            f'</tr>\n'
        )

    risk_color_cls = "danger" if risk_color == "red" else "warn" if risk_color == "yellow" else ""

    html = f'''
<section id="signal-summary">
<h2><span class="phase-badge p5">汇总</span> 最终交易建议</h2>
<div class="card" style="border-left:4px solid var(--accent2);margin-bottom:16px;">
<div style="font-size:0.85rem;color:var(--muted);line-height:1.6;padding:8px 0;">
  以下信号基于 P1 策略扫描 → P2 方向判定 → P3 四源研究 → P4 闫判官终裁 → P5 风控审核的完整流水线产生。
  fast 模式跳过 P3 六阶段辩论，置信度可能偏低。
</div>
</div>
<div class="card">
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
<thead>
<tr style="background:var(--rule);">
  <th style="padding:8px 10px;text-align:left;">品种</th>
  <th style="padding:8px 10px;text-align:left;">方向</th>
  <th style="padding:8px 10px;text-align:center;">置信度</th>
  <th style="padding:8px 10px;text-align:right;">入场价</th>
  <th style="padding:8px 10px;text-align:right;">目标价</th>
  <th style="padding:8px 10px;text-align:right;">止损价</th>
  <th style="padding:8px 10px;text-align:center;">仓位</th>
  <th style="padding:8px 10px;text-align:center;">盈亏比</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>
</div>
<div class="risk-box {risk_color_cls}" style="margin-top:12px;">
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
  <span style="font-weight:700;font-size:1em;">风控状态: <span class="tag tag-{"high" if risk_color=="red" else "mid" if risk_color=="yellow" else "low"}">{risk_label}</span></span>
  <span class="text-sm text-muted">共 {len(actionable)} 个可执行信号</span>
</div>
</div>
</section>'''
    return html




def _build_data_sources(state: DebateState) -> list:
    """从 state 中提取并返回数据溯源列表"""
    sources = []
    research = state.get("research_data", {})
    if research.get("technical_data"):
        sources.append({"source": "technical", "agent": "观澜", "phase": "P2"})
    if research.get("fundamental_data"):
        sources.append({"source": "fundamental", "agent": "探源", "phase": "P2"})
    if research.get("chain_analysis"):
        sources.append({"source": "chain", "agent": "链证源", "phase": "P2"})
    if research.get("sentiment_data"):
        sources.append({"source": "sentiment", "agent": "读心", "phase": "P2"})
    if state.get("fdc_data_status", {}).get("collected"):
        sources.append({"source": "fdc", "agent": "FDC", "phase": "P2.5"})
    scan = state.get("scan_results", {})
    if scan.get("all_ranked"):
        sources.append({"source": "scan", "agent": "数技源", "phase": "P1"})
    return sources



# ==================== 直接辩论模式节点 (cache-based P1) ====================


