"""输出阶段节点 — P6~P6a（报告生成/CTP 信号）。"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from fdt_langgraph.agents import FdtAgentExecutor
from fdt_langgraph.llm_provider import parse_llm_output
from fdt_langgraph.state import DebateState
from fdt_langgraph.single_symbol_report import generate_body as _generate_symbol_body
from fdt_langgraph._nodes_utils import _resolve_report_dir
from fdt_langgraph._nodes_context import _build_signal_summary_html

logger = logging.getLogger(__name__)

def _load_template_css() -> str:
    """从 docs/report-template/report_css.html 加载统一模板 CSS"""
    _REPORT_CSS_PATH = Path(__file__).resolve().parent.parent / "docs" / "report-template" / "report_css.html"
    if _REPORT_CSS_PATH.exists():
        css = _REPORT_CSS_PATH.read_text(encoding="utf-8")
        return "\n".join(line for line in css.splitlines() if not line.strip().startswith("/*"))
    return ""




def _load_template_html() -> str:
    """从 docs/report-template/report_skeleton.html 加载 HTML 骨架"""
    _PATH = Path(__file__).resolve().parent.parent / "docs" / "report-template" / "report_skeleton.html"
    if _PATH.exists():
        return _PATH.read_text(encoding="utf-8")
    return "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><title>{title}</title><style>{css}</style></head><body><main>{body_html}</main></body></html>"


# 模块级缓存
_TEMPLATE_CSS = _load_template_css()
_TEMPLATE_HTML = _load_template_html()




def _render_html(title: str, body_html: str, header_meta: list[tuple[str, str]] | None = None) -> str:
    """统一 HTML 报告模板（骨架从 report_skeleton.html + CSS 从 report_css.html 加载）"""
    from datetime import datetime as _dt
    _now = _dt.now()
    meta_html = ""
    if header_meta:
        items = "".join(
            f'<span>{k.replace("_"," ").title()}: {v}</span>'
            for k, v in header_meta
        )
        meta_html = f'<div class="meta">{items}</div>'

    # 从 body 提取 nav 项 — 仅保留品种(sym-*)和汇总(signal-summary)
    nav_links = ""
    for m in __import__("re").finditer(r'<section[^>]*?id="([^"]+)"[^>]*>.*?<h2[^>]*>(.*?)</h2>', body_html, __import__("re").DOTALL):
        href = m.group(1)
        if not href.startswith("sym-") and href != "signal-summary":
            continue
        label = __import__("re").sub(r'<[^>]+>', '', m.group(2)).strip()[:16]
        nav_links += f'<a href="#{href}">{label}</a>'

    return _TEMPLATE_HTML.format(
        title=title,
        date=_now.strftime('%Y-%m-%d'),
        datetime=_now.strftime('%Y-%m-%d %H:%M:%S'),
        css=_TEMPLATE_CSS,
        meta_html=meta_html,
        nav_links=nav_links,
        body_html=body_html,
    )




def _write_scan_report(trace_id: str, scan_results: dict, output_dir: Path) -> str:
    """生成信号扫描报告 (P1 阶段) — 列出全部可操作品种、信号强度、方向"""
    all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []

    if not all_ranked:
        body = '<div class="section"><h2>📊 扫描结果</h2><p style="color:#888;">本轮无有效信号（可能因策略配置禁用或市场条件不满足）。</p></div>'
    else:
        rows = ""
        for item in all_ranked:
            symbol = item.get("symbol", item.get("pid", "?"))
            name = item.get("name", symbol)
            raw_dir = item.get("direction", "")
            direction = "BUY" if raw_dir in ("bull", "BUY", "buy") else "SELL" if raw_dir in ("bear", "SELL", "sell") else "HOLD"
            total = item.get("total", 0)
            adx = item.get("adx", 0)
            rsi = item.get("rsi") or 0
            price = item.get("price", 0)
            atr = item.get("atr", 0)
            stage = item.get("stage", "")
            rows += f"""<tr>
                <td><span class="tag-{direction.lower()}">{direction} {name}({symbol})</span></td>
                <td class="num">{total:+.0f}</td>
                <td class="num">{adx:.1f}</td>
                <td class="num">{rsi:.1f}</td>
                <td class="num">{price:.0f}</td>
                <td class="num">{atr:.0f}</td>
                <td>{stage}</td>
            </tr>"""
        body = f"""<div class="section">
