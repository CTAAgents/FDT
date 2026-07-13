"""quant-daily auto-generated conftest"""
import pytest, os, sys
from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__, ['skills/quant-daily/scripts'], ['skills/quant-daily/scripts/signals'])
@pytest.fixture
def sample_l1l4_entry():
    return {
        "total": 76,
        "direction": "bull",
        "grade": "A",
        "adx": 59.5,
        "rsi": 27.7,
        "cci": 180,
        "ma_slope": 0.8,
        "macd_cross": "golden",
        "dc20_break": "up",
        "ma_align": "bull",
        "stage": "launch",
        "cons": 3,
        "veto": 0,
        "l1": 25,
        "l2": 20,
        "l3": 18,
        "l4": 13,
        "z_score": 2.3,
        "volume": 85000,
    }


@pytest.fixture
def sample_factor_entry():
    return {
        "total": -45,
        "direction": "bear",
        "grade": "B",
        "vote_net": -3,
        "vote_confidence": -0.65,
        "g_group": "G10",
        "ts_type": "contango",
        "ts_slope": -0.3,
        "resonance": -0.7,
        "market_state": "trending",
        "adx": 35.0,
        "stage": "quiet",
        "cons": 2,
        "veto": 0,
        "l1": -15,
        "l2": -10,
        "l3": -12,
        "l4": -8,
    }


@pytest.fixture
def sample_symbol_entry(sample_l1l4_entry, sample_factor_entry):
    return {
        "symbol": "RB",
        "name": "螺纹钢",
        "l1l4": sample_l1l4_entry,
        "factor_timing": sample_factor_entry,
        "risk_input": {
            "ATR": {"value": 45.2, "period": 14},
            "confidence": 72,
            "adx": 59.5,
            "direction_conflict": True,
            "l1l4_direction": "bull",
            "factor_direction": "bear",
            "pattern_risk": "ADX极端但一致性低 | RSI极端(27.7)",
            "invalid_condition": "日线多头方向ADX59.5强趋势",
        },
    }


@pytest.fixture
def sample_chain_map():
    return {
        "RB": "黑色链",
        "HC": "黑色链",
        "I": "黑色链",
        "SC": "能化系",
        "TA": "聚酯系",
        "AU": "贵金属",
        "CU": "有色金属",
    }


@pytest.fixture
def temp_history_dir():
    d = tempfile.mkdtemp()
    old = os.environ.get("DEBATE_HISTORY_DIR")
    os.environ["DEBATE_HISTORY_DIR"] = d
    yield d
    if old:
        os.environ["DEBATE_HISTORY_DIR"] = old
    else:
        os.environ.pop("DEBATE_HISTORY_DIR", None)
    shutil.rmtree(d, ignore_errors=True)
