import sys
import importlib.util
import os
import logging
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .state import DebateState
from .agents import FdtAgentExecutor

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

logger = logging.getLogger(__name__)

def _ensure_llm_key():
    if not os.environ.get("FDT_LLM_API_KEY"):
        if os.environ.get("OPENAI_API_KEY"):
            os.environ["FDT_LLM_API_KEY"] = os.environ["OPENAI_API_KEY"]
            logger.info("[LLM] Using OPENAI_API_KEY as FDT_LLM_API_KEY")


# ==================== 报告层调度 (v8.8.0) ====================
def _resolve_report_dir() -> Path:
    """解析报告输出目录：用户指定工作空间 > 默认工作空间 > 程序目录 fallback

    优先级：
      1. 环境变量 FDT_REPORT_WORKSPACE 指向的工作空间根目录
      2. 环境变量 FDT_DAILY_WORKSPACE（D:\\FDTWorkspace 之类）
      3. 调用方传入的临时目录（test 场景）
    """
    workspace = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE")
    if workspace:
        from datetime import datetime as _dt
        report_dir = Path(workspace) / _dt.now().strftime("%Y-%m-%d")
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir
    return Path(tempfile.gettempdir()) / "fdt_reports"


def _render_html(title: str, body_html: str, header_meta: list[tuple[str, str]] | None = None) -> str:
    """统一 HTML 报告模板（明鉴秋报告层通用）"""
    from datetime import datetime as _dt
    meta_html = ""
    if header_meta:
        items = "".join(f'<div class="meta-item"><span class="label">{k}</span> <span class="value">{v}</span></div>' for k, v in header_meta)
        meta_html = f'<div class="meta">{items}</div>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} | {_dt.now().strftime('%Y-%m-%d')}</title>
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
table{{width:100%;border-collapse:collapse;font-size:0.85em}}
th{{background:#252836;color:#f59e0b;padding:8px 10px;text-align:left;border-bottom:2px solid #f59e0b44;white-space:nowrap}}
td{{padding:6px 10px;border-bottom:1px solid #2a2d38;word-break:break-word}}
tr:hover td{{background:#25283644}}
.num{{text-align:right;font-family:'Courier New',monospace;white-space:nowrap}}
.tag-buy{{color:#22c55e;font-weight:bold}}
.tag-sell{{color:#ef4444;font-weight:bold}}
.tag-hold{{color:#f59e0b;font-weight:bold}}
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
  <p>FDT 期货辩论团队 | 明鉴秋报告层 | {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  <p style="color:#ef4444;">⚠️ 投资有风险，入市需谨慎。仅供参考，不构成投资建议。</p>
</div>
</div></body></html>"""


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
            rsi = item.get("rsi", 50)
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
    """生成裁决报告 (P5 阶段) — 闫判官裁决 + 风控明审核"""
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
<h2>⚖️ P5 · 闫判官裁决</h2>
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
    """生成研究报告 (P3 阶段) — 三源（链证源/观澜/探源）合并分析"""
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

    body = f"""<div class="section">
<h2>🔗 P3 · 链证源 — 产业链分析</h2>
<p class="subtitle">覆盖产业链 {chain_count} 条</p>
<pre style="background:#252836;padding:12px;border-radius:6px;overflow:auto;font-size:0.78em;color:#ccc;">{str(chain_analysis)[:2000] if chain_analysis else '（未触发）'}</pre>
</div>

<div class="section">
<h2>📈 P3 · 观澜 — 技术面分析（逐品种）</h2>
<p class="subtitle">覆盖 {len(tech_per_symbol)} 个品种</p>
<table><thead><tr><th>品种</th><th>趋势判断</th><th class="num">评分</th></tr></thead>
<tbody>{tech_rows}</tbody></table>
</div>

<div class="section">
<h2>🔬 P3 · 探源 — 基本面分析（逐品种）</h2>
<p class="subtitle">覆盖 {len(fund_per_symbol)} 个品种</p>
<table><thead><tr><th>品种</th><th>供需</th><th>库存</th><th>期限结构</th></tr></thead>
<tbody>{fund_rows}</tbody></table>
</div>"""

    html = _render_html("🔍 研究报告（三源）", body, [
        ("trace_id", trace_id),
        ("产业链", f"{chain_count}"),
        ("技术", f"{len(tech_per_symbol)}"),
        ("基本面", f"{len(fund_per_symbol)}"),
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
<tr><th>入场价</th><td class="num">{signal.get('entry_price', 0)}</td></tr>
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
        sig_rows = '<table><thead><tr><th>\u54c1\u79cd</th><th>\u65b9\u5411</th><th class="num">\u4fe1\u5fc3\u5ea6</th><th class="num">\u5165\u573a\u4ef7</th></tr></thead><tbody>'
        for x in sorted(signals_list, key=lambda v: abs(v.get("score", 0)), reverse=True):
            nm = x.get("symbol", "")
            sd = x.get("direction", "")
            sc = x.get("score", 0) or 0
            ep = float(x.get("entry_price", 0) or 0)
            sig_rows += '<tr><td>%s</td><td>%s</td><td class="num">%d%%</td><td class="num">%.2f</td></tr>' % (nm, sd, min(100, sc), ep)
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


def _import_from_skill(skill_dir: str, module_path: str, function_name: str):
    full_path = _SKILLS_DIR / skill_dir / (module_path.replace("/", "\\") + ".py")
    spec = importlib.util.spec_from_file_location(module_path.replace("/", "."), full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {full_path}")
    mod = importlib.util.module_from_spec(spec)
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
    from pathlib import Path

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
        else:
            scan_results = {"error": "summary file not found: %s" % _summary_file}
    except Exception as e:
        scan_results = {"error": str(e)}
        try:
            _alt = _report_dir / f"full_scan_summary_{_date_compact}.json"
            if _alt.exists():
                with open(str(_alt), "r", encoding="utf-8") as _sf:
                    scan_results = json.load(_sf)
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

    return {**state, "scan_results": scan_results, "scan_report_path": scan_report_path,
            "current_phase": "P1", "completed_phases": ["P1"]}


async def node_judge_direction(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    scan_summary = state.get("scan_results", {}).get("all_ranked", [])[:20]
    context = f"""你是数技源（信号扫描引擎），基于多策略扫描结果输出候选辩论品种。

说明：
- 每条信号已是按品种合并后的综合信号（sub_signals 列出所有参与的因子子策略）
- sub_signals 中每个子信号的 total 有方向（正=多头，负=空头），grade 为 STRONG/WATCH/WEAK/NOISE
- 多个子策略一致性越高（同向共振），该品种的信号越可靠
- ⚠️ 重要：以下方向仅为"扫描参考方向"，辩论环节会基于研究数据重新论证，
  闫判官会根据辩论质量做最终裁决。数技源不锁定辩论方向。

扫描结果 TOP20（按信号强度排序）：
{json.dumps(scan_summary, ensure_ascii=False, indent=2)[:8000]}

请以 JSON 格式返回：
1. scan_direction: 数技源扫描参考方向 (bullish/bearish/neutral) — **仅供参考，辩论环节可推翻**
2. confidence: 扫描置信度 (0-1)
3. symbols: 推荐辩论的品种列表（优先选 total 绝对值高或 sub_signals 一致性强的）
4. reason: 扫描判断理由（引用哪些子策略形成共识）
5. dispatch_sources: 需要哪些数据源（["chain","technical","fundamental"] 的子集）

返回 JSON 格式：
{{"scan_direction": "bearish", "confidence": 0.8, "symbols": ["SF", "SM"], "dispatch_sources": ["chain", "technical"], "reason": "SF/SM 空头信号强（supertrend+sar+macd+tsmom+dual_thrust 五策略共振）"}}
"""

    result = await judge.run(context, state["trace_id"])

    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            verdict = json.loads(output[start:end])
        else:
            verdict = {"scan_direction": "neutral", "symbols": [], "reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse judge output: {e}")
        verdict = {"scan_direction": "neutral", "symbols": [], "reason": output}

    selected_symbols = verdict.get("symbols", [])
    if not selected_symbols:
        selected_symbols = state.get("selected_symbols", [])

    # 兼容新旧字段名: scan_direction (新) 或 direction (旧)
    scan_dir = verdict.get("scan_direction", verdict.get("direction", "neutral"))
    scan_reason = verdict.get("reason", "")

    dispatch_sources = verdict.get("dispatch_sources", ["chain", "technical", "fundamental"])

    new_phases = state["completed_phases"] + ["P2"]
    return {
        **state,
        "judge_direction": {
            "direction": scan_dir,
            "confidence": verdict.get("confidence", 0.5),
            "symbols": selected_symbols,
            "reason": scan_reason,
        },
        "selected_symbols": selected_symbols,
        "dispatch_sources": dispatch_sources,
        "current_phase": "P2",
        "completed_phases": new_phases
    }


async def node_prepare_data(state: DebateState) -> DebateState:
    """P2.5: FDC 数据准备 — 预采集所有选中品种的结构化数据供子 Agent 使用"""
    import asyncio
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

    kline_days = int(os.environ.get("FDT_FDC_KLINE_DAYS", "120"))
    f10_enabled = os.environ.get("FDT_FDC_F10_ENABLED", "true").lower() == "true"
    position_ranking_enabled = os.environ.get("FDT_FDC_POSITION_RANKING_ENABLED", "true").lower() == "true"

    logger.info(f"[FDC] 开始为 {len(symbols)} 个品种准备数据: {symbols}")
    start_time = datetime.now()

    fdc_data: dict[str, dict] = {}
    errors: dict[str, str] = {}

    try:
        from futures_data_core import get_kline, compute_indicators
    except ImportError:
        logger.warning("[FDC] futures_data_core 导入失败，降级无FDC模式")
        return {
            **state,
            "fdc_data": {},
            "fdc_data_status": {"enabled": True, "collected": False, "errors": {"import": "futures_data_core not available"}},
            "current_phase": "P2.5",
            "completed_phases": state["completed_phases"] + ["P2.5"]
        }

    async def collect_symbol_data(symbol: str) -> tuple[str, dict, str | None]:
        symbol_data: dict = {}
        error: str | None = None
        data_grades: dict[str, str] = {}

        try:
            kline_payload = await get_kline(symbol, period="daily", days=kline_days)
            symbol_data["kline"] = {
                "bars": kline_payload.data.get("bars", []),
                "meta": {k: v for k, v in kline_payload.meta.items() if k != "sources"},
                "summary": kline_payload.summary,
            }
            data_grades["kline"] = kline_payload.meta.get("data_grade", "UNKNOWN")

            bars = kline_payload.data.get("bars", [])
            if bars and len(bars) >= 20:
                closes = [float(b.get("close", 0)) for b in bars]
                highs = [float(b.get("high", 0)) for b in bars]
                lows = [float(b.get("low", 0)) for b in bars]
                volumes = [float(b.get("volume", 0)) for b in bars]
                try:
                    ind_result = compute_indicators({
                        "close": closes,
                        "high": highs,
                        "low": lows,
                        "volume": volumes,
                    })
                    symbol_data["indicators"] = {
                        "values": {k: v.tolist() if hasattr(v, 'tolist') else v for k, v in ind_result.items()},
                        "available": list(ind_result.keys()),
                    }
                    data_grades["indicators"] = "PRIMARY"
                except Exception as e:
                    logger.warning(f"[FDC] {symbol} 技术指标失败: {e}")
                    data_grades["indicators"] = "UNAVAILABLE"
        except Exception as e:
            logger.warning(f"[FDC] {symbol} K线获取失败: {e}")
            error = f"kline_error: {e}"
            data_grades["kline"] = "UNAVAILABLE"

        if f10_enabled and not error:
            try:
                from futures_data_core import get_term_structure, get_spread, get_basis, get_warrant, get_fundamental

                for name, fn in [("term_structure", get_term_structure), ("spread", get_spread),
                                 ("basis", get_basis), ("warrant", get_warrant),
                                 ("fundamental", get_fundamental)]:
                    try:
                        payload = await fn(symbol)
                        symbol_data[name] = {
                            "data": payload.data,
                            "summary": payload.summary,
                        }
                        data_grades[name] = payload.meta.get("data_grade", "UNKNOWN")
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
                from futures_data_core import get_position_ranking
                pr_payload = await get_position_ranking(symbol)
                symbol_data["position_ranking"] = {
                    "data": pr_payload.data,
                    "summary": pr_payload.summary,
                }
                data_grades["position_ranking"] = pr_payload.meta.get("data_grade", "UNKNOWN")
            except Exception as e:
                logger.warning(f"[FDC] {symbol} 持仓排名失败: {e}")
                data_grades["position_ranking"] = "UNAVAILABLE"

        symbol_data["data_grades"] = data_grades
        return symbol, symbol_data, error

    tasks = [collect_symbol_data(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[FDC] 数据采集异常: {result}")
            continue
        symbol, data, error = result
        fdc_data[symbol] = data
        if error:
            errors[symbol] = error

    elapsed = (datetime.now() - start_time).total_seconds()
    success_count = len([s for s in symbols if s in fdc_data and fdc_data[s].get("kline", {}).get("bars")])
    logger.info(f"[FDC] 数据准备完成: {success_count}/{len(symbols)} 品种成功, 耗时 {elapsed:.1f}s")

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
        "current_phase": "P2.5",
        "completed_phases": state["completed_phases"] + ["P2.5"]
    }


async def node_chain(state: DebateState) -> dict:
    try:
        analyze_chain = _import_from_skill("commodity-chain-analysis", "scripts/chains", "analyze_chain")
        chain_data = analyze_chain(state["selected_symbols"]) if state["selected_symbols"] else {}
    except Exception as e:
        chain_data = {"error": str(e)}
    return {"chain_analysis": chain_data}


def _build_fdc_technical_context(symbols: list[str], fdc_data: dict) -> str:
    if not fdc_data:
        return "（FDC 数据暂不可用，基于扫描数据进行分析）"
    lines = []
    for symbol in symbols:
        sym_data = fdc_data.get(symbol) or fdc_data.get(symbol.upper()) or fdc_data.get(symbol.lower())
        if not sym_data:
            lines.append(f"\n【{symbol}】无 FDC 数据")
            continue
        lines.append(f"\n【{symbol}】FDC 技术数据")
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
            lines.append(f"  成交量: {latest.get('volume')}, 持仓量: {latest.get('oi') or latest.get('open_interest')}")
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
        else:
            lines.append("  K线数据: 不可用")
        indicators = sym_data.get("indicators", {})
        if indicators and indicators.get("available"):
            avail = indicators["available"]
            lines.append(f"  技术指标: {len(avail)}组可用")
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
            lines.append("  技术指标: 不可用")
        grades = sym_data.get("data_grades", {})
        if grades:
            lines.append(f"  数据质量: K线={grades.get('kline','?')}, 指标={grades.get('indicators','?')}")
    return "\n".join(lines)


def _build_fdc_fundamental_context(symbols: list[str], fdc_data: dict) -> str:
    if not fdc_data:
        return "（FDC 基本面数据暂不可用）"
    lines = []
    for symbol in symbols:
        sym_data = fdc_data.get(symbol) or fdc_data.get(symbol.upper()) or fdc_data.get(symbol.lower())
        if not sym_data:
            lines.append(f"\n【{symbol}】无 FDC 数据")
            continue
        lines.append(f"\n【{symbol}】FDC 基本面数据")
        for field_name, label in [("term_structure", "期限结构"), ("basis", "基差"),
                                   ("spread", "价差"), ("warrant", "仓单"),
                                   ("position_ranking", "持仓排名"), ("fundamental", "基本面")]:
            field = sym_data.get(field_name, {})
            if field and "error" not in field:
                lines.append(f"  {label}:")
                f_data = field.get("data", {})
                if isinstance(f_data, dict):
                    for key in list(f_data.keys())[:5]:
                        val = f_data[key]
                        lines.append(f"    {key}: {val}")
                if field.get("summary"):
                    lines.append(f"    摘要: {field['summary']}")
            else:
                lines.append(f"  {label}: 不可用")
        f10_summary = sym_data.get("f10_summary", {})
        if f10_summary:
            lines.append(f"  F10覆盖率: {f10_summary.get('coverage_pct',0)}%")
        grades = sym_data.get("data_grades", {})
        if grades:
            f10_grades = {k: v for k, v in grades.items() if k in
                          ["term_structure", "basis", "spread", "warrant", "position_ranking", "fundamental"]}
            if f10_grades:
                lines.append(f"  数据质量: {json.dumps(f10_grades, ensure_ascii=False)}")
    return "\n".join(lines)


async def node_technical(state: DebateState) -> dict:
    _ensure_llm_key()
    technical = FdtAgentExecutor("technical_researcher")
    selected = state.get("selected_symbols", [])
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    fdc_data = state.get("fdc_data", {})
    fdc_status = state.get("fdc_data_status", {})

    fdc_tech_context = _build_fdc_technical_context(selected, fdc_data)

    context = f"""作为技术面研究员（观澜），请分析以下品种的技术面状态：

市场方向判断: {direction}
待分析品种: {selected}

【FDC 结构化技术数据（P2.5 预采集）】
{fdc_tech_context}

请以 JSON 格式返回逐品种分析，格式如下：
{{"per_symbol": {{
    "RB": {{"trend": "趋势判断（方向+强度+阶段）", "key_levels": "支撑:xxx, 阻力:xxx", "volume_price": "量价配合情况", "divergence": "背离分析", "pattern": "技术形态", "score": 75}},
    "CU": {{"trend": "趋势判断", "key_levels": "支撑阻力位", "volume_price": "量价配合", "divergence": "背离", "pattern": "形态", "score": 60}}
  }},
  "summary": "总体技术面摘要"
}}

注意：请充分利用 FDC 提供的 K线和技术指标数据进行分析。score为0-100的综合技术评分。"""

    tech_result = await technical.run(context, state["trace_id"])
    tech_result["fdc_data_used"] = fdc_status.get("collected", False) if isinstance(fdc_status, dict) else False

    # Parse structured per-symbol data from LLM output
    output = tech_result.get("output", "")
    per_symbol_tech = {}
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            parsed = json.loads(output[start:end])
            raw_per_symbol = parsed.get("per_symbol", {})
            for sym in selected:
                sym_key = sym.upper()
                if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                    per_symbol_tech[sym] = raw_per_symbol[sym_key]
    except Exception:
        pass

    return {
        "technical_data": {
            "raw": tech_result,
            "per_symbol": per_symbol_tech,
        }
    }


async def node_fundamental(state: DebateState) -> dict:
    _ensure_llm_key()
    fundamental = FdtAgentExecutor("fundamental_researcher")
    selected = state.get("selected_symbols", [])
    direction = state.get("judge_direction", {}).get("direction") if isinstance(state.get("judge_direction"), dict) else None
    fdc_data = state.get("fdc_data", {})
    fdc_status = state.get("fdc_data_status", {})

    fdc_fund_context = _build_fdc_fundamental_context(selected, fdc_data)

    context = f"""作为基本面研究员（探源），请分析以下品种的基本面状态：

市场方向判断: {direction}
待分析品种: {selected}

【FDC 结构化基本面数据（P2.5 预采集 F10）】
{fdc_fund_context}

请以 JSON 格式返回逐品种基本面状态向量，格式如下：
{{"per_symbol": {{
    "RB": {{"supply_demand": "供需平衡分析", "inventory": "库存周期定位", "profit_margin": "利润与开工率", "basis_term": "基差与期限结构", "macro_external": "宏观与外盘联动", "leading_signals": ["领先信号1", "信号2"]}},
    "CU": {{"supply_demand": "...", "inventory": "...", "profit_margin": "...", "basis_term": "...", "macro_external": "...", "leading_signals": [...]}}
  }},
  "summary": "总体基本面摘要"
}}

注意：
- 请充分利用 FDC 提供的期限结构、基差、仓单、持仓排名等结构化数据
- 如需更多最新基本面数据，请使用 WebSearch/WebFetch 工具搜索
- 每个品种的 leading_signals 为数组，包含1-3个关键信号"""

    fund_result = await fundamental.run(context, state["trace_id"])
    fund_result["fdc_data_used"] = fdc_status.get("collected", False) if isinstance(fdc_status, dict) else False

    # Parse structured per-symbol data from LLM output
    output = fund_result.get("output", "")
    per_symbol_fund = {}
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            parsed = json.loads(output[start:end])
            raw_per_symbol = parsed.get("per_symbol", {})
            for sym in selected:
                sym_key = sym.upper()
                if sym_key in raw_per_symbol and isinstance(raw_per_symbol[sym_key], dict):
                    per_symbol_fund[sym] = raw_per_symbol[sym_key]
    except Exception:
        pass

    return {
        "fundamental_data": {
            "raw": fund_result,
            "per_symbol": per_symbol_fund,
        }
    }


async def node_merge_research(state: DebateState) -> DebateState:
    merged_data = {
        "chain_analysis": state.get("chain_analysis", {}),
        "technical_data": state.get("technical_data", {}),
        "fundamental_data": state.get("fundamental_data", {}),
        "dispatch_sources": state.get("dispatch_sources", []),
    }
    new_phases = state["completed_phases"] + ["P3"]

    # v8.8.0: 生成研究报告 (P3 阶段)
    research_report_path = None
    try:
        report_dir = _resolve_report_dir()
        research_report_path = _write_research_report(state["trace_id"], merged_data, report_dir)
        logger.info(f"[MERGE] 研究报告: {research_report_path}")
    except Exception as e:
        logger.warning(f"[MERGE] 研究报告生成失败: {e}")

    return {
        **state,
        "research_data": merged_data,
        "research_report_path": research_report_path,
        "current_phase": "P3",
        "completed_phases": new_phases
    }


def _build_debate_context(state: DebateState) -> str:
    """构建辩论上下文：扫描指标 + 研究员快照（技术面+基本面+产业链），带来源标记"""
    research = state.get("research_data", {})
    symbols = state.get("selected_symbols", [])
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
                f"[scan] ADX={ind['adx']:.1f} RSI={ind['rsi']:.1f} "
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

    return "\n".join(lines)
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
    """P4 步1: 多头立论 — 多头分析员独立寻找做多理由"""
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state)

    context = f"""你是多头分析员，代表多头利益，必须只从分析师资料中寻找做多理由。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考，你完全不受扫描方向限制）

研究数据（逐品种，带来源标记）:
{research_context}

这是辩论的**多头立论阶段（v1）**——你的职责：
1. 代表多头利益，基于研究员提供的资料寻找做多理由
2. 每条论据必须标注引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源] / [chain:链证源] / [scan:数技源]）
3. 按照 6 维度框架（趋势结构、量价关系、期限结构、产业链验证、基本面/市场情绪、风险点）组织论证
4. 每个品种至少构建3条支持多头的论据
5. 禁止使用 WebSearch/WebFetch 自行搜集数据

如果分析师资料中完全找不到做多理由，可以给出低置信度和"缺乏做多依据"的说明。

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["[technical:观澜] 论据1...", "[fundamental:探源] 论据2...", ...], "confidence": 0.7}},
    "CU": {{"arguments": ["[chain:链证源] 论据3...", "[scan:数技源] 论据4...", ...], "confidence": 0.6}}
  }},
  "overall_summary": "总体多头判断"
}}"""

    result = await bullish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P4_bullish_v1"]
    return {
        **state,
        "bullish_arguments": [{"round": 1, "role": "bullish", "phase": "v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bullish_v1",
        "completed_phases": new_phases,
    }
async def node_bearish_v1(state: DebateState) -> DebateState:
    """P4 步2: 空头立论 — 空头分析员独立寻找做空理由（不再是对多头质疑）"""
    _ensure_llm_key()
    bearish = FdtAgentExecutor("bearish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state)

    context = f"""你是空头分析员，代表空头利益，独立从分析师资料中寻找做空理由。

品种列表: {symbols}
数技源参考方向: {judge_dir}（仅供参考，你完全不受扫描方向限制）

研究数据（逐品种，带来源标记）:
{research_context}

这是辩论的**空头立论阶段（v1）**——你的职责：
1. 代表空头利益，独立从研究员提供的资料中寻找做空理由
2. 每条论据必须标注引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源] / [chain:链证源] / [scan:数技源]）
3. 按照 6 维度框架（趋势结构、量价关系、期限结构、产业链验证、基本面/市场情绪、风险点）组织论证
4. 每个品种至少构建3条支持空头的论据
5. 禁止引用多头论据，不做"反驳"——你与多头平级，独立产出
6. 禁止使用 WebSearch/WebFetch 自行搜集数据

如果分析师资料中完全找不到做空理由，可以给出低置信度和"缺乏做空依据"的说明。

请以 JSON 格式返回：
{{"per_symbol": {{
    "RB": {{"arguments": ["[technical:观澜] 论据1...", "[fundamental:探源] 论据2...", ...], "confidence": 0.7}},
    "CU": {{"arguments": ["[chain:链证源] 论据3...", "[scan:数技源] 论据4...", ...], "confidence": 0.6}}
  }},
  "overall_summary": "总体空头判断"
}}"""

    result = await bearish.run(context, state["trace_id"])
    per_symbol = _parse_per_symbol_debate(result, symbols)
    if per_symbol is None:
        output = result.get("output", "")
        per_symbol = {sym: {"arguments": [output[:200]] if output else [], "confidence": 0.5} for sym in symbols}

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P4_bearish_v1"]
    return {
        **state,
        "bearish_arguments": [{"round": 2, "role": "bearish", "phase": "v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bearish_v1",
        "completed_phases": new_phases,
    }

async def node_bearish_rebuttal(state: DebateState) -> DebateState:
    """P4 步3: 空头反驳多头立论 — 针对多头的做多论据进行反驳"""
    _ensure_llm_key()
    bearish = FdtAgentExecutor("bearish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state)

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
{bull_text}

这是辩论的**空头反驳阶段（bearish_rebuttal）**——
1. 对每个品种，逐条阅读多头的做多论据
2. 引用分析师资料中的数据做反证，拆解多头逻辑
3. 必须标注每条反驳引用的分析师资料来源（如 [technical:观澜] / [fundamental:探源]）
4. 每个品种至少反驳2条多头论据
5. 禁止使用 WebSearch/WebFetch 自行搜集数据

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
    new_phases = state["completed_phases"] + ["P4_bearish_rebuttal"]
    return {
        **state,
        "bearish_rebuttal_arguments": [{"round": 3, "role": "bearish", "phase": "rebuttal_v1", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bearish_rebuttal",
        "completed_phases": new_phases,
    }
async def node_bullish_rebuttal(state: DebateState) -> DebateState:
    """P4 步4: 多头反驳 — 针对空头的做空论据和空头反驳进行再反驳"""
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")

    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})
    research_context = _build_debate_context(state)

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
{bear_text}

【空头反驳（对我的多头立论的质疑）】
{bear_rebuttal_text}

这是辩论的**多头反驳阶段（bullish_rebuttal）**——
1. 针对空头立论中的做空论据，用研究员数据正面反驳
2. 针对空头反驳中的质疑，逐条回应
3. 每条反驳必须引用分析师资料中的数据并标注来源（如 [technical:观澜] / [fundamental:探源]）
4. 如果某条论据确实成立（证据不足），承认并降置信度
5. 禁止使用 WebSearch/WebFetch 自行搜集数据

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
    new_phases = state["completed_phases"] + ["P4_bullish_rebuttal"]
    return {
        **state,
        "bullish_rebuttal_arguments": [{"round": 4, "role": "bullish", "phase": "rebuttal", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bullish_rebuttal",
        "completed_phases": new_phases,
    }



async def node_bear_final(state: DebateState) -> DebateState:
    """P4 步5: 空头最终陈述 — 整合空头立论+反驳，给出最终信心度"""
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
{bear_text}

【我方反驳多头立论汇总】
{rebuttal_text}

这是辩论的**空头最终陈述阶段（bear_final）**——
1. 整合空头所有论据（每条论据保持来源标注格式），给出完整的空头立场汇总
2. 调整置信度并说明理由
3. 包含风险提示（做空可能面临的风险）
4. 禁止使用 WebSearch/WebFetch

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

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P4_bear_final"]
    return {
        **state,
        "bear_final_arguments": [{"round": 5, "role": "bearish", "phase": "final", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bear_final",
        "completed_phases": new_phases,
    }


async def node_bull_final(state: DebateState) -> DebateState:
    """P4 步6: 多头最终陈述 — 整合多头立论+反驳，给出最终信心度"""
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
{bull_text}

【我方反驳空头论据及反驳汇总】
{rebuttal_text}

这是辩论的**多头最终陈述阶段（bull_final）**——
1. 整合多头所有论据（每条论据保持来源标注格式），给出完整的做多立场汇总
2. 调整置信度并说明理由
3. 包含风险提示（做多可能面临的风险）
4. 禁止使用 WebSearch/WebFetch

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

    new_round = state.get("debate_round", 0) + 1
    new_phases = state["completed_phases"] + ["P4_bull_final"]
    return {
        **state,
        "bull_final_arguments": [{"round": 6, "role": "bullish", "phase": "final", "symbols": per_symbol}],
        "debate_round": new_round,
        "current_phase": "P4_bull_final",
        "completed_phases": new_phases,
    }
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

    debate_context_lines = []
    for sym in symbols:
        bull = bull_args_dict.get(sym, {})
        bear = bear_args_dict.get(sym, {})
        bull_text = bull.get("arguments", []) if isinstance(bull, dict) else []
        bear_text = bear.get("arguments", []) if isinstance(bear, dict) else []
        debate_context_lines.append(
            f"\n==={sym}===\n"
            f"多头论据: {bull_text}\n"
            f"空头论据: {bear_text}"
        )
    debate_context = "\n".join(debate_context_lines)

    context = f"""作为闫判官（裁决官），请基于以下全部辩论内容对每个品种给出最终裁决。

核心原则：
- **你的裁决完全基于辩论质量，可以且应当推翻数技源的扫描方向**
- 数技源扫描参考方向: {scan_dir} — 这仅作参考，你可以推翻
- 如果空头论据更扎实 裁决空头（即使数技源方向为多头）
- 如果多头论据更扎实 裁决多头（即使数技源方向为空头）
- 双方论证均不充分 裁决 neutral / 低仓位
- 输出完整交易参数

以下为多轮攻防的全部辩论论据（多头立论空头立论空头反驳多头反驳空头最终多头最终）:

{debate_context}

请以 JSON 格式返回逐品种裁决及交易参数，每个品种需标注"是否推翻数技源方向"：
{{"per_symbol": {{
    "RB": {{"direction": "bearish", "confidence": 0.8, "reason": "裁决理由（引用辩论中的关键论据）",
            "overturn_scan": true, "overturn_reason": "推翻数技源方向的理由",
            "entry_price": 3100, "stop_loss_price": 3050, "target_price": 3250,
            "position_pct": 5, "contract": "RB2410", "risk_reward_ratio": 3.0}},
    "CU": {{"direction": "bullish", "confidence": 0.7, "reason": "裁决理由（引用辩论中的关键论据）",
            "overturn_scan": false, "overturn_reason": "与数技源方向一致",
            "entry_price": 71000, "stop_loss_price": 70000, "target_price": 73000,
            "position_pct": 3, "contract": "CU2409", "risk_reward_ratio": 2.5}}
  }},
  "overall_direction": "bearish/neutral/bullish",
  "overall_reason": "总体摘要（总结哪方论证更优，是否推翻扫描方向）",
  "scan_overturned": true/false
}}"""

    result = await judge.run(context, state["trace_id"])

    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            parsed = json.loads(output[start:end])
            per_symbol = parsed.get("per_symbol", {})
            # Validate per-symbol verdicts
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
                    validated_symbols[sym] = sv

            overall = {
                "direction": parsed.get("overall_direction", "neutral"),
                "reason": parsed.get("overall_reason", output[:200]),
                "per_symbol": validated_symbols,
            }
            if validated_symbols:
                new_phases = state["completed_phases"] + ["P5_verdict"]
                return {
                    **state,
                    "verdict": overall,
                    "current_phase": "P5_verdict",
                    "completed_phases": new_phases
                }
    except Exception as e:
        logger.warning(f"Failed to parse verdict output: {e}")

    # Fallback: single verdict
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            verdict_raw = json.loads(output[start:end])
            verdict_raw.setdefault("entry_price", verdict_raw.get("price", 0))
            verdict_raw.setdefault("stop_loss_price", verdict_raw.get("stop_loss", 0))
            verdict_raw.setdefault("target_price", verdict_raw.get("target", 0))
            verdict_raw.setdefault("position_pct", verdict_raw.get("position_pct", 3))
            verdict_raw.setdefault("contract", verdict_raw.get("contract", ""))
            verdict_raw.setdefault("risk_reward_ratio", verdict_raw.get("risk_reward_ratio", 0))
            verdict_raw.setdefault("direction", verdict_raw.get("verdict", verdict_raw.get("direction", "neutral")))
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

    new_phases = state["completed_phases"] + ["P5_verdict"]
    return {
        **state,
        "verdict": verdict,
        "current_phase": "P5_verdict",
        "completed_phases": new_phases
    }


async def node_risk_check(state: DebateState) -> DebateState:
    _ensure_llm_key()
    risk_manager = FdtAgentExecutor("risk_manager")

    verdict = state.get("verdict", {})
    context = f"""作为风控经理，请直接基于以下裁决审核风险（v8.7.0 起不再依赖交易策略师方案）：

裁决: {verdict}

请以 JSON 格式返回风控审核结果，含风险等级判断：
{{"approved": true, "risk_level": "low/medium/high", "risk_color": "green/yellow/red",
  "max_position": 2, "warnings": ["警告1", "警告2"],
  "entry_price_check": true, "stop_loss_check": true, "position_pct_check": true}}
"""

    result = await risk_manager.run(context, state["trace_id"])

    output = result.get("output", "")
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            risk_check = json.loads(output[start:end])
        else:
            risk_check = {"approved": True, "risk_color": "yellow", "warnings": [output]}
    except Exception as e:
        logger.warning(f"Failed to parse risk check: {e}")
        risk_check = {"approved": True, "risk_color": "yellow", "warnings": [output]}

    risk_check.setdefault("risk_color", "green" if risk_check.get("approved", True) else "red")

    new_phases = state["completed_phases"] + ["P5_risk"]

    # v8.8.0: 生成裁决报告 (P5 阶段) — 闫判官裁决 + 风控明审核合并
    verdict_report_path = None
    try:
        report_dir = _resolve_report_dir()
        # Build scan_summary from all_ranked
        _scan_results_ = state.get('scan_results', {})
        _all_ranked_ = _scan_results_.get('all_ranked', [])
        _scan_summary_ = []
        for _item_ in _all_ranked_:
            _raw_dir_ = _item_.get('direction', '')
            _total_ = _item_.get('total', 0) or 0
            if abs(_total_) >= 20:
                _scan_summary_.append({'symbol': _item_.get('symbol', _item_.get('pid', '')),  'decision': 'BUY' if _raw_dir_ in ('bull', 'BUY', 'buy') else 'SELL' if _raw_dir_ in ('bear', 'SELL', 'sell') else 'HOLD', 'total': _total_, 'price': _item_.get('price', 0), 'atr': _item_.get('atr', 0)})
        verdict_report_path = _write_verdict_report(
            state["trace_id"], verdict, risk_check,
            state.get("selected_symbols", []), report_dir,
            scan_summary=_scan_summary_,
        )
    except Exception as e:
        logger.warning(f"[RISK] 裁决报告生成失败: {e}")

    return {
        **state,
        "risk_check": risk_check,
        "verdict_report_path": verdict_report_path,
        "current_phase": "P5_risk",
        "completed_phases": new_phases
    }


async def node_signal_output(state: DebateState) -> DebateState:
    """P6a: CTP 信号输出"""
    risk_check = state.get("risk_check", {})
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
                "score": abs(total),
            })
        elif raw_dir in ("bear", "SELL", "sell") and abs(total) >= 60:
            actionable_signals.append({
                "symbol": item.get("symbol", item.get("pid", "")),
                "direction": "SELL",
                "entry_price": item.get("price", 0),
                "score": abs(total),
            })
    actionable_signals.sort(key=lambda x: x["score"], reverse=True)
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
                "stop_loss_price": best_sell["entry_price"] * 1.03,
                "target_price": best_sell["entry_price"] * 0.95,
                "position_pct": 3,
                "contract": "",
                "risk_reward_ratio": 2.0,
                "confidence": min(1.0, best_sell["score"] / 100),
            }

    new_phases = state["completed_phases"] + ["P6a"]

    # v8.8.0: 生成 CTP 信号扫描报告 (P6a 阶段)
    signal_report_path = None
    try:
        report_dir = _resolve_report_dir()
        _signals_list_ = signal_output.get("signals", [])
        signal_report_path = _write_signal_report(state["trace_id"], signal_output, report_dir, signals_list=_signals_list_)
        logger.info(f"[SIGNAL] CTP 信号扫描报告: {signal_report_path}")
    except Exception as e:
        logger.warning(f"[SIGNAL] CTP 信号扫描报告生成失败: {e}")

    return {
        **state,
        "signal_output": signal_output,
        "signal_report_path": signal_report_path,
        "current_phase": "P6a",
        "completed_phases": new_phases
    }


async def node_report(state: DebateState) -> DebateState:
    import subprocess
    import sys
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
            "rsi": item.get("rsi", 50), "cci": item.get("cci", 0),
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
        rsi = float(judge_sym.get("rsi", 50)) or (float(item.get("rsi", 50)) if item else 50)
        score = float(judge_sym.get("score", 0)) or (abs(item.get("total", 0)) if item else 0)

        verdicts[sym_key] = {
            "direction": per_sym_dir,
            "confidence": judge_confidence if judge_sym else min(1.0, score / 100 + 0.1),
            "judge_verdict": {
                "final_direction": per_sym_dir,
                "confidence": judge_confidence if judge_sym else min(1.0, score / 100 + 0.1),
                "reasoning": judge_reason or verdict_reason,
            },
            "bull_args": "<br>".join(str(a) for a in bull_args_list) if bull_args_list else "",
            "bear_args": "<br>".join(str(a) for a in bear_args_list) if bear_args_list else "",
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

    cmd = [sys.executable, str(report_script),
           "--intermediate", str(intermediate_path),
           "--debate", str(debate_path),
           "--output", str(output_dir)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"⚠️ 报告生成警告: {result.stderr[:200]}")
        # v8.8.0: 优先匹配用户工作空间下的报告，再 fallback 到临时目录
        report_files = list(output_dir.glob("debate_report_*.html"))
        if not report_files:
            report_files = list(temp_dir.glob("*.html"))
        if report_files:
            report_path = str(report_files[0])
        else:
            # fallback: 写入工作空间下，确保报告路径有效
            fallback_html = _render_html(
                "📋 辩论报告（fallback）",
                f'<div class="section"><h2>⚠️ 报告生成降级</h2>'
                f'<p>trace_id={state["trace_id"]} · 主报告脚本未产出HTML，以下为辩论结果概要。</p>'
                f'<pre style="background:#252836;padding:12px;border-radius:6px;overflow:auto;font-size:0.78em;color:#ccc;">{json.dumps(debate_results, ensure_ascii=False, default=str)[:3000]}</pre>'
                f'</div>',
                [("trace_id", state["trace_id"]), ("status", "fallback")],
            )
            fallback_path = output_dir / f"debate_report_{state['trace_id']}.html"
            fallback_path.write_text(fallback_html, encoding="utf-8")
            report_path = str(fallback_path)
    except Exception as e:
        # v8.8.0: fallback 改为用户工作空间，而非 /tmp
        try:
            fallback_html = _render_html(
                "📋 辩论报告（异常）",
                f'<div class="section"><h2>❌ 报告生成异常</h2>'
                f'<p>trace_id={state["trace_id"]} · 错误: {e}</p></div>',
                [("trace_id", state["trace_id"]), ("status", "error")],
            )
            fallback_path = output_dir / f"debate_report_{state['trace_id']}.html"
            fallback_path.write_text(fallback_html, encoding="utf-8")
            report_path = str(fallback_path)
        except Exception:
            report_path = None
        logger.warning(f"[REPORT] 主报告脚本异常: {e}")

    new_phases = state["completed_phases"] + ["P6"]
    return {**state, "report_path": report_path, "current_phase": "P6", "completed_phases": new_phases}


def _build_data_sources(state: DebateState) -> list:
    """从 state 中提取并返回数据溯源列表"""
    sources = []
    research = state.get("research_data", {})
    if research.get("technical_data"):
        sources.append({"source": "technical", "agent": "观澜", "phase": "P3"})
    if research.get("fundamental_data"):
        sources.append({"source": "fundamental", "agent": "探源", "phase": "P3"})
    if research.get("chain_analysis"):
        sources.append({"source": "chain", "agent": "链证源", "phase": "P3"})
    if state.get("fdc_data_status", {}).get("collected"):
        sources.append({"source": "fdc", "agent": "FDC", "phase": "P2.5"})
    scan = state.get("scan_results", {})
    if scan.get("all_ranked"):
        sources.append({"source": "scan", "agent": "数技源", "phase": "P1"})
    return sources



# ==================== 直接辩论模式节点 (cache-based P1) ====================

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
    import subprocess, sys as _sys
    import json as _json
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

        from futures_data_core import get_kline as _fdc_get_kline
        import asyncio as _asyncio

        for sym in symbols:
            try:
                # 拉取实时 K 线数据
                payload = _asyncio.run(_fdc_get_kline(sym.lower(), period="daily", days=120))

                meta = payload.meta
                grade = meta.get("data_grade_label", "")
                bars_raw = payload.data.get("bars", []) if hasattr(payload, "data") else []

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
