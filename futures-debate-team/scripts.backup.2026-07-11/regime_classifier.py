#!/usr/bin/env python3
"""
行情区制识别器 — 前置分流模块（P1-6）
=========================================
基于波动率+趋势强度+成交量识别市场状态，前置分流优化算力分配。

区制类型：
- strong_trend: 强趋势（ADX>30，MA多头排列，成交量放大）
- wide_range: 宽幅震荡（ADX<20，价格区间收敛）
- extreme_event: 极端事件（波动率突增3σ+）
- normal: 正常（其他情况）

分流策略：
- 强趋势：提升技术面权重，简化产业链分析，缩短辩论轮次
- 宽幅震荡：降低ML权重，放大支撑阻力校验，增加产业链深度
- 极端事件：保守风控，减半仓位，启用事件日历

用法:
    from regime_classifier import RegimeClassifier, classify_regime
    regime = classify_regime(df)  # → {"regime": "strong_trend", "confidence": 0.85, ...}
"