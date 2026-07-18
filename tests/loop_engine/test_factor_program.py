"""tests/loop_engine/test_factor_program.py — 因子程序接口测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from loop_engine.contracts import EconomicLogic, FactorSignature
from loop_engine.factor_program import (
    ALLOWED_IMPORTS,
    FORBIDDEN_MODULES,
    FORBIDDEN_NAMES,
    FactorCompileError,
    FactorExecutor,
    create_factor_program,
    generate_factor_id,
    validate_factor_code,
)


# ─── 因子 ID 生成 ─────────────────────────────────────────

def test_generate_factor_id_format():
    """因子 ID 必须符合 fct_<8hex> 格式。"""
    fid = generate_factor_id("test", "def f(): pass")
    assert fid.startswith("fct_")
    assert len(fid) == 12  # fct_ + 8 hex


def test_generate_factor_id_uniqueness():
    """同名同代码的两次调用应产生不同 ID（时间戳参与哈希）。"""
    id1 = generate_factor_id("test", "code")
    id2 = generate_factor_id("test", "code")
    # 高概率不同（依赖 time.time_ns）
    assert id1 != id2


# ─── 代码安全沙箱 ─────────────────────────────────────────

def test_validate_valid_code():
    code = """
import numpy as np
def factor_program(data, params):
    close = data['close'].values
    return np.zeros(len(close))
"""
    ok, reasons = validate_factor_code(code)
    assert ok, f"应通过: {reasons}"


def test_validate_missing_factor_function():
    code = "x = 1"
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("factor_program" in r for r in reasons)


def test_validate_wrong_signature():
    code = "def factor_program(data): return data"
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("参数" in r for r in reasons)


def test_validate_forbidden_import_os():
    code = """
import os
def factor_program(data, params):
    return data['close'].values
"""
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("os" in r for r in reasons)


def test_validate_forbidden_import_subprocess():
    code = """
import subprocess
def factor_program(data, params):
    return data['close'].values
"""
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("subprocess" in r for r in reasons)


def test_validate_forbidden_eval_call():
    code = """
def factor_program(data, params):
    eval("1+1")
    return data['close'].values
"""
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("eval" in r for r in reasons)


def test_validate_forbidden_open_call():
    code = """
def factor_program(data, params):
    f = open('/etc/passwd')
    return data['close'].values
"""
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("open" in r for r in reasons)


def test_validate_syntax_error():
    code = "def factor_program(data, params\n  return"
    ok, reasons = validate_factor_code(code)
    assert not ok
    assert any("语法" in r for r in reasons)


# ─── 因子执行 ─────────────────────────────────────────────

def test_executor_compile_and_run(sample_ohlcv):
    """可执行因子程序应能编译并返回 ndarray。"""
    code = """
import numpy as np
def factor_program(data, params):
    return np.zeros(len(data['close']))
"""
    fp = create_factor_program(
        name="test_zero",
        code=code,
        params={},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
        economic_logic=EconomicLogic(theory=3, behavioral=3, microstructure=3, institutional=3, narrative="测试"),
        source="manual",
    )
    executor = FactorExecutor(fp)
    result = executor.execute(sample_ohlcv, {})
    assert isinstance(result, np.ndarray)
    assert len(result) == len(sample_ohlcv)


def test_executor_reject_invalid_code():
    """无效代码应抛 FactorCompileError。"""
    fp = create_factor_program(
        name="invalid",
        code="def wrong_name(data, params): return None",
        params={},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
        economic_logic=EconomicLogic(theory=3, behavioral=3, microstructure=3, institutional=3, narrative="测试"),
        source="manual",
    )
    with pytest.raises(FactorCompileError):
        FactorExecutor(fp).compile()


def test_executor_reject_non_ndarray_output(sample_ohlcv):
    """输出非 ndarray 应抛 FactorCompileError。"""
    code = """
def factor_program(data, params):
    return [0, 0, 0]
"""
    fp = create_factor_program(
        name="bad_output",
        code=code,
        params={},
        signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
        economic_logic=EconomicLogic(theory=3, behavioral=3, microstructure=3, institutional=3, narrative="测试"),
        source="manual",
    )
    executor = FactorExecutor(fp)
    with pytest.raises(FactorCompileError):
        executor.execute(sample_ohlcv, {})


def test_create_factor_program_rejects_empty_narrative():
    """economic_logic.narrative 不能为空。"""
    with pytest.raises(ValueError):
        create_factor_program(
            name="bad",
            code="def factor_program(d,p): return d['close'].values",
            params={},
            signature=FactorSignature(input_fields=["close"], output_type="signal", frequency="daily", lookback=1),
            economic_logic=EconomicLogic(theory=3, behavioral=3, microstructure=3, institutional=3, narrative=""),
            source="manual",
        )


def test_allowed_imports_includes_numpy():
    assert "numpy" in ALLOWED_IMPORTS
    assert "np" in ALLOWED_IMPORTS


def test_forbidden_modules_includes_os_subprocess():
    assert "os" in FORBIDDEN_MODULES
    assert "subprocess" in FORBIDDEN_MODULES
    assert "sys" in FORBIDDEN_MODULES


def test_forbidden_names_includes_eval_open():
    assert "eval" in FORBIDDEN_NAMES
    assert "open" in FORBIDDEN_NAMES
    assert "exec" in FORBIDDEN_NAMES