<h2>📡 P1 · 数技源 — 信号扫描报告</h2>
<p class="subtitle">trace_id={trace_id} · 扫描品种 {len(all_ranked)} 个</p>
<table><thead><tr>
<th>品种</th><th class="num">总分</th><th class="num">ADX</th><th class="num">RSI</th>
<th class="num">最新价</th><th class="num">ATR</th><th>阶段</th>
</tr></thead><tbody>{rows}</tbody></table>
</div>"""

    html = _render_html("📡 信号扫描报告", body, [
        ("trace_id", trace_id),
        ("信号数", str(len(all_ranked))),
    ])
    out_path = output_dir / f"scan_report_{trace_id}.html"

    out_path.write_text(html, encoding="utf-8")
    return str(out_path)




def _write_verdict_report(trace_id: str, verdict: dict, risk_check: dict,
                          selected_symbols: list, output_dir: Path,
                          scan_summary: list = None) -> str:
    """生成裁决报告 (P4 阶段) — 闫判官裁决 + 风控明审核"""
    direction = verdict.get("direction", verdict.get("verdict", "neutral"))
    direction_cn = {"bull": "多头", "bullish": "多头", "BUY": "做多",
                    "bear": "空头", "bearish": "空头", "SELL": "做空"}.get(direction, "中性")
    confidence = verdict.get("confidence", 0.5) or 0.5
    reason = verdict.get("reason", "") or ""
    entry = verdict.get("entry_price", 0) or 0
    sl = verdict.get("stop_loss_price", 0) or 0
    target = verdict.get("target_price", 0) or 0
    pos = verdict.get("position_pct", 0) or 0
    contract = verdict.get("contract", "") or ""
    rr = verdict.get("risk_reward_ratio", 0) or 0

    risk_color = risk_check.get("risk_color", "yellow")
    risk_level = risk_check.get("risk_level", "—")
    risk_approved = "✅ 通过" if risk_check.get("approved", True) else "❌ 阻断"
    warnings = risk_check.get("warnings", []) or []

    warn_html = "".join(f"<li>{w}</li>" for w in warnings) if warnings else "<li style='color:#888;'>无警告</li>"

    body = f"""<div class="section">
<h2>⚖️ P4 · 闫判官裁决</h2>
<p class="subtitle">trace_id={trace_id} · 辩论品种: {', '.join(selected_symbols) or '—'}</p>
<table>
<tr><th>裁决方向</th><td><span class="tag-{'buy' if 'buy' in str(direction).lower() else 'sell' if 'sell' in str(direction).lower() else 'hold'}">{direction} ({direction_cn})</span></td></tr>
<tr><th>置信度</th><td class="num">{confidence:.0%}</td></tr>
<tr><th>入场价</th><td class="num">{entry}</td></tr>
<tr><th>止损价</th><td class="num">{sl}</td></tr>
<tr><th>目标价</th><td class="num">{target}</td></tr>
<tr><th>仓位</th><td class="num">{pos}%</td></tr>
<tr><th>合约</th><td>{contract}</td></tr>
<tr><th>盈亏比</th><td class="num">{rr:.2f}:1</td></tr>
<tr><th>裁决理由</th><td>{reason}</td></tr>
</table>
</div>

<div class="section">
<h2>🛡️ P5 · 风控明审核</h2>
<p>风险等级: <b style="color:{'#22c55e' if risk_color=='green' else '#f59e0b' if risk_color=='yellow' else '#ef4444'};">{risk_color.upper()}</b>
 · 风险分类: {risk_level} · 审核结果: {risk_approved}</p>
