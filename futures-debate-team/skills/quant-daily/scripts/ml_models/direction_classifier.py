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

from typing import Dict, List, Optional, Tuple
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

    def train(self, X: np.ndarray, y: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None,
              feature_names: Optional[List[str]] = None):
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
            'objective': 'binary',
            'metric': 'auc',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'min_data_in_leaf': 20,
        }

        train_data = lgb.Dataset(X, label=y_binary, feature_name=feature_names)
        valid_sets = [train_data]
        valid_names = ['train']

        if X_val is not None and y_val is not None:
            y_val_binary = np.where(y_val == 1, 1, 0)
            val_data = lgb.Dataset(X_val, label=y_val_binary, reference=train_data)
            valid_sets.append(val_data)
            valid_names.append('val')

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
        if hasattr(self.model, 'predict'):
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
        if hasattr(self.model, 'save_model'):
            self.model.save_model(path)
        else:
            with open(path, 'w') as f:
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

    def __init__(self, rule_weight: float = 0.6, ml_weight: float = 0.4,
                 adapt_online: bool = True):
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

    def export_ensemble_votes(self, symbols: List[str],
                               rule_outputs: Dict[str, Dict],
                               ml_outputs: Dict[str, Dict]) -> Dict[str, Dict]:
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

            rule_dir = "bull" if rule.get("direction", 0) > 0 else ("bear" if rule.get("direction", 0) < 0 else "neutral")
            ml_dir = "bull" if ml.get("direction", 0) > 0 else ("bear" if ml.get("direction", 0) < 0 else "neutral")
            ens_dir = "bull" if ensemble.get("direction", 0) > 0 else ("bear" if ensemble.get("direction", 0) < 0 else "neutral")
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
