"""📅 日线期货辩论系统 — 盘后运行一次 · v2.2

全量监控所有品种（负向过滤无数据/无市场品种），品种池取 FDT 内部 config/symbols.py 的 ALL_SYMBOLS。
有信号→写debate_trigger.json→团队主管启动完整P3-P5辩论。无信号→简约告知。

用法:
  python daily_debate.py               # 扫描+信号触发+轻量报告
  python daily_debate.py --dry-run      # 查看品种列表
v2.0 (2026-07-09): 信号门机制——检测到方向性信号时写入Commodities/debate_trigger.json供团队主管读取
v2.1 (2026-07-11): 机制修正——全量监控+负向过滤，评分仅作优先级，不再按STRONG/WATCH硬性排除
v2.2 (2026-07-12): 内化——移除 Signal 仓库依赖，品种池从 FDT 内部 ALL_SYMBOLS 派生，输出目录自包含
"""

import sys, os, json, shutil
from datetime import datetime

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)

# FDT 内部输出目录（自包含，不依赖外部仓库）
_FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPTS_DIR))))
COMMODITIES_DIR = os.path.join(_FDT_ROOT, "data", "daily_debate")
os.makedirs(COMMODITIES_DIR, exist_ok=True)


def _load_daily_symbols():
    """全量监控品种池: 从 FDT 内部 ALL_SYMBOLS 派生。
    负向过滤只排除无数据/不可监控品种(由 scan_all 自然处理), 不按评分预筛。"""
    try:
        from config.symbols import ALL_SYMBOLS
        symbols = sorted(set(s[0].upper() for s in ALL_SYMBOLS if s and s[0]))
        print(f"  📋 全量监控品种池: FDT内部 ALL_SYMBOLS → {len(symbols)} 个")
        return symbols
    except Exception as e:
        print(f"  ⚠ 读取 ALL_SYMBOLS 失败 ({e}), 回退空列表")
        return []


DAILY_SYMBOLS = _load_daily_symbols()

