"""
双策略信号汇总（纯数据）— 仲裁者决策
=============================================

quant-daily 仅输出两份策略的原始信号数值，不做任何判断。
闫判官（仲裁者）自行决定：
  - 哪些品种值得辩论
  - 辩论的正方方向
  - 最终裁决方向

quant-daily 职责边界：
  - 输出 L1-L4 的40+技术指标数值
  - 输出 factor_timing 的5因子数值
  - 不分类、不推荐、不指定辩论标的
"""

import json, os, sys, logging

logger = logging.getLogger(__name__)


def _extract_risk_input(l_entry: dict, f_entry: dict) -> dict:
    """从L1-L4和factor_timing数据中提取风控明专用字段。

    这是观澜→风控明的结构化契约。风控明只认这个字段。
    """
    l_total = l_entry.get("total", 0)
    f_total = f_entry.get("total", 0)
    l_adx = l_entry.get("adx", 0)

    # 置信度：L1-L4的cons(一致性) + factor的vote_confidence 加权
    l_cons = l_entry.get("cons", 0)
    f_conf = f_entry.get("vote_confidence", 0.0)
    base_confidence = int((l_cons / 4 * 60 + abs(f_conf) * 40))

    # ATR: 优先从信号输出读取，无数据则按价格2%估算（远优于之前的信号总分×0.15）
    atr = l_entry.get("atr", 0)
    if not atr:
        atr = f_entry.get("atr", 0)
    if not atr:
        price = l_entry.get("price", 0)
        if price:
            atr = price * 0.02  # 通用期货日波幅约2%（覆盖LH之类高波品种略保守）
        else:
            atr = 200  # 连价格都没有的情况（罕见），用保守默认值

    # 信号方向
    l_dir = "bull" if l_total > 0 else ("bear" if l_total < 0 else "neutral")
    f_dir = "bull" if f_total > 0 else ("bear" if f_total < 0 else "neutral")
    conflict = (l_dir != f_dir) and (l_dir != "neutral" and f_dir != "neutral")

    return {
        "ATR": {"value": round(atr, 1), "period": 14},
        "confidence": max(0, min(100, base_confidence)),
        "adx": round(l_adx, 1),
        "direction_conflict": conflict,
        "l1l4_direction": l_dir,
        "factor_direction": f_dir,
        "pattern_risk": _detect_pattern_risk(l_entry, f_entry),
        "invalid_condition": _build_invalid_condition(l_entry),
    }


def _detect_pattern_risk(l_entry: dict, f_entry: dict) -> str:
    """检测潜在反转/风险模式。"""
    adx = l_entry.get("adx", 0)
    rsi = l_entry.get("rsi", 50)
    stage = l_entry.get("stage", "")
    cons = l_entry.get("cons", 0)

    risks = []
    if stage == "exhaustion":
        risks.append("衰竭阶段")
    if adx > 60 and cons < 3:
        risks.append("ADX极端但一致性低")
    if rsi > 75 or rsi < 25:
        risks.append(f"RSI极端({rsi})")
    if stage == "launch" and adx < 20:
        risks.append("启动但无趋势确认")
    return " | ".join(risks) if risks else "无"


def _build_invalid_condition(l_entry: dict) -> str:
    """根据技术指标生成关键位失效条件。"""
    adx = l_entry.get("adx", 0)
    total = l_entry.get("total", 0)
    direction = "多头" if total > 0 else "空头"
    if adx > 40:
        return f"日线{direction}方向ADX{adx}强趋势，若ADX跌破25则趋势转弱"
    return f"日线{direction}方向失效条件：收盘反向突破近期极值+OI配合"


