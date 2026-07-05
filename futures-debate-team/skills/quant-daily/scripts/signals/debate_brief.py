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


def _load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
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
        l_entry = l1l4_map.get(sym, {"symbol": sym, "total": 0, "direction": "neutral",
                                       "grade": "NOISE", "name": sym})
        f_entry = factor_map.get(sym, {"symbol": sym, "total": 0, "direction": "neutral",
                                         "grade": "NOISE", "name": sym})
        symbols.append({
            "symbol": sym,
            "name": l_entry.get("name", sym),
            "l1l4": _extract_l1l4(l_entry),
            "factor_timing": _extract_factor(f_entry),
        })

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
    rows_json = json.dumps([{
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
    } for s in summary["symbols"]], ensure_ascii=False)

    meta = summary["_meta"]

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>双策略信号汇总 — quant-daily</title>
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
</body></html>'''
    return html


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="双策略信号汇总（quant-daily纯数据输出）")
    parser.add_argument("l1l4_path", help="L1-L4 策略 JSON 路径")
    parser.add_argument("factor_path", help="factor_timing 策略 JSON 路径")
    parser.add_argument("-o", "--output-dir", help="输出目录", default=".")
    parser.add_argument("-p", "--prefix", help="文件名前缀", default="signal_summary")
    args = parser.parse_args()

    summary = build_signal_summary(args.l1l4_path, args.factor_path)
    os.makedirs(args.output_dir, exist_ok=True)

    json_path = os.path.join(args.output_dir, f"{args.prefix}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON: {json_path}")

    html = build_html(summary)
    html_path = os.path.join(args.output_dir, f"{args.prefix}.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[OK] HTML: {html_path}")

    meta = summary["_meta"]
    print(f"\n信号汇总: {meta['total_symbols']}品种")
    print(f"  L1-L4: {meta['l1l4_bull']}多头 / {meta['l1l4_bear']}空头")
    print(f"  因子择时: {meta['factor_bull']}多头 / {meta['factor_bear']}空头")
