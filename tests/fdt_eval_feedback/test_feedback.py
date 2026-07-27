"""
Tests for fdt_eval.feedback — ConfigStore, PositionTuner, ParameterTuner.

Running:
    python -m pytest tests/fdt_eval_feedback/test_feedback.py -v
"""
from __future__ import annotations

import json
import math

import pytest

from fdt_eval.feedback.config_store import ConfigStore, SymbolConfig, FeedbackConfig
from fdt_eval.feedback.position_tuner import PositionTuner, PositionAdjustment
from fdt_eval.feedback.parameter_tuner import ParameterTuner, ParameterCalibration


# ============================================================================
# TestConfigStore
# ============================================================================

class TestConfigStore:
    """ConfigStore — 品种参数持久化存储测试。"""

    def test_default_config(self, tmp_path):
        """新 ConfigStore 对未知品种返回默认 SymbolConfig。"""
        store = ConfigStore(path=tmp_path / "test_config.json")
        cfg = store.get("UNKNOWN")
        assert isinstance(cfg, SymbolConfig)
        assert cfg.position_base_pct == 3.0
        assert cfg.position_weight == 1.0
        assert cfg.atr_stop_multiplier == 2.0
        assert cfg.atr_target_multiplier == 3.0
        assert cfg.confidence_offset == 0.0
        assert cfg.min_accuracy == 0.0
        assert cfg.n_validations == 0
        assert cfg.recent_accuracy == 0.0

    def test_update_symbol(self, tmp_path):
        """更新品种权重后再次读取可验证持久化。"""
        store = ConfigStore(path=tmp_path / "test_config.json")
        store.update("rb8888", position_weight=1.8, recent_accuracy=0.75)

        cfg = store.get("rb8888")
        assert cfg.position_weight == 1.8
        assert cfg.recent_accuracy == 0.75

        # 再次读取同一文件验证持久化
        store2 = ConfigStore(path=tmp_path / "test_config.json")
        cfg2 = store2.get("rb8888")
        assert cfg2.position_weight == 1.8
        assert cfg2.recent_accuracy == 0.75
        # version 已在 update 中自增
        assert cfg2.version > 1

    def test_get_position_pct(self, tmp_path):
        """验证仓位计算公式: base_pct * weight * conf_factor。"""
        store = ConfigStore(path=tmp_path / "test_config.json")

        # 默认: base_pct=3.0, weight=1.0, offset=0.0
        # conf >= 0.7 → factor=1.0
        pct = store.get_position_pct("ANY", base_confidence=0.7)
        assert math.isclose(pct, 3.0, rel_tol=1e-3), f"expected 3.0, got {pct}"

        # conf 0.4-0.7 → factor=0.5  →  3.0 * 1.0 * 0.5 = 1.5
        pct = store.get_position_pct("ANY", base_confidence=0.5)
        assert math.isclose(pct, 1.5, rel_tol=1e-3), f"expected 1.5, got {pct}"

        # conf < 0.4 → factor=0.25 →  3.0 * 1.0 * 0.25 = 0.75 → clamped to 1.0
        pct = store.get_position_pct("ANY", base_confidence=0.3)
        assert math.isclose(pct, 1.0, rel_tol=1e-3), f"expected 1.0, got {pct}"

    def test_get_position_pct_with_fallback(self, tmp_path):
        """ConfigStore 禁用时返回 position_base_pct。"""
        store = ConfigStore(path=tmp_path / "test_config.json")
        store._global.enabled = False

        pct = store.get_position_pct("ANY", base_confidence=0.5)
        assert math.isclose(pct, 3.0, rel_tol=1e-3), f"expected 3.0, got {pct}"

    def test_get_stop_params(self, tmp_path):
        """验证 ATR 止损/目标距离计算。"""
        store = ConfigStore(path=tmp_path / "test_config.json")
        # 默认: atr_stop_multiplier=2.0, atr_target_multiplier=3.0
        stop_dist, target_dist = store.get_stop_params("ANY", atr=10.0)
        assert math.isclose(stop_dist, 20.0, rel_tol=1e-3), f"expected 20.0, got {stop_dist}"
        assert math.isclose(target_dist, 30.0, rel_tol=1e-3), f"expected 30.0, got {target_dist}"

    def test_get_effective_confidence(self, tmp_path):
        """验证 confidence_offset 正确应用于置信度。"""
        store = ConfigStore(path=tmp_path / "test_config.json")

        # 默认 offset=0.0 → 无变化
        eff = store.get_effective_confidence("ANY", 0.7)
        assert math.isclose(eff, 0.7, rel_tol=1e-3)

        # 正向偏移
        store.update("TEST", confidence_offset=0.2)
        eff = store.get_effective_confidence("TEST", 0.5)
        assert math.isclose(eff, 0.7, rel_tol=1e-3)

        # 负向偏移
        store.update("TEST", confidence_offset=-0.3)
        eff = store.get_effective_confidence("TEST", 0.8)
        assert math.isclose(eff, 0.5, rel_tol=1e-3)

    def test_save_and_load(self, tmp_path):
        """保存配置到临时文件，重新加载后验证值一致。"""
        path = tmp_path / "save_load.json"
        store = ConfigStore(path=path)

        store.update("AG", position_weight=1.5, atr_stop_multiplier=2.5, confidence_offset=-0.1)
        store.update("CU", position_weight=0.5, atr_target_multiplier=4.0)
        store.save()

        # 新 ConfigStore 加载同一文件
        store2 = ConfigStore(path=path)
        cfg_ag = store2.get("AG")
        assert cfg_ag.position_weight == 1.5
        assert cfg_ag.atr_stop_multiplier == 2.5
        assert cfg_ag.confidence_offset == -0.1

        cfg_cu = store2.get("CU")
        assert cfg_cu.position_weight == 0.5
        assert cfg_cu.atr_target_multiplier == 4.0


