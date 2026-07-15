"""self-improve-enhanced auto-generated conftest"""
import pytest, os, sys
from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__, ["scripts"])

def sample_debate_results() -> dict:
    """Minimal but realistic debate_results.json for testing."""
    return {
        "scan": {
            "signals": [
                {"symbol": "RB", "signal_type": "channel_breakout",
                 "direction": "bull", "total": 76, "adx": 59.5}
            ]
        },
        "researchers": {
            "观澜": {"valid": True, "summary": "均线多头排列，RSI 62"},
            "探源": {"valid": True, "summary": "库存下降，基差走强"}
        },
        "debaters": {
            "多头": {
                "valid": True,
                "arguments": [
                    {"strategy": "F1", "text": "均线多头排列",
                     "impact": "HIGH", "confidence": 0.85}
                ]
            },
            "空头": {
                "valid": False,
                "arguments": [
                    {"strategy": "F1", "text": "ADX开始掉头",
                     "impact": "MEDIUM"}
                ],
                "validation_error": "confidence field type mismatch"
            }
        },
        "judge": {
            "reasoning": "多头信号强劲，ADX支撑趋势延续",
            "verdict": "bull",
            "confidence": 0.80
        }
    }


def sample_trajectory() -> list:
    """Pre-built trajectory for unit tests that don't need parsing."""
    return [
        {"step_id": "P1", "agent_role": "数技源", "action": "channel_breakout_scan",
         "observation": '[{"signal_type": "channel_breakout"}]', "reward": 1.0, "skill_used": "quant-daily"},
        {"step_id": "P3", "agent_role": "观澜", "action": "research",
         "observation": "均线多头排列", "reward": 1.0, "skill_used": "technical-analysis"},
        {"step_id": "P3", "agent_role": "探源", "action": "research",
         "observation": "库存下降", "reward": 1.0, "skill_used": "fundamental-data-collector"},
        {"step_id": "P4", "agent_role": "多头", "action": "argue",
         "observation": "[]", "reward": 1.0, "skill_used": "debate-argument-builder"},
        {"step_id": "P4", "agent_role": "空头", "action": "argue",
         "observation": '{"confidence": "str_instead_of_float", "type_error": true}',
         "reward": 0.0, "skill_used": "debate-argument-builder"},
        {"step_id": "P5_judge", "agent_role": "闫判官", "action": "verdict",
         "observation": "一致裁决多头", "reward": 1.0, "skill_used": "debate-judge"},
    ]


def sample_vibench_cases() -> list:
    """Minimal ViBench test cases."""
    return [
        {"symbol": "RB", "direction": "bull", "expected": 1,
         "pro_args": ["均线多头"], "con_args": ["ADX高位"]},
        {"symbol": "SC", "direction": "bear", "expected": -1,
         "pro_args": ["库存高企"], "con_args": ["地缘风险"]},
    ]
