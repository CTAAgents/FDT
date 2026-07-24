"""边缘情况与集成测试 — 针对覆盖率报告中缺失行"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "quant-daily", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# 清除 scripts 缓存，确保从已设置的 sys.path 加载
if "scripts" in sys.modules:
    del sys.modules["scripts"]
for k in list(sys.modules.keys()):
    if k.startswith("scripts."):
        del sys.modules[k]

import numpy as np
from signals import debate_brief as db

from debate import history as dh
from ml import trainer as ato

# ═══════════════════════════════════════════════════════════
# debate_history.py 覆盖缺口 (90% → 目标 95%+)
# ═══════════════════════════════════════════════════════════


class TestDebateHistoryGaps:
    def test_record_ioerror_on_records(self, temp_history_dir):
        """record_feedback 写入records文件IO异常"""
        with patch("builtins.open") as mock_open:
            mock_open.side_effect = IOError("disk full")
            # 不应该抛出异常
            dh.record_feedback("RB", 80, 80, outcome="win")

    def test_record_ioerror_on_summary(self, temp_history_dir):
        """record_feedback 写入summary文件IO异常"""
        # 先让records写入成功，summary写入失败
        real_open = __builtins__["open"] if isinstance(__builtins__, dict) else open
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            if call_count[0] >= 2:  # 第二次open = summary
                raise IOError("disk full")
            return real_open(*a, **kw)

        with patch("builtins.open", side_effect=side_effect):
            dh.record_feedback("SC", 70, 70)

    def test_get_recent_records_ioerror(self, temp_history_dir):
        """get_recent_records 读取异常"""
        with patch("builtins.open") as mock_open:
            mock_open.side_effect = IOError("read error")
            assert dh.get_recent_records() == []

    def test_clear_history_ioerror(self, temp_history_dir):
        """clear_history IO异常"""
        with patch("os.remove") as mock_remove:
            mock_remove.side_effect = IOError("remove failed")
            dh.clear_history()  # 不应抛出异常

    def test_load_feedback_ioerror(self, temp_history_dir):
        """load_feedback 读取总结文件IO异常"""
        # 先通过直接写入模拟数据
        import builtins

        real_open = builtins.open
        call_count = [0]

        def mock_file(*args, **kwargs):
            call_count[0] += 1
            # 仅让读取summary文件失败
            if "debate_feedback" in str(args[0]):
                raise IOError("read error")
            return real_open(*args, **kwargs)

        with patch("builtins.open", mock_file):
            fb = dh.load_feedback()
            assert fb == {}


# ═══════════════════════════════════════════════════════════
# auto_train_orchestrator.py 覆盖缺口 (84% → 目标 90%+)
# ═══════════════════════════════════════════════════════════


class TestAutoTrainGaps:
    def test_check_time_naive_datetime(self, tmp_path):
        """check_conditions 使用naive datetime覆盖tzinfo处理"""
        from datetime import datetime, timedelta

        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), max_days_since_train=3)
        st = o._load_state()
        # 使用不含tzinfo的ISO字符串
        st["last_train_date"] = (datetime.now() - timedelta(days=10)).isoformat()
        st["total_trained"] = 1
        o._save_state(st)
        c = o.check_conditions(0)
        assert any("距上次训练" in x for x in c)

    def test_xgboost_validation_metrics(self, tmp_path):
        """XGBoost带验证集的metric路径"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        np.random.seed(42)
        X = np.random.rand(30, 5)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        r = o.run_incremental_train(X[:20], y[:20], X[20:], y[20:], model_type="xgboost", force=True)
        assert r["success"]
        assert "auc" in r.get("metrics", {})

    def test_lightgbm_no_validation(self, tmp_path):
        """LightGBM 无验证集"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        X = np.random.rand(15, 5)
        y = (X[:, 0] > 0.5).astype(int)
        r = o.run_incremental_train(X, y, model_type="lightgbm", force=True)
        assert r["success"]

    def test_train_with_none_data(self, tmp_path):
        """传入None训练数据"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=3)
        # force=False, no X → should return False
        r = o.run_incremental_train(None, None, force=False)
        assert r["success"] is False

    def test_deploy_no_candidate(self, tmp_path):
        """部署时候选模型不存在"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        dummy_result = {"metrics": {}, "model_path": "/nonexistent/model.pkl"}
        r = o.deploy_model(dummy_result, {"decision": "deploy"})
        assert r["success"] is False

    def test_dispute_predictor_train_with_history(self, tmp_path):
        """DisputePredictor带历史反馈训练"""
        dp = ato.DisputePredictor(model_path=str(tmp_path / "dp.pkl"))
        np.random.seed(42)
        X = np.random.rand(20, 12)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        assert dp.train(X, y)["success"]

    def test_rollback_stable_perf_no_baseline(self, tmp_path):
        """check_rollback 无current_perf"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        r = o.check_rollback(None)
        assert r["rollback"] is False

    def test_daily_check_conditions_no_train(self, tmp_path):
        """run_daily_check 条件触发但无训练数据"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=3)
        r = o.run_daily_check(new_samples_count=10, force=True)
        # 条件触发，但无训练数据 → no_training_data
        assert r["final_decision"] in ("no_training_data",)

    def test_full_xgboost_flow(self, tmp_path):
        """完整XGBoost训练→评估→部署流程"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        np.random.seed(42)
        X = np.random.rand(30, 5)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        t = o.run_incremental_train(X[:20], y[:20], X[20:], y[20:], model_type="xgboost", force=True)
        assert t["success"]
        e = o.evaluate_model(t, X[20:], y[20:])
        d = o.deploy_model(t, e)
        assert d["success"]