# ============================================================================
# TestPositionTuner
# ============================================================================

class TestPositionTuner:
    """PositionTuner — 仓位调优器测试。"""

    def _make_stats_json(self, path, data: dict):
        """写入 mock validation_stats.json (by_symbol 格式)。"""
        path.write_text(json.dumps({"by_symbol": data}, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_accuracy_high_weight(self, tmp_path):
        """准确率 80% → 权重升至 1.5。"""
        stats_path = tmp_path / "validation_stats.json"
        self._make_stats_json(stats_path, {
            "RB": {"total": 10, "correct": 8, "wrong": 2},
        })
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=stats_path)

        assert len(adjustments) == 1
        adj = adjustments[0]
        assert adj.symbol == "RB"
        assert adj.accuracy == 0.8
        assert adj.new_weight == 1.5
        assert adj.direction == "up"

    def test_accuracy_low_weight(self, tmp_path):
        """准确率 30% → 权重降至 0.5。"""
        stats_path = tmp_path / "validation_stats.json"
        self._make_stats_json(stats_path, {
            "RB": {"total": 10, "correct": 3, "wrong": 7},
        })
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=stats_path)

        assert len(adjustments) == 1
        adj = adjustments[0]
        assert adj.accuracy == 0.3
        assert adj.new_weight == 0.5
        assert adj.direction == "down"

    def test_accuracy_too_low_weight(self, tmp_path):
        """准确率 20% → 权重降至最低 0.3。"""
        stats_path = tmp_path / "validation_stats.json"
        self._make_stats_json(stats_path, {
            "RB": {"total": 10, "correct": 2, "wrong": 8},
        })
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=stats_path)

        assert len(adjustments) == 1
        adj = adjustments[0]
        assert adj.accuracy == 0.2
        assert adj.new_weight == 0.3
        assert adj.direction == "down"

    def test_accuracy_very_high_weight(self, tmp_path):
        """准确率 90% → 权重升至 2.0。"""
        stats_path = tmp_path / "validation_stats.json"
        self._make_stats_json(stats_path, {
            "RB": {"total": 10, "correct": 9, "wrong": 1},
        })
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=stats_path)

        assert len(adjustments) == 1
        adj = adjustments[0]
        assert adj.accuracy == 0.9
        assert adj.new_weight == 2.0
        assert adj.direction == "up"

    def test_insufficient_samples(self, tmp_path):
        """样本不足 min_samples(3) → 不调整。"""
        stats_path = tmp_path / "validation_stats.json"
        self._make_stats_json(stats_path, {
            "RB": {"total": 2, "correct": 2, "wrong": 0},
        })
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=stats_path)

        assert len(adjustments) == 0, "less than min_samples should produce no adjustments"

    def test_no_stats_file(self, tmp_path):
        """验证统计文件不存在 → 返回空列表。"""
        store = ConfigStore(path=tmp_path / "config.json")
        tuner = PositionTuner(config_store=store)
        adjustments = tuner.tune(stats_path=tmp_path / "nonexistent.json")

        assert adjustments == []