def compute_debate_score(l1l4: dict, factor: dict, chain: str = "未知") -> dict:
    """
    五维加权辩论价值评分 (0-100)。

    评估一个品种的辩论价值——分歧越大、趋势越清晰、数据越极端，辩论价值越高。

    Dimensions:
        ├─ 信号强度 40%: |total_l|+|total_f| 归一化 (max anchor=200)
        ├─ 趋势质量 25%: ADX≥25加分 + stage非quiet加分 + cons一致性加分
        ├─ 极端性   20%: RSI极端 + z-score极端 + 方向分歧
        ├─ 数据质量 10%: veto计数罚分 (基值10)
        └─ 链重要性  5%: 基于链名 heuristic
    """
    if l1l4 is None:
        l1l4 = {}
    if factor is None:
        factor = {}

    # ── 1. 信号强度 (40%) ──
    l_total = abs(l1l4.get("total", 0))
    f_total = abs(factor.get("total", 0))
    raw_signal = l_total + f_total
    signal_score = min(40.0, raw_signal / 200.0 * 40.0)

    # ── 2. 趋势质量 (25%) ──
    quality_score = 0.0
    adx = l1l4.get("adx", 0) or factor.get("adx", 0)
    if adx >= 25:
        quality_score += 10.0
    if adx >= 40:
        quality_score += 3.0  # 强趋势额外加分

    stage = l1l4.get("stage", "unknown") or factor.get("stage", "unknown")
    if stage not in ("quiet", "unknown", ""):
        quality_score += 5.0

    cons = max(l1l4.get("cons", 0) or 0, factor.get("cons", 0) or 0)
    quality_score += min(7.0, cons / 4.0 * 7.0)

    quality_score = min(25.0, quality_score)

    # ── 3. 极端性 (20%) ──
    extreme_score = 0.0
    rsi = l1l4.get("rsi", 50) or 50
    if rsi > 75:
        extreme_score += 8.0
    elif rsi < 25:
        extreme_score += 8.0
    elif rsi > 70 or rsi < 30:
        extreme_score += 4.0

    z_score = l1l4.get("z_score", 0) or 0
    if abs(z_score) > 2.5:
        extreme_score += 7.0
    elif abs(z_score) > 2.0:
        extreme_score += 4.0
    elif abs(z_score) > 1.5:
        extreme_score += 2.0

    l_dir = l1l4.get("direction", "neutral")
    f_dir = factor.get("direction", "neutral")
    if l_dir != f_dir and l_dir != "neutral" and f_dir != "neutral":
        extreme_score += 5.0  # 方向分歧是好的辩论素材

    extreme_score = min(20.0, extreme_score)

    # ── 4. 数据质量 (10%) ──
    veto = max(l1l4.get("veto", 0) or 0, factor.get("veto", 0) or 0)
    data_score = max(0.0, 10.0 - veto * 3.0)

    # ── 5. 链重要性 (5%) ──
    key_chains = {"黑色链", "能化系", "有色金属", "贵金属"}
    chain_score = 5.0 if chain in key_chains else 3.0

    # ── 汇总 ──
    debate_value = round(signal_score + quality_score + extreme_score + data_score + chain_score, 1)
    debate_value = max(0.0, min(100.0, debate_value))

    # ── 标签生成 ──
    tags = []
    if l_dir != f_dir and l_dir != "neutral" and f_dir != "neutral":
        tags.append("方向分歧")
    if adx >= 40:
        tags.append("强趋势")
    elif adx >= 25:
        tags.append("趋势中")
    if rsi > 70:
        tags.append("RSI超买")
    elif rsi < 30:
        tags.append("RSI超卖")
    if abs(z_score) > 2.0:
        tags.append("极端值")
    if veto > 0:
        tags.append(f"veto×{veto}")
    if debate_value >= 80:
        tags.append("高辩论价值")
    elif debate_value >= 60:
        tags.append("中等辩论价值")

    return {
        "debate_value": debate_value,
        "breakdown": {
            "signal": round(signal_score, 1),
            "quality": round(quality_score, 1),
            "extreme": round(extreme_score, 1),
            "data": round(data_score, 1),
            "chain": round(chain_score, 1),
        },
        "tags": tags,
    }


