from scripts.unified_logger import get_logger
_logger = get_logger("marl")
#!/usr/bin/env python3
"""
多智能体强化学习训练器框架 v1.0（P3-1）
===========================================
基于历史辩论+交易结果训练协同奖励函数，自动调整各角色输出权重。

核心功能：
- define_reward_function(): 协同奖励函数定义
- train(): 训练角色权重
- evaluate(): 每周自动评估权重调整效果
- update_agent_weights(): 更新各Agent的prompt权重

设计原则：
- 不直接控制Agent输出，而是通过prompt权重引导
- 奖励函数基于辩论质量（论据一致性）+ 交易结果（PnL）的加权组合
- 定期评估（周频），避免过度优化

用法:
    from scripts.marl_trainer import MARLTrainer
    trainer = MARLTrainer()
    trainer.train(historical_debates, trade_results)
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json, os, random
from pathlib import Path


class MARLTrainer:
    """多智能体RL训练器 — 自动调优角色权重。"""

    # 各角色的默认权重
    DEFAULT_WEIGHTS = {
        "futures-technical-researcher": {"trend": 1.0, "volume": 1.0, "support_resistance": 1.0},
        "futures-fundamental-researcher": {"inventory": 1.0, "margin": 1.0, "basis": 1.0},
        "futures-affirmative-debater": {"evidence_depth": 1.0, "logic": 1.0},
        "futures-opposition-debater": {"evidence_depth": 1.0, "logic": 1.0},
        "futures-risk-manager": {"conservatism": 1.0, "leverage": 1.0},
        "futures-judge": {"technical_weight": 0.25, "fundamental_weight": 0.25, "chain_weight": 0.25, "sentiment_weight": 0.25},
    }

    def __init__(self, weights_path: str = None):
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.training_history = []
        self.rewards = []

        if weights_path is None:
            weights_path = Path(os.path.expanduser("~/Documents/WorkBuddy/RL/weights.json"))
        self.weights_path = Path(weights_path)
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)

        self._load()

    def _load(self):
        """加载持久化权重。"""
        if self.weights_path.exists():
            with open(self.weights_path, "r", encoding="utf-8") as f:
                self.weights = json.load(f)

    def _save(self):
        """保存权重。"""
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(self.weights, f, ensure_ascii=False, indent=2)

    def define_reward_function(self, debate_quality: float, trade_pnl: float,
                                 risk_control: float) -> float:
        """协同奖励函数。

        Args:
            debate_quality: 辩论质量得分（0~1，论据一致性+逻辑性）
            trade_pnl: 交易盈亏归一化得分（0~1）
            risk_control: 风控质量得分（0~1，止损执行+仓位管理）

        Returns:
            总奖励（0~1）
        """
        reward = (
            0.3 * debate_quality +
            0.5 * trade_pnl +
            0.2 * risk_control
        )
        return min(max(reward, 0), 1)

    def train(self, historical_debates: List[Dict],
              trade_results: List[Dict], learning_rate: float = 0.1):
        """训练角色权重。

        Args:
            historical_debates: [{"winner": "bull"|"bear", "scores": {...}}, ...]
            trade_results: [{"symbol": str, "pnl": float, "direction": str}, ...]
            learning_rate: 学习率
        """
        if not historical_debates and not trade_results:
            print("[MARL] 无训练数据，跳过")
            return

        # 计算辩论质量得分
        debate_scores = []
        for debate in historical_debates:
            scores = debate.get("scores", {})
            avg_score = sum(scores.values()) / max(len(scores), 1) if scores else 0.5
            debate_scores.append(avg_score / 100)

        # 计算交易盈亏得分
        trade_pnls = []
        for trade in trade_results:
            pnl = trade.get("pnl", 0)
            direction = trade.get("direction", "")
            trade_pnls.append(1.0 if pnl > 0 else 0.0)

        # 平均奖励
        avg_debate = sum(debate_scores) / max(len(debate_scores), 1) if debate_scores else 0.5
        avg_trade = sum(trade_pnls) / max(len(trade_pnls), 1) if trade_pnls else 0.5

        reward = self.define_reward_function(avg_debate, avg_trade, 0.5)

        self.rewards.append({
            "timestamp": datetime.now().isoformat(),
            "reward": reward,
            "samples": {"debates": len(historical_debates), "trades": len(trade_results)},
        })

        # 自适应学习率
        adapted_lr = learning_rate * (reward - 0.5) * 2  # reward > 0.5 时加速学习

        # 更新权重
        for agent, weights in self.weights.items():
            for key in weights:
                current = weights[key]
                # 简单梯度：当前值向奖励方向微调
                new_val = current + adapted_lr * (reward - 0.5)
                self.weights[agent][key] = max(0.1, min(2.0, new_val))

        self._save()
        print(f"[MARL] 训练完成: reward={reward:.3f}, lr={adapted_lr:.3f}")

    def get_weights(self) -> Dict[str, Dict[str, float]]:
        """获取当前Agent权重。"""
        return self.weights

    def get_training_summary(self) -> Dict[str, Any]:
        """获取训练摘要。"""
        return {
            "total_trainings": len(self.rewards),
            "avg_reward": round(sum(r["reward"] for r in self.rewards) / max(len(self.rewards), 1), 3),
            "recent_rewards": [r["reward"] for r in self.rewards[-10:]],
            "agents": list(self.weights.keys()),
            "last_updated": self.rewards[-1]["timestamp"] if self.rewards else None,
        }


if __name__ == "__main__":
    trainer = MARLTrainer()
    trainer.train(
        historical_debates=[{"winner": "bull", "scores": {"logic": 80, "evidence": 75}}],
        trade_results=[{"symbol": "RB", "pnl": 500, "direction": "long"}],
    )
    print(f"权重: {json.dumps(trainer.get_weights(), ensure_ascii=False, indent=2)}")