<ul>{warn_html}</ul>
</div>"""

    # Per-symbol table from scan data
    if scan_summary:
        sym_rows_str = '<table><thead><tr><th>\u54c1\u79cd</th><th>\u65b9\u5411</th><th class="num">\u4fe1\u53f7\u5206</th><th class="num">\u5f53\u524d\u4ef7</th></tr></thead><tbody>'
        for x in sorted(scan_summary, key=lambda v: abs(v.get("total", 0)), reverse=True)[:30]:
            sym = x.get("symbol", x.get("pid", ""))
            sd = x.get("decision", x.get("direction", "HOLD"))
            st = x.get("total", 0) or 0
            sp = float(x.get("price", 0) or 0)
            sym_rows_str += '<tr><td>%s</td><td>%s</td><td class="num">%d</td><td class="num">%.2f</td></tr>' % (sym, sd, abs(st), sp)
        sym_rows_str += '</tbody></table>'
        body += '<div class="section"><h2>\U0001f4ca \u9010\u54c1\u79cd\u91cf\u5316\u4fe1\u53f7</h2>' + sym_rows_str + '</div>'

    html = _render_html("⚖️ 裁决报告", body, [
        ("trace_id", trace_id),
        ("方向", f"{direction} ({direction_cn})"),
        ("风控", f"{risk_color}"),
    ])
    out_path = output_dir / f"verdict_report_{trace_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)




def _write_research_report(trace_id: str, research_data: dict, output_dir: Path) -> str:
    """生成研究报告 (P2 阶段) — 四源（链证源/观澜/探源/读心）合并分析"""
    chain_analysis = research_data.get("chain_analysis", {}) or {}
    technical_data = research_data.get("technical_data", {}) or {}
    fundamental_data = research_data.get("fundamental_data", {}) or {}

    chain_count = len(chain_analysis) if isinstance(chain_analysis, dict) else 0

    # Extract structured per-symbol data for display
    tech_per_symbol = technical_data.get("per_symbol", {}) if isinstance(technical_data, dict) else {}
    fund_per_symbol = fundamental_data.get("per_symbol", {}) if isinstance(fundamental_data, dict) else {}

    # Build per-symbol technical display
    tech_rows = ""
    for sym, data in tech_per_symbol.items():
        score = data.get("score", "—")
        trend = data.get("trend", "—")
        tech_rows += f"<tr><td>{sym}</td><td>{trend[:120]}</td><td class='num'>{score}</td></tr>"
    if not tech_rows:
        tech_rows = f'<tr><td colspan="3" style="color:#888;text-align:center;">{str(technical_data)[:500] if technical_data else "（未触发）"}</td></tr>'

    # Build per-symbol fundamental display
    fund_rows = ""
    for sym, data in fund_per_symbol.items():
        sd = data.get("supply_demand", "—")[:100]
        inv = data.get("inventory", "—")[:60]
        bs = data.get("basis_term", "—")[:60]
        fund_rows += f"<tr><td>{sym}</td><td>{sd}</td><td>{inv}</td><td>{bs}</td></tr>"
    if not fund_rows:
        fund_rows = f'<tr><td colspan="4" style="color:#888;text-align:center;">{str(fundamental_data)[:500] if fundamental_data else "（未触发）"}</td></tr>'

    # Build sentiment display
    sentiment_data = research_data.get("sentiment_data", {}) or {}
    sentiment_output = ""
    if isinstance(sentiment_data, dict):
        sent_raw = sentiment_data.get("raw", {})
        sentiment_output = (sent_raw.get("output", "") if isinstance(sent_raw, dict) else "")[:500]

    body = f"""<div class="section">
<h2>🔗 P2 · 链证源 — 产业链分析</h2>
<p class="subtitle">覆盖产业链 {chain_count} 条</p>
<pre style="background:#252836;padding:12px;border-radius:6px;overflow:auto;font-size:0.78em;color:#ccc;">{str(chain_analysis)[:2000] if chain_analysis else '（未触发）'}</pre>
</div>

<div class="section">
<h2>📈 P2 · 观澜 — 技术面分析（逐品种）</h2>
<p class="subtitle">覆盖 {len(tech_per_symbol)} 个品种</p>
<table><thead><tr><th>品种</th><th>趋势判断</th><th class="num">评分</th></tr></thead>
<tbody>{tech_rows}</tbody></table>
</div>

<div class="section">
<h2>🔬 P2 · 探源 — 基本面分析（逐品种）</h2>
<p class="subtitle">覆盖 {len(fund_per_symbol)} 个品种</p>
<table><thead><tr><th>品种</th><th>供需</th><th>库存</th><th>期限结构</th></tr></thead>
<tbody>{fund_rows}</tbody></table>
</div>

<div class="section">
<h2>📰 P2 · 读心 — 新闻情绪分析</h2>
<pre style="background:#252836;padding:12px;border-radius:6px;overflow:auto;font-size:0.78em;color:#ccc;">{sentiment_output if sentiment_output else '（未触发）'}</pre>
</div>"""

    html = _render_html("🔍 研究报告（四源）", body, [
        ("trace_id", trace_id),
        ("产业链", f"{chain_count}"),
        ("技术", f"{len(tech_per_symbol)}"),
        ("基本面", f"{len(fund_per_symbol)}"),
        ("情绪", f"{'✅' if sentiment_output else '—'}"),
    ])
    out_path = output_dir / f"research_report_{trace_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)




def _write_signal_report(trace_id: str, signal_output: dict, output_dir: Path,
                           signals_list: list = None) -> str:
    """生成 CTP 信号扫描报告 (P6a 阶段) — 风控通过/阻断 + 完整交易信号清单"""
    risk_color = signal_output.get("risk_color", "red")
    status = signal_output.get("status", "blocked")
    message = signal_output.get("message", "")
    risk_check = signal_output.get("risk_check", {}) or {}
    signal = signal_output.get("signal", {}) or {}

    status_color = "#22c55e" if status == "sent" else "#ef4444"
    status_label = "✅ 已发送" if status == "sent" else "❌ 已阻断"

    body = f"""<div class="section">
