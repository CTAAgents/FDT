#!/usr/bin/env python3
"""
自动增量训练管道（P1-3）
===========================
每日收盘后自动执行：
1. 从 TradeJournal 提取今日交易样本
2. 构建特征向量
3. 增量训练 DirectionClassifierV2
4. 更新 AdaptiveEnsemble 权重
5. 运行特征衰减分析
6. 记录模型版本

用法:
    # 手动触发
    python scripts/auto_train.py --symbols RB,PK

    # cron 自动（每日 15:00 收盘后）
    0 15 * * 1-5 cd /path && python scripts/auto_train.py --auto
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.unified_logger import get_logger

logger = get_logger("auto_train")


def run_daily_training(symbols: list[str] = None, auto: bool = False):
    """每日训练管道入口。"""
    logger.info(f"自动训练启动: symbols={symbols}, auto={auto}")

    try:
        # 1. 读取今日交易记录
        from skills.quant_daily.scripts.feedback.trade_journal import query_history

        trades = query_history(days=1)
        logger.info(f"今日交易记录: {len(trades)}条")

        # 2. 构建训练样本（简化版）
        X_new, y_new = _build_training_samples(trades)
        logger.info(f"训练样本: {len(X_new)}个")

        if len(X_new) < 3:
            logger.warning("样本不足(<3)，跳过今日增量训练")
            return {"status": "skipped", "reason": "样本不足"}

        # 3. 增量训练
        from skills.quant_daily.scripts.ml_models.direction_classifier import DirectionClassifierV2

        model = DirectionClassifierV2()
        model.incremental_train(X_new, y_new)
        logger.info("增量训练完成")

        # 4. 更新自适应权重
        _update_adaptive_weights(trades)

        # 5. 特征衰减分析
        decay = model.get_feature_decay_analysis()
        if decay.get("decaying_features"):
            logger.warning(f"特征衰减: {decay['decaying_features']}")
        else:
            logger.info("所有特征稳定")

        # 6. 记录版本
        version_info = _record_model_version(model, len(X_new))

        result = {
            "status": "success",
            "samples": len(X_new),
            "decaying_features": decay.get("decaying_features", []),
            "version": version_info,
            "timestamp": datetime.now().isoformat(),
        }
        logger.info(f"训练完成: {json.dumps(result, ensure_ascii=False)}")
        return result

    except Exception as e:
        logger.error(f"自动训练失败: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


def _build_training_samples(trades: list) -> tuple:
    """从交易记录构建训练样本。"""
    import random
    import numpy as np

    if not trades:
        return np.array([]), np.array([])

    # 简化：生成模拟特征（实际应基于 real 市场数据构建）
    X = np.random.randn(max(len(trades), 3), 5)
    y = np.array([1 if t.get("pnl", 0) > 0 else 0 for t in trades])
    return X, y


def _update_adaptive_weights(trades: list):
    """更新自适应权重。"""
    from skills.quant_daily.scripts.ml_models.direction_classifier import AdaptiveEnsemble

    ae = AdaptiveEnsemble()
    for t in trades[-20:]:  # 最多20笔
        ae.record(
            rule_correct=t.get("rule_correct", True),
            ml_correct=t.get("ml_correct", False),
            pnl=t.get("pnl", 0),
        )
    stats = ae.get_stats()
    logger.info(f"自适应权重: rule={stats['weights'][0]}, ml={stats['weights'][1]}")
    return stats


def _record_model_version(model, samples: int) -> dict:
    """记录模型版本。"""
    version_info = {
        "timestamp": datetime.now().isoformat(),
        "samples": samples,
        "model_type": "DirectionClassifierV2",
    }
    # 持久化到 version_control.json
    version_path = os.path.join(os.path.dirname(__file__), "..", "skills/quant-daily/models/version_control.json")
    os.makedirs(os.path.dirname(version_path), exist_ok=True)

    history = []
    if os.path.exists(version_path):
        with open(version_path, "r") as f:
            history = json.load(f)
    history.append(version_info)
    history = history[-100:]  # 保留最近100次

    with open(version_path, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return version_info


def main():
    parser = argparse.ArgumentParser(description="自动增量训练管道")
    parser.add_argument("--symbols", help="品种列表（逗号分隔）")
    parser.add_argument("--auto", action="store_true", help="cron自动模式")
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else None
    result = run_daily_training(symbols, auto=args.auto)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
