"""
PTA609 FDT 全流程辩论 — 完整部署运行

通过预种子扫描数据 + 绕过新鲜度闸门 + 禁用 FDC 注入，
让 LangGraph 13-Agent 全流程跑通并产出真实 LLM 驱动的完整报告。
"""
import asyncio, json, os, sys
from datetime import datetime

FDT_ROOT = r"D:\Programs\FDT"
sys.path.insert(0, FDT_ROOT)

# ── 环境变量：关键配置 ──
os.environ["FDT_BYPASS_FRESHNESS_GATE"] = "true"   # 跳过数据新鲜度闸门
os.environ["FDT_FDC_INJECTION_ENABLED"] = "false"  # 禁用 FDC 数据注入（用种子数据代替）
os.environ["FDT_LLM_MOCK"] = "false"               # 真实 LLM 调用
os.environ["FDT_GENERATE_INTERMEDIATE_REPORTS"] = "false"
os.environ["FDT_GENERATE_SCAN_REPORT"] = "false"

from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
from fdt_langgraph.state import create_initial_state

def build_seed_data():
    now = datetime.now().isoformat()
    return {
        "all_ranked": [
            {
                "symbol": "TA",
                "name": "精对苯二甲酸",
                "contract": "TA609",
                "total": 3.5,
                "signal_strength": "medium",
                "direction": "bull",
                "price": 5858,
                "strategies": {
                    "trend_following": {"score": 3.0, "direction": "bull"},
                    "breakout": {"score": 2.5, "direction": "bull"},
                    "basis": {"score": 1.5, "direction": "neutral"},
                },
                "breakouts": {"daily_breakout_up": True, "weekly_support": 5700},
                "indicators": {
                    "rsi_14": 58, "adx_14": 28, "ma_20": 5720, "ma_60": 5650,
                    "bb_upper": 6020, "bb_lower": 5480,
                },
            }
        ],
        "primary_symbols": ["TA"],
        "total_signals": 1,
        "bull_signals": [{"symbol": "TA", "total": 3.5}],
        "bear_signals": [],
        "per_strategy": {},
        "_meta": {"scan_time": now, "data_grade": "NETWORK"},
    }

async def main():
    trace_id = "fdt-pta609-full-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    print("=" * 60)
    print("FDT PTA609 全流程辩论系统 — 部署运行")
    print(f"trace_id: {trace_id}")
    print("=" * 60)

    initial = create_initial_state(trace_id, mode="deep_research")
    
    seed = build_seed_data()
    initial["scan_results"] = seed
    initial["selected_symbols"] = ["TA"]
    initial["_original_symbols"] = ["TA"]
    initial["symbol_index"] = 0
    initial["freshness_report"] = {
        "status": "BYPASS",
        "valid_symbols": 1,
        "summary": "手动种子数据注入绕过新鲜度闸门",
    }
    initial["fdc_data"] = {
        "TA": {
            "quote": {"price": 5858, "change": -106, "change_pct": -1.78},
            "indicators": {
                "rsi_14": 58, "adx_14": 28, "ma_20": 5720, "ma_60": 5650,
                "bb_upper": 6020, "bb_lower": 5480, "volume_ratio": 1.2,
            },
            "fundamental": {
                "supply": {"operating_rate": 57.81, "weekly_output": 111.12, "inventory": 227.47},
                "demand": {"polyester_rate": 80.9, "weaving_rate": 58.5},
                "cost": {"processing_fee": 448, "px_price": 1105.33},
                "notes": "2026年无新增产能，8月约570万吨装置计划重启。美伊冲突持续，霍尔木兹海峡通航停滞。",
            },
            "chain": {
                "upstream": "PX开工61.34%低位，加工费225.87美元/吨",
                "midstream": "PTA开工57.81%历史低位，社会库存月降44万吨",
                "downstream": "聚酯负荷80.9%低于往年，淡季织造58.5%",
                "transmission": "原油地缘溢价→PX→PTA→聚酯，成本驱动型上涨",
            },
        }
    }

    print("\n[1/5] 构建 LangGraph 辩论图 (deep_research 模式) ...")
    graph = build_debate_graph(mode="deep_research")
    print("  图构建完成：扫描→新鲜度闸门→初判→准备→四源→辩论→裁决→风控→质检→报告→信号输出")

    print("\n[2/5] 开始执行 13-Agent 全流程辩论 ...")
    print(f"  品种: PTA (TA609) | trace_id: {trace_id}")
    print("  ⏱ 预计耗时 3-8 分钟\n")

    result = await graph.ainvoke(initial)

    print("\n" + "=" * 60)
    print("[3/5] 辩论完成！报告产出：")
    print("=" * 60)
    for k in ("scan_report_path","research_report_path","verdict_report_path","report_path","signal_report_path"):
        v = result.get(k)
        if v: print(f"  ✅ {k}: {v}")

    if result.get("report_path"):
        print(f"\n📄 完整辩论报告: {result['report_path']}")

    print("\n" + "=" * 60)
    print("[4/5] 闫判官裁决摘要：")
    print("=" * 60)
    verdict = result.get("verdict", {})
    if verdict:
        print(f"  方向: {verdict.get('direction', 'N/A')}")
        print(f"  置信度: {verdict.get('confidence', 'N/A')}")
        print(f"  信号等级: {verdict.get('grade', 'N/A')}")
        if verdict.get('entry_price'):
            print(f"  入场价: {verdict.get('entry_price')}")
            print(f"  目标价: {verdict.get('target_price')}")
            print(f"  止损价: {verdict.get('stop_loss_price')}")
            print(f"  建议仓位: {verdict.get('position_pct', 'N/A')}")
            print(f"  盈亏比: {verdict.get('risk_reward_ratio', 'N/A')}")
    else:
        print("  (无裁决数据)")

    risk = result.get("risk_check", {})
    if risk:
        print(f"\n  风控结果: {risk.get('risk_level', 'N/A')} / {risk.get('approval', 'N/A')}")

    print("\n" + "=" * 60)
    print("[5/5] 辩论论据统计：")
    print("=" * 60)
    for name, key in [("多头立论","bullish_arguments"),("空头立论","bearish_arguments"),
                       ("多头反驳","bullish_rebuttal_arguments"),("空头反驳","bearish_rebuttal_arguments"),
                       ("多头结辩","bull_final_arguments"),("空头结辩","bear_final_arguments")]:
        data = result.get(key, [])
        print(f"  {name}: {len(data)} 条论据")

    print("\n✅ FDT PTA609 全流程辩论完成！")

if __name__ == "__main__":
    asyncio.run(main())
