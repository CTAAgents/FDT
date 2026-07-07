"""FDT 质量门禁测试配置 (2026-07-07 改动集)

与团队其它测试目录一致的约定：
  - 通过 PROJECT_ROOT 推导（tests/<dir> → tests → futures-debate-team）
  - 把 scripts/ 与 PROJECT_ROOT 注入 sys.path，使 `from scripts.xxx` 与
    `from scheduler.triggers` 均可解析
  - 用 importlib 动态加载被测模块，规避 run_benchmark 顶层 `from replay_harness import`
    之类的相对导入副作用
"""

import os
import sys
import importlib.util
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
for _p in (SCRIPTS_DIR, PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 2026-07-07 新增/修改的被测模块
FILE_MAP = {
    "apm_scorecard": "scripts/apm_scorecard.py",
    "enforce_discipline": "scripts/enforce_discipline.py",
    "self_improve": "scripts/self_improve.py",
    "memory_writer": "scripts/memory_writer.py",
    "triggers": "scheduler/triggers.py",
    "replay_harness": "scripts/replay_harness.py",
    "run_benchmark": "scripts/run_benchmark.py",
}


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PROJECT_ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def modules():
    """尽最大努力导入所有被测模块；失败的模块不抛出，交由测试用例断言。"""
    mods = {}
    for name, rel in FILE_MAP.items():
        try:
            mods[name] = _load(name, rel)
        except Exception:
            pass
    return mods


@pytest.fixture(scope="module")
def clamped(modules):
    """加载真实生产 followup，钳制前后各跑一次 RuleChecker，供 G4/G2 复用。"""
    import copy
    import json
    from pathlib import Path

    fu = json.loads(
        (Path(PROJECT_ROOT) / "memory" / "execution_followup.json").read_text(encoding="utf-8")
    )
    verdicts = [v for r in fu["records"] for v in r["verdicts"]]
    before = modules["apm_scorecard"].RuleChecker().check_all(verdicts)
    _chg, fu2 = modules["enforce_discipline"].clamp_verdicts(copy.deepcopy(fu))
    verdicts2 = [v for r in fu2["records"] for v in r["verdicts"]]
    after = modules["apm_scorecard"].RuleChecker().check_all(verdicts2)
    return before, after
