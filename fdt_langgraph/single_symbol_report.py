"""单品种辩论报告生成器 — 从 FDT state 生成精简报告"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path


def _fmt(v, digits: int = 2) -> str:
    """截断浮点数到指定精度"""
    if v is None:
        return "—"
    try:
        fv = float(v)
        if abs(fv) > 10000:
            return f"{fv:,.0f}"
        if abs(fv) > 100:
            return f"{fv:,.1f}"
        if digits == 0:
            return f"{fv:.0f}"
        return f"{fv:.{digits}f}"
    except (ValueError, TypeError):
        return str(v)


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.1f}%"
    except (ValueError, TypeError):
        return str(v)


def _esc(s: str) -> str:
    return html.escape(str(s)) if s else ""


def _extract_agent_output(state: dict, agent_tag: str, sym: str, sym_upper: str) -> str:
    """从辩论论据中提取指定 Agent 标签的原始输出文字"""
    for key in (
        "debate_arguments",
        "bullish_arguments",
        "bearish_arguments",
        "bearish_rebuttal_arguments",
        "bullish_rebuttal_arguments",
        "bear_final_arguments",
        "bull_final_arguments",
    ):
        lst = state.get(key, [])
        for entry in lst:
            if not isinstance(entry, dict):
                continue
            syms = entry.get("symbols", {})
            for k in (sym_upper, sym_upper.lower(), sym):
                sdata = syms.get(k)
                if not isinstance(sdata, dict):
                    continue
                args = sdata.get("arguments", [])
                for arg in args:
                    if isinstance(arg, str) and f"{agent_tag}:" in arg:
                        idx = arg.index(f"{agent_tag}:")
                        return arg[idx + len(agent_tag) + 1 :].strip()
    return ""


def _extract_args_from_list(lst: list, symbol_upper: str) -> list:
    for entry in lst:
        if isinstance(entry, dict) and entry.get("symbols"):
            syms = entry["symbols"]
            for key in (symbol_upper, symbol_upper.lower()):
                if key in syms:
                    sdata = syms[key]
                    if isinstance(sdata, dict):
                        return sdata.get("arguments", [])
                    if isinstance(sdata, list):
                        return sdata
    return []


def _nav_items(body_html: str) -> str:
    """从 body HTML 中提取带 id 的 section 标题，生成导航栏链接"""
    links = []
    for m in re.finditer(r'<section[^>]*?id="([^"]+)"[^>]*>.*?<h2[^>]*>(.*?)</h2>', body_html, re.DOTALL):
        label = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        label = re.sub(r'<span[^>]*>.*?</span>\s*', '', label)  # 去掉 phase-badge
        label = label[:16]
        links.append(f'<a href="#{m.group(1)}">{label}</a>')
    return ''.join(links)


def _load_template_css() -> str:
    """从 docs/report-template/report_css.html 加载统一模板 CSS（仅读取一次）"""
    _REPORT_CSS_PATH = Path(__file__).parent.parent / "docs" / "report-template" / "report_css.html"
    if _REPORT_CSS_PATH.exists():
        css = _REPORT_CSS_PATH.read_text(encoding="utf-8")
        # 移除注释行
        return "\n".join(line for line in css.splitlines() if not line.strip().startswith("/*"))
    return ""


# 模块级缓存：CSS 仅加载一次
_TEMPLATE_CSS = _load_template_css()


def _render_html(title: str, body_html: str, header_meta: list | None = None) -> str:
    """统一 HTML 报告模板（暖灰商务风，参考 report_template_standards.md）"""
    meta_html = ""
    if header_meta:
        items = "".join(
            f'<span>{k.replace("_"," ").title()}: {v}</span>'
            for k, v in header_meta
        )
        meta_html = f'<div class="meta">{items}</div>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} | {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
{_TEMPLATE_CSS}
</style></head>
<body>

<header class="report-header">
  <div class="container">
    <div class="badge">FDT 辩论报告</div>
    <h1>{title}</h1>
    <p class="subtitle">明鉴秋 · 报告层调度 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    {meta_html}
  </div>
</header>

<nav class="nav-bar"><div class="container">{_nav_items(body_html)}</div></nav>

<main class="container">
{body_html}
</main>

<footer>
  <p>FDT 期货辩论团队 · 明鉴秋报告层</p>
  <p style="color:var(--red);margin-top:4px;">⚠️ 投资有风险，入市需谨慎。仅供参考，不构成投资建议。</p>
</footer>

</body></html>"""


