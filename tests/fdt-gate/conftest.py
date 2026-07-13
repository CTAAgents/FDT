"""fdt-gate auto-generated conftest"""
import pytest, os, sys
from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__, [])

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