OUTPUT_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "reports", "daily")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def run_daily_debate(dry_run: bool = False) -> dict:
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M")
    date_str = now.strftime("%Y-%m-%d %H:%M")

    result = {
        "has_signals": False, "signal_count": 0,
        "strong": [], "watch": [],
        "report_path": "", "timestamp": timestamp,
    }

    print(f"\n{'='*50}")
    print(f"  📅 日线辩论 — {date_str}")
    print(f"  扫描品种: {len(DAILY_SYMBOLS)}个 (全量监控)")
    print(f"{'='*50}")

    if dry_run:
        print("\n  [干运行] 品种列表:\n")
        from optimizer.knowledge_bridge import get_symbol_knowledge
        for sym in DAILY_SYMBOLS:
            k = get_symbol_knowledge(sym)
            cat = k.get("cycle_category", "?")
            dd = k.get("daily_test_accuracy", "?")
            print(f"  {sym:4s} | {cat} | 日线测试={dd}%")
        return result

    # ── 扫描 ──
    print("\n  [1] 扫描通道突破信号...")
    try:
        from scan_all import run_scan
        from config.settings import PRIMARY_PERIOD
        scan_result = run_scan(
            output_dir=OUTPUT_DIR,
            output_prefix=f"daily_{timestamp}",
            symbols=[(s, s) for s in DAILY_SYMBOLS],
            strategy_name="channel_breakout",
            period=PRIMARY_PERIOD,
        )
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        import traceback; traceback.print_exc()
        return result

    all_ranked = scan_result.get("all_ranked", []) if isinstance(scan_result, dict) else []
    # 负向过滤 + 全量监控：任意方向性信号(|total|≥DEBATE_ENTRY_MIN_ABS)即进入辩论候选池
    # 评分(grade)仅作优先级标签，不作为进入辩论的硬性门槛
    from config.settings import DEBATE_ENTRY_MIN_ABS, signal_passes_entry_gate
    # 去融合后：每(策略×子信号)独立门禁 = grade∈{STRONG,WATCH}（兼容旧 |total|≥阈值 兜底）
    candidates = [s for s in all_ranked if signal_passes_entry_gate(s, DEBATE_ENTRY_MIN_ABS)]
    strong = [s for s in candidates if s.get("grade") == "STRONG"]      # 高优先级
    watch = [s for s in candidates if s.get("grade") != "STRONG"]       # 其余按评分排序，下游再决交易适配性
    has_signals = len(candidates) > 0

    # ── 周期发现（v5.11.0，仅对候选品种，成本可控）──
    period_fitness_path = None
    if has_signals:
        try:
            from signals.period_fitness import build_period_fitness
            from scan_all import run_scan
            from config.settings import SYMBOL_CHAIN_MAP

            def _pf_scan(period, symbol):
                r = run_scan(
                    output_dir=OUTPUT_DIR,
                    output_prefix=f"pf_{period}_{timestamp}",
                    symbols=[(symbol, symbol)],
                    strategy_name="channel_breakout",
                    period=period,
                )
                for e in r.get("all_ranked", []):
                    if e["symbol"] == symbol:
                        return {"total": e.get("total", 0), "grade": e.get("grade", "NOISE"),
                                "direction": e.get("direction", "neutral")}
                return None

            pf_syms = [(s["symbol"], SYMBOL_CHAIN_MAP.get(s["symbol"], "未知")) for s in candidates]
            period_fitness_path = build_period_fitness(pf_syms, _pf_scan, OUTPUT_DIR, timestamp)
            print(f"  周期发现产出: {period_fitness_path}")
        except Exception as e:
            print(f"  ⚠ 周期发现跳过（不影响主辩论）: {e}")

    result["has_signals"] = has_signals
    result["signal_count"] = len(candidates)
    result["strong"] = strong
    result["watch"] = watch
    print(f"  辩论候选={len(candidates)} (STRONG={len(strong)} 其余={len(watch)})")

    # ── 信号门 ──
    if not has_signals:
        print("  ⏹ 无方向性信号 → 跳过辩论")
        report = _no_signal_report(date_str, len(DAILY_SYMBOLS))
    else:
        print(f"  🔥 有{len(strong)+len(watch)}个信号 → 进入完整辩论")
        # 🔴 写入触发文件，由团队主管的自动化读取并触发完整P3-P5辩论
        trigger_path = os.path.join(COMMODITIES_DIR, "debate_trigger.json")
        with open(trigger_path, "w", encoding="utf-8") as tf:
            json.dump({
                "triggered_at": date_str,
                "timestamp": timestamp,
                "signal_count": len(strong) + len(watch),
                "signals": [
                    {
                        "symbol": s["symbol"],
                        "name": s.get("name", s["symbol"]),
                        "direction": s.get("direction", "bear"),
                        "grade": s.get("grade", "WATCH"),
                        "total": s.get("total", 0),
                        "adx": s.get("ADX", s.get("adx", 0)),
                        "rsi": s.get("RSI14", s.get("rsi", 50)),
                        "price": s.get("price", 0),
                        "signal_type": s.get("signal_type", ""),
                    }
                    for s in (strong + watch)
                ],
                "period_fitness_path": period_fitness_path,
                "_note": "完整辩论由明鉴秋（团队主管）调度，不走daily_debate.py内建的轻量分析。此文件为触发信号。"
            }, tf, ensure_ascii=False, indent=2)
        print(f"  触发文件: {trigger_path}")
        print(f"  ⚠ 需团队主管读取触发文件后启动完整辩论流程(P3-P5)")
        # 仍然生成轻量报告作为速览
        report = _debate_report(result, date_str)

    # ── 输出 ──
    report_path = os.path.join(OUTPUT_DIR, f"daily_{timestamp}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    result["report_path"] = report_path

    commodities_link = os.path.join(COMMODITIES_DIR, "daily_debate_latest.html")
    shutil.copy2(report_path, commodities_link)

    print(f"\n  报告: {report_path}")
    print(f"  同步: {commodities_link}")
    return result


def _no_signal_report(date_str: str, count: int = None) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>无信号 — {date_str}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #f5f5f5; display:flex;
  justify-content:center; align-items:center; height:100vh; margin:0; }}