def build_judge_brief(symbol_entry: dict, debate_score: dict, risk_input: dict = None) -> dict:
    """
    为闫判官生成速览摘要 + 关键指标速览。

    Args:
        symbol_entry: summary["symbols"] 中的单个品种条目
        debate_score: compute_debate_score() 的返回
        risk_input: _extract_risk_input() 的返回（可选）

    Returns:
        包含 quick_summary, conflict, strength, risk_flags 等字段
    """
    l = symbol_entry.get("l1l4", {})
    f = symbol_entry.get("factor_timing", {})

    l_total = l.get("total", 0)
    f_total = f.get("total", 0)
    l_adx = l.get("adx", 0)
    l_dir = l.get("direction", "neutral")
    f_dir = f.get("direction", "neutral")

    # 一句话摘要
    l_summary = f"L1-L4{l_dir}(总分{l_total:+d}"
    l_summary += f", ADX{l_adx})" if l_adx else ")"
    f_summary = f"因子{f_dir}(总分{f_total:+d})"
    quick_summary = f"{l_summary} vs {f_summary}"

    # 方向冲突检测
    conflict = (l_dir != f_dir) and (l_dir != "neutral" and f_dir != "neutral")

    # 信号强度分级
    def _strength_grade(total_val: int) -> str:
        if abs(total_val) >= 60:
            return "STRONG"
        elif abs(total_val) >= 30:
            return "MODERATE"
        elif abs(total_val) > 0:
            return "WEAK"
        return "NOISE"

    # 风险标签
    risk_flags_parts = []
    rsi = l.get("rsi", 50)
    if rsi > 75:
        risk_flags_parts.append(f"RSI超买({rsi})")
    elif rsi < 25:
        risk_flags_parts.append(f"RSI超卖({rsi})")
    adx = l.get("adx", 0)
    cons = l.get("cons", 0)
    if adx > 60 and cons < 3:
        risk_flags_parts.append("ADX极端但一致性低")
    stage = l.get("stage", "")
    if stage == "exhaustion":
        risk_flags_parts.append("衰竭阶段")
    z_score = l.get("z_score", 0)
    if abs(z_score) > 2.5:
        risk_flags_parts.append(f"Z分数极端({z_score:.1f})")

    risk_flags = " | ".join(risk_flags_parts) if risk_flags_parts else "正常"

    result = {
        "quick_summary": quick_summary,
        "conflict": conflict,
        "strength": {
            "l1l4": _strength_grade(l_total),
            "factor": _strength_grade(f_total),
        },
        "risk_flags": risk_flags,
    }

    if risk_input:
        result["direction_conflict"] = risk_input.get("direction_conflict", conflict)
        result["pattern_risk"] = risk_input.get("pattern_risk", "无")

    return result


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_l1l4(entry: dict) -> dict:
    """提取 L1-L4 原始信号数值"""
    return {
        "total": entry.get("total", 0),
        "direction": entry.get("direction", "neutral"),
        "grade": entry.get("grade", "NOISE"),
        "adx": entry.get("adx", 0),
        "rsi": entry.get("rsi", 50),
        "cci": entry.get("cci", 0),
        "ma_slope": entry.get("ma_slope", 0),
        "macd_cross": entry.get("macd_cross", "none"),
        "dc20_break": entry.get("dc20_break", "none"),
        "ma_align": entry.get("ma_align", "mixed"),
        "stage": entry.get("stage", "unknown"),
        "cons": entry.get("cons", 0),
        "veto": entry.get("veto", 0),
        "l1": entry.get("l1", 0),
        "l2": entry.get("l2", 0),
        "l3": entry.get("l3", 0),
        "l4": entry.get("l4", 0),
		"z_score": entry.get("z_score", 0),
		"volume": entry.get("volume", 0),
		"atr": entry.get("atr", 0),
	}


def _extract_factor(entry: dict) -> dict:
    """提取 factor_timing 原始信号数值"""
    return {
        "total": entry.get("total", 0),
        "direction": entry.get("direction", "neutral"),
        "grade": entry.get("grade", "NOISE"),
        "vote_net": entry.get("vote_net", 0),
        "vote_confidence": entry.get("vote_confidence", 0.0),
        "g_group": entry.get("g_group", "none"),
        "ts_type": entry.get("ts_type", "unknown"),
        "ts_slope": entry.get("ts_slope", 0.0),
        "resonance": entry.get("resonance", 0),
        "market_state": entry.get("market_state", "unknown"),
        "adx": entry.get("adx", 0),
        "stage": entry.get("stage", "unknown"),
        "cons": entry.get("cons", 0),
        "veto": entry.get("veto", 0),
        "l1": entry.get("l1", 0),
        "l2": entry.get("l2", 0),
        "l3": entry.get("l3", 0),
        "l4": entry.get("l4", 0),
    }


def build_signal_summary(l1l4_path: str, factor_path: str) -> dict:
    """
    构建双策略信号汇总表。

    纯数据输出——不包含任何分类、推荐或判断。
    闫判官根据此数据自行决定辩论策略。

    Returns:
        {
            "_meta": {"type": "signal_summary", "version": "1.0.0", ...},
            "symbols": [
                {
                    "symbol": "rb",
                    "name": "螺纹钢",
                    "l1l4": { ... },    # L1-L4 原始信号
                    "factor_timing": { ... }, # factor_timing 原始信号
                },
                ...
            ]
        }
    """
    l1l4_data = _load_json(l1l4_path)
    factor_data = _load_json(factor_path)

    l1l4_map = {e["symbol"]: e for e in l1l4_data.get("all_ranked", [])}
    factor_map = {e["symbol"]: e for e in factor_data.get("all_ranked", [])}
    all_symbols = sorted(set(list(l1l4_map.keys()) + list(factor_map.keys())))

    symbols = []
    for sym in all_symbols:
        l_entry = l1l4_map.get(sym, {"symbol": sym, "total": 0, "direction": "neutral", "grade": "NOISE", "name": sym})
        f_entry = factor_map.get(
            sym, {"symbol": sym, "total": 0, "direction": "neutral", "grade": "NOISE", "name": sym}
        )
        symbols.append(
            {
                "symbol": sym,
                "name": l_entry.get("name", sym),
                "l1l4": _extract_l1l4(l_entry),
                "factor_timing": _extract_factor(f_entry),
                "risk_input": _extract_risk_input(l_entry, f_entry),
            }
        )

    l1l4_meta = l1l4_data.get("_meta", {})
    factor_meta = factor_data.get("_meta", {})

    output = {
        "_meta": {
            "type": "signal_summary",
            "version": "1.0.0",
            "source": "quant-daily (纯数据输出, 不做判断)",
            "total_symbols": len(symbols),
            "l1l4_strategy": l1l4_meta.get("strategy", "layered_l1l4"),
            "factor_strategy": factor_meta.get("strategy", "factor_timing"),
            "l1l4_bull": l1l4_meta.get("bull", 0),
            "l1l4_bear": l1l4_meta.get("bear", 0),
            "factor_bull": factor_meta.get("bull", 0),
            "factor_bear": factor_meta.get("bear", 0),
        },
        "symbols": symbols,
    }
    return output