def _build_body_sections(state: dict) -> str:
    """内部函数：从 state 生成单品种 body HTML（章节部分）"""
    trace_id = state.get("trace_id", "")
    symbols = state.get("selected_symbols", [])
    sym = symbols[0] if symbols else "unknown"
    sym_upper = sym.upper()
    now = datetime.now()

    # 品种信息
    profile_path = (
        Path(__file__).parent.parent / "memory" / "knowledge" / sym.lower() / "profile.json"
    )
    sym_name = sym_upper
    sym_exchange = ""
    sym_chain = ""
    try:
        if profile_path.exists():
            import json

            with open(profile_path, "r", encoding="utf-8") as pf:
                prof = json.load(pf)
            sym_name = prof.get("name", sym_upper)
            sym_exchange = prof.get("exchange", "")
            sym_chain = prof.get("chain", "")
    except Exception:
        pass

    # 各阶段数据
    scan_results = state.get("scan_results", {})
    all_ranked = scan_results.get("all_ranked", [])
    scan_item = next(
        (r for r in all_ranked if r.get("symbol", "").upper() == sym_upper), {}
    )
    stats = scan_item.get("stats", {})

    fdc_data = state.get("fdc_data", {})
    fdc_sym = fdc_data.get(sym, fdc_data.get(sym_upper, fdc_data.get(sym.lower(), {})))

    research_data = state.get("research_data") or {}

    tech_data = research_data.get("technical_data", {})
    tech_per_sym = tech_data.get("per_symbol", {}) if isinstance(tech_data, dict) else {}
    tech_sym = tech_per_sym.get(sym, tech_per_sym.get(sym_upper, tech_per_sym.get(sym.lower(), {})))

    fund_data = research_data.get("fundamental_data", {})
    fund_per_sym = fund_data.get("per_symbol", {}) if isinstance(fund_data, dict) else {}
    fund_sym = fund_per_sym.get(sym, fund_per_sym.get(sym_upper, fund_per_sym.get(sym.lower(), {})))

    sentiment_data = research_data.get("sentiment_data", {})

    verdict = state.get("verdict") or {}
    risk_check = state.get("risk_check") or {}
    if not risk_check:
        risk_check = (state.get("signal_output") or {}).get("risk_check", {})

    # K线
    kline_info = ""
    indicators = {}
    latest_close = 0
    latest_vol = 0
    if isinstance(fdc_sym, dict):
        kline_raw = fdc_sym.get("kline", [])
        # 兼容两种 kline 格式：list（node_load_cache）或 {"bars":[...]}（node_prepare_data）
        if isinstance(kline_raw, dict) and "bars" in kline_raw:
            kline_bars = kline_raw["bars"]
        elif isinstance(kline_raw, list):
            kline_bars = kline_raw
        else:
            kline_bars = []
        if isinstance(kline_bars, list) and kline_bars:
            last_bar = kline_bars[-1] if kline_bars else {}
            latest_close = float(last_bar.get("close", 0) or 0)
            latest_vol = int(last_bar.get("volume", 0) or 0)
            latest_oi = int(last_bar.get("oi", 0) or 0)
            kline_info = f"最新收盘={_fmt(latest_close)} | 成交量={latest_vol:,} | 持仓={latest_oi:,} | K线数={len(kline_bars)}"
        ind_raw = fdc_sym.get("indicators", {})
        if isinstance(ind_raw, dict):
            indicators = ind_raw.get("values", {})

    # P1 有效性
    p1_valid = bool(stats) or bool(indicators)

    # 裁决
    judge_per_sym = verdict.get("per_symbol", {}) if isinstance(verdict, dict) else {}
    sym_verdict = judge_per_sym.get(sym, judge_per_sym.get(sym_upper, judge_per_sym.get(sym.lower(), {})))
    if not isinstance(sym_verdict, dict):
        sym_verdict = {}

    verdict_dir = sym_verdict.get("direction", verdict.get("direction", "neutral"))
    verdict_conf = float(sym_verdict.get("confidence", verdict.get("confidence", 0.5)) or 0.5)
    verdict_reason = sym_verdict.get("reason", verdict.get("reason", ""))
    entry_p = float(sym_verdict.get("entry_price", 0) or 0)
    target_p = float(sym_verdict.get("target_price", 0) or 0)
    stop_p = float(sym_verdict.get("stop_loss_price", 0) or 0)
    pos_pct = float(sym_verdict.get("position_pct", 0) or 0)
    rr = float(sym_verdict.get("risk_reward_ratio", 0) or 0)

    dir_cn = {
        "buy": "做多", "bull": "做多", "bullish": "做多",
        "sell": "做空", "bear": "做空", "bearish": "做空",
        "neutral": "观望", "hold": "观望",
    }.get(str(verdict_dir).lower(), "观望")
    dir_color = (
        "#16a34a" if "buy" in str(verdict_dir).lower() or "bull" in str(verdict_dir).lower()
        else "#dc2626" if "sell" in str(verdict_dir).lower() or "bear" in str(verdict_dir).lower()
        else "#d97706"
    )

    # 风控
    risk_approved = risk_check.get("approved", False)
    risk_level = risk_check.get("risk_level", "unknown")
    risk_color_label = risk_check.get("risk_color", "unknown")
    risk_warnings = risk_check.get("warnings", [])
    risk_notes = risk_check.get("notes", "")
    risk_blocking = risk_check.get("blocking_reason", "")
    if not risk_blocking and not risk_approved:
        sig_msg = (state.get("signal_output") or {}).get("message", "")
        if sig_msg:
            risk_blocking = sig_msg

    # 辩论论据
    bull_v1 = _extract_args_from_list(state.get("bullish_arguments", []), sym_upper)
    bear_v1 = _extract_args_from_list(state.get("bearish_arguments", []), sym_upper)
    bear_rebut = _extract_args_from_list(state.get("bearish_rebuttal_arguments", []), sym_upper)
    bull_rebut = _extract_args_from_list(state.get("bullish_rebuttal_arguments", []), sym_upper)
    bear_final = _extract_args_from_list(state.get("bear_final_arguments", []), sym_upper)
    bull_final = _extract_args_from_list(state.get("bull_final_arguments", []), sym_upper)

    # 从辩论论据回退提取 P3 内容
    tech_from_debate = _extract_agent_output(state, "technical:观澜", sym, sym_upper)
    fund_from_debate = _extract_agent_output(state, "fundamental:探源", sym, sym_upper)
    sent_from_debate = _extract_agent_output(state, "sentiment:读心", sym, sym_upper)

    # ── 模板颜色变量 ──
    var_green = "var(--green)"  # #2d7d4f
    var_red = "var(--red)"      # #c44536
    var_yellow = "var(--yellow)"  # #c49a2b
    var_accent2 = "var(--accent2)"  # #2b6c7e

    # ── 构建各章节 ──
    sections: list[tuple[str, str, str]] = []

    # P1 数据总览 — metrics-summary 三列卡片
    if p1_valid:
        chg = stats.get("change_pct", 0) or 0 if stats else 0
        chg_cls = "chg-up" if chg >= 0 else "chg-down"
        price_latest = _fmt(stats.get("latest_close")) if stats else _fmt(latest_close)
        stats_rows = (
            f'<div class="metrics-summary">\n'
            f'<div class="metric-card"><div class="symbol">{sym_upper}</div>'
            f'<div class="price" style="color:{var_green if chg>=0 else var_red}">{price_latest}</div>'
            f'<div class="detail">涨跌幅 <span class="{chg_cls}">{_fmt_pct(chg)}</span></div></div>\n'
            f'<div class="metric-card"><div class="symbol">趋势</div>'
            f'<div class="price" style="font-size:1.2rem;">{_esc(stats.get("ma_align", "—"))}</div>'
            f'<div class="detail">ADX={_fmt(stats.get("adx_14"),1)} | RSI={_fmt(stats.get("rsi_14"),1)}</div></div>\n'
            f'<div class="metric-card"><div class="symbol">波动</div>'
            f'<div class="price" style="font-size:1.2rem;">ATR {_fmt(stats.get("atr_14"))}</div>'
            f'<div class="detail">量比 {_fmt(stats.get("volume_ma20_ratio"),2)}x | 20日位置 {_fmt(stats.get("price_position_pct"),1)}%</div></div>\n'
            f'</div>\n'
        )
        if stats:
            stats_rows += (
                f'<div class="info-grid">\n'
                f'<div class="info-card"><div class="head">关键指标</div>'
                f'<div class="info-item"><span class="k">MA20</span><span class="v">{_fmt(stats.get("ma_20"))}</span></div>'
                f'<div class="info-item"><span class="k">MA60</span><span class="v">{_fmt(stats.get("ma_60"))}</span></div>'
                f'<div class="info-item"><span class="k">RSI14</span><span class="v">{_fmt(stats.get("rsi_14"),1)}</span></div>'
                f'<div class="info-item"><span class="k">ADX14</span><span class="v">{_fmt(stats.get("adx_14"),1)}</span></div>'
                f'<div class="info-item"><span class="k">ATR14</span><span class="v">{_fmt(stats.get("atr_14"))}</span></div>'
                f'</div>\n'
                f'<div class="info-card"><div class="head">量价持仓</div>'
                f'<div class="info-item"><span class="k">持仓</span><span class="v">{_fmt(stats.get("oi"))}</span></div>'
                f'<div class="info-item"><span class="k">持仓变化</span><span class="v">{_fmt(stats.get("oi_change"))}</span></div>'
                f'<div class="info-item"><span class="k">量比20</span><span class="v">{_fmt(stats.get("volume_ma20_ratio"),2)}x</span></div>'
                f'<div class="info-item"><span class="k">20日位置</span><span class="v">{_fmt(stats.get("price_position_pct"),1)}%</span></div>'
                f'<div class="info-item"><span class="k">K线</span><span class="v">{_fmt(stats.get("n_bars"))}根</span></div>'
                f'</div>\n'
                f'</div>\n'
            )
        elif indicators:
            stats_rows += (
                f'<div class="info-grid">\n'
                f'<div class="info-card"><div class="head">FDC 原始指标</div>'
                f'<div class="info-item"><span class="k">收盘价</span><span class="v">{_fmt(latest_close)}</span></div>'
                f'<div class="info-item"><span class="k">RSI</span><span class="v">{_fmt(indicators.get("RSI14", indicators.get("rsi_14")),1)}</span></div>'
                f'<div class="info-item"><span class="k">ADX</span><span class="v">{_fmt(indicators.get("ADX", indicators.get("adx")),1)}</span></div>'
                f'<div class="info-item"><span class="k">MACD_DIF</span><span class="v">{_fmt(indicators.get("MACD_DIF", indicators.get("macd_dif")),1)}</span></div>'
                f'<div class="info-item"><span class="k">ATR14</span><span class="v">{_fmt(indicators.get("ATR14", indicators.get("atr_14")),1)}</span></div>'
                f'</div>\n'
                f'</div>\n'
            )
        else:
            stats_rows = '<div class="callout">无统计数据</div>'
        sections.append(
            ("P1 数技源 · 数据总览", stats_rows, "#c44536"),
        )

    # P2 观澜 — info-grid 展示技术面
    if isinstance(tech_sym, dict) and tech_sym.get("analysis"):
        tech_html = f'<div class="info-grid"><div class="info-card"><div class="head">观澜技术分析</div><div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(tech_sym["analysis"])}</div></div></div>'
    elif isinstance(tech_sym, dict) and tech_sym.get("summary"):
        tech_html = f'<div class="info-grid"><div class="info-card"><div class="head">观澜技术摘要</div><div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(tech_sym["summary"])}</div></div></div>'
    # v9.23.1: 渲染 node_technical fallback 产生的结构化字段 (trend/key_levels/volume_price/divergence/pattern/score)
    elif isinstance(tech_sym, dict) and tech_sym.get("trend"):
        tech_items = [
            ("趋势判断", tech_sym.get("trend", "")),
            ("关键价位", tech_sym.get("key_levels", "")),
            ("量价关系", tech_sym.get("volume_price", "")),
            ("MACD背离", tech_sym.get("divergence", "")),
            ("技术形态", tech_sym.get("pattern", "")),
        ]
        score_val = tech_sym.get("score")
        score_html = f'<span style="font-size:1.3rem;font-weight:700;">{score_val}</span>' if score_val else ""
        tech_inner = "".join(
            f'<div class="info-item"><span class="k">{label}</span><span class="v">{_esc(str(val))}</span></div>'
            for label, val in tech_items
        )
        if score_val:
            score_html = f'<div class="info-card"><div class="head">综合评分</div><div style="font-size:1.3rem;font-weight:700;text-align:center;">{score_val}</div></div>'
        tech_html = f'<div class="info-grid"><div class="info-card"><div class="head">观澜技术面（FDC自主计算）</div>{tech_inner}</div>{score_html}</div>'
    elif tech_from_debate:
        tech_html = f'<div class="info-grid"><div class="info-card"><div class="head">辩论引用</div><div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(tech_from_debate)}</div></div></div>'
    elif indicators:
        rsi_v = _fmt(indicators.get("RSI14", indicators.get("rsi_14")), 1)
        adx_v = _fmt(indicators.get("ADX", indicators.get("adx")), 1)
        macd_v = _fmt(indicators.get("MACD_DIF", indicators.get("macd_dif")), 1)
        atr_v = _fmt(indicators.get("ATR14", indicators.get("atr_14")), 1)
        tech_html = (
            f'<div class="info-grid">\n'
            f'<div class="info-card"><div class="head">RSI</div><div style="font-size:1.2rem;font-weight:700;">{rsi_v}</div></div>\n'
            f'<div class="info-card"><div class="head">ADX</div><div style="font-size:1.2rem;font-weight:700;">{adx_v}</div></div>\n'
            f'<div class="info-card"><div class="head">MACD_DIF</div><div style="font-size:1.2rem;font-weight:700;">{macd_v}</div></div>\n'
            f'<div class="info-card"><div class="head">ATR14</div><div style="font-size:1.2rem;font-weight:700;">{atr_v}</div></div>\n'
            f'</div>\n'
            f'<div class="callout">FDC 原始指标 — LLM 分析未返回结构化数据</div>\n'
        )
    else:
        tech_html = '<div class="callout">无技术分析数据</div>'
    sections.append(("P2 观澜 · 技术面", tech_html, var_accent2))

    # P2 探源 — info-grid 展示基本面
    fund_parts = []
    if isinstance(fund_sym, dict):
        for k, label in (
            ("supply_demand", "供需"),
            ("inventory", "库存"),
            ("profit_margin", "利润"),
            ("basis_term", "期限"),
            ("leading_signals", "领先信号"),
        ):
            v = fund_sym.get(k, "")
            if v:
                if isinstance(v, list):
                    v = "; ".join(str(x) for x in v)
                fund_parts.append(f'<div class="info-item"><span class="k">{label}</span><span class="v">{_esc(v)}</span></div>')
    if fund_parts:
        fund_html = f'<div class="info-grid"><div class="info-card"><div class="head">探源基本面</div>{"".join(fund_parts)}</div></div>'
    elif fund_from_debate:
        fund_html = f'<div class="info-grid"><div class="info-card"><div class="head">辩论引用</div><div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(fund_from_debate)}</div></div></div>'
    else:
        fund_html = '<div class="callout">无基本面数据（FDC 全维度 UNAVAILABLE，LLM 未返回结构化数据）</div>'
    sections.append(("P3 探源 · 基本面", fund_html, var_yellow))

    # P2 读心 — info-card 展示情绪
    if isinstance(sentiment_data, dict) and sentiment_data:
        score = sentiment_data.get("overall_score", 0)
        score_color = var_green if score > 0 else var_red if score < 0 else var_yellow
        sent_html = (
            f'<div class="info-grid">\n'
            f'<div class="info-card"><div class="head">情绪评分</div>'
            f'<div style="font-size:1.8rem;font-weight:800;color:{score_color};">{score}</div></div>\n'
            f'<div class="info-card"><div class="head">摘要</div>'
            f'<div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(sentiment_data.get("summary", ""))}</div></div>\n'
            f'</div>\n'
        )
    elif sent_from_debate:
        sent_html = f'<div class="info-grid"><div class="info-card"><div class="head">辩论引用</div><div style="font-size:0.82rem;color:var(--muted);line-height:1.8;">{_esc(sent_from_debate)}</div></div></div>'
    else:
        sent_html = '<div class="callout">无情绪数据</div>'
    sections.append(("P3 读心 · 新闻情绪", sent_html, var_accent2))

    # P3 辩论 — debate-round 组件
    debate_html = ""
    debate_rounds = [
        ("bull_v1", "🟢 多头立论", var_red, "#c44536"),
        ("bear_v1", "🔴 空头立论", var_accent2, "#2b6c7e"),
        ("bear_rebut", "🔴 空头反驳", var_accent2, "#2b6c7e"),
        ("bull_rebut", "🟢 多头反驳", var_red, "#c44536"),
        ("bear_final", "🔴 空头终述", var_accent2, "#2b6c7e"),
        ("bull_final", "🟢 多头终述", var_red, "#c44536"),
    ]
    args_map = {"bull_v1": bull_v1, "bear_v1": bear_v1, "bear_rebut": bear_rebut, "bull_rebut": bull_rebut, "bear_final": bear_final, "bull_final": bull_final}

    def _debate_round_html(label, args, color, num_cls):
        if not args:
            return ""
        import re
        items = "".join(
            f'<div class="arg-item"><div class="arg-claim">{_esc(re.sub(r"\[\w+:", "[", a))}</div></div>'
            for a in args
        )
        num_tag = f'<span class="num {num_cls}">{"B" if "bull" in label.lower() else "S"}</span>'
        return f'<div class="debate-round"><div class="round-title">{num_tag} {label}</div><div class="round-body">{items}</div></div>'

    for key, label, _, num_cls in debate_rounds:
        debate_html += _debate_round_html(label, args_map.get(key, []), _, num_cls)
    if not debate_html:
        debate_html = '<div class="callout">无辩论论据（fast 模式跳过辩论）</div>'
    sections.append(("P3 六阶段辩论 · 多空攻防", debate_html, "#6366f1"))

    # P4 终裁 — verdict-box 组件
    rr_color = var_green if rr >= 2 else var_yellow if rr >= 1 else var_red
    current_price = latest_close if latest_close > 0 else (float(scan_item.get("price", 0) or 0) if scan_item else 0)
    action_hint = f"当前市价 {_fmt(current_price)}，以 market order 执行" if current_price > 0 else ""
    if entry_p > 0 and current_price > 0 and entry_p != current_price:
        entry_p = current_price
    entry_p = current_price if current_price > 0 else entry_p

    verdict_html = (
        f'<div class="verdict-box">\n'
        f'<div class="vh"><div class="vd">{dir_cn}</div>'
        f'<div class="vc">置信度 <strong>{verdict_conf:.0%}</strong>'
        f'<div class="vb"><div class="f" style="width:{verdict_conf*100}%;background:{dir_color};"></div></div></div></div>\n'
        f'<div class="sg">\n'
        f'<div class="si"><div class="l">入场价</div><div class="v">{_fmt(entry_p)}</div><div class="w">市价</div></div>\n'
        f'<div class="si"><div class="l">目标价</div><div class="v">{_fmt(target_p)}</div><div class="w">→ {dir_cn}</div></div>\n'
        f'<div class="si"><div class="l">止损价</div><div class="v" style="color:var(--red);">{_fmt(stop_p)}</div><div class="w">风险控制</div></div>\n'
        f'<div class="si"><div class="l">仓位</div><div class="v">{pos_pct:.1f}%</div><div class="w">建议比例</div></div>\n'
        f'<div class="si"><div class="l">盈亏比</div><div class="v" style="color:{rr_color};">{rr:.2f}:1</div><div class="w">{action_hint}</div></div>\n'
        f'</div>\n'
        f'</div>\n'
        f'<div class="callout">{_esc(verdict_reason)}</div>\n'
    )
    sections.append(("P4 闫判官 · 终裁与交易参数", verdict_html, dir_color))

    # P5 风控 — risk-box 组件
    risk_cls = "danger" if risk_color_label in ("red", "红灯") else "warn" if risk_color_label in ("yellow", "黄灯") else ""
    risk_status = "✅ 审核通过" if risk_approved else "❌ 阻断"
    risk_html = (
        f'<div class="risk-box {risk_cls}">\n'
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">\n'
        f'<span style="font-weight:700;font-size:1.05em;">{risk_status}</span>\n'
        f'<span class="text-sm text-muted">风控等级: <span class="tag {"tag-high" if risk_color_label in ("red","红灯") else "tag-mid" if risk_color_label in ("yellow","黄灯") else "tag-low"}">{risk_level}</span></span>\n'
        f'</div>\n'
    )
    if risk_blocking:
        risk_html += f'<div style="margin-top:8px;color:var(--red);font-size:0.85em;line-height:1.6;"><b>阻断原因:</b> {_esc(risk_blocking)}</div>\n'
    if risk_warnings:
        for w in risk_warnings:
            risk_html += f'<div class="text-sm text-muted" style="margin-top:4px;">⚠ {_esc(w)}</div>\n'
    if risk_notes:
        risk_html += f'<div style="margin-top:6px;color:var(--yellow);font-size:0.82em;">📝 {_esc(risk_notes)}</div>\n'
    risk_html += '</div>\n'
    sections.append(("P5 风控明 · 风险审核", risk_html, var_yellow if "warn" in risk_cls else var_green))

    # ── 组装 body ──
    section_ids = {
        "P1 数技源 · 数据总览": "p1-stats",
        "P2 观澜 · 技术面": "p2-tech",
        "P3 探源 · 基本面": "p3-fund",
        "P3 读心 · 新闻情绪": "p3-sent",
        "P3 六阶段辩论 · 多空攻防": "p3-debate",
        "P4 闫判官 · 终裁与交易参数": "p4-verdict",
        "P5 风控明 · 风险审核": "p5-risk",
    }
    body_html = ""
    for stitle, shtml, _ in sections:
        sid = section_ids.get(stitle, "")
        phase = sid.split("-")[0] if sid else ""
        color_map = {"p1": "p1", "p2": "p2", "p3": "p3", "p4": "p4", "p5": "p5"}
        badge_cls = color_map.get(phase, phase)
        badge = f'<span class="phase-badge {badge_cls}">{phase.upper()}</span>' if phase else ""
        body_html += (
            f'<section id="{sid}">\n'
            f'<h2>{badge} {stitle.split("·")[-1].strip()}</h2>\n'
            f'{shtml}\n'
            f'</section>\n'
        )

    return body_html