<h2>📡 CTP 信号输出总览</h2>
<table>
<tr><th>trace_id</th><td>{trace_id}</td></tr>
<tr><th>信号状态</th><td style="color:{status_color};font-weight:bold;">{status_label}</td></tr>
<tr><th>风控等级</th><td><span class="tag-{('sell' if risk_color=='red' else 'hold' if risk_color=='yellow' else 'buy')}">{risk_color.upper()}</span></td></tr>
<tr><th>说明</th><td>{message}</td></tr>
</table>
</div>"""

    if signal:
        body += f"""<div class="section">
<h2>📋 信号详情 (CTP 就绪)</h2>
<table>
<tr><th>方向</th><td>{signal.get('direction', '—')}</td></tr>
<tr><th>合约</th><td>{signal.get('contract', '—')}</td></tr>
<tr><th>指令类型</th><td>市价单 (market order)</td></tr>
<tr><th>参考入场价</th><td class="num">{signal.get('entry_price', 0)}</td></tr>
<tr><th>止损价</th><td class="num">{signal.get('stop_loss_price', 0)}</td></tr>
<tr><th>目标价</th><td class="num">{signal.get('target_price', 0)}</td></tr>
<tr><th>仓位</th><td class="num">{signal.get('position_pct', 0)}%</td></tr>
<tr><th>盈亏比</th><td class="num">{(signal.get('risk_reward_ratio') or 0):.2f}:1</td></tr>
<tr><th>置信度</th><td class="num">{(signal.get('confidence') or 0):.0%}</td></tr>
</table>
</div>"""
    else:
        body += '<div class="section"><h2>📋 信号详情</h2><p style="color:#888;">无信号（已阻断或未达风控阈值）</p></div>'

    body += f"""<div class="section">
