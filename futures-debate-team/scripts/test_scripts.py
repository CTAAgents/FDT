"""
scripts/ 模块测试（技术债清理 — 测试覆盖率）
测试 fingerprint, memory_writer, attribution_analyzer, portfolio_risk, config_manager
"""

import sys, os, json, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from scripts.fingerprint import generate_fingerprint, apply_selection_gate, set_global_seed
from scripts.portfolio_risk import PortfolioRisk
from scripts.config_manager import ConfigManager


class TestFingerprint:
    def test_generate_fingerprint(self):
        fp = generate_fingerprint(
            strategy_params={"thresholds": [0.6]},
            seed=42,
        )
        assert fp.startswith("FDB_v")
        assert "seed42" in fp
        assert "md5_" in fp

    def test_generate_fingerprint_no_seed(self):
        fp = generate_fingerprint(strategy_params={})
        assert "_noseed" in fp

    def test_apply_selection_gate_passes(self):
        gate = apply_selection_gate(
            l1l4_data={"RB": {"confidence": 0.72, "direction": 1}},
            factor_data={"RB": {"total": 2.5, "vote_net": 4}},
            threshold=0.65,
        )
        assert "RB" in gate["selected"]
        assert len(gate["rejected"]) == 0

    def test_apply_selection_gate_rejects_low_confidence(self):
        gate = apply_selection_gate(
            l1l4_data={"PK": {"confidence": 0.55, "direction": -1}},
            factor_data={"PK": {"total": -1.2, "vote_net": -3}},
            threshold=0.65,
        )
        assert "PK" in gate["rejected"]

    def test_set_global_seed(self):
        import random

        set_global_seed(42)
        a = random.randint(0, 1000)
        set_global_seed(42)
        b = random.randint(0, 1000)
        assert a == b


class TestPortfolioRisk:
    def test_green_portfolio(self):
        positions = [{"symbol": "RB", "margin": 5000, "lots": 2, "direction": 1}]
        risk = PortfolioRisk(account_equity=100000)
        result = risk.calculate(positions, daily_pnl=0)
        assert result["overall"] == "green"
        assert not result["veto_debate"]

    def test_red_drawdown(self):
        positions = [{"symbol": "RB", "margin": 5000, "lots": 2, "direction": 1}]
        risk = PortfolioRisk(account_equity=100000)
        result = risk.calculate(positions, daily_pnl=-3000)
        assert not result["drawdown_ok"]
        assert result["veto_debate"]

    def test_concentration_breach(self):
        positions = [
            {"symbol": "RB", "margin": 20000, "lots": 10, "direction": 1},
            {"symbol": "HC", "margin": 15000, "lots": 8, "direction": 1},
        ]
        risk = PortfolioRisk(account_equity=100000)
        result = risk.calculate(positions)
        assert not result["concentration_ok"]

    def test_consecutive_loss(self):
        positions = [{"symbol": "RB", "margin": 5000, "lots": 2, "direction": 1}]
        risk = PortfolioRisk(account_equity=100000)
        result = risk.calculate(positions, consecutive_losses=5)
        assert not result["consecutive_ok"]


class TestConfigManager:
    def test_load_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "settings.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"mode": "paper", "selection_threshold": 0.7}, f)
            cfg = ConfigManager(cfg_path)
            assert cfg.get("mode") == "paper"
            assert cfg.get("selection_threshold") == 0.7

    def test_default_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "empty.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({}, f)
            cfg = ConfigManager(cfg_path)
            assert cfg.get("nonexistent", "fallback") == "fallback"

    def test_set_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "settings.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({}, f)
            cfg = ConfigManager(cfg_path)
            cfg.set("fee_rate", 0.001)
            assert cfg.get("fee_rate") == 0.001
            # 验证持久化
            cfg2 = ConfigManager(cfg_path)
            assert cfg2.get("fee_rate") == 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
