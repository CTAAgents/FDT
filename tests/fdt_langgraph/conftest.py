import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(autouse=True)
def mock_heavy_io(monkeypatch):
    """自动 mock 所有重 I/O 操作，防止测试触发真实数据采集。"""
    # mock node_scan 的 run_scan
    monkeypatch.setattr(
        "fdt_langgraph.nodes._import_from_skill",
        lambda skill_dir, module_path, function_name: _mock_skill_function(function_name)
    )


def _mock_skill_function(name):
    """返回 mock 的 skill 函数"""
    mocks = {
        "run_scan": lambda: {"symbols": ["RB", "CU"], "signals": []},
        "analyze_chain": lambda symbols: {"chains": [], "symbols": symbols},
        "generate": lambda state: f"/tmp/report-{state.get('trace_id', 'test')}.html",
    }
    return mocks.get(name, lambda *a, **kw: {})