def build_html(summary: dict) -> str:
    """生成信号汇总表HTML（纯数据展示）"""
    rows_json = json.dumps(
        [
            {
                "sym": s["symbol"],
                "name": s["name"],
                "l_total": s["l1l4"]["total"],
                "l_dir": s["l1l4"]["direction"],
                "l_grade": s["l1l4"]["grade"],
                "l_adx": s["l1l4"]["adx"],
                "l_stage": s["l1l4"]["stage"],
                "l_cons": s["l1l4"]["cons"],
                "l_rsi": s["l1l4"]["rsi"],
                "f_total": s["factor_timing"]["total"],
                "f_dir": s["factor_timing"]["direction"],
                "f_grade": s["factor_timing"]["grade"],
                "f_ts": s["factor_timing"]["ts_type"],
                "f_vote": s["factor_timing"]["vote_net"],
                "f_confidence": s["factor_timing"]["vote_confidence"],
                "f_market": s["factor_timing"]["market_state"],
                "f_stage": s["factor_timing"]["stage"],
            }
            for s in summary["symbols"]
        ],
        ensure_ascii=False,
    )

    meta = summary["_meta"]

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>双策略信号汇总 — quant-daily</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #2a2d3a}}
.hd h1{{font-size:22px;color:#f59e0b}} .hd .m{{color:#9ca3af;font-size:12px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px}}
.st{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700}} .sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
.sc.b .n{{color:#ef4444}} .sc.bl .n{{color:#22c55e}} .sc.n .n{{color:#9ca3af}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:11px}}
thead{{background:#252940}}
th{{padding:6px 6px;text-align:left;font-weight:600;color:#9ca3af;font-size:10px;letter-spacing:.3px;white-space:nowrap;cursor:pointer;user-select:none}}
th:hover{{color:#f59e0b}}
td{{padding:5px 6px;border-top:1px solid #2a2d3a20;white-space:nowrap;font-size:11px}} tr:hover{{background:#f59e0b08!important}}
</style></head><body>
<div class="hd"><h1>双策略信号汇总 — quant-daily</h1>
<div class="m"><span>{meta["total_symbols"]}品种</span><span>L1-L4 {meta["l1l4_bull"]}多/{meta["l1l4_bear"]}空</span><span>因子 {meta["factor_bull"]}多/{meta["factor_bear"]}空</span><span>纯数据、不做判断</span></div></div>
<div class="st">
<div class="sc n"><div class="n">{meta["l1l4_bull"]}</div><div class="l">L1-L4 多头</div></div>
<div class="sc b"><div class="n">{meta["l1l4_bear"]}</div><div class="l">L1-L4 空头</div></div>
<div class="sc bl"><div class="n">{meta["factor_bull"]}</div><div class="l">因子 多头</div></div>
<div class="sc b"><div class="n">{meta["factor_bear"]}</div><div class="l">因子 空头</div></div>
</div>
<p style="color:#6b7280;font-size:11px;margin-bottom:10px">quant-daily 仅输出原始信号数值，仲裁者（闫判官）自行决定辩论品种与方向</p>
<table id="tbl"><thead><tr>
<th onclick="sortBy(0)">品种</th>
<th onclick="sortBy(1)">L总分</th><th onclick="sortBy(2)">L向</th><th onclick="sortBy(3)">L级</th><th onclick="sortBy(4)">ADX</th><th onclick="sortBy(5)">RSI</th><th onclick="sortBy(6)">阶段</th><th onclick="sortBy(7)">CONS</th>
<th onclick="sortBy(8)">F总分</th><th onclick="sortBy(9)">F向</th><th onclick="sortBy(10)">F级</th><th onclick="sortBy(11)">TS</th><th onclick="sortBy(12)">投票</th><th onclick="sortBy(13)">置信</th><th onclick="sortBy(14)">市场</th>
</tr></thead><tbody id="tb"></tbody></table>
<script>
var DATA={rows_json};
function _v(d,c){{var a=[d.sym,d.l_total,d.l_dir,d.l_grade,d.l_adx,d.l_rsi,d.l_stage,d.l_cons,d.f_total,d.f_dir,d.f_grade,d.f_ts,d.f_vote,d.f_confidence,d.f_market];return a[c];}}
var _sortCol=0,_sortAsc=true;
function render(){{var data=DATA.slice();if(_sortCol>=0){{var asc=_sortAsc;data.sort(function(a,b){{var va=_v(a,_sortCol),vb=_v(b,_sortCol);if(typeof va==='string')return asc?va.localeCompare(vb):vb.localeCompare(va);return asc?(va-vb):(vb-va);}});}}
var h='';for(var i=0;i<data.length;i++){{var d=data[i];
var lc=d.l_dir==='bull'?'#22c55e':(d.l_dir==='bear'?'#ef4444':'#6b7280');
var fc=d.f_dir==='bull'?'#22c55e':(d.f_dir==='bear'?'#ef4444':'#6b7280');
h+='<tr><td style="font-weight:700">'+d.sym+'</td>';
h+='<td style="color:'+lc+'">'+(d.l_total>0?'+':'')+d.l_total+'</td><td style="color:'+lc+'">'+d.l_dir+'</td><td>'+d.l_grade+'</td><td>'+d.l_adx+'</td><td>'+d.l_rsi+'</td><td style="color:#9ca3af;font-size:10px">'+d.l_stage+'</td><td>'+d.l_cons+'</td>';
h+='<td style="color:'+fc+'">'+(d.f_total>0?'+':'')+d.f_total+'</td><td style="color:'+fc+'">'+d.f_dir+'</td><td>'+d.f_grade+'</td><td style="color:#9ca3af;font-size:10px">'+d.f_ts+'</td><td>'+d.f_vote+'</td><td>'+d.f_confidence+'</td><td style="color:#9ca3af;font-size:10px">'+d.f_market+'</td></tr>';}}
document.getElementById('tb').innerHTML=h;}}
function sortBy(col){{if(_sortCol===col){{_sortAsc=!_sortAsc;}}else{{_sortCol=col;_sortAsc=col===0?true:false;}}render();}}
render();
</script>
</body></html>"""
    return html


def select_debate_symbols(
    summary: dict, chain_map: dict = None, min_count: int = 20, min_chains: int = 12, history_path: str = None
) -> dict:
    """
    从信号汇总中精选辩论品种。

    增强版：使用五维加权的 debate_value 替代原简单 divergence_score，
    并添加闫判官速览摘要和历史反馈。

    Args:
        summary: build_signal_summary() 的输出
        chain_map: {symbol_upper: chain_name} 映射。None时标记为"未知"
        min_count: 最少辩论品种数
        min_chains: 最少覆盖产业链数
        history_path: 历史反馈JSON路径（可选）

    Returns:
        {
            "_meta": {...},
            "divergence": [{"symbol":..., "debate_value":..., ...}, ...],
            "consensus_bear": [...],
            "consensus_bull": [...],
            "debate_candidates": [{"symbol":..., "chain":..., "proposition_side":"bear/bull",
                                    "debate_value":..., "breakdown":..., "tags":...,
                                    "quick_summary":..., "conflict":..., "strength":...,
                                    "risk_flags":..., "history":..., ...}, ...],
            "chain_coverage": {...},
            "z_extremes": [...],
        }
    """
    if chain_map is None:
        chain_map = {}

    symbols = summary.get("symbols", [])
    meta = summary.get("_meta", {})

    # 加载历史反馈（从 history_path 或默认位置）
    history_feedback = {}
    if history_path:
        try:
            with open(history_path, "r", encoding="utf-8") as _hf:
                history_feedback = json.load(_hf)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            try:
                from debate import history as dh

                history_feedback = dh.load_feedback()
            except ImportError:
                pass

    # 分类 + 多维评分
    divergence = []
    consensus_bear = []
    consensus_bull = []
    neutral = []

    for s in symbols:
        sym = s["symbol"]
        l = s["l1l4"]
        f = s["factor_timing"]
        l_dir, l_total = l.get("direction", "neutral"), l.get("total", 0)
        f_dir, f_total = f.get("direction", "neutral"), f.get("total", 0)
        chain = chain_map.get(sym.upper(), "未知")

        # 五维辩论价值评分
        debate_score = compute_debate_score(l, f, chain=chain)
        debate_value = debate_score["debate_value"]

        # 闫判官速览摘要
        l_dir_cn = "多头" if l_dir == "bull" else ("空头" if l_dir == "bear" else "中性")
        f_dir_cn = "多头" if f_dir == "bull" else ("空头" if f_dir == "bear" else "中性")
        l_adx_val = l.get("adx", 0)
        quick_summary = f"L1-L4{l_dir_cn}(总分{l_total:+d}, ADX{l_adx_val}) vs 因子{f_dir_cn}(总分{f_total:+d})"
        conflict = (l_dir != f_dir) and (l_dir != "neutral" and f_dir != "neutral")

        def _strength_grade(total_val: int) -> str:
            if abs(total_val) >= 60:
                return "STRONG"
            elif abs(total_val) >= 30:
                return "MODERATE"
            elif abs(total_val) > 0:
                return "WEAK"
            return "NOISE"

        risk_parts = []
        rsi = l.get("rsi", 50)
        if rsi > 75:
            risk_parts.append(f"RSI超买({rsi})")
        elif rsi < 25:
            risk_parts.append(f"RSI超卖({rsi})")
        adx = l.get("adx", 0)
        cons = l.get("cons", 0)
        if adx > 60 and cons < 3:
            risk_parts.append("ADX极端但一致性低")
        if l.get("stage", "") == "exhaustion":
            risk_parts.append("衰竭阶段")
        z_score = l.get("z_score", 0)
        if abs(z_score) > 2.5:
            risk_parts.append(f"Z分数极端({z_score:.1f})")
        risk_flags = " | ".join(risk_parts) if risk_parts else "正常"

        item = {
            "symbol": sym,
            "name": s.get("name", sym),
            "chain": chain,
            "l1l4_dir": l_dir,
            "l1l4_total": l_total,
            "factor_dir": f_dir,
            "factor_total": f_total,
            "price": l.get("price", 0),
            "adx": l.get("adx", 0),
            "grade": l.get("grade", "NOISE"),
            "debate_value": debate_value,
            "breakdown": debate_score["breakdown"],
            "tags": debate_score["tags"],
            "quick_summary": quick_summary,
            "conflict": conflict,
            "strength": {"l1l4": _strength_grade(l_total), "factor": _strength_grade(f_total)},
            "risk_flags": risk_flags,
        }

        # 极端分歧品种 → 标记左侧反转机会
        # 当品种位于极端位置（RSI超买/超卖或Z分数极端）且两套信号方向相反时，
        # 可能存在行情逆转的交易机会
        _extreme_rsi = (rsi > 75 or rsi < 25)
        _extreme_z = (abs(z_score) > 2.5)
        if conflict and (_extreme_rsi or _extreme_z):
            # 逆转方向：极端位置的对面
            reversal_dir = "bear" if (rsi > 75 or z_score > 2.5) else "bull"
            item["left_side_reversal"] = True
            item["reversal_direction"] = reversal_dir
            if "左侧反转机会" not in item["tags"]:
                item["tags"].append("左侧反转机会")

        if l_dir != f_dir and l_dir != "neutral" and f_dir != "neutral":
            divergence.append(item)
        elif l_dir == "bear" and f_dir == "bear":
            consensus_bear.append(item)
        elif l_dir == "bull" and f_dir == "bull":
            consensus_bull.append(item)
        else:
            neutral.append(item)

    # 按 debate_value 排序
    divergence.sort(key=lambda x: x["debate_value"], reverse=True)
    consensus_bear.sort(key=lambda x: x["debate_value"], reverse=True)
    consensus_bull.sort(key=lambda x: x["debate_value"], reverse=True)

    # ════════════════════════════════════════════════════
    # 双通道分离：交易推荐 vs 辩论选题
    # ════════════════════════════════════════════════════
    # 共识 + launch + 非极端 → 直接推荐，跳过辩论
    # 其余品种 → 进入辩论流程
    # ════════════════════════════════════════════════════
    _raw_l_data = {s["symbol"]: s["l1l4"] for s in symbols}

    def _is_direct_recommend(item) -> str:
        """检查是否为直接推荐品种。返回 ""(不推荐) / "STRONG_RECOMMEND" / "WATCH" """
        raw_l = _raw_l_data.get(item["symbol"], {})
        rsi_val = raw_l.get("rsi", 50)
        z_val = raw_l.get("z_score", 0)
        stage_val = raw_l.get("stage", "")
        consensus = (item["l1l4_dir"] == item["factor_dir"] and item["l1l4_dir"] != "neutral")
        if not consensus:
            return ""
        is_launch = (stage_val == "launch")
        non_extreme_rsi = (30 <= rsi_val <= 70)
        non_extreme_z = (abs(z_val) < 2.0)
        signal_ok = max(abs(item["l1l4_total"]), abs(item["factor_total"])) >= 30

        # STRONG_RECOMMEND：全部条件满足
        if is_launch and non_extreme_rsi and non_extreme_z and signal_ok:
            return "STRONG_RECOMMEND"
        # WATCH：共识 + (launch 或 非极端) 至少其一
        if is_launch and signal_ok:
            # launch 但微极端（RSI 25-75, |z|<2.5）
            slightly_non_extreme_rsi = (25 <= rsi_val <= 75)
            slightly_non_extreme_z = (abs(z_val) < 2.5)
            if slightly_non_extreme_rsi and slightly_non_extreme_z:
                return "WATCH"
        if non_extreme_rsi and non_extreme_z and signal_ok:
            # 非极端但非 launch（trending 阶段，趋势延续）
            if stage_val in ("trending", "launch"):
                return "WATCH"
        return ""

    trading_recommendations = []
    watch_list = []

    for src_list, label in [(consensus_bear, "bear"), (consensus_bull, "bull")]:
        filtered = []
        for item in src_list:
            rec_type = _is_direct_recommend(item)
            if rec_type == "STRONG_RECOMMEND":
                item["recommendation"] = "STRONG_RECOMMEND"
                item["reason"] = f"共识{label}+启动+非极端: 直接推荐"
                trading_recommendations.append(item)
            elif rec_type == "WATCH":
                item["recommendation"] = "WATCH"
                item["reason"] = f"共识{label}+观察级: 可直接关注"
                watch_list.append(item)
            else:
                filtered.append(item)  # 保留到辩论池
        src_list[:] = filtered  # 原地替换掉被取走的品种

    print(f"\n  [双通道] 直接推荐(免辩论): {len(trading_recommendations)}个 | 观察级: {len(watch_list)}个 | 辩论候选: {len(divergence) + len(consensus_bear) + len(consensus_bull)}个")

    # 精选辩论品种
    candidates = []
    covered_chains = set()

    # 第一轮：分歧品种（仅纳入至少一边信号强度 >= MODERATE 的品种）
    # 低于此阈值的分歧标记为弱分歧，不进入候选池——避免为辩论而辩论
    MIN_DIVERGENCE_SIGNAL = 30  # 对应 MODERATE 阈值
    skipped_weak_divergence = 0
    for item in divergence:
        strength_l1l4 = abs(item["l1l4_total"])
        strength_factor = abs(item["factor_total"])
        if max(strength_l1l4, strength_factor) < MIN_DIVERGENCE_SIGNAL:
            skipped_weak_divergence += 1
            continue
        item["proposition_side"] = (
            item.get("reversal_direction")   # 极端分歧 → 逆转方向为正方
            if item.get("left_side_reversal")
            else (
                "bear"
                if (abs(item["l1l4_total"]) >= abs(item["factor_total"]) and item["l1l4_dir"] == "bear")
                else item["l1l4_dir"]
            )
        )
        if item["proposition_side"] == "neutral":
            item["proposition_side"] = item["factor_dir"]
        item["reason"] = (
            f"左侧反转机会: 极端{item['l1l4_dir']}位置+分歧, 正方=逆转方向({item['proposition_side']})"
            if item.get("left_side_reversal")
            else (
                f"方向分歧: L1L4={item['l1l4_dir']}({item['l1l4_total']:+d}) vs 因子={item['factor_dir']}({item['factor_total']:+d})"
            )
        )
        # 添加历史调整值
        if history_feedback:
            try:
                from debate import history as dh

                item["history_adjustment"] = dh.get_symbol_value_score(item["symbol"], history_feedback)
            except ImportError:
                try:
                    from debate import history as dh

                    item["history_adjustment"] = dh.get_symbol_value_score(item["symbol"], history_feedback)
                except ImportError:
                    pass
        candidates.append(item)
        covered_chains.add(item["chain"])

    if skipped_weak_divergence > 0:
        print(f"  [辩论筛选] 跳过 {skipped_weak_divergence} 个弱信号分歧品种（两边信号强度 < {MIN_DIVERGENCE_SIGNAL}）")

    left_side_count = sum(1 for c in candidates if c.get("left_side_reversal"))
    if left_side_count > 0:
        print(f"  [左侧反转] 极端分歧品种 x{left_side_count}: {', '.join(c['symbol'] for c in candidates if c.get('left_side_reversal'))}")

    # 第二轮：补充新链的共识空头
    for item in consensus_bear:
        if item["chain"] not in covered_chains and len(candidates) < min_count + 5:
            item["proposition_side"] = "bear"
            item["reason"] = (
                f"双空共识: L1L4({item['l1l4_total']:+d}) + 因子({item['factor_total']:+d}) | 链:{item['chain']}"
            )
            if history_feedback:
                try:
                    from debate import history as dh

                    item["history_adjustment"] = dh.get_symbol_value_score(item["symbol"], history_feedback)
                except ImportError:
                    pass
            candidates.append(item)
            covered_chains.add(item["chain"])

    # 第三轮：如果链覆盖不足，从剩余品种补充
    all_known_chains = set(chain_map.values()) - {"未知", "其他"}
    for chain in sorted(all_known_chains):
        if chain not in covered_chains and len(candidates) < min_count + 5:
            for item in neutral + consensus_bull + consensus_bear:
                if item["chain"] == chain and item not in candidates:
                    item["proposition_side"] = item["l1l4_dir"] if item["l1l4_dir"] != "neutral" else "bear"
                    item["reason"] = f"链覆盖补充: {chain}"
                    candidates.append(item)
                    covered_chains.add(chain)
                    break

    # 第四轮：仍不足则补高分共识空头
    if len(candidates) < min_count:
        for item in consensus_bear:
            if item not in candidates and len(candidates) < min_count + 3:
                item["proposition_side"] = "bear"
                item["reason"] = f"补足数量: 双空共识强度(debate_value={item['debate_value']})"
                candidates.append(item)

    # Z分数极端
    z_extremes = [
        {"symbol": s["symbol"], "z_score": s["l1l4"].get("z_score", 0)}
        for s in symbols
        if abs(s["l1l4"].get("z_score", 0)) > 2
    ]
    z_extremes.sort(key=lambda x: abs(x["z_score"]), reverse=True)

    # 链覆盖统计
    chain_counts = {}
    for c in candidates:
        chain_counts[c["chain"]] = chain_counts.get(c["chain"], 0) + 1

    return {
        "_meta": {
            "mode": "debate_selection",
            "total_candidates": len(candidates),
            "chains_covered": len(covered_chains),
            "divergence_count": len(divergence),
            "consensus_bear_count": len(consensus_bear),
            "consensus_bull_count": len(consensus_bull),
            "trading_recommendations": len(trading_recommendations),
            "watch_list": len(watch_list),
            "enhanced": True,
            "debate_scoring": "五维加权评分 v1",
        },
        "divergence": divergence,
        "consensus_bear": consensus_bear,
        "consensus_bull": consensus_bull,
        "debate_candidates": candidates,
        "trading_recommendations": trading_recommendations,
        "watch_list": watch_list,
        "chain_coverage": chain_counts,
        "z_extremes": z_extremes,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="双策略信号汇总（quant-daily纯数据输出）")
    parser.add_argument("l1l4_path", help="L1-L4 策略 JSON 路径")
    parser.add_argument("factor_path", help="factor_timing 策略 JSON 路径")
    parser.add_argument("-o", "--output-dir", help="输出目录", default=".")
    parser.add_argument("-p", "--prefix", help="文件名前缀", default="signal_summary")
    parser.add_argument("--select-debate", help="链映射JSON路径，启用辩论品种精选", default=None)
    parser.add_argument("--min-count", type=int, help="最少辩论品种数", default=20)
    parser.add_argument("--min-chains", type=int, help="最少覆盖产业链数", default=12)
    parser.add_argument("--history-path", help="历史反馈JSON路径（可选）", default=None)
    args = parser.parse_args()

    summary = build_signal_summary(args.l1l4_path, args.factor_path)
    os.makedirs(args.output_dir, exist_ok=True)

    json_path = os.path.join(args.output_dir, f"{args.prefix}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON: {json_path}")

    html = build_html(summary)
    html_path = os.path.join(args.output_dir, f"{args.prefix}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] HTML: {html_path}")

    meta = summary["_meta"]
    print(f"\n信号汇总: {meta['total_symbols']}品种")
    print(f"  L1-L4: {meta['l1l4_bull']}多头 / {meta['l1l4_bear']}空头")
    print(f"  因子择时: {meta['factor_bull']}多头 / {meta['factor_bear']}空头")

    if args.select_debate:
        with open(args.select_debate, "r", encoding="utf-8") as f:
            chain_data = json.load(f)
        chain_results = chain_data.get("chain_results", chain_data)
        chain_map = {}
        for sym, info in chain_results.items():
            if isinstance(info, dict):
                chain_map[sym.upper()] = info.get("chain", "未知")
        selection = select_debate_symbols(
            summary,
            chain_map=chain_map,
            min_count=args.min_count,
            min_chains=args.min_chains,
            history_path=args.history_path,
        )
        sel_path = os.path.join(args.output_dir, f"{args.prefix}_candidates.json")
        with open(sel_path, "w", encoding="utf-8") as f:
            json.dump(selection, f, ensure_ascii=False, indent=2)
        sm = selection["_meta"]
        print(f"\n辩论品种精选:")
        print(f"  候选: {sm['total_candidates']}个, 覆盖{sm['chains_covered']}条产业链")
        print(f"  分歧: {sm['divergence_count']}个, 共识空头: {sm['consensus_bear_count']}个")
        print(f"  → {sel_path}")
