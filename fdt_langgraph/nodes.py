import sys
import importlib.util
import os
import logging
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .state import DebateState, FdcDataStatus
from .agents import FdtAgentExecutor
from typing import List, Dict, Optional

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
                          selected_symbols: list, output_dir: Path) -> str:
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


def _write_signal_report(trace_id: str, signal_output: dict, output_dir: Path) -> str:
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
    import json
    from pathlib import Path

    existing_results = state.get("scan_results", {})
    if existing_results and existing_results.get("all_ranked"):
        print("[SCAN] 已有扫描结果，跳过重新扫描")
        scan_report_path = state.get("scan_report_path")
        if not scan_report_path:
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

    # v8.8.0: 生成信号扫描报告 (P1 阶段)
    scan_report_path = None
    try:
        report_dir = _resolve_report_dir()
        scan_report_path = _write_scan_report(state["trace_id"], scan_results, report_dir)
        logger.info(f"[SCAN] 扫描报告: {scan_report_path}")
    except Exception as e:
        logger.warning(f"[SCAN] 扫描报告生成失败: {e}")

    return {**state, "scan_results": scan_results, "scan_report_path": scan_report_path,
            "current_phase": "P1", "completed_phases": ["P1"]}


async def node_judge_direction(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

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

    output = result.get("output", "")
    import json
    try:
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            verdict = json.loads(output[start:end])
        else:
            verdict = {"direction": "neutral", "symbols": [], "reason": output}
    except Exception as e:
        logger.warning(f"Failed to parse judge output: {e}")
        verdict = {"direction": "neutral", "symbols": [], "reason": output}

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
    import json
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
    import json
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


async def node_debate(state: DebateState) -> DebateState:
    _ensure_llm_key()
    bullish = FdtAgentExecutor("bullish_analyst")
    bearish = FdtAgentExecutor("bearish_analyst")

    research = state.get("research_data", {})
    symbols = state.get("selected_symbols", [])
    judge_dir = state.get("judge_direction", {})

    # Build per-symbol context from research data
    research_context_lines = []
    for sym in symbols:
        lines = [f"\n==={sym}==="]
        tech = research.get('technical_data', {})
        fund = research.get('fundamental_data', {})
        # Extract agent output text for this symbol
        if isinstance(tech, dict) and tech.get("output"):
            lines.append(f"技术面: {tech['output'][:300]}")
        if isinstance(fund, dict) and fund.get("output"):
            lines.append(f"基本面: {fund['output'][:300]}")
        research_context_lines.append("\n".join(lines))
    research_context = "\n".join(research_context_lines)

    context = f"""作为辩论分析师，请对每个品种分别给出论据（多头或空头，取决于你的角色）。

品种列表: {symbols}
市场整体判断: {judge_dir}

研究数据（逐品种）:
{research_context}

请以 JSON 格式返回逐品种论据，格式如下：
{{"per_symbol": {{
    "RB": {{"arguments": ["论据1", "论据2", ...], "confidence": 0.7}},
    "CU": {{"arguments": ["论据3", "论据4", ...], "confidence": 0.6}}
  }},
  "overall_summary": "总体判断"
}}
对每个品种给出2-4条针对性论据，confidence为0-1之间的置信度。
"""

    bull_result = await bullish.run(context, state["trace_id"])
    bear_result = await bearish.run(context, state["trace_id"])

    import json
    def parse_per_symbol(result):
        """从LLM输出解析逐品种论据"""
        output = result.get("output", "")
        try:
            if "{" in output and "}" in output:
                start = output.find("{")
                end = output.rfind("}") + 1
                parsed = json.loads(output[start:end])
                per_symbol = parsed.get("per_symbol", {})
                # Validate: return only known symbols
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
        # Fallback: return generic arguments
        return None

    bull_per_symbol = parse_per_symbol(bull_result)
    bear_per_symbol = parse_per_symbol(bear_result)

    # If per-symbol parsing failed, fallback to generic arguments
    if bull_per_symbol is None:
        def parse_generic(result):
            output = result.get("output", "")
            try:
                if "{" in output and "}" in output:
                    start = output.find("{")
                    end = output.rfind("}") + 1
                    return json.loads(output[start:end]).get("arguments", [])
            except:
                pass
            return [output[:200]] if output else []
        bull_per_symbol = {sym: {"arguments": parse_generic(bull_result), "confidence": 0.5} for sym in symbols}
    if bear_per_symbol is None:
        def parse_generic(result):
            output = result.get("output", "")
            try:
                if "{" in output and "}" in output:
                    start = output.find("{")
                    end = output.rfind("}") + 1
                    return json.loads(output[start:end]).get("arguments", [])
            except:
                pass
            return [output[:200]] if output else []
        bear_per_symbol = {sym: {"arguments": parse_generic(bear_result), "confidence": 0.5} for sym in symbols}

    new_phases = state["completed_phases"] + ["P4"]
    return {
        **state,
        "bullish_arguments": bull_per_symbol,
        "bearish_arguments": bear_per_symbol,
        "current_phase": "P4",
        "completed_phases": new_phases
    }


async def node_verdict(state: DebateState) -> DebateState:
    _ensure_llm_key()
    judge = FdtAgentExecutor("judge")

    # Build per-symbol debate context
    bull_args_dict = state.get("bullish_arguments", {})
    bear_args_dict = state.get("bearish_arguments", {})
    symbols = state.get("selected_symbols", [])

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

    context = f"""作为裁决官，请基于以下辩论内容对每个品种给出最终裁决并输出完整交易参数。

逐品种辩论论据:
{debate_context}

请以 JSON 格式返回逐品种裁决及交易参数：
{{"per_symbol": {{
    "RB": {{"direction": "bearish", "confidence": 0.8, "reason": "裁决理由",
            "entry_price": 3100, "stop_loss_price": 3050, "target_price": 3250,
            "position_pct": 5, "contract": "RB2410", "risk_reward_ratio": 3.0}},
    "CU": {{"direction": "bullish", "confidence": 0.7, "reason": "裁决理由",
            "entry_price": 71000, "stop_loss_price": 70000, "target_price": 73000,
            "position_pct": 3, "contract": "CU2409", "risk_reward_ratio": 2.5}}
  }},
  "overall_direction": "bearish/neutral/bullish",
  "overall_reason": "总体摘要"
}}
每个品种请确保:
- direction: bullish/bearish/neutral
- entry_price, stop_loss_price, target_price 为数值
- position_pct 为0-100的数值
- risk_reward_ratio 为数值
"""

    result = await judge.run(context, state["trace_id"])

    import json
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

    import json
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
        verdict_report_path = _write_verdict_report(
            state["trace_id"], verdict, risk_check,
            state.get("selected_symbols", []), report_dir,
        )
        logger.info(f"[RISK] 裁决报告: {verdict_report_path}")
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
        signal_report_path = _write_signal_report(state["trace_id"], signal_output, report_dir)
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

    # Get per-symbol arguments from debate (v8.8.0+ per-symbol output)
    bull_args_dict = state.get("bullish_arguments", {})
    bear_args_dict = state.get("bearish_arguments", {})

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
    report_syms = set()
    if symbols_summary:
        for item in all_actionable:
            report_syms.add(item["pid"])
        for sym in state.get("selected_symbols", []):
            report_syms.add(sym.lower())
        for item in symbols_summary:
            g = item.get("grade", item.get("level", ""))
            t = abs(item.get("total", 0))
            if g in ("STRONG", "WATCH") or t >= 20:
                report_syms.add(item["pid"])
        if len(report_syms) < 5:
            for item in sorted(symbols_summary, key=lambda x: abs(x.get("total", 0)), reverse=True)[:30]:
                report_syms.add(item["pid"])
    else:
        for sym in state.get("selected_symbols", []):
            report_syms.add(sym.lower())
        if not report_syms:
            report_syms.update(["rb", "hc", "i", "au", "ag", "cu", "al", "sc", "SA"])

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
            bull_args_list = state.get("bullish_arguments", [])
            if isinstance(bull_args_list, dict):
                bull_args_list = []

        if isinstance(bear_sym, dict) and bear_sym.get("arguments"):
            bear_args_list = bear_sym["arguments"]
        else:
            bear_args_list = state.get("bearish_arguments", [])
            if isinstance(bear_args_list, dict):
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
            # Compute position from score
            abs_sc = abs(item.get("total", 0) or 0)
            if abs_sc >= 75:
                pos_pct = 5.0
            elif abs_sc >= 60:
                pos_pct = 3.0
            elif abs_sc >= 40:
                pos_pct = 1.5
            elif abs_sc >= 20:
                pos_pct = 0.5
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
