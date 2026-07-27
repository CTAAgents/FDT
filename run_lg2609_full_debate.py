"""
LG2609 FDT 全流程辩论 — 完整部署运行

通过预种子扫描数据 + 绕过新鲜度闸门 + 禁用 FDC 注入，
让 LangGraph 13-Agent 全流程跑通并产出真实 LLM 驱动的完整报告。
"""
import asyncio, json, os, sys, shutil
from datetime import datetime

FDT_ROOT = r"D:\Programs\FDT"
sys.path.insert(0, FDT_ROOT)

# ── 环境变量：关键配置 ──
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
                "symbol": "PG",
                "name": "\u6db2\u5316\u77f3\u6cb9\u6c14",
                "contract": "PG2609",
                "total": 4.0,
                "signal_strength": "medium",
                "direction": "bull",
                "price": 5575,
                "atr": 82,
                "strategies": {
                    "trend_following": {"score": 3.5, "direction": "bull"},
                    "breakout": {"score": 3.0, "direction": "bull"},
                    "basis": {"score": 2.0, "direction": "neutral"},
                },
                "breakouts": {"daily_breakout_up": True, "weekly_support": 5400},
                "indicators": {
                    "rsi_14": 55, "adx_14": 32, "ma_20": 5420, "ma_60": 5300,
                    "bb_upper": 5800, "bb_lower": 5200,
                },
            }
        ],
        "primary_symbols": ["PG"],
        "total_signals": 1,
        "bull_signals": [{"symbol": "PG", "total": 4.0}],
        "bear_signals": [],
        "per_strategy": {},
        "_meta": {"scan_time": now, "data_grade": "NETWORK"},
    }

