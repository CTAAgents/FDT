import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
from fdt_langgraph.state import create_initial_state
from datetime import datetime

async def main():
    trace_id = "pta-debate-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    print("[PTA] trace_id:", trace_id)
    initial = create_initial_state(trace_id, mode="deep_research")
    initial["selected_symbols"] = ["TA"]
    graph = build_debate_graph(mode="deep_research")
    result = await graph.ainvoke(initial)
    print("\n=== Report Paths ===")
    for k in ("scan_report_path","research_report_path","verdict_report_path","report_path","signal_report_path"):
        v = result.get(k)
        if v: print("  OK", k, ":", v)

asyncio.run(main())
