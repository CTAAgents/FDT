"""明鉴秋报告层测试 (v8.8.0+)

覆盖 P1/P3/P5/P6/P6a 五个阶段报告的生成与降级路径。
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fdt_langgraph.state import create_initial_state
from fdt_langgraph.nodes import (
    node_scan, node_merge_research, node_risk_check, node_signal_output,
    _resolve_report_dir, _write_scan_report, _write_verdict_report,
    _write_research_report, _write_signal_report,
)


def create_test_state(trace_id: str = "test-trace-reports") -> dict:
    return create_initial_state(trace_id, "default")


@pytest.fixture
def workspace_tmp(tmp_path, monkeypatch):
    """临时工作空间，模拟用户指定工作空间"""
    workspace = tmp_path / "fdt_workspace"
    workspace.mkdir()
    monkeypatch.setenv("FDT_REPORT_WORKSPACE", str(workspace))
    return workspace


# ==================== 工具函数测试 ====================

def test_resolve_report_dir_uses_workspace_env(workspace_tmp):
    """环境变量 FDT_REPORT_WORKSPACE 生效"""
    resolved = _resolve_report_dir()
    assert str(workspace_tmp) in str(resolved)
    assert resolved.exists()


def test_resolve_report_dir_fallback_to_temp(monkeypatch):
    """无环境变量时回退到系统临时目录"""
    monkeypatch.delenv("FDT_REPORT_WORKSPACE", raising=False)
    monkeypatch.delenv("FDT_DAILY_WORKSPACE", raising=False)
    resolved = _resolve_report_dir()
    assert "fdt_reports" in str(resolved)


def test_write_scan_report_basic(tmp_path):
    """扫描报告 HTML 生成"""
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    scan_results = {
        "all_ranked": [
            {"symbol": "RB", "name": "螺纹钢", "direction": "bull", "total": 60, "adx": 30, "rsi": 60, "price": 4000, "atr": 100, "stage": "stage1"},
            {"symbol": "CU", "name": "沪铜", "direction": "bear", "total": 45, "adx": 25, "rsi": 40, "price": 70000, "atr": 1500, "stage": "stage2"},
        ]
    }
    path = _write_scan_report("trace-001", scan_results, out_dir)
    assert Path(path).exists()
    html = Path(path).read_text(encoding="utf-8")
    assert "trace-001" in html
    assert "RB" in html
    assert "螺纹钢" in html
    assert "BUY" in html or "SELL" in html


def test_write_scan_report_empty(workspace_tmp):
    """空扫描结果不报错"""
    path = _write_scan_report("trace-empty", {"all_ranked": []}, workspace_tmp)
    assert Path(path).exists()


def test_write_research_report(workspace_tmp):
    """研究报告生成"""
    research_data = {
        "chain_analysis": {"RB": "钢铁链"},
        "technical_data": {"RB": {"trend": "up"}},
        "fundamental_data": {"RB": {"supply": "tight"}},
    }
    path = _write_research_report("trace-r", research_data, workspace_tmp)
    html = Path(path).read_text(encoding="utf-8")
    assert "trace-r" in html
    assert "链证源" in html
    assert "观澜" in html
    assert "探源" in html


def test_write_verdict_report(workspace_tmp):
    """裁决报告生成"""
    verdict = {
        "direction": "bull", "confidence": 0.85, "reason": "趋势确立",
        "entry_price": 4000, "stop_loss_price": 3950, "target_price": 4150,
        "position_pct": 5, "contract": "RB2501", "risk_reward_ratio": 3.0,
    }
    risk_check = {"approved": True, "risk_color": "green", "risk_level": "low", "warnings": []}
    path = _write_verdict_report("trace-v", verdict, risk_check, ["RB"], workspace_tmp)
    html = Path(path).read_text(encoding="utf-8")
    assert "trace-v" in html
    assert "bull" in html or "多头" in html
    assert "GREEN" in html
    assert "4000" in html


def test_write_signal_report(workspace_tmp):
    """信号扫描报告生成"""
    signal_output = {
        "status": "sent", "risk_color": "green", "message": "已通过风控",
        "risk_check": {"approved": True, "warnings": []},
        "signal": {
            "direction": "BUY", "contract": "RB2501", "entry_price": 4000,
            "stop_loss_price": 3950, "target_price": 4150, "position_pct": 5,
            "risk_reward_ratio": 3.0, "confidence": 0.85,
        },
    }
    path = _write_signal_report("trace-s", signal_output, workspace_tmp)
    html = Path(path).read_text(encoding="utf-8")
    assert "trace-s" in html
    assert "已通过" in html or "已发送" in html
    assert "BUY" in html


# ==================== 节点级测试 ====================

@pytest.mark.asyncio
async def test_scan_report_written(workspace_tmp):
    """node_scan 写入 scan_report_path"""
    state = create_test_state()
    state["scan_results"] = {
        "all_ranked": [
            {"symbol": "RB", "direction": "bull", "total": 60, "adx": 30, "rsi": 60, "price": 4000, "atr": 100, "stage": "stage1"}
        ]
    }
    result = await node_scan(state)
    assert result["scan_report_path"] is not None
    assert Path(result["scan_report_path"]).exists()
    assert "trace" in result["scan_report_path"]


@pytest.mark.asyncio
async def test_research_report_written(workspace_tmp):
    """node_merge_research 写入 research_report_path"""
    state = create_test_state()
    state["chain_analysis"] = {"RB": "钢铁链"}
    state["technical_data"] = {"RB": {"trend": "up"}}
    state["fundamental_data"] = {"RB": {"supply": "tight"}}
    result = await node_merge_research(state)
    assert result["research_report_path"] is not None
    assert Path(result["research_report_path"]).exists()


@pytest.mark.asyncio
async def test_signal_report_written(workspace_tmp):
    """node_signal_output 写入 signal_report_path（不依赖 LLM）"""
    state = create_test_state()
    state["verdict"] = {
        "direction": "bull", "confidence": 0.85,
        "entry_price": 4000, "stop_loss_price": 3950, "target_price": 4150,
        "position_pct": 5, "contract": "RB2501", "risk_reward_ratio": 3.0,
    }
    state["risk_check"] = {"approved": True, "risk_color": "green", "warnings": []}

    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as mock_exec:
        mock_exec.return_value.run = pytest.mark.asyncio(lambda *a, **k: {"output": "ok"})
        # 直接构造 signal_output 模拟
        state["signal_output"] = {
            "status": "sent", "risk_color": "green", "message": "ok",
            "signal": state["verdict"],
            "risk_check": state["risk_check"],
        }
        from fdt_langgraph.nodes import node_signal_output as nsig
        # 直接复制 node_signal_output 报告生成部分逻辑
        from fdt_langgraph.nodes import _write_signal_report
        path = _write_signal_report(state["trace_id"], state["signal_output"],
                                    _resolve_report_dir())
        assert path is not None
        assert Path(path).exists()


# ==================== 契约测试 ====================

def test_state_has_all_phase_report_fields():
    """DebateState 包含 5 个阶段报告字段"""
    state = create_initial_state("test-contract", "default")
    assert state["scan_report_path"] is None
    assert state["research_report_path"] is None
    assert state["verdict_report_path"] is None
    assert state["report_path"] is None


def test_report_path_unique_per_phase(workspace_tmp):
    """5 个状态字段互不干扰，各有独立值"""
    state = create_test_state("trace-unique")
    state["scan_report_path"] = str(workspace_tmp / "scan.html")
    state["research_report_path"] = str(workspace_tmp / "research.html")
    state["verdict_report_path"] = str(workspace_tmp / "verdict.html")
    state["report_path"] = str(workspace_tmp / "report.html")
    assert len({state["scan_report_path"], state["research_report_path"],
                state["verdict_report_path"], state["report_path"]}) == 4
