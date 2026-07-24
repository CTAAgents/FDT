"""⏰ 小时级期货辩论系统 — 只分析适合60分钟/双周期的品种

无信号 → 简短告知
有信号 → 进入辩论流程（信号分析+知识库参考+交易方案）

用法:
  python hourly_debate.py --dry-run        # 查看品种列表
  python hourly_debate.py                  # 扫描+辩论+报告
"""

import os
import shutil
import sys
from datetime import datetime

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
from config.settings import HOURLY_PERIOD

# ── 适合60分钟分析的21个品种（来自知识库） ──
HOURLY_SYMBOLS = [
    "PX", "PR", "V", "L", "TA", "EG", "SA", "PB", "NI", "AG",
    "M", "Y", "RM", "C", "SR", "CF", "JD", "AP", "FG", "OP", "LC",
]

OUTPUT_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "reports", "hourly")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 报告同步到FDT内部data目录（v2.2: 移除Signal依赖）
_FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPTS_DIR))))
COMMODITIES_DIR = os.path.join(_FDT_ROOT, "data", "hourly_debate")
os.makedirs(COMMODITIES_DIR, exist_ok=True)


def run_hourly_debate(dry_run: bool = False) -> dict:
    """执行一轮小时级辩论

    流程:
      1. 扫描21品种 → 提取STRONG/WATCH信号
      2. 有信号 → 注入知识库信息 → 生成辩论报告
      3. 无信号 → 简短告知
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M")
    date_str = now.strftime("%Y-%m-%d %H:%M")

    result = {
        "has_signals": False,
        "signal_count": 0,
        "strong": [],
        "watch": [],
        "report_path": "",
        "symbols": HOURLY_SYMBOLS,
        "timestamp": timestamp,
    }

    print(f"\n{'='*50}")
    print(f"  ⏰ 小时级辩论 — {date_str}")
    print(f"  扫描品种: {len(HOURLY_SYMBOLS)}个 (60分钟适宜品种)")
    print(f"{'='*50}")

    if dry_run:
        print("\n  [干运行] 品种列表:\n")
        from optimizer.knowledge_bridge import get_symbol_knowledge
        for sym in HOURLY_SYMBOLS:
            k = get_symbol_knowledge(sym)
            cat = k.get("cycle_category", "?")
            d60 = k.get("h_test_accuracy", "?")
            opt = "✅" if k.get("optimized_params", {}).get("60m") else "  "
            print(f"  {sym:4s} | {cat} | 60m测试={d60}% | 60m参数{opt}")
        return result

    # ── Step 1: 扫描 ──
    print("\n  [1] 扫描通道突破信号...")
    try:
        from scan_all import run_scan
        scan_result = run_scan(
            output_dir=OUTPUT_DIR,
            output_prefix=f"hourly_{timestamp}",
            symbols=[(s, s) for s in HOURLY_SYMBOLS],
            strategy_name="channel_breakout",
            period=HOURLY_PERIOD,
        )
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        import traceback
        traceback.print_exc()
        return result

    # ── 负向过滤 + 全量监控：任意方向性信号(|total|≥DEBATE_ENTRY_MIN_ABS)即进入辩论候选池 ──
    # 评分(grade)仅作优先级标签，不作为进入辩论的硬性门槛
    from config.settings import DEBATE_ENTRY_MIN_ABS, signal_passes_entry_gate
    all_ranked = scan_result.get("all_ranked", [])
    # 去融合后：每(策略×子信号)独立门禁 = grade∈{STRONG,WATCH}（兼容旧 |total|≥阈值 兜底）
    candidates = [s for s in all_ranked if signal_passes_entry_gate(s, DEBATE_ENTRY_MIN_ABS)]
    strong = [s for s in candidates if s.get("grade") == "STRONG"]      # 高优先级
    watch = [s for s in candidates if s.get("grade") != "STRONG"]       # 其余按评分排序，下游再决交易适配性
    has_signals = len(candidates) > 0

    result["has_signals"] = has_signals
    result["signal_count"] = len(candidates)
    result["strong"] = strong
    result["watch"] = watch

    print(f"  辩论候选={len(candidates)} (STRONG={len(strong)} 其余={len(watch)})")

    # ── Step 2: 信号门 ──
    if not has_signals:
        print("  ⏹ 无方向性信号 → 跳过辩论")
        report = _no_signal_report(date_str)
    else:
        print(f"  🔥 有{len(strong)+len(watch)}个信号 → 进入辩论")
        report = _debate_report(result, date_str)

    # ── Step 3: 输出报告 ──
    report_path = os.path.join(OUTPUT_DIR, f"hourly_{timestamp}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    result["report_path"] = report_path

    # 同步到Commodities
    commodities_link = os.path.join(COMMODITIES_DIR, "hourly_debate_latest.html")
    shutil.copy2(report_path, commodities_link)

    print(f"\n  报告: {report_path}")
    print(f"  同步: {commodities_link}")
    return result


def _no_signal_report(date_str: str) -> str:
    """无信号时的简洁报告"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>无信号 — {date_str}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #f5f5f5; display: flex;
  justify-content: center; align-items: center; height: 100vh; margin: 0; }}