# ============================================================================
# TestParameterTuner
# ============================================================================

class TestParameterTuner:
    """ParameterTuner — 参数调优器测试。"""

    def _make_followup_json(self, path, rounds: list):
        """写入 mock execution_followup.json。每个 round 是 dict，含 results 列表。"""
        path.write_text(
            json.dumps({"rounds": rounds}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_confidence_bias(self, tmp_path):
        """平均置信度 0.8、准确率 0.5 → bias=0.3 → offset=-0.3。"""
        followup_path = tmp_path / "execution_followup.json"
        rounds = [
            {
                "results": [
                    {"symbol": "RB", "confidence": 0.8, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.8, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.8, "correct": False,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.8, "correct": False,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.8, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                ],
            },
        ]
        # n=5, avg_conf=0.8, correct=3 → accuracy=0.6 → bias=0.2
        # Let me recalculate: corrects=[1,1,0,0,1] → sum=3, avg=3/5=0.6
        # bias = 0.8 - 0.6 = 0.2 → offset = -0.2
        self._make_followup_json(followup_path, rounds)

        store = ConfigStore(path=tmp_path / "config.json")
        tuner = ParameterTuner(config_store=store)
        calibrations = tuner.tune(followup_path=followup_path)

        assert len(calibrations) == 1
        cal = calibrations[0]
        assert cal.symbol == "RB"
        # avg_conf=0.8, accuracy=0.6 → bias=0.2 → offset=-0.2
        assert cal.confidence_bias == 0.2
        assert cal.confidence_offset == -0.2

    def test_stop_multiplier_increase(self, tmp_path):
        """止损触发率 > 0.4 → ATR 止损乘数提升 1.2 倍。"""
        followup_path = tmp_path / "execution_followup.json"
        # 5 samples, 3 hit_stop → stop_hit_rate=0.6 > 0.4
        rounds = [
            {
                "results": [
                    {"symbol": "RB", "confidence": 0.5, "correct": True,
                     "hit_stop": True, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.5, "correct": True,
                     "hit_stop": True, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.5, "correct": False,
                     "hit_stop": True, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.5, "correct": False,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.5, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                ],
            },
        ]
        self._make_followup_json(followup_path, rounds)

        store = ConfigStore(path=tmp_path / "config.json")
        tuner = ParameterTuner(config_store=store)
        calibrations = tuner.tune(followup_path=followup_path)

        assert len(calibrations) == 1
        cal = calibrations[0]
        # 默认 atr_stop_multiplier=2.0 → *1.2 = 2.4
        assert cal.new_stop_mult == 2.4
        assert cal.changes_applied is True

    def test_no_changes(self, tmp_path):
        """稳定数据 → 无参数变化。

        确保以下条件同时成立:
          - avg_conf == accuracy → bias=0 → offset=0
          - stop_hit_rate ∈ (0.1, 0.4] → 不变
          - target_hit_rate ∈ [0.2, 0.5] → 不变
        """
        followup_path = tmp_path / "execution_followup.json"
        # 5 个样本: conf=0.6, 3 correct → accuracy=0.6, bias=0
        # hit_stop=1/5=0.2 → 不变; hit_target=1/5=0.2 → 不变
        rounds = [
            {
                "results": [
                    {"symbol": "RB", "confidence": 0.6, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.6, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": True},
                    {"symbol": "RB", "confidence": 0.6, "correct": True,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.6, "correct": False,
                     "hit_stop": True, "hit_target1": False, "hit_target2": False},
                    {"symbol": "RB", "confidence": 0.6, "correct": False,
                     "hit_stop": False, "hit_target1": False, "hit_target2": False},
                ],
            },
        ]
        self._make_followup_json(followup_path, rounds)

        store = ConfigStore(path=tmp_path / "config.json")
        tuner = ParameterTuner(config_store=store)
        calibrations = tuner.tune(followup_path=followup_path)

        assert len(calibrations) == 1
        cal = calibrations[0]
        assert cal.confidence_offset == 0.0  # bias=0
        assert cal.new_stop_mult == 2.0       # stop 不变
        assert cal.new_target_mult == 3.0     # target 不变
        assert cal.changes_applied is False
