"""单品种辩论报告生成器 — 从 FDT state 生成精简报告"""

from __future__ import annotations

import html
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


def _render_html(title: str, body_html: str, header_meta: list | None = None) -> str:
    """统一 HTML 报告模板（明鉴秋报告层通用）"""
    meta_html = ""
    if header_meta:
        items = "".join(
            f'<div class="meta-item"><span class="label">{k}</span> <span class="value">{v}</span></div>'
            for k, v in header_meta
        )
        meta_html = f'<div class="meta">{items}</div>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} | {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f1117;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1d28 0%,#2a1f1f 50%,#1a1d28 100%);padding:32px;border-radius:14px;margin-bottom:24px;text-align:center;border:1px solid #f59e0b33}}
.header h1{{font-size:1.8em;color:#f59e0b;margin-bottom:6px}}
.header .subtitle{{color:#888;font-size:0.9em}}
.header .meta{{display:flex;justify-content:center;gap:14px;margin-top:14px;flex-wrap:wrap}}
.meta-item{{background:#1a1d28;padding:6px 14px;border-radius:6px;border:1px solid #2a2d38;font-size:0.85em}}
.meta-item .label{{color:#888}}
.meta-item .value{{color:#f59e0b;font-weight:bold}}
.section{{background:#1a1d28;border-radius:10px;padding:20px 24px;margin-bottom:18px;border:1px solid #2a2d38}}
.section h2{{color:#f59e0b;font-size:1.2em;margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid #2a2d38}}
.kv{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #232530;}}
.kv .k{{color:#777;font-size:0.78em;}}
.kv .v{{color:#e8e8e8;font-weight:600;font-size:0.88em;}}
.kv-box{{background:#1a1c26;border-radius:8px;padding:14px 16px;border:1px solid #2a2d3a;}}
.arg-box{{margin:3px 0;padding:5px 10px;background:#14161f;border-radius:4px;border-left:3px solid;font-size:0.8em;color:#bbb;line-height:1.5;}}
.footer{{text-align:center;color:#555;font-size:0.8em;padding:24px;border-top:1px solid #2a2d38;margin-top:24px}}
</style></head>
<body><div class="container">
<div class="header">
  <h1>{title}</h1>
  <div class="subtitle">明鉴秋 · 报告层调度</div>
  {meta_html}
</div>
{body_html}
<div class="footer">
  <p>FDT 期货辩论团队 | 明鉴秋报告层 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  <p style="color:#ef4444;">⚠️ 投资有风险，入市需谨慎。仅供参考，不构成投资建议。</p>
</div>
</div></body></html>"""


def generate(state: dict) -> str:
    """从 state 生成单品种辩论报告 HTML"""
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

    judge_dir = state.get("judge_direction", {})
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
        kline_bars = fdc_sym.get("kline", [])
        if isinstance(kline_bars, list) and kline_bars:
            last_bar = kline_bars[-1] if kline_bars else {}
            latest_close = float(last_bar.get("close", 0) or 0)
            latest_vol = int(last_bar.get("volume", 0) or 0)
            latest_oi = int(last_bar.get("oi", 0) or 0)
            kline_info = f"最新收盘={_fmt(latest_close)} | 成交量={latest_vol:,} | 持仓={latest_oi:,} | K线数={len(kline_bars)}"
        ind_raw = fdc_sym.get("indicators", {})
        if isinstance(ind_raw, dict):
            indicators = ind_raw.get("values", {})

    # P1/P2 有效性
    p1_valid = bool(stats) or bool(indicators)
    p2_valid = judge_dir.get("direction") not in (None, "neutral") or judge_dir.get("confidence", 0) > 0.3

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

    # ── 构建各章节 ──
    sections: list[tuple[str, str, str]] = []

    # P1
    if p1_valid:
        if stats:
            stats_rows = (
                f'<div class="kv"><span class="k">收盘价</span><span class="v">{_fmt(stats.get("latest_close"))}</span></div>\n'
                f'<div class="kv"><span class="k">涨跌幅</span><span class="v" style="color:{"#16a34a" if (stats.get("change_pct", 0) or 0) >= 0 else "#dc2626"};">{_fmt_pct(stats.get("change_pct"))}</span></div>\n'
                f'<div class="kv"><span class="k">MA20</span><span class="v">{_fmt(stats.get("ma_20"))}</span></div>\n'
                f'<div class="kv"><span class="k">MA60</span><span class="v">{_fmt(stats.get("ma_60"))}</span></div>\n'
                f'<div class="kv"><span class="k">ATR14</span><span class="v">{_fmt(stats.get("atr_14"))}</span></div>\n'
                f'<div class="kv"><span class="k">RSI14</span><span class="v">{_fmt(stats.get("rsi_14"), 1)}</span></div>\n'
                f'<div class="kv"><span class="k">ADX14</span><span class="v">{_fmt(stats.get("adx_14"), 1)}</span></div>\n'
                f'<div class="kv"><span class="k">量比20</span><span class="v">{_fmt(stats.get("volume_ma20_ratio"), 2)}x</span></div>\n'
                f'<div class="kv"><span class="k">MA排列</span><span class="v">{_esc(stats.get("ma_align", "—"))}</span></div>\n'
                f'<div class="kv"><span class="k">20日位置</span><span class="v">{_fmt(stats.get("price_position_pct"), 1)}%</span></div>'
            )
        elif indicators:
            stats_rows = (
                f'<div class="kv"><span class="k">收盘价</span><span class="v">{_fmt(latest_close)}</span></div>\n'
                f'<div class="kv"><span class="k">RSI</span><span class="v">{_fmt(indicators.get("RSI14", indicators.get("rsi_14")), 1)}</span></div>\n'
                f'<div class="kv"><span class="k">ADX</span><span class="v">{_fmt(indicators.get("ADX", indicators.get("adx")), 1)}</span></div>\n'
                f'<div class="kv"><span class="k">MACD_DIF</span><span class="v">{_fmt(indicators.get("MACD_DIF", indicators.get("macd_dif")), 1)}</span></div>\n'
                f'<div class="kv"><span class="k">ATR14</span><span class="v">{_fmt(indicators.get("ATR14", indicators.get("atr_14")), 1)}</span></div>'
            )
        else:
            stats_rows = '<div style="color:#888;">无统计数据</div>'
        sections.append(
            (
                "P1 数技源 · 统计特征",
                f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px;font-size:0.82em;">{stats_rows}</div>',
                "#3b82f6",
            )
        )

    # P2
    if p2_valid:
        p2_html = (
            f'<div style="color:#ccc;font-size:0.85em;line-height:1.7;">\n'
            f'<b>预判方向</b>: {judge_dir.get("direction", "—")} &nbsp;|&nbsp;\n'
            f'<b>置信度</b>: {judge_dir.get("confidence", 0):.0%} &nbsp;|&nbsp;\n'
            f'<b>数据源</b>: {", ".join(judge_dir.get("dispatch_sources", [])) or "—"}<br>\n'
            f'<span style="color:#aaa;">{_esc(judge_dir.get("reason", ""))}</span>\n'
            f'</div>'
        )
        sections.append(("P2 闫判官 · 方向预判", p2_html, "#8b5cf6"))

    # P3 观澜
    if isinstance(tech_sym, dict) and tech_sym.get("analysis"):
        tech_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{_esc(tech_sym["analysis"])}</div>'
    elif isinstance(tech_sym, dict) and tech_sym.get("summary"):
        tech_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{_esc(tech_sym["summary"])}</div>'
    elif tech_from_debate:
        tech_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{_esc(tech_from_debate)}</div>'
    elif indicators:
        tech_html = (
            f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">\n'
            f'RSI={_fmt(indicators.get("RSI14", indicators.get("rsi_14")), 1)} |\n'
            f'ADX={_fmt(indicators.get("ADX", indicators.get("adx")), 1)} |\n'
            f'MACD_DIF={_fmt(indicators.get("MACD_DIF", indicators.get("macd_dif")), 1)} |\n'
            f'ATR14={_fmt(indicators.get("ATR14", indicators.get("atr_14")), 1)}\n'
            f'<br><span style="color:#888;">（FDC 原始指标，LLM 分析未返回结构化数据）</span>\n'
            f'</div>'
        )
    else:
        tech_html = '<div style="color:#888;">无技术分析数据</div>'
    sections.append(("P3 观澜 · 技术面", tech_html, "#06b6d4"))

    # P3 探源
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
                fund_parts.append(f'<b style="color:#aaa;">{label}</b>: {_esc(v)}')
    if fund_parts:
        fund_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{"<br>".join(fund_parts)}</div>'
    elif fund_from_debate:
        fund_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{_esc(fund_from_debate)}</div>'
    else:
        fund_html = '<div style="color:#888;">无基本面数据（FDC 全维度 UNAVAILABLE，LLM 未返回结构化数据）</div>'
    sections.append(("P3 探源 · 基本面", fund_html, "#f59e0b"))

    # P3 读心
    if isinstance(sentiment_data, dict) and sentiment_data:
        score = sentiment_data.get("overall_score", 0)
        sent_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">情绪评分: {score} | {_esc(sentiment_data.get("summary", ""))}</div>'
    elif sent_from_debate:
        sent_html = f'<div style="color:#ccc;font-size:0.85em;line-height:1.8;">{_esc(sent_from_debate)}</div>'
    else:
        sent_html = '<div style="color:#888;">无情绪数据</div>'
    sections.append(("P3 读心 · 新闻情绪", sent_html, "#ec4899"))

    # P4 辩论
    debate_html = ""
    if bull_v1 or bear_v1:

        def _args_block(args, label, color):
            if not args:
                return ""
            items = "".join(
                f'<div class="arg-box" style="border-left-color:{color};">{_esc(a)}</div>'
                for a in args
            )
            return f'<div style="margin-top:6px;"><div style="color:{color};font-size:0.75em;font-weight:bold;margin-bottom:4px;">{label}</div>{items}</div>'

        debate_html = _args_block(bull_v1, "🟢 多头立论", "#16a34a")
        debate_html += _args_block(bear_v1, "🔴 空头立论", "#dc2626")
        debate_html += _args_block(bear_rebut, "🔴 空头反驳", "#dc2626")
        debate_html += _args_block(bull_rebut, "🟢 多头反驳", "#16a34a")
        debate_html += _args_block(bear_final, "🔴 空头终述", "#dc2626")
        debate_html += _args_block(bull_final, "🟢 多头终述", "#16a34a")
    else:
        debate_html = '<div style="color:#888;">无辩论论据（fast 模式跳过辩论）</div>'
    sections.append(("P4 六阶段辩论 · 多空攻防", debate_html, "#6366f1"))

    # P5 终裁
    rr_color = "#16a34a" if rr >= 2 else "#d97706" if rr >= 1 else "#dc2626"
    verdict_html = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">\n'
        f'<div class="kv-box" style="border-left:3px solid {dir_color};">\n'
        f'<div class="kv"><span class="k">裁决方向</span><span class="v" style="color:{dir_color};font-size:1.1em;">{dir_cn}</span></div>\n'
        f'<div class="kv"><span class="k">置信度</span><span class="v">{verdict_conf:.0%}</span></div>\n'
        f'<div class="kv"><span class="k">盈亏比</span><span class="v" style="color:{rr_color};">{rr:.2f}:1</span></div>\n'
        f'</div>\n'
        f'<div class="kv-box" style="border-left:3px solid #6366f1;">\n'
        f'<div class="kv"><span class="k">入场价</span><span class="v">{_fmt(entry_p)}</span></div>\n'
        f'<div class="kv"><span class="k">目标价</span><span class="v">{_fmt(target_p)}</span></div>\n'
        f'<div class="kv"><span class="k">止损价</span><span class="v" style="color:#dc2626;">{_fmt(stop_p)}</span></div>\n'
        f'<div class="kv"><span class="k">仓位</span><span class="v">{pos_pct:.1f}%</span></div>\n'
        f'</div>\n'
        f'</div>\n'
        f'<div style="margin-top:10px;color:#aaa;font-size:0.82em;line-height:1.6;padding:8px 12px;background:#14161f;border-radius:6px;">{_esc(verdict_reason)}</div>'
    )
    sections.append(("P5 闫判官 · 终裁与交易参数", verdict_html, dir_color))

    # P5 风控
    risk_status = "✅ 审核通过" if risk_approved else "❌ 阻断"
    risk_status_color = "#16a34a" if risk_approved else "#dc2626"
    risk_html = (
        f'<div style="margin-bottom:10px;">\n'
        f'<span style="font-weight:bold;color:{risk_status_color};font-size:1.05em;">{risk_status}</span>\n'
        f'<span style="color:#888;margin-left:12px;font-size:0.85em;">风险等级: {risk_level} | 风险颜色: {risk_color_label}</span>\n'
        f'</div>'
    )
    if risk_blocking:
        risk_html += (
            f'<div style="margin:8px 0;padding:8px 12px;background:#1a0a0a;border-radius:6px;'
            f'border-left:3px solid #dc2626;color:#dc2626;font-size:0.85em;line-height:1.6;">\n'
            f'<b>阻断原因:</b> {_esc(risk_blocking)}\n'
            f'</div>'
        )
    if risk_warnings:
        risk_html += '<div style="margin-top:6px;">'
        for w in risk_warnings:
            risk_html += (
                f'<div style="color:#ef4444;font-size:0.8em;margin:3px 0;padding:5px 10px;'
                f'background:#14161f;border-radius:4px;">⚠ {_esc(w)}</div>'
            )
        risk_html += "</div>"
    if risk_notes:
        risk_html += (
            f'<div style="color:#d97706;font-size:0.82em;margin-top:8px;padding:6px 10px;'
            f'background:#14161f;border-radius:4px;">📝 {_esc(risk_notes)}</div>'
        )
    sections.append(("P5 风控明 · 风险审核", risk_html, risk_status_color))

    # ── 组装 body ──
    body_sections = ""
    for title, html, accent_color in sections:
        body_sections += (
            f'<div class="section" style="border-left:3px solid {accent_color}33;">\n'
            f'<h2 style="color:{accent_color};">{title}</h2>\n'
            f'{html}\n'
            f'</div>\n'
        )

    # 报告头（简洁，不重复 _render_html 的 header）
    header_html = (
        f'<div style="text-align:center;margin-bottom:20px;padding:16px;background:#181a24;'
        f'border-radius:10px;border:1px solid {dir_color}25;">\n'
        f'<div style="color:#888;font-size:0.85em;margin-bottom:6px;">'
        f'{sym_name} {sym_upper} · {sym_exchange or "—"} · {sym_chain or "—"}</div>\n'
        f'<div style="display:inline-block;padding:6px 18px;border-radius:6px;font-weight:700;'
        f'font-size:1.1em;color:{dir_color};background:{dir_color}12;border:1px solid {dir_color}35;">\n'
        f'{dir_cn} · 置信度 {verdict_conf:.0%}\n'
        f'</div>\n'
        f'<div style="margin-top:8px;color:#666;font-size:0.78em;">\n'
        f'最新价 {_fmt(latest_close)} · 成交量 {latest_vol:,} · 风控: {risk_status}\n'
        f'</div>\n'
        f'</div>\n'
    )

    body = (
        header_html
        + body_sections
        + '<div class="section" style="border-left:3px solid #dc262633;background:#1a0a0a;">\n'
        + '<h2 style="color:#dc2626;">⚠️ 风险提示</h2>\n'
        + '<p style="color:#c45c5c;font-size:0.82em;line-height:1.8;margin:0;">\n'
        + "1. 本报告仅为量化分析参考，不构成任何投资建议。<br>\n"
        + "2. 右侧交易铁律：所有信号需等待价格突破关键位置确认后方可执行，禁止提前布局。<br>\n"
        + "3. 期货交易具有高风险性，可能导致本金全部亏损，请谨慎参与。\n"
        + "</p>\n"
        + "</div>\n"
    )

    return _render_html(
        f"{sym_name} {sym_upper} 辩论报告",
        body,
        [
            ("trace_id", trace_id),
            ("品种", f"{sym_name} ({sym_upper})"),
            ("交易所", sym_exchange or "—"),
            ("产业链", sym_chain or "—"),
            ("裁决", f"{dir_cn} ({verdict_conf:.0%})"),
            ("风控", "通过" if risk_approved else "阻断"),
        ],
    )
