"""LG2609 FDT 全流程辩论 — 完整部署运行

品种: 原木 (Logs/Lumber) LG2609 @ DCE
合约代码: LG
价位: ~827 元/立方米 (2026-07-27)
"""
import asyncio, json, os, sys, shutil
from datetime import datetime

FDT_ROOT = r"D:\Programs\FDT"
sys.path.insert(0, FDT_ROOT)

os.environ["FDT_BYPASS_FRESHNESS_GATE"] = "true"
os.environ["FDT_FDC_INJECTION_ENABLED"] = "false"
os.environ["FDT_LLM_MOCK"] = "false"
os.environ["FDT_GENERATE_INTERMEDIATE_REPORTS"] = "false"
os.environ["FDT_GENERATE_SCAN_REPORT"] = "false"

from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
from fdt_langgraph.state import create_initial_state

def build_seed_data():
    now = datetime.now().isoformat()
    return {
        "all_ranked": [
            {
                "symbol": "LG",
                "name": "\u539f\u6728",
                "contract": "LG2609",
                "total": 3.0,
                "signal_strength": "medium",
                "direction": "bull",
                "price": 827.0,
                "atr": 12.5,
                "strategies": {
                    "trend_following": {"score": 2.5, "direction": "bull"},
                    "breakout": {"score": 3.0, "direction": "neutral"},
                    "basis": {"score": 1.5, "direction": "neutral"},
                },
                "breakouts": {"daily_breakout_up": False, "weekly_support": 800},
                "indicators": {
                    "rsi_14": 48, "adx_14": 18, "ma_20": 822, "ma_60": 815,
                    "bb_upper": 850, "bb_lower": 795,
                },
            }
        ],
        "primary_symbols": ["LG"],
        "total_signals": 1,
        "bull_signals": [{"symbol": "LG", "total": 3.0}],
        "bear_signals": [],
        "per_strategy": {},
        "_meta": {"scan_time": now, "data_grade": "NETWORK"},
    }

