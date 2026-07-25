"""测试代码-推理边界硬切割函数。

覆盖：
- _compute_stop_target: stop_loss/target 精确计算（Phase 2）
- _clamp_position: 仓位钳制（Phase 3）
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 直接从 nodes.py 导入待测函数（避免 conftest mock 干扰）
from fdt_langgraph.nodes import (
    _clamp_position,
    _compute_stop_target,
)


# ══════════════════════════════════════════════════════
# _compute_stop_target 测试
# ══════════════════════════════════════════════════════

class TestComputeStopTarget:
    """Phase 2: stop_loss/target 代码精确计算。"""

    def test_bullish_standard(self):
        """多头：正常 ATR 值。"""
        stop, target = _compute_stop_target("bullish", 5000.0, 100.0)
        assert stop == 4850.0, f"Stop should be 5000-150=4850, got {stop}"
        assert target == 5200.0, f"Target should be 5000+200=5200, got {target}"

    def test_bearish_standard(self):
        """空头：正常 ATR 值。"""
        stop, target = _compute_stop_target("bearish", 5000.0, 100.0)
        assert stop == 5150.0, f"Stop should be 5000+150=5150, got {stop}"
        assert target == 4800.0, f"Target should be 5000-200=4800, got {target}"

    def test_neutral_no_stop_target(self):
        """neutral：返回 (0, 0)。"""
        stop, target = _compute_stop_target("neutral", 5000.0, 100.0)
        assert stop == 0.0
        assert target == 0.0

    @pytest.mark.parametrize("direction,entry,atr,exp_stop,exp_target", [
        ("long", 3000.0, 50.0, 2925.0, 3100.0),
        ("short", 3000.0, 50.0, 3075.0, 2900.0),
        ("buy", 4000.0, 80.0, 3880.0, 4160.0),
        ("sell", 4000.0, 80.0, 4120.0, 3840.0),
        ("BUY", 4000.0, 80.0, 3880.0, 4160.0),
        ("SELL", 4000.0, 80.0, 4120.0, 3840.0),
    ])
    def test_direction_aliases(self, direction, entry, atr, exp_stop, exp_target):
        """方向别名兼容性。"""
        stop, target = _compute_stop_target(direction, entry, atr)
        assert stop == exp_stop, f"{direction}: expected stop={exp_stop}, got {stop}"
        assert target == exp_target, f"{direction}: expected target={exp_target}, got {target}"

    def test_atr_none_fallback(self):
        """ATR 为 None 时使用百分比降级。"""
        stop, target = _compute_stop_target("bullish", 5000.0, None)
        # 降级: atr = 5000 * 0.01 = 50
        assert stop == 4925.0, f"ATR=None stop should be 5000-75=4925, got {stop}"
        assert target == 5100.0, f"ATR=None target should be 5000+100=5100, got {target}"

    def test_atr_zero_fallback(self):
        """ATR 为 0 时使用百分比降级。"""
        stop, target = _compute_stop_target("bullish", 5000.0, 0.0)
        assert stop == 4925.0, f"ATR=0 stop should be 4925, got {stop}"
        assert target == 5100.0, f"ATR=0 target should be 5100, got {target}"

    def test_custom_multipliers(self):
        """自定义乘数。"""
        stop, target = _compute_stop_target("bullish", 5000.0, 100.0,
                                            risk_multiplier=2.0, reward_multiplier=3.0)
        assert stop == 4800.0, f"Custom risk stop should be 5000-200=4800, got {stop}"
        assert target == 5300.0, f"Custom reward target should be 5000+300=5300, got {target}"

    def test_entry_zero(self):
        """入场价为 0 的特殊情况。"""
        stop, target = _compute_stop_target("bullish", 0.0, 100.0)
        assert stop == -150.0
        assert target == 200.0


# ══════════════════════════════════════════════════════
# _clamp_position 测试
# ══════════════════════════════════════════════════════

class TestClampPosition:
    """Phase 3: 仓位代码硬校验。"""

    def test_within_limit(self):
        """仓位在限额内，不钳制。"""
        result = _clamp_position("RB", 10.0)
        assert result == 10.0

    def test_exceeds_limit(self):
        """仓位超限，钳制到上限。"""
        result = _clamp_position("RB", 25.0)
        assert result == 20.0, f"25% should be clamped to 20%, got {result}"

    def test_exactly_at_limit(self):
        """仓位等于上限，不钳制。"""
        result = _clamp_position("RB", 20.0)
        assert result == 20.0

    def test_negative_llm_pct(self):
        """LLM 输出负值，钳制到最大值（min 会取 0）。"""
        result = _clamp_position("RB", -5.0)
        assert result == -5.0, "Negative values should pass through (clamp to max_single won't clamp)"

    def test_custom_max(self):
        """自定义上限。"""
        result = _clamp_position("RB", 15.0, max_single_pct=10.0)
        assert result == 10.0, f"15% with max=10% should be clamped to 10%, got {result}"

    def test_invalid_input_none(self):
        """None 输入，返回默认值 3%。"""
        result = _clamp_position("RB", None)
        assert result == 3.0, f"None should return 3%, got {result}"

    def test_invalid_input_string(self):
        """非法字符串输入，返回默认值 3%。"""
        result = _clamp_position("RB", "abc")
        assert result == 3.0, f"Invalid string should return 3%, got {result}"

    def test_zero_pct(self):
        """0% 通过。"""
        result = _clamp_position("RB", 0.0)
        assert result == 0.0

    def test_reproducibility(self):
        """相同输入产生相同输出。"""
        r1 = _clamp_position("RB", 12.5)
        r2 = _clamp_position("RB", 12.5)
        assert r1 == r2
