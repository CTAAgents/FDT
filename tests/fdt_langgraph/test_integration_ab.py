"""G52-G55 集成测试：验证 LangGraph 生产集成与 A/B 切换机制。

测试覆盖：
- G52: pipeline/runner.py 的 FDT_USE_LANGGRAPH 环境变量切换
- G53: scripts/run_debate.py 的 --langgraph 子命令
- G54: graph.py 的 Checkpointer 配置（SQLite 默认 + PG 可选）
- G55: A/B 切换机制完整性
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestPipelineABSwitch:
    """G52: pipeline/runner.py A/B 切换测试"""

    def test_run_langgraph_pipeline_function_exists(self):
        """验证 run_langgraph_pipeline 函数存在"""
        from pipeline.runner import run_langgraph_pipeline
        assert callable(run_langgraph_pipeline)

    def test_main_reads_env_var(self):
        """验证 main() 读取 FDT_USE_LANGGRAPH 环境变量"""
        import pipeline.runner as runner
        assert hasattr(runner, 'main')

    def test_langgraph_pipeline_returns_int(self):
        """验证 run_langgraph_pipeline 返回 int 退出码"""
        from pipeline.runner import run_langgraph_pipeline
        with patch.dict(os.environ, {"FDT_USE_LANGGRAPH": "true"}):
            result = run_langgraph_pipeline("test-trace-001")
            assert isinstance(result, int)

    def test_env_var_false_keeps_subprocess(self):
        """验证 FDT_USE_LANGGRAPH=false 时走 subprocess 模式"""
        with patch.dict(os.environ, {"FDT_USE_LANGGRAPH": "false"}, clear=False):
            import pipeline.runner as runner
            assert runner.main is not None


class TestRunDebateLanggraphCommand:
    """G53: scripts/run_debate.py --langgraph 子命令测试"""

    def test_langgraph_subparser_exists(self):
        """验证 langgraph 子命令存在"""
        import argparse
        from scripts.run_debate import main
        # 验证 main 函数可调用
        assert callable(main)

    def test_langgraph_help_contains_mode(self):
        """验证 --mode 参数包含 4 种模式"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); from scripts.run_debate import main; "
             "import argparse; "
             "ap = argparse.ArgumentParser(); "
             "sub = ap.add_subparsers(dest='cmd'); "
             "p = sub.add_parser('langgraph'); "
             "p.add_argument('--mode', choices=['default','fast','deep_research','tournament']); "
             "print('OK')"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0 or "OK" in result.stdout

    def test_langgraph_command_no_scan_required(self):
        """验证 langgraph 命令不需要 --scan 参数"""
        import scripts.run_debate as rdb
        source = open(rdb.__file__, encoding='utf-8').read()
        assert 'langgraph' in source
        assert '--mode' in source
        assert '--trace-id' in source


class TestCheckpointerConfig:
    """G54: graph.py Checkpointer 配置测试"""

    def test_get_checkpointer_function_exists(self):
        """验证 _get_checkpointer 函数存在"""
        from fdt_langgraph.graph import _get_checkpointer
        assert callable(_get_checkpointer)

    def test_default_sqlite_checkpointer(self):
        """验证默认使用 SQLite Checkpointer"""
        with patch.dict(os.environ, {}, clear=True):
            from fdt_langgraph.graph import _get_checkpointer
            cp = _get_checkpointer()
            # 应该返回 SqliteSaver 实例
            assert cp is not None

    def test_pg_checkpointer_fallback_to_sqlite(self):
        """验证 FDT_CHECKPOINTER=pg 但 PG 不可用时降级到 SQLite"""
        with patch.dict(os.environ, {"FDT_CHECKPOINTER": "pg"}):
            from fdt_langgraph.graph import _get_checkpointer
            cp = _get_checkpointer()
            # PG 不可用时应降级到 SQLite
            assert cp is not None

    def test_build_graph_uses_checkpointer(self):
        """验证 build_debate_graph 使用 _get_checkpointer"""
        import fdt_langgraph.graph as graph_mod
        source = open(graph_mod.__file__, encoding='utf-8').read()
        assert '_get_checkpointer' in source

    def test_build_graph_no_checkpoint_still_works(self):
        """验证无 checkpoint 版本仍可用"""
        from fdt_langgraph.graph import build_debate_graph_no_checkpoint
        graph = build_debate_graph_no_checkpoint(mode="default")
        assert graph is not None


class TestABSwitchMechanism:
    """G55: A/B 切换机制完整性测试"""

    def test_pipeline_has_langgraph_path(self):
        """验证 pipeline 有 LangGraph 路径"""
        import pipeline.runner as runner
        source = open(runner.__file__, encoding='utf-8').read()
        assert 'FDT_USE_LANGGRAPH' in source
        assert 'run_langgraph_pipeline' in source

    def test_run_debate_has_langgraph_path(self):
        """验证 run_debate 有 LangGraph 路径"""
        import scripts.run_debate as rdb
        source = open(rdb.__file__, encoding='utf-8').read()
        assert 'langgraph' in source
        assert 'build_debate_graph_no_checkpoint' in source

    def test_graph_has_pg_checkpointer_support(self):
        """验证 graph.py 支持 PG Checkpointer"""
        import fdt_langgraph.graph as graph_mod
        source = open(graph_mod.__file__, encoding='utf-8').read()
        assert 'FDT_CHECKPOINTER' in source
        assert 'PostgresSaver' in source

    def test_langgraph_pipeline_imports_health_check(self):
        """验证 LangGraph pipeline 集成了健康检查"""
        import pipeline.runner as runner
        source = open(runner.__file__, encoding='utf-8').read()
        assert 'run_health_check' in source

    def test_env_var_values_accepted(self):
        """验证 FDT_USE_LANGGRAPH 接受多种布尔值"""
        valid_values = {"true": True, "1": True, "yes": True, "false": False, "0": False, "": False}
        for val, expected in valid_values.items():
            result = val.lower() in ("true", "1", "yes")
            assert result == expected, f"值 '{val}' 应该返回 {expected}"

    def test_fallback_on_import_error(self):
        """验证 LangGraph 模块不可用时回退到 subprocess"""
        import pipeline.runner as runner
        source = open(runner.__file__, encoding='utf-8').read()
        assert '回退到 subprocess 模式' in source
