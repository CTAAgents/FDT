"""📅 日线期货辩论系统 — 盘后运行一次

只分析适合日线和双周期的品种（共28个），与小时级辩论互补。
有信号→辩论报告，无信号→简约告知。

用法:
  python daily_debate.py               # 扫描+辩论+报告
  python daily_debate.py --dry-run      # 查看品种列表
"""

import sys, os, json, shutil
from datetime import datetime

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)

DAILY_SYMBOLS = [
    # 黑色系
    "RB", "HC",
    # 能源链
    "SC", "LU", "FU", "BU", "PG", "PX",
    # 聚酯链
    "TA", "PF", "PR", "EB",
    # 塑化链
    "V", "PP", "L", "MA",
    # 化工
    "SA", "UR",
    # 贵金属
    "AU", "AG",
    # 农产品
    "C", "JD", "LH",
    # 果蔬
    "AP",
    # 建材化工
    "NR", "BR", "SP",
    # 新能源
    "PS",
    # ── 勉强可用（准确率50-55%） ──
    "EC", "SH", "CS", "CU", "P", "I", "RR", "OI", "AO", "RU", "PK", "A", "J", "SI",
]

OUTPUT_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "reports", "daily")
os.makedirs(OUTPUT_DIR, exist_ok=True)

COMMODITIES_DIR = r"C:\Users\yangd\Documents\Signal\Commodities"
os.makedirs(COMMODITIES_DIR, exist_ok=True)


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
    print(f"  扫描品种: {len(DAILY_SYMBOLS)}个 (日线适宜+勉强可用)")
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
        scan_result = run_scan(
            output_dir=OUTPUT_DIR,
            output_prefix=f"daily_{timestamp}",
            symbols=[(s, s) for s in DAILY_SYMBOLS],
            strategy_name="channel_breakout",
            period="daily",
        )
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        import traceback; traceback.print_exc()
        return result

    all_ranked = scan_result.get("all_ranked", []) if isinstance(scan_result, dict) else []
    strong = [s for s in all_ranked if s.get("grade") == "STRONG"]
    watch = [s for s in all_ranked if s.get("grade") == "WATCH"]
    has_signals = len(strong) + len(watch) > 0

    result["has_signals"] = has_signals
    result["signal_count"] = len(strong) + len(watch)
    result["strong"] = strong
    result["watch"] = watch
    print(f"  STRONG={len(strong)}  WATCH={len(watch)}")

    # ── 信号门 ──
    if not has_signals:
        print("  ⏹ 无STRONG/WATCH信号 → 跳过辩论")
        report = _no_signal_report(date_str)
    else:
        print(f"  🔥 有{len(strong)+len(watch)}个信号 → 进入辩论")
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


def _no_signal_report(date_str: str) -> str:
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
  <p>42个日线品种均无STRONG/WATCH信号</p>
  <p style="color:#bbb;">不产生交易建议</p>
  <div class="time">{date_str}</div>
</div>
</body></html>"""


def _debate_report(result: dict, date_str: str) -> str:
    from optimizer.knowledge_bridge import get_symbol_knowledge, get_knowledge_summary

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
        adx = s.get("ADX", 0); rsi = s.get("RSI14", 50)
        direction = s.get("direction", "?"); total = s.get("total", 0)
        grade = s.get("grade", "?")
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
            <td>{adx:.1f}</td>
            <td>{rsi:.0f}</td>
        </tr>""")

    debate_rows = []
    for s in all_signals:
        sym = s["symbol"]; direction = s.get("direction", "neutral")
        total = s.get("total", 0); adx = s.get("ADX", 0); rsi = s.get("RSI14", 50)
        k = get_symbol_knowledge(sym); cat = k.get("cycle_category", "")
        dd = k.get("daily_test_accuracy", 0) or 0

        if direction == "bull":
            bull_args = [f"信号方向:多头(总分{total})", f"ADX={adx:.1f}", f"日线回测准确率{dd}%"]
            bear_args = [f"RSI={rsi:.0f}" + ("(偏高)" if rsi > 70 else "")]
            if k.get("daily_overfit"): bear_args.append("日线过拟合⚠")
            bull_args = [a for a in bull_args if a]; bear_args = [a for a in bear_args if a]
            if not bear_args: bear_args.append("无明显反向信号")
            verdict = "偏向多头" if len(bull_args) >= len(bear_args) else "需谨慎"
        else:
            bear_args = [f"信号方向:空头(总分{abs(total)})", f"日线回测准确率{dd}%", f"ADX={adx:.1f}"]
            bull_args = [f"RSI={rsi:.0f}" + ("(偏低)" if rsi < 30 else "")]
            if k.get("daily_overfit"): bull_args.append("日线过拟合⚠")
            bull_args = [a for a in bull_args if a]; bear_args = [a for a in bear_args if a]
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
<tr><th>品种</th><th>周期分类</th><th>日线测试</th><th>等级</th><th>方向</th><th>总分</th><th>ADX</th><th>RSI</th></tr>
{chr(10).join(signal_rows)}
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
        print(f"\n【辩论结果】{r['signal_count']}个信号已辩论 → {r['report_path']}")
    else:
        print("\n【辩论结果】无STRONG/WATCH信号，无交易建议")