# ═══════════════════════════════════════════════════════════
# debate_brief.py 覆盖缺口 (75% → 目标 80%+)
# ═══════════════════════════════════════════════════════════


class TestDebateBriefGaps:
    def test_enhanced_meta_flag(self, tmp_path):
        """select_debate_symbols 输出应有 enhanced 标记"""
        l = tmp_path / "l.json"
        f = tmp_path / "f.json"
        l.write_text(
            json.dumps(
                {
                    "_meta": {},
                    "all_ranked": [
                        {
                            "symbol": "RB",
                            "total": 50,
                            "direction": "bull",
                            "name": "RB",
                            "adx": 30,
                            "rsi": 55,
                            "stage": "trending",
                            "cons": 2,
                            "veto": 0,
                            "atr": 30,
                            "z_score": 1.5,
                            "volume": 100,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        f.write_text(
            json.dumps(
                {
                    "_meta": {},
                    "all_ranked": [
                        {
                            "symbol": "RB",
                            "total": -30,
                            "direction": "bear",
                            "vote_net": -2,
                            "vote_confidence": -0.5,
                            "g_group": "G10",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        s = db.build_signal_summary(str(l), str(f))
        sel = db.select_debate_symbols(s, chain_map={"RB": "黑色链"}, min_count=1)
        assert sel["_meta"]["enhanced"] is True
        assert sel["_meta"]["debate_scoring"] == "五维加权评分 v1"

    def test_chain_coverage_with_neutral(self, sample_chain_map):
        """链覆盖补充从neutral品种中选取"""
        s = [
            {
                "symbol": "RB",
                "name": "RB",
                "l1l4": {
                    "total": 5,
                    "direction": "neutral",
                    "adx": 12,
                    "rsi": 52,
                    "stage": "quiet",
                    "cons": 0,
                    "veto": 0,
                    "z_score": 0,
                    "grade": "NOISE",
                    "price": 100,
                    "volume": 100,
                    "ma_slope": 0,
                    "macd_cross": "none",
                    "dc20_break": "none",
                    "ma_align": "mixed",
                    "l1": 0,
                    "l2": 0,
                    "l3": 0,
                    "l4": 0,
                },
                "risk_input": {"confidence": 50},
            },
            {
                "symbol": "SC",
                "name": "SC",
                "l1l4": {
                    "total": 5,
                    "direction": "neutral",
                    "adx": 10,
                    "rsi": 50,
                    "stage": "quiet",
                    "cons": 0,
                    "veto": 0,
                    "z_score": 0,
                    "grade": "NOISE",
                    "price": 100,
                    "volume": 100,
                    "ma_slope": 0,
                    "macd_cross": "none",
                    "dc20_break": "none",
                    "ma_align": "mixed",
                    "l1": 0,
                    "l2": 0,
                    "l3": 0,
                    "l4": 0,
                },
                "risk_input": {"confidence": 50},
            },
        ]
        sel = db.select_debate_symbols(
            {"_meta": {}, "symbols": s}, chain_map=sample_chain_map, min_count=3, min_chains=12
        )
        assert sel["_meta"]["total_candidates"] >= 1