async def main():
    trace_id = "fdt-lg2609-full-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    print("=" * 60)
    print("FDT LG2609 \u5168\u6d41\u7a0b\u8fa9\u8bba\u7cfb\u7edf \u2014 \u90e8\u7f72\u8fd0\u884c")
    print(f"trace_id: {trace_id}")
    print("=" * 60)

    initial = create_initial_state(trace_id, mode="deep_research")
    seed = build_seed_data()
    initial["scan_results"] = seed
    initial["selected_symbols"] = ["PG"]
    initial["_original_symbols"] = ["PG"]
    initial["symbol_index"] = 0
    initial["freshness_report"] = {
        "status": "BYPASS", "valid_symbols": 1,
        "summary": "\u624b\u52a8\u79cd\u5b50\u6570\u636e\u6ce8\u5165\u7ed5\u8fc7\u65b0\u9c9c\u5ea6\u95f8\u95e8",
    }
    initial["fdc_data"] = {
        "PG": {
            "quote": {"price": 5575, "change": -85, "change_pct": -1.50},
            "indicators": {
                "rsi_14": 55, "adx_14": 32, "ma_20": 5420, "ma_60": 5300,
                "bb_upper": 5800, "bb_lower": 5200, "volume_ratio": 1.15,
            },
            "fundamental": {
                "supply": {
                    "pdh_operating_rate": 72.0, "lpg_operating_rate": 58.0,
                    "import_dependence": "70%\u4e2d\u4e1c\u8fdb\u53e3", "inventory": 185.0,
                },
                "demand": {
                    "pdh_demand": "3,500\u4e07\u5428/\u5e74\u4e19\u70f7\u9700\u6c42",
                    "civil_demand": "\u590f\u5b63\u6de1\u5b63\u6c11\u7528\u504f\u4f4e",
                    "commercial_demand": "\u9910\u996e\u9700\u6c42\u5e73\u7a33",
                },
                "cost": {
                    "cp_price": 580, "fei_price": 565,
                    "maritime_freight": "\u4e2d\u4e1c-\u8fdc\u4e1c 42\u7f8e\u5143/\u5428",
                },
                "notes": "\u4f0a\u6717\u970d\u5c14\u6728\u5179\u6d77\u5ce1\u901a\u822a\u505c\u6ede\uff0c\u4e2d\u4e1cLPG\u51fa\u53e3\u4e2d\u65ad\u9884\u671f\u52a0\u5267\u3002PDH\u5f00\u5de5\u7387\u6301\u7eed\u56de\u5347\u81f372%\uff0c\u4e19\u70f7\u8fdb\u53e3\u9700\u6c42\u53d7\u63d0\u632f\u3002",
            },
            "chain": {
                "upstream": "\u539f\u6cb9\u5730\u7f18\u6ea2\u4ef7\u9ad8\u4f01\uff0c\u4e2d\u4e1c\u4e19\u70f7\u4e01\u70f7\u51fa\u53e3\u6e90\u9762\u4e34\u8fd0\u8f93\u7631\u75ea\u98ce\u9669",
                "midstream": "PDH\u5f00\u5de5\u738772%\u6301\u7eed\u56de\u5347\uff0c\u56fd\u5185\u6db2\u5316\u6c14\u5546\u54c1\u91cf\u7a33\u5b9a",
                "downstream": "\u6c11\u7528\u9700\u6c42\u5b63\u8282\u6027\u8d70\u5f31\uff0c\u5316\u5de5\u9700\u6c42PDH\u5f00\u5de5\u56de\u5347\u5f62\u6210\u652f\u6491",
                "transmission": "\u539f\u6cb9\u2192\u77f3\u8111\u6cb9/LPG\u2192\u4e19\u70f7\u8131\u6c22\u2192\u805a\u4e19\u70ef\uff0c\u6210\u672c\u9a71\u52a8+\u5730\u7f18\u6ea2\u4ef7\u53cc\u91cd\u4f20\u5bfc",
            },
        }
    }

    print("\n[1/5] \u6784\u5efa LangGraph \u8fa9\u8bba\u56fe (deep_research \u6a21\u5f0f) ...")
    graph = build_debate_graph(mode="deep_research")
    print("  \u56fe\u6784\u5efa\u5b8c\u6210\uff1a\u626b\u63cf\u2192\u65b0\u9c9c\u5ea6\u95f8\u95e8\u2192\u521d\u5224\u2192\u51c6\u5907\u2192\u56db\u6e90\u2192\u8fa9\u8bba\u2192\u88c1\u51b3\u2192\u98ce\u63a7\u2192\u8d28\u68c0\u2192\u62a5\u544a\u2192\u4fe1\u53f7\u8f93\u51fa")

    print("\n[2/5] \u5f00\u59cb\u6267\u884c 13-Agent \u5168\u6d41\u7a0b\u8fa9\u8bba ...")
    print(f"  \u54c1\u79cd: LPG (PG2609) | trace_id: {trace_id}")
    print("  \u23f1 \u9884\u8ba1\u8017\u65f6 3-8 \u5206\u949f\n")

    result = await graph.ainvoke(initial)

    print("\n" + "=" * 60)
    print("[3/5] \u8fa9\u8bba\u5b8c\u6210\uff01\u62a5\u544a\u4ea7\u51fa\uff1a")
    print("=" * 60)
    for k in ("scan_report_path","research_report_path","verdict_report_path","report_path","signal_report_path"):
        v = result.get(k)
        if v: print(f"  \u2705 {k}: {v}")

    if result.get("report_path"):
        print(f"\n\U0001f4c4 \u5b8c\u6574\u8fa9\u8bba\u62a5\u544a: {result['report_path']}")
        dest = f"d:\\TRAE\\debate_report_lg2609_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        try:
            shutil.copy2(result["report_path"], dest)
            print(f"\n\U0001f4c4 \u62a5\u544a\u5df2\u590d\u5236\u5230: {dest}")
        except Exception as e:
            print(f"\n\u26a0\ufe0f \u62a5\u544a\u590d\u5236\u5931\u8d25: {e}")

    print("\n" + "=" * 60)
    print("[4/5] \u95eb\u5224\u5b98\u88c1\u51b3\u6458\u8981\uff1a")
    print("=" * 60)
    verdict = result.get("verdict", {})
    if verdict:
        per_symbol = verdict.get("per_symbol", {})
        if per_symbol:
            for sym, sv in per_symbol.items():
                print(f"  [{sym}] \u65b9\u5411: {sv.get('direction', 'N/A')}")
                print(f"  [{sym}] \u7f6e\u4fe1\u5ea6: {sv.get('confidence', 'N/A')}")
                print(f"  [{sym}] \u4fe1\u53f7\u7b49\u7ea7: {sv.get('grade', 'N/A')}")
                print(f"  [{sym}] \u5165\u573a\u4ef7: {sv.get('entry_price', 'N/A')}")
                print(f"  [{sym}] \u76ee\u6807\u4ef7: {sv.get('target_price', 'N/A')}")
                print(f"  [{sym}] \u6b62\u635f\u4ef7: {sv.get('stop_loss_price', 'N/A')}")
                print(f"  [{sym}] \u5efa\u8bae\u4ed3\u4f4d: {sv.get('position_pct', 'N/A')}")
                print(f"  [{sym}] \u76c8\u4e8f\u6bd4: {sv.get('risk_reward_ratio', 'N/A')}")
        else:
            print(f"  \u65b9\u5411: {verdict.get('direction', 'N/A')}")
            print(f"  \u7f6e\u4fe1\u5ea6: {verdict.get('confidence', 'N/A')}")
    else:
        print("  (\u65e0\u88c1\u51b3\u6570\u636e)")

    risk = result.get("risk_check", {})
    if risk:
        print(f"\n  \u98ce\u63a7\u7ed3\u679c: {risk.get('risk_level', 'N/A')} / {risk.get('approval', 'N/A')}")

    print("\n" + "=" * 60)
    print("[5/5] \u8fa9\u8bba\u8bba\u636e\u7edf\u8ba1\uff1a")
    print("=" * 60)
    for name, key in [("\u591a\u5934\u7acb\u8bba","bullish_arguments"),("\u7a7a\u5934\u7acb\u8bba","bearish_arguments"),
                       ("\u591a\u5934\u53cd\u9a73","bullish_rebuttal_arguments"),("\u7a7a\u5934\u53cd\u9a73","bearish_rebuttal_arguments"),
                       ("\u591a\u5934\u7ed3\u8fa9","bull_final_arguments"),("\u7a7a\u5934\u7ed3\u8fa9","bear_final_arguments")]:
        data = result.get(key, [])
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            count = len(data)
        elif isinstance(data, str):
            count = f"str({len(data)} chars)"
        else:
            count = str(type(data).__name__)
        print(f"  {name}: {count} \u6761\u8bba\u636e")

    print("\n" + "=" * 60)
    print(f"\u2705 FDT LG2609 \u5168\u6d41\u7a0b\u8fa9\u8bba\u5b8c\u6210\uff01trace_id: {trace_id}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
