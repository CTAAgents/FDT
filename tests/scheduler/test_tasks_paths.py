"""
scheduler/tasks.py 路径解析回归测试
====================================
锁定 _project_root() 语义修复：返回 FDT_ROOT（futures-debate-team 包根），
而非此前的 scheduler/ 子目录。这是全文件路径一致性的根：
- _run_script(rel) 以 FDT_ROOT 为基准 join
- daily_debate 的 root/'skills'、root/'memory'
- validate_and_evolve / ml_training_check 的 'scripts/...'、'ml/...'
- 模块级 ALL_SYMBOL_CODES（line 59 config.symbols 加载）
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


class TestProjectRoot:
    def test_project_root_is_fdt_root(self):
        """_project_root() 应指向 FDT_ROOT（含 skills/ scripts/ ml/ pyproject.toml），非 scheduler/"""
        from scheduler.tasks import _project_root

        root = _project_root()
        assert root.name == "futures-debate-team"
        assert (root / "pyproject.toml").exists()
        assert (root / "skills").is_dir()
        assert (root / "scripts").is_dir()
        assert (root / "ml").is_dir()

    def test_run_script_targets_resolve(self):
        """所有 _run_script 调用的相对脚本路径应在 FDT_ROOT 下真实存在"""
        from scheduler.tasks import _project_root

        root = _project_root()
        rels = [
            "skills/quant-daily/scripts/scan_all.py",
            "skills/futures-trading-analysis/scripts/phase3_generate_report.py",
            "scripts/validate_verdicts.py",
            "scripts/calibrate_weights.py",
            "scripts/evolve_agents.py",
            "ml/trainer.py",
            "scripts/self_improve.py",
            "scripts/skillevolver_evolution.py",
            "scripts/verify_evolution.py",
        ]
        missing = [r for r in rels if not (root / r).exists()]
        assert not missing, f"未解析到（_project_root 语义错？）: {missing}"

    def test_symbols_loaded(self):
        """line 59: config.symbols 应正确加载品种代码（路径正确的直接证据）"""
        from scheduler.tasks import ALL_SYMBOL_CODES

        assert isinstance(ALL_SYMBOL_CODES, list)
        assert len(ALL_SYMBOL_CODES) >= 60  # 约 63 品种


class TestRunScriptGuard:
    def test_missing_script_returns_false(self):
        """_run_script 对不存在脚本优雅返回 (False, 含'不存在')"""
        from scheduler.tasks import _run_script

        ok, msg = _run_script("nonexistent/__no_such__.py", timeout=5)
        assert ok is False
        assert "不存在" in msg

    def test_absolute_path_accepted(self):
        """_run_script 对 FDT 包外绝对路径（如 quant-bare sync）应能识别其存在性
        （pathlib root/abs = abs），不因 join 语义崩溃"""
        from scheduler.tasks import _run_script

        # 一个必不存在的绝对路径 → 走 not exists 分支，返回 False+提示，不抛异常
        ok, msg = _run_script("C:/__definitely_not_here__/sync.py", timeout=5)
        assert ok is False
        assert "不存在" in msg