.card {{ background: #fff; border-radius: 12px; padding: 40px; text-align: center;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 400px; }}
.icon {{ font-size: 48px; margin-bottom: 15px; }}
h1 {{ font-size: 20px; color: #333; margin: 0 0 8px 0; }}
p {{ color: #999; font-size: 14px; margin: 0 0 4px 0; }}
.time {{ color: #bbb; font-size: 12px; margin-top: 15px; }}
</style></head><body>
<div class="card">
  <div class="icon">🟢</div>
  <h1>无有效信号</h1>
  <p>60分钟品种均无方向性信号</p>
  <p style="color:#bbb;">不产生交易建议</p>
  <div class="time">{date_str}</div>
</div>
</body></html>"""


def _debate_report(result: dict, date_str: str) -> str:
    """有信号时的辩论报告（含知识库参考+信号分析+辩论论点）"""
    from optimizer.knowledge_bridge import get_knowledge_summary, get_symbol_knowledge

    all_signals = result.get("strong", []) + result.get("watch", [])
    strong_count = len(result.get("strong", []))
    watch_count = len(result.get("watch", []))

    # ── 信号明细表 ──
    signal_rows = []
    signal_symbols = []
    for s in all_signals:
        sym = s["symbol"]
        signal_symbols.append(sym)
        k = get_symbol_knowledge(sym)
        cat = k.get("cycle_category", "")
        d60 = k.get("h_test_accuracy", "?")
        adx = s.get("adx", s.get("ADX", 0))
        rsi = s.get("rsi", s.get("RSI14", 50))
        direction = s.get("direction", "?")
        total = s.get("total", 0)
        grade = s.get("grade", "?")
        overfit = " ⚠" if k.get("h_overfit") else ""
        dir_icon = "🟢" if direction == "bull" else ("🔴" if direction == "bear" else "⚪")
        grade_icon = "🔥" if grade == "STRONG" else "👁"
        signal_rows.append(f"""<tr>
            <td><b>{sym}</b></td>
            <td>{cat}{overfit}</td>
            <td>{d60}%</td>
            <td>{grade_icon} {grade}</td>
            <td>{dir_icon} {direction}</td>
            <td>{total}</td>
            <td>{adx:.1f}</td>
            <td>{rsi:.0f}</td>
        </tr>""")

    # ── 辩论论点（动态正反方） ──
    _sv = lambda r, k, d=0: r.get(k, d) if isinstance(r.get(k), (int, float)) else d
    score_rows = []
    for s in all_signals:
        sym = s["symbol"]
        adx = s.get("adx", s.get("ADX", 0)); rsi = s.get("rsi", s.get("RSI14", 50))
        total = s.get("total", 0); direction = s.get("direction", "neutral"); grade = s.get("grade", "?")
        ss = "🔥 强信号" if abs(total) >= 50 else ("👁 可关注" if abs(total) >= 40 else ("⚠ 弱信号" if abs(total) >= 30 else "⚪ 噪声级"))
        dc = "#22c55e" if direction == "bull" else "#ef4444"
        score_rows.append(f"""<tr><td><b>{sym}</b></td><td style="color:{dc};font-weight:700">{direction}</td><td>{grade}</td><td><b>{total}</b></td><td>{adx:.1f}</td><td>{rsi:.0f}</td><td style="font-size:11px">{ss}</td></tr>""")

    from config.settings import SYMBOL_CHAIN_MAP
    chain_signals = {}
    for s in all_signals:
        sym = s["symbol"]; chain = SYMBOL_CHAIN_MAP.get(sym.lower(), SYMBOL_CHAIN_MAP.get(sym, "其他"))
        if chain not in chain_signals: chain_signals[chain] = {"bull": 0, "bear": 0, "total": 0, "symbols": []}
        d = s.get("direction", "neutral")
        if d == "bull": chain_signals[chain]["bull"] += 1
        elif d == "bear": chain_signals[chain]["bear"] += 1
        chain_signals[chain]["total"] += 1; chain_signals[chain]["symbols"].append(sym)
    chain_rows = []
    for chain, cd in sorted(chain_signals.items()):
        ct = "多头偏强" if cd["bull"] > cd["bear"] else ("空头偏强" if cd["bear"] > cd["bull"] else "多空均衡")
        tc = "#22c55e" if "多头" in ct else "#ef4444"
        chain_rows.append(f"""<tr><td><b>{chain}</b></td><td>{cd["total"]}</td><td style="color:#22c55e">{cd["bull"]}</td><td style="color:#ef4444">{cd["bear"]}</td><td style="color:{tc};font-weight:600">{ct}</td><td style="font-size:11px">{", ".join(cd["symbols"])}</td></tr>""")

    debate_rows = []
    for s in all_signals:
        sym = s["symbol"]
        direction = s.get("direction", "neutral")
        total = s.get("total", 0)
        adx = s.get("adx", s.get("ADX", 0))
        rsi = s.get("rsi", s.get("RSI14", 50))
        k = get_symbol_knowledge(sym)
        cat = k.get("cycle_category", "")
        d60 = k.get("h_test_accuracy", 0) or 0
        dd = k.get("daily_test_accuracy", 0) or 0

        # 根据信号方向产生辩论论点
        if direction == "bull":
            # 正方=多头, 反方=空头
            bull_args = [
                f"信号方向: 多头 (总分{total})",
                f"ADX={adx:.1f}",
                f"60m回测准确率{d60}%",
            ]
            bear_args = [
                f"RSI={rsi:.0f}" + ("(偏高)" if rsi > 70 else ""),
                f"日线回测{d_daily:.0f}%" if (d_daily := dd) else "",
            ]
            if k.get("h_overfit"):
                bear_args.append("60分钟过拟合⚠")
            # 过滤空论据
            bull_args = [a for a in bull_args if a]
            bear_args = [a for a in bear_args if a]
            if not bear_args:
                bear_args.append("无明显反向信号")
            verdict = "偏向多头" if len(bull_args) >= len(bear_args) else "需谨慎"
        else:
            # 正方=空头, 反方=多头
            bear_args = [
                f"信号方向: 空头 (总分{abs(total)})",
                f"60m回测准确率{d60}%",
                f"ADX={adx:.1f}",
            ]
            bull_args = [
                f"RSI={rsi:.0f}" + ("(偏低)" if rsi < 30 else ""),
            ]
            if k.get("h_overfit"):
                bull_args.append("60分钟过拟合⚠")
            bull_args = [a for a in bull_args if a]
            bear_args = [a for a in bear_args if a]
            if not bull_args:
                bull_args.append("无明显反向信号")
            verdict = "偏向空头" if len(bear_args) >= len(bull_args) else "需谨慎"

        debate_rows.append(f"""<tr>
            <td><b>{sym}</b></td>
            <td>{direction}</td>
            <td><ul style="margin:0;padding-left:16px;">{"".join(f'<li>{a}</li>' for a in (bull_args if direction == "bull" else bear_args))}</ul></td>
            <td><ul style="margin:0;padding-left:16px;">{"".join(f'<li>{a}</li>' for a in (bear_args if direction == "bull" else bull_args))}</ul></td>
            <td>{verdict}</td>
        </tr>""")

    kb_summary = get_knowledge_summary(signal_symbols)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>小时级辩论报告 — {date_str}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
h1 {{ font-size: 20px; margin: 0; color: #fff; }}
h2 {{ font-size: 15px; color: #333; margin: 20px 0 10px 0; }}
.header {{ background: #E65100; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; }}
.header .sub {{ font-size: 13px; opacity: 0.8; margin-top: 5px; color: #fff; }}
.summary {{ display: flex; gap: 15px; margin-bottom: 20px; }}
.card {{ background: #fff; border-radius: 8px; padding: 15px; flex: 1; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.card .num {{ font-size: 28px; font-weight: bold; color: #E65100; }}
.card .label {{ font-size: 12px; color: #999; }}
.card.green .num {{ color: #4CAF50; }}
.card.red .num {{ color: #F44336; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); margin-bottom:20px; }}
th {{ background:#f8f9fa; padding:10px 12px; text-align:left; font-size:12px; color:#666; border-bottom:2px solid #eee; }}
td {{ padding:10px 12px; font-size:13px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
tr:hover td {{ background:#f8f9ff; }}
.kb {{ background:#e8f5e9; border:1px solid #c8e6c9; border-radius:8px; padding:12px 16px; font-size:13px; color:#2e7d32; margin-bottom:20px; white-space:pre-line; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px; background:#e3f2fd; color:#1565C0; }}
.tag.red {{ background:#ffebee; color:#c62828; }}
.tag.green {{ background:#e8f5e9; color:#2e7d32; }}
.footer {{ font-size:11px; color:#999; margin-top:20px; }}
</style></head><body>

<div class="header">
  <h1>⏰ 小时级辩论报告</h1>
  <div class="sub">{date_str} | 扫描{len(HOURLY_SYMBOLS)}个品种 | STRONG={strong_count} WATCH={watch_count}</div>
</div>

<div class="summary">
  <div class="card red"><div class="num">{strong_count}</div><div class="label">STRONG🔥</div></div>
  <div class="card"><div class="num">{watch_count}</div><div class="label">WATCH👁</div></div>
  <div class="card green"><div class="num">{len(signal_symbols)}</div><div class="label">辩论品种</div></div>
</div>

<h2>📡 信号明细</h2>
<table>
<tr><th>品种</th><th>周期分类</th><th>60m测试</th><th>等级</th><th>方向</th><th>总分</th><th>ADX</th><th>RSI</th></tr>
{chr(10).join(signal_rows)}
</table>

<h2>🔬 多空评分明细</h2>
<table>
<tr><th>品种</th><th>方向</th><th>等级</th><th>总分</th><th>ADX</th><th>RSI</th><th>信号强度</th></tr>
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
  知识库:2026-07-07 WF回测优化 | Commodities/hourly_debate_latest.html
</div>
</body></html>"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    r = run_hourly_debate(dry_run=args.dry_run)
    # 标准输出最后一行用来告诉用户结果
    if r["has_signals"]:
        print(f"\n【辩论结果】{r['signal_count']}个信号已辩论 → {r['report_path']}")
    else:
        print("\n【辩论结果】无STRONG/WATCH信号，无交易建议")
