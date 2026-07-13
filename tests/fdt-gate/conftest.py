"""fdt-gate auto-generated conftest"""
import pytest, os, sys, importlib
from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__, [])

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    mods = {}
    for name, rel in FILE_MAP.items():
        try:
            mods[name] = _load(name, rel)
        except Exception:
            pass
    # 清理所有被加载的 scripts.* 模块，避免污染其他测试
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("scripts.") or mod_name in ("scheduler.triggers",):
            sys.modules.pop(mod_name, None)
    return mods


@pytest.fixture(scope="module")
def clamped(modules):
    import copy, json
    from pathlib import Path
    fu = json.loads(
        (Path(PROJECT_ROOT) / "memory" / "execution_followup.json").read_text(encoding="utf-8")
    )
    verdicts = []
    for r in fu["records"]:
        if "verdicts" in r:
            if isinstance(r["verdicts"], list):
                verdicts.extend(r["verdicts"])
            else:
                verdicts.append(r["verdicts"])
    before = modules["apm_scorecard"].RuleChecker().check_all(verdicts)
    _chg, fu2 = modules["enforce_discipline"].clamp_verdicts(copy.deepcopy(fu))
    verdicts2 = []
    for r in fu2["records"]:
        if "verdicts" in r:
            if isinstance(r["verdicts"], list):
                verdicts2.extend(r["verdicts"])
            else:
                verdicts2.append(r["verdicts"])
    after = modules["apm_scorecard"].RuleChecker().check_all(verdicts2)
    return before, after