def generate(state: dict) -> str:
    """从 state 生成完整的单品种辩论报告 HTML"""
    symbols = state.get("selected_symbols", [])
    sym = symbols[0] if symbols else "unknown"
    body = generate_body(state, sym)
    sym_upper = sym.upper()

    # 提取 header metadata（轻量级）
    profile_path = Path(__file__).parent.parent / "memory" / "knowledge" / sym.lower() / "profile.json"
    sym_name = sym_upper
    try:
        if profile_path.exists():
            import json
            with open(profile_path, "r", encoding="utf-8") as pf:
                prof = json.load(pf)
            sym_name = prof.get("name", sym_upper)
    except Exception:
        pass

    verdict = state.get("verdict") or {}
    js = verdict.get("per_symbol", {}) if isinstance(verdict, dict) else {}
    sv = js.get(sym, js.get(sym_upper, js.get(sym.lower(), {})))
    if not isinstance(sv, dict): sv = {}
    vd = sv.get("direction", verdict.get("direction", "neutral"))
    vc = float(sv.get("confidence", verdict.get("confidence", 0.5)) or 0.5)
    dcn = {"buy": "做多", "bull": "做多", "bullish": "做多", "sell": "做空", "bear": "做空", "bearish": "做空", "neutral": "观望", "hold": "观望"}.get(str(vd).lower(), "观望")
    rc = state.get("risk_check") or {}
    if not rc: rc = (state.get("signal_output") or {}).get("risk_check", {})
    rapp = rc.get("approved", False)

    return _render_html(f"{sym_name} {sym_upper} 辩论报告", body, [
        ("trace_id", state.get("trace_id", "")),
        ("品种", f"{sym_name} ({sym_upper})"),
        ("交易所", prof.get("exchange", "—")),
        ("产业链", prof.get("chain", "—")),
        ("裁决", f"{dcn} ({vc:.0%})"),
        ("风控", "通过" if rapp else "阻断"),
    ])


def generate_body(state: dict, sym: str) -> str:
    """生成单品种辩论报告 body HTML（不含 _render_html 外壳）

    构造 single-symbol state 快照后调用 generate() 提取 body 部分。
    """
    single_state = dict(state)
    single_state["selected_symbols"] = [sym]
    return _build_body_sections(single_state)
