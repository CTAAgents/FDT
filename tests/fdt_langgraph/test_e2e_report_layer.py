"""端到端报告层快速验证（v8.8.0）—— 绕过 LLM，直接验证报告生成"""
import pytest
import tempfile
from pathlib import Path

from fdt_langgraph.state import create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_merge_research, node_risk_check,
    node_signal_output, node_report,
)


@pytest.mark.asyncio
async def test_e2e_report_layer_fast():
    """快速端到端：构造完整 state → 跑报告节点 → 验证 5 个报告路径"""
    trace_id = "e2e-report-layer-001"
    state = create_initial_state(trace_id, mode="default")
    state["selected_symbols"] = ["RB", "CU"]

    # P1: scan（已有 scan_results 则复用）
    state["scan_results"] = {
        "all_ranked": [
            {"symbol": "RB", "name": "螺纹钢", "direction": "bull", "total": 60,
             "adx": 30, "rsi": 60, "price": 4000, "atr": 100, "stage": "stage1"},
            {"symbol": "CU", "name": "沪铜", "direction": "bear", "total": 45,
             "adx": 25, "rsi": 40, "price": 70000, "atr": 1500, "stage": "stage2"},
        ]
    }
    s1 = await node_scan(state)
    assert s1["scan_report_path"] is not None
    assert Path(s1["scan_report_path"]).exists()

    # P3: merge research
    s1["chain_analysis"] = {"钢铁": "强"}
    s1["technical_data"] = {"RB": {"trend": "up"}}
    s1["fundamental_data"] = {"RB": {"inventory": "low"}}
    s3 = await node_merge_research(s1)
    assert s3["research_report_path"] is not None
    assert Path(s3["research_report_path"]).exists()

    # P5: verdict + risk_check
    s3["verdict"] = {
        "direction": "bull", "confidence": 0.85, "reason": "趋势确立",
        "entry_price": 4000, "stop_loss_price": 3950, "target_price": 4150,
        "position_pct": 5, "contract": "RB2501", "risk_reward_ratio": 3.0,
    }
    s5 = await node_risk_check(s3)
    assert s5["verdict_report_path"] is not None
    assert Path(s5["verdict_report_path"]).exists()

    # P6: report（使用 mock intermediate/debate 数据）
    s5["bullish_arguments"] = [{"argument": "多头论据"}]
    s5["bearish_arguments"] = [{"argument": "空头论据"}]
    s6 = await node_report(s5)
    assert s6["report_path"] is not None
    assert Path(s6["report_path"]).exists()

    # P6a: signal_output
    s6["signal_output"] = {
        "status": "sent", "risk_color": "green", "message": "已通过",
        "risk_check": {"approved": True, "warnings": []},
        "signal": s3["verdict"],
    }
    s7 = await node_signal_output(s6)
    assert s7["signal_report_path"] is not None
    assert Path(s7["signal_report_path"]).exists()

    # 统一验证 HTML 内容
    # P1/P3/P5/P6a 由 _render_html 生成，含 trace_id；P6 由外部脚本生成，仅验证存在
    report_checks = [
        ("P1 scan", s1["scan_report_path"], True),
        ("P3 research", s3["research_report_path"], True),
        ("P5 verdict", s5["verdict_report_path"], True),
        ("P6 report", s6["report_path"], False),
        ("P6a signal", s7["signal_report_path"], True),
    ]
    for label, path, expect_trace_id in report_checks:
        html = Path(path).read_text(encoding="utf-8")
        if expect_trace_id:
            assert trace_id in html, f"{label} 报告缺失 trace_id"
        assert "明鉴秋" in html or "FDT" in html or "期货" in html, f"{label} 报告内容异常"

    # 验证 fdt_cli._print_phase_reports 输出格式
    from fdt_cli import _print_phase_reports
    import io
    import sys
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    _print_phase_reports(s7)
    sys.stdout = old_stdout
    output = captured.getvalue()
    assert "阶段报告汇总" in output
    assert "P1 扫描报告" in output
    assert "P3 研究报告" in output
    assert "P5 裁决报告" in output
    assert "P6 辩论报告" in output
    assert "P6a 信号扫描报告" in output
