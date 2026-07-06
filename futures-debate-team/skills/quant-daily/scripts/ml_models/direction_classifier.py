# -*- coding: utf-8 -*-
"""方向概率预测模型 — LightGBM 二分类器。

集成到技术Agent的推理链路：
技术Agent同时运行规则层 + ML层 → 两层加权输出 → 最终(方向,概率,置信度)

使用方式:
    from ml_models.direction_classifier import DirectionClassifier, EnsemblePredictor

    # 训练
    model = DirectionClassifier()
    model.train(X_train, y_train, X_val, y_val)

    # 推理
    prob, direction, confidence = model.predict(features_dict)

    # 集成
    ensemble = EnsemblePredictor(rule_weight=0.6, ml_weight=0.4)
    result = ensemble.predict(rule_output, ml_output)
"""

from typing import Dict, List, Optional, Tuple, Any
import json, os, math
import numpy as np


class DirectionClassifier:
    """方向概率预测模型 — LightGBM 包装器。

    期货小样本友好：特征数30+，样本量几千到几万。
    输出 (方向概率, 方向, 置信度) 三元组。
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.feature_names = None
        self.model_path = model_path

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ):
        """训练 LightGBM 分类器。

        Args:
            X: 训练特征矩阵 (n_samples, n_features)
            y: 训练标签 (1=涨, -1=跌, 0=横盘) — 训练时转二分类：1 vs 非1
            X_val: 验证集
            y_val: 验证标签
            feature_names: 特征名列表
        """
        try:
            import lightgbm as lgb
        except ImportError:
            print("[WARN] lightgbm 未安装，使用 fallback 逻辑回归")
            self._train_fallback(X, y)
            return

        self.feature_names = feature_names

        # 转二分类：涨=1，非涨=0
        y_binary = np.where(y == 1, 1, 0)

        params = {
            "objective": "binary",
            "metric": "auc",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "min_data_in_leaf": 20,
        }

        train_data = lgb.Dataset(X, label=y_binary, feature_name=feature_names)
        valid_sets = [train_data]
        valid_names = ["train"]

        if X_val is not None and y_val is not None:
            y_val_binary = np.where(y_val == 1, 1, 0)
            val_data = lgb.Dataset(X_val, label=y_val_binary, reference=train_data)
            valid_sets.append(val_data)
            valid_names.append("val")

        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=200,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
        )

    def _train_fallback(self, X: np.ndarray, y: np.ndarray):
        """fallback: 简单逻辑回归（无lightgbm时）"""
        y_binary = np.where(y == 1, 1, 0)
        n_features = X.shape[1] if len(X.shape) > 1 else 0
        self.model = {
            "weights": np.random.randn(n_features) * 0.01,
            "bias": 0.0,
            "fallback": True,
        }

    def predict(self, features: Dict[str, float]) -> Tuple[float, int, float]:
        """单样本推理。

        Args:
            features: 特征字典 {特征名: 值}

        Returns:
            (概率, 方向, 置信度): (0.72, 1, 75) 表示上涨概率72%，方向多，置信度75
        """
        if self.model is None:
            return (0.5, 0, 30)

        if self.feature_names:
            X = np.array([[features.get(f, 0) for f in self.feature_names]])
        else:
            X = np.array([list(features.values())])

        # LightGBM 推理
        if hasattr(self.model, "predict"):
            prob = float(self.model.predict(X)[0])
        else:
            # fallback
            w = self.model.get("weights", np.zeros(X.shape[1]))
            b = self.model.get("bias", 0)
            logit = np.dot(X[0], w) + b
            prob = 1.0 / (1.0 + math.exp(-logit))

        direction = 1 if prob >= 0.55 else (-1 if prob <= 0.45 else 0)
        confidence = int(abs(prob - 0.5) * 200)  # 0.5→0, 0.75→50, 0.9→80
        confidence = max(0, min(100, confidence))

        return (round(prob, 3), direction, confidence)

    def save(self, path: str):
        """保存模型"""
        if hasattr(self.model, "save_model"):
            self.model.save_model(path)
        else:
            with open(path, "w") as f:
                json.dump({"fallback": True, "feature_names": self.feature_names}, f)

    def load(self, path: str):
        """加载模型"""
        try:
            import lightgbm as lgb

            self.model = lgb.Booster(model_file=path)
        except Exception:
            with open(path) as f:
                data = json.load(f)
            self.model = data
        self.model_path = path


class EnsemblePredictor:
    """集成预测器 — 规则层 + ML 层加权输出。

    权重根据近期准确率在线调整（类似 Expert Tracking）。
    """

    def __init__(self, rule_weight: float = 0.6, ml_weight: float = 0.4, adapt_online: bool = True):
        self.rule_weight = rule_weight
        self.ml_weight = ml_weight
        self.adapt_online = adapt_online
        self.performance_log = []  # 记录每次预测的准确度

    def predict(self, rule_output: Dict, ml_output: Dict) -> Dict:
        """集成预测。

        Args:
            rule_output: {"prob": 0.6, "direction": 1, "confidence": 70}
            ml_output: {"prob": 0.72, "direction": 1, "confidence": 75}

        Returns:
            {"prob": 0.648, "direction": 1, "confidence": 72,
             "rule_weight": 0.6, "ml_weight": 0.4}
        """
        prob = rule_output.get("prob", 0.5) * self.rule_weight + ml_output.get("prob", 0.5) * self.ml_weight
        direction = 1 if prob >= 0.55 else (-1 if prob <= 0.45 else 0)

        conf_rule = rule_output.get("confidence", 50)
        conf_ml = ml_output.get("confidence", 50)
        confidence = int(conf_rule * self.rule_weight + conf_ml * self.ml_weight)

        return {
            "prob": round(prob, 3),
            "direction": direction,
            "confidence": max(0, min(100, confidence)),
            "rule_weight": round(self.rule_weight, 2),
            "ml_weight": round(self.ml_weight, 2),
        }

    def update_weights(self, actual_direction: int, rule_pred: Dict, ml_pred: Dict):
        """在线更新权重 — 根据近期的预测准确率调整。

        Args:
            actual_direction: 实际方向 (1/-1/0)
            rule_pred: 规则层预测
            ml_pred: ML层预测
        """
        if not self.adapt_online:
            return

        rule_correct = 1 if rule_pred.get("direction") == actual_direction else 0
        ml_correct = 1 if ml_pred.get("direction") == actual_direction else 0

        self.performance_log.append({"rule": rule_correct, "ml": ml_correct})
        if len(self.performance_log) > 50:
            self.performance_log = self.performance_log[-50:]

        # 每20条记录重新计算权重
        if len(self.performance_log) >= 20:
            recent = self.performance_log[-20:]
            rule_acc = sum(r["rule"] for r in recent) / 20
            ml_acc = sum(r["ml"] for r in recent) / 20
            total = rule_acc + ml_acc
            if total > 0:
                self.rule_weight = rule_acc / total
                self.ml_weight = ml_acc / total

    def export_ensemble_votes(
        self, symbols: List[str], rule_outputs: Dict[str, Dict], ml_outputs: Dict[str, Dict]
    ) -> Dict[str, Dict]:
        """批量导出品种级的集成投票结果。

        供闫判官证据简报作为第3路（ML+规则集成）证据源。

        Args:
            symbols: 品种列表
            rule_outputs: {symbol: {"prob": 0.6, "direction": 1, "confidence": 70}}
            ml_outputs: {symbol: {"prob": 0.72, "direction": 1, "confidence": 75}}

        Returns:
            {symbol: {"rule_dir": str, "ml_dir": str, "ensemble_dir": str,
                       "ensemble_prob": float, "confidence": int, "consensus": bool}}
        """
        results = {}
        for sym in symbols:
            rule = rule_outputs.get(sym, {"prob": 0.5, "direction": 0, "confidence": 50})
            ml = ml_outputs.get(sym, {"prob": 0.5, "direction": 0, "confidence": 50})
            ensemble = self.predict(rule, ml)

            rule_dir = (
                "bull" if rule.get("direction", 0) > 0 else ("bear" if rule.get("direction", 0) < 0 else "neutral")
            )
            ml_dir = "bull" if ml.get("direction", 0) > 0 else ("bear" if ml.get("direction", 0) < 0 else "neutral")
            ens_dir = (
                "bull"
                if ensemble.get("direction", 0) > 0
                else ("bear" if ensemble.get("direction", 0) < 0 else "neutral")
            )
            consensus = rule_dir == ml_dir

            results[sym] = {
                "rule_dir": rule_dir,
                "ml_dir": ml_dir,
                "ensemble_dir": ens_dir,
                "ensemble_prob": ensemble.get("prob", 0.5),
                "confidence": ensemble.get("confidence", 50),
                "consensus": consensus,
                "rule_weight": self.rule_weight,
                "ml_weight": self.ml_weight,
            }
        return results

    # ── P1-2: 四路集成预测（规则+ML+情感+因子新鲜度） ──

    def predict_four_way(
        self,
        rule_output: Dict[str, float],
        ml_output: Dict[str, float],
        sentiment_output: Dict[str, float] = None,
        freshness_output: Dict[str, float] = None,
    ) -> Dict[str, Any]:
        """四路集成预测。

        Args:
            rule_output: 规则策略输出 {"direction", "prob", "confidence"}
            ml_output: ML模型输出 {"direction", "prob", "confidence"}
            sentiment_output: 情感因子输出 {"direction", "prob", "confidence"}，可选
            freshness_output: 因子新鲜度输出 {"direction", "prob", "confidence"}，可选

        Returns:
            {"prob": float, "direction": int, "confidence": float,
             "vote_details": {"rule": float, "ml": float, "sentiment": float, "freshness": float}}
        """
        import math

        # 基础双路
        votes = {
            "rule": rule_output.get("prob", 50) * (1 if rule_output.get("direction", 0) > 0 else -1),
            "ml": ml_output.get("prob", 50) * (1 if ml_output.get("direction", 0) > 0 else -1),
        }

        # 情感因子（可选）
        if sentiment_output:
            s_dir = 1 if sentiment_output.get("direction", 0) > 0 else -1
            votes["sentiment"] = sentiment_output.get("prob", 50) * s_dir * 0.5  # 情感权重减半

        # 因子新鲜度（可选）
        if freshness_output:
            f_dir = 1 if freshness_output.get("direction", 0) > 0 else -1
            votes["freshness"] = freshness_output.get("prob", 50) * f_dir * 0.3  # 新鲜度权重最低

        # 加权投票
        weights = {"rule": self.rule_weight, "ml": self.ml_weight}
        if sentiment_output and "sentiment" in votes:
            weights["sentiment"] = 0.15
        else:
            votes["sentiment"] = 0
        if freshness_output and "freshness" in votes:
            weights["freshness"] = 0.10
        else:
            votes["freshness"] = 0

        total_weight = sum(v * w for v, w in zip(votes.values(), weights.values()))
        total_weight_sum = sum(weights.values())

        if total_weight_sum == 0:
            return {"prob": 50, "direction": 0, "confidence": 50}

        weighted_vote = total_weight / total_weight_sum
        direction = 1 if weighted_vote > 0 else -1
        prob = min(abs(weighted_vote), 99)
        confidence = int(prob * 1.5)

        return {
            "prob": round(prob, 2),
            "direction": direction,
            "confidence": min(confidence, 99),
            "vote_details": {
                "rule": round(votes.get("rule", 0), 2),
                "ml": round(votes.get("ml", 0), 2),
                "sentiment": round(votes.get("sentiment", 0), 2),
                "freshness": round(votes.get("freshness", 0), 2),
            },
        }


class DirectionClassifierV2(DirectionClassifier):
    """P1-2: ML方向分类器 v2 — 支持增量训练、因子衰减、四路集成。"""

    def __init__(self, model_path: Optional[str] = None):
        super().__init__(model_path)
        self.feature_decay_rate = 0.05  # 因子衰减率
        self.feature_importance_history = []  # 特征重要性历史

    def incremental_train(
        self,
        X_new: np.ndarray,
        y_new: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
    ):
        """增量训练：在现有模型基础上微调，避免模型固化老化。

        使用 LightGBM 的 init_model 参数实现增量学习。
        每日收盘用实盘PnL样本微调模型。

        Args:
            X_new: 新样本特征
            y_new: 新样本标签
            X_val: 验证集特征（可选）
            y_val: 验证集标签（可选）
        """
        if self.model is None:
            return super().train(X_new, y_new, X_val, y_val)

        try:
            import lightgbm as lgb

            train_data = lgb.Dataset(X_new, y_new)
            val_data = lgb.Dataset(X_val, y_val) if X_val is not None and y_val is not None else None

            params = {
                "objective": "binary",
                "metric": "binary_logloss",
                "learning_rate": 0.01,  # 增量训练用小学习率
                "num_leaves": 15,
                "min_data_in_leaf": 10,
                "verbose": -1,
            }

            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=10,  # 少量轮次微调
                valid_sets=[val_data] if val_data else None,
                init_model=self.model,  # 关键：基于现有模型增量训练
            )
        except ImportError:
            import warnings

            warnings.warn("LightGBM 不可用，增量训练跳过")

    def update_feature_freshness(self, feature_names: List[str], importance_scores: np.ndarray):
        """更新因子新鲜度权重。

        Args:
            feature_names: 特征名列表
            importance_scores: 特征重要性分数
        """
        self.feature_importance_history.append(
            {
                "date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                "features": {name: float(score) for name, score in zip(feature_names, importance_scores)},
            }
        )

        # 仅保留最近3条历史
        if len(self.feature_importance_history) > 3:
            self.feature_importance_history = self.feature_importance_history[-3:]

    def get_feature_decay_analysis(self) -> Dict[str, Any]:
        """分析因子衰减情况。

        Returns:
            {"decaying_features": [str], "top_features": [str], "decay_rate": float}
        """
        if len(self.feature_importance_history) < 2:
            return {"decaying_features": [], "top_features": [], "decay_rate": self.feature_decay_rate}

        recent = self.feature_importance_history[-1]["features"]
        previous = self.feature_importance_history[0]["features"]

        decaying = []
        for feature in recent:
            if feature in previous:
                decline = previous[feature] - recent[feature]
                if decline > previous[feature] * 0.3:  # 衰减超过30%
                    decaying.append(feature)

        top = sorted(recent, key=recent.get, reverse=True)[:5]

        return {
            "decaying_features": decaying,
            "top_features": top,
            "decay_rate": self.feature_decay_rate,
            "history_count": len(self.feature_importance_history),
        }


class AdaptiveEnsemble:
    """自适应集成投票 — 规则 vs ML 权重基于滚动窗口动态调整。

    用法:
        ae = AdaptiveEnsemble(window=20)
        ae.record(rule_correct=True, ml_correct=True, pnl=500)
        rule_w, ml_w = ae.get_weight()  # 动态权重
    """

    def __init__(self, window: int = 20, default_rule_weight: float = 0.6):
        self.window = window
        self.default_rule_weight = default_rule_weight
        self.rule_hits: list[bool] = []  # 规则方向正确次数
        self.ml_hits: list[bool] = []  # ML方向正确次数
        self.rule_pnls: list[float] = []
        self.ml_pnls: list[float] = []

    def record(self, rule_correct: bool, ml_correct: bool, pnl: float = 0):
        """记录一次交易的结果。

        Args:
            rule_correct: 规则方向是否正确
            ml_correct: ML方向是否正确
            pnl: 实际盈亏（可选，用于PnL加权）
        """
        self.rule_hits.append(rule_correct)
        self.ml_hits.append(ml_correct)
        if pnl != 0:
            self.rule_pnls.append(pnl if rule_correct else -pnl)
            self.ml_pnls.append(pnl if ml_correct else -pnl)
        # 只保留最近 window 笔
        if len(self.rule_hits) > self.window:
            self.rule_hits.pop(0)
            self.ml_hits.pop(0)
            if len(self.rule_pnls) > self.window:
                self.rule_pnls.pop(0)
                self.ml_pnls.pop(0)

    def get_weight(self) -> tuple[float, float]:
        """计算动态权重。

        Returns:
            (rule_weight, ml_weight) 总和为 1.0
        """
        if not self.rule_hits:
            return (self.default_rule_weight, 1 - self.default_rule_weight)

        # 方法1: 基于胜率
        rule_win = sum(self.rule_hits) / len(self.rule_hits)
        ml_win = sum(self.ml_hits) / len(self.ml_hits)

        # 方法2: 基于PnL（如果有）
        if self.rule_pnls and sum(abs(p) for p in self.rule_pnls) > 0:
            rule_pnl_ratio = sum(self.rule_pnls) / max(abs(sum(self.ml_pnls)), 1)
            ml_pnl_ratio = sum(self.ml_pnls) / max(abs(sum(self.rule_pnls)), 1)
            # 融合胜率和PnL
            rule_score = rule_win * 0.6 + min(max(rule_pnl_ratio, -1), 1) * 0.4
            ml_score = ml_win * 0.6 + min(max(ml_pnl_ratio, -1), 1) * 0.4
        else:
            rule_score = rule_win
            ml_score = ml_win

        total = rule_score + ml_score
        if total <= 0:
            return (self.default_rule_weight, 1 - self.default_rule_weight)

        rule_w = rule_score / total
        ml_w = ml_score / total

        # 限制极端值：权重不低于 0.2，不高于 0.8
        rule_w = max(0.2, min(0.8, rule_w))
        ml_w = 1 - rule_w

        return (round(rule_w, 4), round(ml_w, 4))

    def get_stats(self) -> dict:
        """获取滚动窗口统计。"""
        if not self.rule_hits:
            return {"samples": 0}
        return {
            "samples": len(self.rule_hits),
            "rule_win_rate": round(sum(self.rule_hits) / len(self.rule_hits), 4),
            "ml_win_rate": round(sum(self.ml_hits) / len(self.ml_hits), 4),
            "weights": self.get_weight(),
            "rule_pnl_avg": round(sum(self.rule_pnls) / max(len(self.rule_pnls), 1), 2) if self.rule_pnls else 0,
            "ml_pnl_avg": round(sum(self.ml_pnls) / max(len(self.ml_pnls), 1), 2) if self.ml_pnls else 0,
        }


if __name__ == "__main__":
    ae = AdaptiveEnsemble(window=10)
    for i in range(15):
        ae.record(
            rule_correct=(i % 3 != 0),  # 规则66%胜率
            ml_correct=(i % 2 == 0),  # ML50%胜率
            pnl=100 if i % 2 == 0 else -50,
        )
    print(f"动态权重: {ae.get_weight()}")
    print(f"统计: {ae.get_stats()}")