.card {{ background:#fff; border-radius:12px; padding:40px; text-align:center;
  box-shadow:0 2px 10px rgba(0,0,0,0.1); max-width:400px; }}
.icon {{ font-size:48px; margin-bottom:15px; }}
h1 {{ font-size:20px; color:#333; margin:0 0 8px 0; }}
p {{ color:#999; font-size:14px; margin:0 0 4px 0; }}
.time {{ color:#bbb; font-size:12px; margin-top:15px; }}
</style></head><body>
<div class="card">
  <div class="icon">🟢</div>
  <h1>无有效信号</h1>
  <p>{count}个日线品种均无方向性信号</p>
  <p style="color:#bbb;">不产生交易建议</p>
  <div class="time">{date_str}</div>
</div>
</body></html>"""


def _debate_report(result: dict, date_str: str) -> str:
    from optimizer.knowledge_bridge import get_symbol_knowledge, get_knowledge_summary
    from config.settings import SYMBOL_CHAIN_MAP

    all_signals = result.get("strong", []) + result.get("watch", [])
    strong_count = len(result.get("strong", []))
    watch_count = len(result.get("watch", []))
    signal_symbols = []

    signal_rows = []
    for s in all_signals:
        sym = s["symbol"]; signal_symbols.append(sym)
        k = get_symbol_knowledge(sym)
        cat = k.get("cycle_category", "")
        dd = k.get("daily_test_accuracy", "?")
        adx = s.get("ADX", s.get("adx", 0)); rsi = s.get("RSI14", s.get("rsi", 50))
        direction = s.get("direction", "?"); total = s.get("total", 0)
        grade = s.get("grade", "?")
        sig = s.get("signal_type", "-")
        overfit = " ⚠" if k.get("daily_overfit") else ""
        dir_icon = "🟢" if direction == "bull" else ("🔴" if direction == "bear" else "⚪")
        grade_icon = "🔥" if grade == "STRONG" else "👁"
        signal_rows.append(f"""<tr>
            <td><b>{sym}</b></td>
            <td>{cat}{overfit}</td>
            <td>{dd}%</td>
            <td>{grade_icon} {grade}</td>
            <td>{dir_icon} {direction}</td>
            <td>{total}</td>
            <td>{sig}</td>
            <td>{adx:.1f}</td>
            <td>{rsi:.0f}</td>
        </tr>""")

    # ── 多空评分明细表 ──
    score_rows = []
    for s in all_signals:
        sym = s["symbol"]
        dc20 = s.get("dc20", "-"); dc55 = s.get("dc55", "-")
        bb = s.get("bb", "-"); vol = s.get("vol_score", 0)
        adx = s.get("ADX", s.get("adx", 0)); rsi = s.get("RSI14", s.get("rsi", 50))
        sig = s.get("signal_type", "-")
        total = s.get("total", 0); direction = s.get("direction", "neutral")
        grade = s.get("grade", "?")
        signal_strength = ""
        if abs(total) >= 50: signal_strength = "🔥 强信号"
        elif abs(total) >= 40: signal_strength = "👁 可关注"
        elif abs(total) >= 30: signal_strength = "⚠ 弱信号"
        else: signal_strength = "⚪ 噪声级"

        dir_color = "#22c55e" if direction == "bull" else "#ef4444"
        bull_score = abs(total) if direction == "bull" else abs(total) * 0.3
        bear_score = abs(total) if direction == "bear" else abs(total) * 0.3
        score_rows.append(f"""<tr>
            <td><b>{sym}</b></td>
            <td style="color:{dir_color};font-weight:700">{direction}</td>
            <td>{grade}</td>
            <td><b>{total}</b></td>
            <td>{sig}</td>
            <td>{dc20}</td><td>{dc55}</td><td>{bb}</td><td>{vol:.1f}</td>
            <td>{adx:.1f}</td><td>{rsi:.0f}</td>
            <td style="font-size:11px">{signal_strength}</td>
        </tr>""")

    # ── 产业链分析摘要 ──
    chain_signals = {}
    for s in all_signals:
        sym = s["symbol"]
        chain = SYMBOL_CHAIN_MAP.get(sym.lower(), SYMBOL_CHAIN_MAP.get(sym, "其他"))
        if chain not in chain_signals:
            chain_signals[chain] = {"bull": 0, "bear": 0, "total": 0, "symbols": []}
        direction = s.get("direction", "neutral")
        if direction == "bull": chain_signals[chain]["bull"] += 1
        elif direction == "bear": chain_signals[chain]["bear"] += 1
        chain_signals[chain]["total"] += 1
        chain_signals[chain]["symbols"].append(sym)

    chain_rows = []
    for chain, cd in sorted(chain_signals.items()):
        chain_trend = "多头偏强" if cd["bull"] > cd["bear"] else ("空头偏强" if cd["bear"] > cd["bull"] else "多空均衡")
        trend_color = "#22c55e" if "多头" in chain_trend else "#ef4444"
        symbols_str = ", ".join(cd["symbols"])
        chain_rows.append(f"""<tr>
            <td><b>{chain}</b></td>
            <td>{cd["total"]}</td>
            <td style="color:#22c55e">{cd["bull"]}</td>
            <td style="color:#ef4444">{cd["bear"]}</td>
            <td style="color:{trend_color};font-weight:600">{chain_trend}</td>
            <td style="font-size:11px">{symbols_str}</td>
        </tr>""")

    debate_rows = []
    for s in all_signals:
        sym = s["symbol"]; direction = s.get("direction", "neutral")
        total = s.get("total", 0); adx = s.get("ADX", s.get("adx", 0)); rsi = s.get("RSI14", s.get("rsi", 50))
        sig = s.get("signal_type", "-"); dc20 = s.get("dc20", "-"); dc55 = s.get("dc55", "-")
        bb = s.get("bb", "-"); vol = s.get("vol_score", 0)
        k = get_symbol_knowledge(sym); cat = k.get("cycle_category", "")
        dd = k.get("daily_test_accuracy", 0) or 0

        if direction == "bull":
            bull_args = [f"信号方向:多头(总分{total})", f"信号类型:{sig}", f"DC20={dc20}", f"DC55={dc55}", f"布林带={bb}", f"ADX={adx:.1f}", f"日线回测{dd}%"]
            bear_args = [f"RSI={rsi:.0f}" + ("(偏高)" if rsi > 70 else "")]
            if vol < 0.5: bear_args.append(f"量比{vol:.1f}(缩量)")
            if k.get("daily_overfit"): bear_args.append("日线过拟合⚠")
            if not bear_args: bear_args.append("无明显反向信号")
            verdict = "偏向多头" if len(bull_args) >= len(bear_args) else "需谨慎"
        else:
            bear_args = [f"信号方向:空头(总分{abs(total)})", f"信号类型:{sig}", f"DC20={dc20}", f"DC55={dc55}", f"布林带={bb}", f"ADX={adx:.1f}", f"日线回测{dd}%"]
            bull_args = [f"RSI={rsi:.0f}" + ("(偏低)" if rsi < 30 else "")]
            if vol < 0.5: bull_args.append(f"量比{vol:.1f}(缩量)")
            if k.get("daily_overfit"): bull_args.append("日线过拟合⚠")
            if not bull_args: bull_args.append("无明显反向信号")
            verdict = "偏向空头" if len(bear_args) >= len(bull_args) else "需谨慎"

        debate_rows.append(f"""<tr>
            <td><b>{sym}</b></td>
            <td>{direction}</td>
            <td><ul style="margin:0;padding-left:16px;">{"".join(f'<li>{a}</li>' for a in (bull_args if direction=="bull" else bear_args))}</ul></td>
            <td><ul style="margin:0;padding-left:16px;">{"".join(f'<li>{a}</li>' for a in (bear_args if direction=="bull" else bull_args))}</ul></td>
            <td>{verdict}</td>
        </tr>""")

    kb_summary = get_knowledge_summary(signal_symbols)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>日线辩论报告 — {date_str}</title>
<style>
body {{ font-family:'Segoe UI',sans-serif; margin:0; padding:20px; background:#f5f5f5; }}
h1 {{ font-size:20px; margin:0; color:#fff; }}
h2 {{ font-size:15px; color:#333; margin:20px 0 10px 0; }}
.header {{ background:#1565C0; padding:15px 20px; border-radius:8px; margin-bottom:20px; }}
.header .sub {{ font-size:13px; opacity:0.8; margin-top:5px; color:#fff; }}
.summary {{ display:flex; gap:15px; margin-bottom:20px; }}
.card {{ background:#fff; border-radius:8px; padding:15px; flex:1; box-shadow:0 1px 3px rgba(0,0,0,0.1); }}
.card .num {{ font-size:28px; font-weight:bold; color:#1565C0; }}
.card .label {{ font-size:12px; color:#999; }}
.card.red .num {{ color:#F44336; }}
.card.green .num {{ color:#4CAF50; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); margin-bottom:20px; }}
th {{ background:#f8f9fa; padding:10px 12px; text-align:left; font-size:12px; color:#666; border-bottom:2px solid #eee; }}
td {{ padding:10px 12px; font-size:13px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
tr:hover td {{ background:#f8f9ff; }}
.kb {{ background:#e8f5e9; border:1px solid #c8e6c9; border-radius:8px; padding:12px 16px; font-size:13px; color:#2e7d32; margin-bottom:20px; white-space:pre-line; }}
.footer {{ font-size:11px; color:#999; margin-top:20px; }}
</style></head><body>

<div class="header">
  <h1>📅 日线辩论报告</h1>
  <div class="sub">{date_str} | 扫描{len(DAILY_SYMBOLS)}个品种 | STRONG={strong_count} WATCH={watch_count}</div>
</div>

<div class="summary">
  <div class="card red"><div class="num">{strong_count}</div><div class="label">STRONG🔥</div></div>
  <div class="card"><div class="num">{watch_count}</div><div class="label">WATCH👁</div></div>
  <div class="card green"><div class="num">{len(signal_symbols)}</div><div class="label">辩论品种</div></div>
</div>

<h2>📡 信号明细</h2>
<table>
<tr><th>品种</th><th>周期分类</th><th>日线测试</th><th>等级</th><th>方向</th><th>总分</th><th>信号类型</th><th>ADX</th><th>RSI</th></tr>
{chr(10).join(signal_rows)}
</table>

<h2>🔬 多空评分明细</h2>
<table>
<tr><th>品种</th><th>方向</th><th>等级</th><th>总分</th><th>信号类型</th><th>DC20</th><th>DC55</th><th>布林带</th><th>量比</th><th>ADX</th><th>RSI</th><th>信号强度</th></tr>
{chr(10).join(score_rows)}
</table>

<h2>🔗 产业链分析摘要</h2>
<table>
<tr><th>产业链</th><th>信号数</th><th>多头</th><th>空头</th><th>链倾向</th><th>涉及品种</th></tr>
{chr(10).join(chain_rows)}
</table>

<h2>⚖ 辩论论点（动态正反方）</h2>
<table>
<tr><th>品种</th><th>信号方向</th><th>正方论据</th><th>反方论据</th><th>倾向</th></tr>
{chr(10).join(debate_rows)}
</table>

<div class="kb">{kb_summary.replace(chr(10), '<br>')}</div>

<div class="footer">
  知识库:2026-07-07 WF回测优化 | Commodities/daily_debate_latest.html
</div>
</body></html>"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    r = run_daily_debate(dry_run=args.dry_run)
    if r["has_signals"]:
        print(f"\n【扫描结果】{r['signal_count']}个信号已写入触发文件 → Commodities/debate_trigger.json")
        print(f"【下一步】团队主管读取触发文件 → 启动完整P3-P5辩论流程")
        print(f"【速览】轻量报告 → {r['report_path']}")
    else:
        print("\n【扫描结果】无STRONG/WATCH信号，无交易建议")