async def main():
    trace_id = "fdt-lg2609-full-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    print("=" * 60)
    print("FDT LG2609 \u5168\u6d41\u7a0b\u8fa9\u8bba\u7cfb\u7edf \u2014 \u539f\u6728")
    print(f"trace_id: {trace_id}")
    print("=" * 60)

    initial = create_initial_state(trace_id, mode="deep_research")
    seed = build_seed_data()
    initial["scan_results"] = seed
    initial["selected_symbols"] = ["LG"]
    initial["_original_symbols"] = ["LG"]
    initial["symbol_index"] = 0
    initial["freshness_report"] = {"status": "BYPASS", "valid_symbols": 1, "summary": "\u624b\u52a8\u79cd\u5b50\u6570\u636e\u6ce8\u5165"}
    initial["fdc_data"] = {
        "LG": {
            "quote": {"price": 827.0, "change": -0.5, "change_pct": -0.06},
            "indicators": {
                "rsi_14": 48, "adx_14": 18, "ma_20": 822, "ma_60": 815,
                "bb_upper": 850, "bb_lower": 795, "volume_ratio": 0.85,
            },
            "fundamental": {
                "supply": {"import_jan_jun": "1165.88\u4e07m\u00b3(\u540c\u6bd4-5.49%)", "import_jun": "239.73\u4e07m\u00b3(\u540c\u6bd4+10.13%)", "new_zealand_share": "66%", "inventory": "\u6e2f\u53e3\u5e93\u5b58\u4e2d\u6027\u504f\u9ad8"},
                "demand": {"real_estate": "\u623f\u5730\u4ea7\u65b0\u5f00\u5de5\u6301\u7eed\u4f4e\u8ff7", "construction": "\u57fa\u5efa\u9700\u6c42\u7a33\u5b9a\u4f46\u589e\u91cf\u6709\u9650", "furniture": "\u5bb6\u5177\u51fa\u53e3\u53d7\u5173\u7a0e\u5f71\u54cd\u504f\u5f31"},
                "cost": {"log_cfr": "120-125\u7f8e\u5143/m\u00b3", "shipping": "\u65b0\u897f\u5170-\u4e2d\u56fd 25\u7f8e\u5143/m\u00b3"},
                "notes": "\u4f9b\u9700\u5bbd\u677e\u683c\u5c40\u5ef6\u7eed\uff0c\u8fdb\u53e36\u6708\u73af\u6bd4\u56de\u5347\u4f46\u4ecd\u4f4e\u4e8e\u53bb\u5e74\u540c\u671f\u3002\u623f\u5730\u4ea7\u65b0\u5f00\u5de5\u540c\u6bd4\u964d\u5e45\u6269\u5927\uff0c\u9700\u6c42\u7aef\u7f3a\u4e4f\u9a71\u52a8\u3002\u4f4e\u5e93\u5b58\u63d0\u4f9b\u4e00\u5b9a\u652f\u6491\u4f46\u4e0a\u884c\u7a7a\u95f4\u6709\u9650\u3002",
            },
            "chain": {
                "upstream": "\u65b0\u897f\u5170\u4f9b\u5e94\u7a33\u5b9a\uff0c\u4fc4\u7f57\u65af\u56e0\u5173\u7a0e\u8c03\u6574\u4efd\u989d\u4e0b\u964d",
                "midstream": "\u6e2f\u53e3\u5230\u8d27\u91cf\u56de\u5347\uff0c\u8d38\u6613\u5546\u51fa\u8d27\u610f\u613f\u589e\u5f3a",
                "downstream": "\u952f\u6750/\u4eba\u9020\u677f\u9700\u6c42\u5f31\uff0c\u623f\u5730\u4ea7\u4f4e\u8ff7\u62d6\u7d2f",
                "transmission": "\u65b0\u897f\u5170\u539f\u6728CFR\u2192\u6e2f\u53e3\u73b0\u8d27\u2192\u52a0\u5de5\u5382\u2192\u7ec8\u7aef\uff0c\u4f9b\u9700\u5bbd\u677e\u4f20\u5bfc",
            },
        }
    }

    print("\n[1/5] \u6784\u5efa LangGraph \u8fa9\u8bba\u56fe ...")
    graph = build_debate_graph(mode="deep_research")
    print("  OK")

    print("\n[2/5] \u5f00\u59cb\u6267\u884c 13-Agent \u5168\u6d41\u7a0b\u8fa9\u8bba ...")
    print(f"  \u54c1\u79cd: \u539f\u6728 (LG2609) @ 827.0 | trace_id: {trace_id}")
    print("  \u23f1 3-8 min\n")

    result = await graph.ainvoke(initial)

    print("\n" + "=" * 60)
    print("[3/5] \u62a5\u544a\u4ea7\u51fa:")
    print("=" * 60)
    for k in ("scan_report_path","research_report_path","verdict_report_path","report_path","signal_report_path"):
        v = result.get(k)
        if v: print(f"  OK {k}: {v}")

    if result.get("report_path"):
        dest = f"d:\\TRAE\\debate_report_lg2609_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        try:
            shutil.copy2(result["report_path"], dest)
            print(f"\nReport -> {dest}")
        except Exception as e:
            print(f"\nCopy failed: {e}")

    print("\n" + "=" * 60)
    print("[4/5] \u88c1\u51b3\u6458\u8981:")
    print("=" * 60)
    verdict = result.get("verdict", {})
    quality_report = result.get("quality_report", {})
    qc_status = quality_report.get("status", "N/A") if quality_report else "N/A"
    print(f"  \u8d28\u68c0: {qc_status}")
    if verdict:
        per_symbol = verdict.get("per_symbol", {})
        if per_symbol:
            for sym, sv in per_symbol.items():
                flag = " (QC_FAIL)" if sv.get("_quality_fail_override") else ""
                print(f"  [{sym}]{flag} dir={sv.get('direction','N/A')}")
                print(f"  [{sym}] conf={sv.get('confidence','N/A')}")
                print(f"  [{sym}] entry={sv.get('entry_price','N/A')}")
                print(f"  [{sym}] target={sv.get('target_price','N/A')}")
                print(f"  [{sym}] stop={sv.get('stop_loss_price','N/A')}")
                print(f"  [{sym}] pos={sv.get('position_pct','N/A')}")
        else:
            print(f"  dir={verdict.get('direction','N/A')}")
    risk = result.get("risk_check", {})
    if risk:
        print(f"\n  \u98ce\u63a7: {risk.get('risk_level','N/A')} / {risk.get('approval','N/A')}")

    print("\n" + "=" * 60)
    print(f"OK FDT LG2609 done! trace_id: {trace_id}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
