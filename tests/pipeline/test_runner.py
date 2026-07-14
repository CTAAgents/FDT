"""
Pipeline Runner 集成测试 — G5
=============================

覆盖: 6 阶段流水线主流程、部分失败行为、trace_id 注入、run_cmd 异常处理。
策略: mock 子进程调用 + 步骤函数，验证控制流而非 I/O。
"""

import os, sys, subprocess
import pytest
from unittest.mock import MagicMock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["test"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestPipelineRunner:
    """主流程控制流测试"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.report_dir = tmp_path / "report"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.html = os.path.join(str(self.report_dir), "daily_analysis_20260710.html")

        monkeypatch.setattr("pipeline.runner.REPORT_DIR", str(self.report_dir))
        monkeypatch.setattr("pipeline.runner.DATE_COMPACT", "20260710")
        monkeypatch.setattr("pipeline.runner.DATE_STR", "2026-07-10")
        monkeypatch.setattr("pipeline.runner.ALL_SYMBOL_CODES", ["CU", "RB", "PK"])
        self.mock_run = MagicMock(return_value=_cp(0))
        monkeypatch.setattr("pipeline.runner.subprocess.run", self.mock_run)

    def _mock_steps(self, monkeypatch, results: dict):
        """批量 mock 步骤函数。results: {step_name: bool}"""
        for name, ok in results.items():
            monkeypatch.setattr(f"pipeline.runner.step_{name}", lambda ok=ok: ok)

    def test_all_succeed(self, monkeypatch):
        self._mock_steps(monkeypatch, {
            "scan": True, "chain_analysis": True, "debate_brief": True,
            "assemble_intermediate": True, "generate_report": True, "record_history": True,
        })
        monkeypatch.setattr("os.path.exists", lambda p: p == self.html)
        from pipeline.runner import main
        assert main() == 0

    def test_scan_fails_others_ok(self, monkeypatch):
        """scan 失败 → 流水线继续完成 → 返回 1"""
        self._mock_steps(monkeypatch, {
            "scan": False, "chain_analysis": True, "debate_brief": True,
            "assemble_intermediate": True, "generate_report": True, "record_history": True,
        })
        monkeypatch.setattr("os.path.exists", lambda p: p == self.html)
        from pipeline.runner import main
        assert main() == 1

    def test_chain_fails_others_ok(self, monkeypatch):
        """chain 失败 → 其余正常 → 返回 1"""
        self._mock_steps(monkeypatch, {
            "scan": True, "chain_analysis": False, "debate_brief": True,
            "assemble_intermediate": True, "generate_report": True, "record_history": True,
        })
        monkeypatch.setattr("os.path.exists", lambda p: p == self.html)
        from pipeline.runner import main
        assert main() == 1

    def test_report_fails(self, monkeypatch):
        """报告失败 + HTML 不存在 → 返回 1"""
        self._mock_steps(monkeypatch, {
            "scan": True, "chain_analysis": True, "debate_brief": True,
            "assemble_intermediate": True, "generate_report": False, "record_history": True,
        })
        monkeypatch.setattr("os.path.exists", lambda p: False)
        from pipeline.runner import main
        assert main() == 1

    def test_multi_warn(self, monkeypatch):
        """3 个警告 + HTML 存在 → 返回 1（有警告即非零）"""
        self._mock_steps(monkeypatch, {
            "scan": True, "chain_analysis": False, "debate_brief": False,
            "assemble_intermediate": False, "generate_report": True, "record_history": True,
        })
        monkeypatch.setattr("os.path.exists", lambda p: p == self.html)
        from pipeline.runner import main
        assert main() == 1

    def test_trace_id_in_run_cmd(self, monkeypatch):
        """run_cmd 将 FDT_TRACE_ID 注入子进程 env"""
        from pipeline.runner import run_cmd
        from scripts.trace_id import new_trace
        new_trace("test")

        run_cmd(["echo", "hi"], "trace-test", check=False)

        for c in self.mock_run.call_args_list:
            env = c[1].get("env", {})
            if "FDT_TRACE_ID" in env:
                assert env["FDT_TRACE_ID"].startswith("test-")
                return
        pytest.fail("FDT_TRACE_ID 未注入")


class TestRunCmd:
    """run_cmd 异常处理单元测试"""

    def test_success(self, monkeypatch):
        mock = MagicMock(return_value=_cp(0, "OK"))
        monkeypatch.setattr("pipeline.runner.subprocess.run", mock)
        from pipeline.runner import run_cmd
        r = run_cmd(["echo"], "ok")
        assert r.returncode == 0

    def test_nonzero_no_check(self, monkeypatch):
        mock = MagicMock(return_value=_cp(1, "", "err"))
        monkeypatch.setattr("pipeline.runner.subprocess.run", mock)
        from pipeline.runner import run_cmd
        r = run_cmd(["fail"], "no-check", check=False)
        assert r.returncode == 1

    def test_timeout_reraises(self, monkeypatch):
        import subprocess as rs
        mock = MagicMock(side_effect=rs.TimeoutExpired(cmd=["t"], timeout=600))
        monkeypatch.setattr("pipeline.runner.subprocess.run", mock)
        from pipeline.runner import run_cmd
        with pytest.raises(rs.TimeoutExpired):
            run_cmd(["t"], "timeout")

    def test_called_process_error_reraises(self, monkeypatch):
        import subprocess as rs
        mock = MagicMock(side_effect=rs.CalledProcessError(1, cmd=["t"]))
        monkeypatch.setattr("pipeline.runner.subprocess.run", mock)
        from pipeline.runner import run_cmd
        with pytest.raises(rs.CalledProcessError):
            run_cmd(["t"], "cpe")
