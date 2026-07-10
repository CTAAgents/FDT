# OmniOpt: Taxonomy, Geometry, and Benchmarking of Modern Optimizers

- **日期**: 2026-07-09
- **来源**: https://arxiv.org/abs/2607.04033 | GitHub: github.com/OpenRaiser/OmniOpt | Project: openraiser.github.io/OmniOpt
- **分类**: 论文研报
- **标签**: 优化器, OmniOpt, 深度学习, 训练优化, Survey, Benchmark, LMO, Meta-Pipeline, LLM训练, 大模型

## BibTeX

```bibtex
@article{li2026omniopt,
  title = {OmniOpt: Taxonomy, Geometry, and Benchmarking of Modern Optimizers},
  author = {Li, Siyuan and Pan, Jiabao and Liu, Yumou and Ouyang, Zhuoli and Jin, Xin and Xu, Xinglong and Wei, Jingxuan and Pang, Shengye and Che, Jintao and Zhou, Xuanhe and He, Conghui and Tan, Cheng},
  journal = {arXiv preprint arXiv:2607.04033},
  year = {2026},
  url = {https://arxiv.org/abs/2607.04033}
}
```

## 核心要点

- 五阶段元流水线(S0-S5)统一所有优化器更新过程：信号获取→参数路由→梯度变换→状态演化→重建→最终化
- 基于LMO(线性最小化预言机)的四轴几何分解框架，从更新域、状态估计器、几何算子、最终化四个维度分析优化器
- 双重分类法：方法家族(T1-T5) × 效果目标(O1-O6)
- 两阶段跨领域基准测试(60M~1B参数, C4 + FineWeb-Edu 32K, 四种架构)
- 核心发现：SOAP长上下文质量最强但成本最高；RMNP矩阵结构中最实用；AdamW仍是稳定参考锚点
- 关键警告：APOLLO短上下文优势在长上下文中不成立——短上下文优化器优势不自动迁移
- 共91页survey+benchmark，覆盖100+优化器方法

## 可应用场景

- 期货模型训练优化器选型 — Pareto前沿决策指南
- 大模型微调优化器配置 — 内存/效率/质量的三角权衡
- Agent调优性价比分析 — 方法家族×效果目标矩阵

## 详细内容

### 论文基本信息

- **标题**: OmniOpt: Taxonomy, Geometry, and Benchmarking of Modern Optimizers
- **作者**: 李思远、潘佳宝、刘雨谋、欧阳卓立、金鑫、徐兴龙、魏靖轩、庞盛业、车金涛、周轩鹤、何聪辉、谭成（上海AI Lab、西湖大学、上交大、UCSB、浙大、南科大等）
- **提交日期**: 2026年7月4日
- **页数**: 91页（Survey + Benchmark V1）
- **代码**: https://github.com/OpenRaiser/OmniOpt
- **项目页**: https://openraiser.github.io/OmniOpt/

### 四大核心组件

#### 1. 通用元流水线 (Universal Meta-Pipeline)
将优化器每一步分解为五个阶段：
- **S0**: 信号获取 (从loss/gradient获取信号)
- **S1**: 参数路由 (确定更新应用于哪些参数)
- **S2**: 梯度变换 (动量、二阶矩、曲率等变换)
- **S3**: 状态演化 (内部状态更新如exp_avg, exp_avg_sq)
- **S4-S5**: 重建与最终化 (LR调度、裁剪、投影等)

#### 2. LMO驱动的四轴几何分解
- **轴I: 更新域** — 全参数空间、矩阵空间、旋转坐标、低秩子空间
- **轴II: 状态估计器** — 动量、二阶矩、曲率代理
- **轴III: 几何算子** — LMO约束集或预条件器
- **轴IV: 最终化包装器** — LR、衰减、投影、裁剪

#### 3. 双重分类法

**方法家族 (T1-T5)**:
| 家族 | 代表 | 核心机制 |
|------|------|---------|
| T1 元素级自适应矩 | AdamW, Adan, RAdam | 标量控制+矩估计 |
| T2 矩阵层级结构 | Muon, Shampoo, SOAP, GaLore | 谱分解/Kronecker积/低秩 |
| T3 离散化方向 | Lion, MARS-Lion | 符号函数/量化几何 |
| T4 状态压缩 | AdaFactor, APOLLO, Adam-mini | 因子化/低比特/内存压缩 |
| T5 几何正则化 | Sophia, AdaHessian, LAMB | 曲率估计/信任域 |

**效果目标 (O1-O6)**: 收敛效率、单步成本、内存、稳定性、超参鲁棒性、泛化能力

#### 4. 跨领域基准测试
- Stage-1: C4短上下文(60M/130M/350M/1B)
- Stage-2: FineWeb-Edu 32K长上下文(Transformer++/Gated DeltaNet/DeltaNet/GLA)
- Pareto前沿分析 + 跨场景排名稳定性

### 决策指南

| 目标 | 推荐 | 理由 |
|------|------|------|
| 默认基线 | AdamW | 稳定的通用参考锚点 |
| 质量-效率平衡 | RMNP | 矩阵结构中最实用 |
| 质量上限 | SOAP | 长上下文跨场景最强 |
| 机制透明 | Muon | 强大但行为依赖拓扑 |
| 内存紧张 | AdaFactor | 安全低内存选项 |
| 低开销探索 | Lion | 速度快但接受质量差距 |
