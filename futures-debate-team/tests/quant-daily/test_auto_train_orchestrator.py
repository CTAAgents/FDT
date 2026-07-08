"""auto_train_orchestrator.py 单元测试"""

import os, numpy as np, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ml import trainer as ato


class TestTrainingOrchestrator:
    def test_init(self, tmp_path):
        o = ato.TrainingOrchestrator(
            model_dir=str(tmp_path), min_new_samples=10, max_days_since_train=14, auto_deploy=False
        )
        assert o.min_new_samples == 10 and o.max_days_since_train == 14 and o.auto_deploy is False

    def test_check_new_samples(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=5)
        assert len(o.check_conditions(10)) >= 1

    def test_check_no_trigger(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=50)
        assert o.check_conditions(0) == []

    def test_check_first_train(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=5)
        assert "首次训练" in o.check_conditions(10)

    def test_get_status(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        s = o.get_status()
        assert "model_dir" in s and "total_trained" in s

    def test_sklearn(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        X = np.random.rand(10, 3)
        y = np.array([0, 1] * 5)
        r = o.run_incremental_train(X, y, model_type="sklearn", force=True)
        assert r["success"]

    def test_lightgbm(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        np.random.seed(42)
        X = np.random.rand(30, 5)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        r = o.run_incremental_train(X[:20], y[:20], X[20:], y[20:], model_type="lightgbm", force=True)
        assert r["success"] and "auc" in r.get("metrics", {})

    def test_evaluate_first(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        r = o.evaluate_model({"metrics": {"auc": 0.85, "precision": 0.8, "recall": 0.75, "f1": 0.78}})
        assert r["decision"] == "deploy"

    def test_deploy(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        X = np.random.rand(10, 3)
        y = np.array([0, 1] * 5)
        t = o.run_incremental_train(X, y, model_type="sklearn", force=True)
        assert t["success"]
        d = o.deploy_model(t, o.evaluate_model(t))
        assert d["success"]

    def test_daily_check(self, tmp_path):
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        np.random.seed(42)
        X = np.random.rand(20, 5)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        r = o.run_daily_check(
            X_train=X[:15], y_train=y[:15], X_val=X[15:], y_val=y[15:], new_samples_count=30, force=True
        )
        assert r["final_decision"] in ("deployed", "skipped", "flagged_need_review")

    # ─── 新增测试：XGBoost ────────────────────────────────
    def test_xgboost(self, tmp_path):
        """XGBoost 训练路径"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        np.random.seed(42)
        X = np.random.rand(30, 5)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        r = o.run_incremental_train(X[:20], y[:20], X[20:], y[20:], model_type="xgboost", force=True)
        assert r["success"]
        assert "auc" in r.get("metrics", {})

    def test_xgboost_no_val(self, tmp_path):
        """XGBoost 无验证集路径"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        X = np.random.rand(20, 5)
        y = (X[:, 0] > 0.5).astype(int)
        r = o.run_incremental_train(X, y, model_type="xgboost", force=True)
        assert r["success"]

    # ─── 新增测试：评估和性能下降 ──────────────────────────
    def test_evaluate_worse(self, tmp_path):
        """候选模型更差 → flag"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        st = o._load_state()
        st["production_perf"] = {"auc": 0.95, "precision": 0.92, "f1": 0.90, "recall": 0.88}
        st["total_trained"] = 1
        o._save_state(st)
        r = o.evaluate_model({"metrics": {"auc": 0.70, "precision": 0.60, "recall": 0.50, "f1": 0.45}})
        assert r["decision"] in ("flag", "skip")

    def test_evaluate_better(self, tmp_path):
        """候选模型更好 → deploy"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), auto_deploy=True)
        st = o._load_state()
        st["production_perf"] = {"auc": 0.75, "precision": 0.70, "f1": 0.68, "recall": 0.65}
        st["total_trained"] = 1
        o._save_state(st)
        r = o.evaluate_model({"metrics": {"auc": 0.90, "precision": 0.85, "recall": 0.80, "f1": 0.82}})
        assert r["decision"] in ("deploy", "flag")

    # ─── 新增测试：回滚 ────────────────────────────────────
    def test_check_rollback_stable(self, tmp_path):
        """性能稳定 → 不回滚"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        st = o._load_state()
        st["production_perf"] = {"auc": 0.90, "precision": 0.85, "f1": 0.82, "recall": 0.80}
        # 设置一个30天前的日期以通过3天检查
        from datetime import datetime, timedelta, timezone

        st["last_train_date"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        st["total_trained"] = 1
        o._save_state(st)
        r = o.check_rollback({"auc": 0.89, "precision": 0.84, "f1": 0.81, "recall": 0.79})
        assert r["rollback"] is False
        assert "性能稳定" in r["reason"]

    def test_check_rollback_no_baseline(self, tmp_path):
        """无基线 → 不回滚"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        r = o.check_rollback(None)
        assert r["rollback"] is False

    def test_check_rollback_degraded(self, tmp_path):
        """性能下降>10% → 回滚"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        st = o._load_state()
        st["production_perf"] = {"auc": 0.90, "precision": 0.85, "f1": 0.82, "recall": 0.80}
        from datetime import datetime, timedelta, timezone

        st["last_train_date"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        st["total_trained"] = 1
        o._save_state(st)
        import pickle

        dummy_model = os.path.join(o._production_dir, "dummy.pkl")
        with open(dummy_model, "wb") as f:
            pickle.dump({"dummy": True}, f)
        r = o.check_rollback({"auc": 0.50, "precision": 0.40, "f1": 0.30, "recall": 0.20})
        assert r["rollback"] is True

    # ─── 新增边缘测试 ────────────────────────────────────
    def test_check_time_trigger(self, tmp_path):
        """距上次训练超过7天触发"""
        from datetime import datetime, timedelta, timezone

        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=100)
        st = o._load_state()
        st["last_train_date"] = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        st["total_trained"] = 1
        o._save_state(st)
        c = o.check_conditions(0)
        assert any("距上次训练" in x for x in c)

    def test_deploy_with_backup(self, tmp_path):
        """部署时已有生产模型应备份"""
        import pickle

        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        # 放一个旧模型
        old = os.path.join(o._production_dir, "old_model.pkl")
        with open(old, "wb") as f:
            pickle.dump({"v": 1}, f)
        X = np.random.rand(10, 3)
        y = np.array([0, 1] * 5)
        t = o.run_incremental_train(X, y, model_type="sklearn", force=True)
        d = o.deploy_model(t, o.evaluate_model(t))
        assert d["success"]
        assert d["backup_path"] is not None
        assert os.path.exists(d["backup_path"])

    def test_daily_check_no_trigger(self, tmp_path):
        """每日检查无触发条件"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path), min_new_samples=100)
        r = o.run_daily_check(new_samples_count=0)
        assert r["final_decision"] == "skip_no_trigger"

    def test_dispute_predictor_no_symbol(self):
        """DisputePredictor 无symbol应不崩溃"""
        dp = ato.DisputePredictor()
        e = {
            "breakdown": {"signal": 10, "quality": 10, "extreme": 5, "data": 8, "chain": 3},
            "conflict": False,
            "symbol": "",
            "adx": 25,
            "l1l4_total": 30,
            "factor_total": 20,
        }
        f = dp.extract_features(e)
        assert len(f) == 12

    def test_sklearn_no_val(self, tmp_path):
        """Sklearn 无验证集"""
        o = ato.TrainingOrchestrator(model_dir=str(tmp_path))
        X = np.random.rand(10, 5)
        y = (X[:, 0] > 0.5).astype(int)
        r = o.run_incremental_train(X, y, model_type="sklearn", force=True)
        assert r["success"]


class TestDisputePredictor:
    def test_extract(self):
        e = {
            "breakdown": {"signal": 24, "quality": 23, "extreme": 13, "data": 10, "chain": 5},
            "conflict": True,
            "symbol": "RB",
            "adx": 60,
            "l1l4_total": 76,
            "factor_total": -45,
        }
        assert len(ato.DisputePredictor().extract_features(e)) == 12

    def test_predict_no_model(self):
        assert ato.DisputePredictor().predict([0.5] * 12) == 0.5

    def test_train_predict(self, tmp_path):
        dp = ato.DisputePredictor(model_path=str(tmp_path / "m.pkl"))
        np.random.seed(42)
        X = np.random.rand(20, 12)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        assert dp.train(X, y)["success"]
        assert 0 <= dp.predict(X[0]) <= 1