<h2>🛡️ 风控审核明细</h2>
<pre style="background:#252836;padding:12px;border-radius:6px;overflow:auto;font-size:0.78em;color:#ccc;">{str(risk_check)[:1500]}</pre>
</div>"""

    if signals_list:
        sig_rows = '<table><thead><tr><th>\u54c1\u79cd</th><th>\u65b9\u5411</th><th>\u6307\u4ee4</th><th class="num">\u4fe1\u5fc3\u5ea6</th><th class="num">\u53c2\u8003\u4ef7</th></tr></thead><tbody>'
        for x in sorted(signals_list, key=lambda v: abs(v.get("score", 0)), reverse=True):
            nm = x.get("symbol", "")
            sd = x.get("direction", "")
            sc = x.get("score", 0) or 0
            ep = float(x.get("entry_price", 0) or 0)
            sig_rows += '<tr><td>%s</td><td>%s</td><td>market</td><td class="num">%d%%</td><td class="num">%.2f</td></tr>' % (nm, sd, min(100, sc), ep)
        sig_rows += '</tbody></table>'
        body += '<div class="section"><h2>\U0001f4ca \u5168\u90e8\u53ef\u6267\u884c\u4fe1\u53f7\u6e05\u5355</h2>' + sig_rows + '</div>'

    html = _render_html("📡 CTP 信号扫描报告", body, [
        ("trace_id", trace_id),
        ("状态", status_label),
        ("风控", risk_color.upper()),
    ])
    out_path = output_dir / f"signal_report_{trace_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)




async def node_report(state: DebateState) -> DebateState:
    """品藻报告节点（P6）。

    组装辩论结果 → HTML 辩论报告 → 核验完整性。
    品藻负责报告排版、验证和数据归档。
    """
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
        raw_dir = item.get("direction", "")
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
            "symbol": symbol, "pid": symbol.lower(), "name": item.get("name", symbol),
            "product_name": item.get("name", symbol), "direction": direction,
            "total": item.get("total", 0), "adx": item.get("adx", 0),
            "rsi": item.get("rsi") or 0, "cci": item.get("cci", 0),
            "stage": item.get("stage", ""), "z_score": item.get("z_score", 0),
            "cons": item.get("cons", 0), "volume": item.get("volume", 0),
            "dc20_break": item.get("dc20_break", "none"), "ma_align": item.get("ma_align", "mixed"),
            "macd_cross": item.get("macd_cross", "none"),
            "factor_direction": item.get("factor_direction", "neutral"),
            "factor_total": item.get("factor_total", 0),
            "direction_conflict": item.get("direction_conflict", False),
            "last_price": price, "price": price,
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

    # Extract structured per-symbol data from technical/fundamental nodes
    tech_raw = research_data.get("technical_data", {})
    fund_raw = research_data.get("fundamental_data", {})
    tech_per_symbol = tech_raw.get("per_symbol", {}) if isinstance(tech_raw, dict) else {}
    fund_per_symbol = fund_raw.get("per_symbol", {}) if isinstance(fund_raw, dict) else {}

    # Supplement fund_per_symbol from fdc_data for debate symbols not covered by LLM
    fdc_data = state.get("fdc_data", {})
    debate_pids = set()
    for pid in list((state.get("debate_results") or {}).keys()):
        debate_pids.add(pid); debate_pids.add(pid.upper()); debate_pids.add(pid.lower())
    if fdc_data and debate_pids:
        for sym_key in list(fdc_data.keys()):
            sk_up = sym_key.upper()
            if sk_up in fund_per_symbol or sym_key in fund_per_symbol:
                continue
            if sym_key not in debate_pids and sk_up not in debate_pids:
                continue
            sd = fdc_data[sym_key]
            if not isinstance(sd, dict):
                continue
            def _f10s(fn):
                entry = sd.get(fn)
                if not entry or "error" in (entry if isinstance(entry, dict) else {}):
                    return None
                summary = entry.get("summary") if isinstance(entry, dict) else None
                if summary and isinstance(summary, str) and len(summary) > 5:
                    s = summary.strip()
                    if not re.search(r'(independent|暂缺|待[核实查计算]|占位|placeholder)', s, re.I) and not re.match(r'^[a-zA-Z]{1,4}\s*基本面', s):
                        return s[:150]
                data = entry.get("data") if isinstance(entry, dict) else None
                if isinstance(data, dict) and data:
                    skip_k = {"symbol","structure","exchange","product_id"}
                    skip_v = {"UNKNOWN","unknown","N/A","","None","none"}
                    parts = [f"{k}={v}" for k, v in list(data.items())[:6] if k not in skip_k and str(v).strip() and str(v).strip() not in skip_v]
                    return ", ".join(parts)[:150] if parts else None
                return None
            ts=_f10s("term_structure"); sp=_f10s("spread"); ba=_f10s("basis"); fu=_f10s("fundamental"); wa=_f10s("warrant")
            sd_parts = []
            if ts: sd_parts.append(f"期限结构: {ts}")
            if sp: sd_parts.append(f"价差: {sp}")
            if fu: sd_parts.append(f"基本面: {fu}")
            ind = (sd.get("indicators") or {}).get("values", {})
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
            pr = sd.get("position_ranking")
            if pr and isinstance(pr,dict):
                prd = pr.get("data")
                if isinstance(prd,dict):
                    t=prd.get("top1_name",""); c=prd.get("top1_change","")
                    if t: leading.append(f"持仓第一: {t}")
                    if c and str(c)!="0": leading.append(f"持仓变化: {c}")
            if not leading: leading = ["持仓数据暂缺"]
            fund_per_symbol[sym_key] = {"supply_demand":supply_demand,"inventory":inventory,"profit_margin":fu if fu else "利润和开工率数据待查","basis_term":basis_term,"leading_signals":leading}

    intermediate_data = {
        "scan_results": scan_results,
        "symbols_summary": symbols_summary,
        "chain_results": chain_results,
        "all_actionable": all_actionable,
        "BUY_top5": BUY_top5,
        "SELL_top5": SELL_top5,
        "judge_direction": state.get("judge_direction", {}),
        "research_data": research_data,
        "technical_data": research_data.get("technical_data", {}),
        "technical_per_symbol": tech_per_symbol,
        "fundamental_data": research_data.get("fundamental_data", {}),
        "fundamental_per_symbol": fund_per_symbol,
        "bullish_arguments": state.get("bullish_arguments", {}),
        "bearish_arguments": state.get("bearish_arguments", {}),
        "verdict": state.get("verdict", {}),
        "risk_check": state.get("risk_check", {}),
    }

    verdict = state.get("verdict") or {}
    risk_check = state.get("risk_check") or {}
    if not risk_check:
        risk_check = (state.get("signal_output") or {}).get("risk_check", {})

    # Get per-symbol data from judge verdict (v8.8.0+ per-symbol output)
    judge_per_symbol = verdict.get("per_symbol", {}) if isinstance(verdict, dict) else {}

    # Get per-symbol arguments from debate (v8.9.0+ reducer list format)
    _bull_raw = state.get("bullish_arguments", {})
    bull_args_dict = {}
    if isinstance(_bull_raw, list):
        for _entry in _bull_raw:
            if isinstance(_entry, dict) and _entry.get("symbols"):
                bull_args_dict.update(_entry["symbols"])
    elif isinstance(_bull_raw, dict):
        bull_args_dict = _bull_raw

    _bear_raw = state.get("bearish_arguments", {})
    bear_args_dict = {}
    if isinstance(_bear_raw, list):
        for _entry in _bear_raw:
            if isinstance(_entry, dict) and _entry.get("symbols"):
                bear_args_dict.update(_entry["symbols"])
    elif isinstance(_bear_raw, dict):
        bear_args_dict = _bear_raw

    verdict_overall = verdict.get("direction", verdict.get("verdict", "neutral")) if verdict else "neutral"
    verdict_confidence = float(verdict.get("confidence", 0.5)) if verdict else 0.5
    verdict_reason = verdict.get("reason", "") if verdict else ""
    risk_approved = risk_check.get("approved", True) if risk_check else True
    debate_overall = {
        "tendency": verdict_overall,
        "confidence": verdict_confidence,
        "reason": verdict_reason,
        "risk_approved": risk_approved,
    }

    # Build report_syms from scan data
    # 规则：仅含已辩论品种 或 信号≥WATCH/|total|≥20的品种，不输出NOISE且未辩论品种
    _debated_list = [s.upper() for s in (state.get("selected_symbols", []) or [])]
    report_syms = set()
    if symbols_summary:
        for item in all_actionable:
            report_syms.add(item["pid"])
        for sym in state.get("selected_symbols", []):
            report_syms.add(sym.lower())
        for item in symbols_summary:
            g = item.get("grade", item.get("level", ""))
            t = abs(item.get("total", 0))
            pid = item.get("pid", "").lower()
            is_debated = pid.upper() in _debated_list
            if is_debated or g in ("STRONG", "WATCH") or t >= 20:
                report_syms.add(pid)
        if len(report_syms) < 3:
            for item in sorted(symbols_summary, key=lambda x: abs(x.get("total", 0)), reverse=True)[:5]:
                if abs(item.get("total", 0)) >= 15:
                    report_syms.add(item["pid"])
    else:
        for sym in state.get("selected_symbols", []):
            report_syms.add(sym.lower())
        if not report_syms:
            report_syms.update(["sc", "au", "ag", "cu"])

    # Build per-symbol verdicts: prefer judge per-symbol, fallback to scan data
    scan_data_map = {item["pid"]: item for item in symbols_summary}
    verdicts = {}
    for sym_key in sorted(report_syms):
        # 仅包含实际参与辩论的品种，排除全量扫描的额外品种
        if sym_key.upper() not in _debated_list:
            continue
        item = scan_data_map.get(sym_key, {})
        if not item and symbols_summary:
            continue

        # Try to get judge per-symbol verdict for this symbol
        sym_upper = sym_key.upper()
        judge_sym = judge_per_symbol.get(sym_key, judge_per_symbol.get(sym_upper, {}))

        if judge_sym and isinstance(judge_sym, dict) and judge_sym.get("direction"):
            # Use judge verdict for this symbol
            per_sym_dir = judge_sym.get("direction", "HOLD")
            per_sym_dir = "BUY" if per_sym_dir in ("bullish", "bull", "BUY", "buy", "long") else \
                         "SELL" if per_sym_dir in ("bearish", "bear", "SELL", "sell", "short") else "HOLD"
        else:
            # Fallback to scan data direction
            per_sym_dir = item.get("decision", "HOLD") if item else "HOLD"

        # Get per-symbol debate arguments
        bull_sym = bull_args_dict.get(sym_key, bull_args_dict.get(sym_upper, {}))
        bear_sym = bear_args_dict.get(sym_key, bear_args_dict.get(sym_upper, {}))

        if isinstance(bull_sym, dict) and bull_sym.get("arguments"):
            bull_args_list = bull_sym["arguments"]
        else:
            # 未找到该品种辩论论据 → 留空，不fallback到全局state（会泄露raw dict）
            bull_args_list = []

        if isinstance(bear_sym, dict) and bear_sym.get("arguments"):
            bear_args_list = bear_sym["arguments"]
        else:
            bear_args_list = []

        # Compute entry/target/stop: prefer judge values, fallback to scan-based calculation
        if judge_sym and isinstance(judge_sym, dict):
            entry_p = float(judge_sym.get("entry_price", 0) or 0)
            tg_p = float(judge_sym.get("target_price", 0) or 0)
            sl_p = float(judge_sym.get("stop_loss_price", 0) or 0)
            pos_pct = float(judge_sym.get("position_pct", 0) or 0)
            rr = float(judge_sym.get("risk_reward_ratio", 0) or 0)
            judge_confidence = float(judge_sym.get("confidence", 0.5) or 0.5)
            judge_reason = judge_sym.get("reason", "") or ""
        else:
            entry_p = 0
            tg_p = 0
            sl_p = 0
            pos_pct = 0
            rr = 0.0
            judge_confidence = 0.5
            judge_reason = ""

        # 价格合理性校验：judge的entry_price与scan价格偏差超20%时报警并使用scan数据
        scan_price = float(item.get("price", 0) or 0) if item else 0
        if entry_p > 0 and scan_price > 0:
            deviation = abs(entry_p - scan_price) / scan_price
            if deviation > 0.20:
                logger.warning(f"⚠️ 价格偏差过大: {sym_key} judge_entry={entry_p} scan_price={scan_price} deviation={deviation:.1%}，回退至scan价格")
                entry_p = scan_price
                # 重新计算止损和目标
                if per_sym_dir == "BUY":
                    sl_p = entry_p * 0.97
                    tg_p = entry_p * 1.05
                elif per_sym_dir == "SELL":
                    sl_p = entry_p * 1.03
                    tg_p = entry_p * 0.95

        # If judge didn't provide prices, compute from scan data
        if entry_p == 0 and item:
            price = float(item.get("price", 0) or 0)
            atr_val = float(symbol_atr_map.get(item.get("symbol", ""), 0) or 0)
            entry_p = price
            if per_sym_dir == "BUY":
                sl_p = entry_p - atr_val * 1.5 if atr_val > 0 else entry_p * 0.97
                tg_p = entry_p + atr_val * 2.5 if atr_val > 0 else entry_p * 1.05
            elif per_sym_dir == "SELL":
                sl_p = entry_p + atr_val * 1.5 if atr_val > 0 else entry_p * 1.03
                tg_p = entry_p - atr_val * 2.5 if atr_val > 0 else entry_p * 0.95
            # Compute position from score (仅当judge没有给出判决策略时)
            abs_sc = abs(item.get("total", 0) or 0)
            if abs_sc >= 75:
                pos_pct = 5.0
            elif abs_sc >= 60:
                pos_pct = 3.0
            elif abs_sc >= 40:
                pos_pct = 1.5
            elif abs_sc >= 20:
                pos_pct = 0.5
            else:
                pos_pct = 0.0  # 弱信号品种不分配仓位
            # Compute RR
            if entry_p and sl_p and tg_p and abs(entry_p - sl_p) > 0:
                risk = abs(entry_p - sl_p)
                reward = abs(tg_p - entry_p)
                if risk > 0:
                    rr = round(reward / risk, 2)

        adx = float(judge_sym.get("adx", 0)) or (float(item.get("adx", 0)) if item else 0)
        rsi = float(judge_sym.get("rsi") or 0) or (float(item.get("rsi") or 0) if item else 0)
        score = float(judge_sym.get("score", 0)) or (abs(item.get("total", 0)) if item else 0)

        # G35: 论据为空时从 judge reasoning 生成最小论据
        _ba = "<br>".join(str(a) for a in bull_args_list) if bull_args_list else ""
        _bea = "<br>".join(str(a) for a in bear_args_list) if bear_args_list else ""
        _reason = judge_reason or verdict_reason
        if not _ba and _reason:
            _ba = f"[裁决摘要] {_reason}"
        if not _bea and _reason:
            _bea = f"[裁决摘要] {_reason}"
        verdicts[sym_key] = {
            "direction": per_sym_dir,
            "confidence": judge_confidence if judge_sym else min(1.0, score / 100 + 0.1),
            "judge_verdict": {
                "final_direction": per_sym_dir,
                "confidence": judge_confidence if judge_sym else min(1.0, score / 100 + 0.1),
                "reasoning": judge_reason or verdict_reason,
            },
            "bull_args": _ba,
            "bear_args": _bea,
            "entry_price": round(entry_p, 2),
            "target_price": round(tg_p, 2),
            "stop_loss_price": round(sl_p, 2),
            "position_size": pos_pct,
            "risk_reward_ratio": rr,
            "adx": adx,
            "rsi": rsi,
            "score": score,
            "chain": item.get("chain", "") if item else "",
        }


    debate_results = {
        "trace_id": state.get("trace_id", ""),
        "verdicts": verdicts,
        "overall": debate_overall,
        "bullish_arguments": state.get("bullish_arguments", []),
        "bearish_arguments": state.get("bearish_arguments", []),
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

    # v8.8.0: 输出到用户指定工作空间（按日期），而非临时目录
    user_workspace_dir = _resolve_report_dir()
    output_dir = user_workspace_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # v9.12.0: 逐个品种生成 body 段，合并为一份报告，跳过中间 JSON + 子进程
    _selected = state.get("selected_symbols", [])
    if _selected:
        all_bodies = []
        meta_pairs = [("trace_id", state.get("trace_id", ""))]
        for sym in _selected:
            try:
                sym_body = _generate_symbol_body(state, sym)
                all_bodies.append(
                    f'<section id="sym-{sym.lower()}">'
                    f'<h2><span class="phase-badge p3">{sym.upper()}</span> 辩论分析</h2>\n'
                    + sym_body
                    + '</section>'
                )
            except Exception as e:
                logger.warning(f"[REPORT] 品种 {sym} 报告段生成失败: {e}")
        # v9.26.0: 在品种 body 后追加交易信号汇总章节
        signal_summary_html = _build_signal_summary_html(verdicts, risk_check)
        final_body_with_summary = "\n".join(all_bodies) + "\n" + signal_summary_html
        all_signals = [v for v in verdicts.values() if v.get("direction") in ("BUY", "SELL")]
        title_suffix = f" · {len(all_signals)} 信号" if all_signals else " · 无交易信号"
        report_html = _render_html(
            f"多品种辩论报告 · {', '.join(s.upper() for s in _selected)}{title_suffix}",
            final_body_with_summary,
            meta_pairs,
        )
        report_path = output_dir / f"debate_report_{state['trace_id']}.html"
        report_path.write_text(report_html, encoding="utf-8")
        logger.info(f"[REPORT] 多品种辩论报告已生成: {report_path}")
    else:
        # 无选中品种 → fallback
        fallback_html = _render_html(
            "📋 辩论报告（无选定品种）",
            '<div class="callout"><h2>⚠️ 无选定品种</h2><p>未指定辩论品种，跳过报告生成。</p></div>',
            [("trace_id", state.get("trace_id", ""))],
        )
        report_path = output_dir / f"debate_report_{state['trace_id']}.html"
        report_path.write_text(fallback_html, encoding="utf-8")
        report_path = str(report_path)

    # ── D6 Output: 输出版本化 ──
    try:
        from scripts.output_versioning import OutputVersioning
        ov = OutputVersioning("debate_report")
        vid = ov.save_output({
            "trace_id": state.get("trace_id", ""),
            "report_path": str(report_path),
            "symbols": state.get("selected_symbols", []),
            "verdict_count": len(state.get("per_symbol_results", {})),
        }, agent_name="quality_assurance")
        logger.info(f"[D6] 报告版本已记录: {vid}")
    except Exception:
        pass

    new_phases = state["completed_phases"] + ["P6"]
    return {**state, "report_path": report_path, "current_phase": "P6", "completed_phases": new_phases}




async def node_signal_output(state: DebateState) -> DebateState:
    from fdt_langgraph._nodes_verdict import node_risk_check
    """品藻 P6a: CTP 信号输出 — 从 state 中读取已由 node_risk_check 构建的信号，输出并记录。

    依赖上游 node_risk_check 已写入 state["signal_output"]。
    """
    signal_output = state.get("signal_output") or {}
    signal_report_path = state.get("signal_report_path")
    trace_id = state.get("trace_id", "")

    status = signal_output.get("status", "unknown")
    risk_color = signal_output.get("risk_color", "unknown")
    signals_count = len(signal_output.get("signals", []))
    message = signal_output.get("message", "")

    logger.info(f"[SIGNAL_OUTPUT] trace={trace_id} status={status} risk={risk_color} signals={signals_count}")
    if message:
        logger.info(f"[SIGNAL_OUTPUT] {message}")
    if signal_report_path:
        logger.info(f"[SIGNAL_OUTPUT] 报告: {signal_report_path}")

    # 将 CTP 信号写入工作区目录（优先 FDT_REPORT_WORKSPACE，fallback 到 memory/ctp_signals/）
    try:
        import datetime as _dt
        import json
        workspace_env = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE")
        if workspace_env:
            signal_dir = str(_resolve_report_dir())
        else:
            signal_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "ctp_signals")
        os.makedirs(signal_dir, exist_ok=True)
        date_compact = _dt.datetime.now().strftime("%Y%m%d")
        archive_path = os.path.join(signal_dir, f"ctp_signals_{trace_id.split('-')[-1]}_{date_compact}.json")
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(signal_output, f, ensure_ascii=False, indent=2)
        logger.info(f"[SIGNAL_OUTPUT] 已归档: {archive_path}")
    except Exception as e:
        logger.warning(f"[SIGNAL_OUTPUT] 归档失败: {e}")

    new_phases = state.get("completed_phases", [])
    if "P6a" not in new_phases:
        new_phases = new_phases + ["P6a"]

    return {
        **state,
        "signal_output": signal_output,
        "signal_report_path": signal_report_path,
        "current_phase": "P6a",
        "completed_phases": new_phases,
    }



