# G21: Harness 自适应优化设计文档

> **版本**: v1.0 (MemoHarness + RHI 整合)
> **日期**: 2026-07-23
> **关联**: MemoHarness (arXiv:2607.14159), RHI (arXiv:2607.15524), AHE

## 1. 问题陈述

当前 FDT 的 Outer Loop（自进化闭环）只优化 Agent 参数和 ML 权重，不优化 Harness 配置本身。在辩论过程中，固定 Harness 配置无法根据具体品种特性、数据可用性、市场状态进行自适应调整。

两篇论文提供了互补的解决方案：

| 维度 | MemoHarness | RHI |
|:-----|:------------|:----|
| 核心方法 | 从执行经验学习，六维空间搜索 + 双层经验库 | 轨迹局部 pairwise 比较，O(1) 每轮 |
| 搜索空间 | D1-D6 六维 Harness 控制空间 | 三层 Harness 规范 (Agent/Workflow/Rules) |
| 优化方式 | 训练时搜索 → 测试时检索适配 | 递归自改进，对比前后两轮产出 |
| 经验存储 | Et (案例级) + Gt (全局模式) | Dx (pairwise 偏好历史) |
| 适合场景 | 跨任务模式挖掘 + 冷启动 | 单任务快速迭代 + 低成本优化 |

**本文档将两者整合为统一方案**：RHI 提供快速的轨迹局部搜索，MemoHarness 提供跨任务经验复用。

## 2. 设计目标

1. **Harness 自优化**：基于 pairwise 偏好反馈，递归优化 RHI 三层 Harness 规范
2. **经验复用**：跨案例/跨品种的 MemoHarness 式经验检索 + 全局模式蒸馏
3. **低成本**：每轮仅需 1 次辩论执行 + 1 次 pairwise 评估 — O(1) 而非 O(m²)
4. **正确性优先**：辩论质量 (质检得分 + 风控通过率 + 信号质量) 决定排名，成本仅做次级指标
5. **渐进式部署**：与现有自进化循环兼容，不破坏现有逻辑

## 3. 架构设计

### 3.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                    RHI 递归自改进循环                             │
│                                                                  │
│  Hⁱ (当前Harness)                                                │
│    │                                                             │
│    ▼                                                             │
│  Agent A 用 Hⁱ 执行辩论 → 产出 outputⁱ                           │
│    │                                                             │
│    ▼                                                             │
│  Pairwise Evaluator Leval(outputⁱ, outputⁱ⁻¹) → 偏好反馈         │
│    │                                                             │
│    ▼                                                             │
│  偏好历史 Dx 累积: {Leval(outputᵏ, outputᵏ⁻¹)}_k=1..ⁱ            │
│    │                                                             │
│    ▼                                                             │
│  Harness Optimizer Lharness(Hⁱ, Dx) → Hⁱ⁺¹                       │
│    │                                                             │
│    ▼                                                             │
│  停止条件: 改进率 sⁱ < ε(0.3) 或 最大轮次(5)                     │
│    │                                                             │
│    ▼                                                             │
│  H* (优化后的最优Harness) → 持久化到经验库                        │
│                                                                  │
│  ─── MemoHarness 经验层 ───                                      │
│  Et 记录: {task_conditions, harness_config, result, diagnosis}    │
│  Gt 蒸馏: 跨案例模式 {conditions, config_delta, confidence}       │
│  测试时适配: W(x_j) = W* + retrieve(Et, Gt)                     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Harness 三层规范 (RHI 定义)

FDT 的 Harness 按 RHI 论文分解为三层文本规范：

#### ① Agent Candidates — 候选 Agent 定义

```
每个 Agent = {role, instruction, contract(out-to-orchestrator)}

FDT 映射:
  观澜       → role:"technical_researcher",
               instruction:"作为技术面研究员（观澜），请分析以下品种的技术面状态...",
               contract:{trend, key_levels, volume_price, divergence, pattern, score}
  探源       → role:"fundamental_researcher",
               instruction:"作为基本面研究员（探源），请分析以下品种的基本面状态...",
               contract:{supply_demand, inventory, profit_margin, basis_term, macro_external, leading_signals}
  链证源     → role:"chain_researcher",
               contract:{chain_structure, cost_profit, capacity, policy_impact}
  读心       → role:"sentiment_analyst",
               contract:{news_summary, sentiment_shift, key_events}
  多头分析员 → role:"bullish_analyst",
               contract:{arguments, confidence, source_refs}
  空头分析员 → role:"bearish_analyst",
               contract:{arguments, confidence, source_refs}
  闫判官     → role:"judge",
               contract:{direction, confidence, entry_price, stop_loss, target1, reason}
  风控明     → role:"risk_manager",
               contract:{risk_level, check_items, conclusion}
```

#### ② Workflow — 流程定义 (Contract + Hop)

```
Contracts — 子Agent间信息传递契约:
  DebateState 字段定义
  per_symbol_tech ← 观澜 → orchestrator
  per_symbol_fund ← 探源 → orchestrator
  chain_report ← 链证源 → orchestrator
  sentiment ← 读心 → orchestrator
  bullish_arguments ← 多头 → orchestrator
  bearish_arguments ← 空头 → orchestrator
  verdict ← 闫判官 → 风控明
  risk_check ← 风控明 → 品藻

Hops — 交互步骤:
  Hop 0: P0 数技源扫描 → scan_results
  Hop 1: P1 链证源产业链分析 → chain_reports
  Hop 2: P2 闫判官初判 → selected_symbols, dispatch_sources
  Hop 3: P2.5 FDC 数据准备 → fdc_data
  Hop 4: P3 四源并行 → 观澜/探源/链证源/读心
  Hop 5: P3 六阶段攻防辩论 → 立论×2 → 反驳×2 → 结辩×2
  Hop 6: P4 闫判官终裁 → verdict
  Hop 7: P5 风控明审核 → risk_check
  Hop 8: P6 品藻汇总输出 → debate_report
```

#### ③ Auxiliary Rules — 辅助规则

```
验收门禁:
  - 12 项 commit 前检查清单 (C01-C12)
  - 10 条反模式检测 (AP01-AP10)
  - 验证器质量度量 (漏放率 ≈ 0%, 误杀率 < 20%)

回退规则:
  - D06 降级: 任一源超时(300s)跳过，其余继续
  - 辩论降级: 辩论阶段超时(600s)跳过，arguments=[] 继续
  - NO_FUSION: 8 策略独立打分，方向冲突交辩论层裁决

通信规则:
  - Agent 只写文件不通信
  - 辩手禁搜 (依赖分析师供弹)
  - 禁止代写 (闫判官不得替风控做决策)
  - DataCore→TDX→TqSdk→QMT→WebFallback 四级降级链

召回触发:
  - ADX<20: 鼓励确认，增加基本面权重
  - ADX≥60: 不得作为致命伤，提及占比 ≤ 1/3
  - 分歧度>0.7: 追加深度辩论轮次
```

### 3.3 RHI 算法实现

```python
Algorithm 1: Recursive Harness Self-Improvement (FDT 适配版)

输入: 品种集合 {symbols}, Agent A, Pairwise Evaluator Leval,
     Harness Optimizer Lharness, 停止阈值 ε=0.3, 最大轮次 N=5
初始化: H⁰ = 当前 FDT Harness（从 agents/ + graph.py + rules/ 加载）
     Dx = [] (pairwise 偏好历史)
首次执行: Agent A 用 H⁰ 执行辩论 → output⁰

循环 i = 1..N:
  1. Agent A 用 Hⁱ 执行辩论 → outputⁱ
  2. Leval(outputⁱ, outputⁱ⁻¹; 品种, 任务描述) → 偏好:
     - "改进" (outputⁱ 更优)
     - "退步" (outputⁱ⁻¹ 更优)
     - "平局" (质量相当)
  3. Dx ← Dx ∪ {Leval结果}
  4. 计算改进率 sⁱ = (改进次数 / 总比较次数)
  5. 若 sⁱ < ε: BREAK
  6. Lharness(Hⁱ, Dx) → Hⁱ⁺¹

返回 H* = argmax_{H∈{H⁰..Hⁱ}} Leval(H output)

集成点:
  - 在 evolution_graph.py 中新增 RHI 分支
  - Pairwise Evaluator 复用 quality_inspector.py
  - Harness Optimizer 使用 LLM agent (FdtAgentExecutor)
```

### 3.4 Pairwise Evaluator 评估维度

评估两次辩论产出 quality_report 时，使用以下四维评分：

| 维度 | 权重 | 度量方式 | 数据来源 |
|:-----|:----:|:---------|:---------|
| 质检通过率 | 0.35 | 未通过质检的品种数 + issue 严重度 | `quality_report` |
| 风控通过率 | 0.25 | green/yellow 品种占比 | `risk_check` |
| 信号质量 | 0.25 | CTP 信号数 + confidence 均值 | `signal_report` |
| 报告完整性 | 0.15 | 缺失区块数、占位文本、裁决覆盖率 | `check_report_integrity` |

总分 = Σ(维度得分 × 权重)，直接比较两轮产出的总分。

### 3.5 结合 MemoHarness 双层经验库

RHI 产生的优化 Harness H* 持久化到 MemoHarness 双层经验库：

**Et (案例级条目)**:
```python
{
    "trace_id": "fdt-20260723-...",
    "loop_id": "daily-debate",
    "timestamp": "2026-07-23T17:41:00",
    "task_conditions": {
        "symbols": ["CF2609", "SF"],
        "adx_range": "low (<20)",
        "data_source_status": "tdx=ok, tq=fail"
    },
    "harness_config": {
        "dispatch_sources": ["chain", "technical", "fundamental"],
        "debate_rounds": 6,
        "quality_threshold": 0.7
    },
    "result": {
        "quality_score": 0.85,
        "signal_count": 3,
        "risk_passed": "green"
    },
    "diagnosis": {"weak_areas": ["fundamental_llm_parse"]},
    "preference_history": [  # RHI pairwise 历史
        {"iteration": 1, "preference": "improve", "rationale": "..."},
        {"iteration": 2, "preference": "improve", "rationale": "..."}
    ]
}
```

**Gt (全局蒸馏模式)** — 在 pattern_distiller.py 中从多个 Et 聚类生成：
```python
{
    "pattern_id": "Gt-20260723-001",
    "pattern_type": "success",
    "conditions": {"adx_range": "low (<20)", "symbol_type": "chemical"},
    "config_delta": {
        "dispatch_sources": {"chain_weight": "+0.2", "technical_weight": "-0.1"},
        "debate_rounds_diff": 0,
        "contract_mod": {"fundamental_leading_signals": "expand"}
    },
    "confidence": 0.85,
    "sample_count": 12,
    "rhi_iters": 3  # RHI 收敛所需的迭代次数（新指标）
}
```

### 3.6 测试时适配 (MemoHarness Phase B)

运行新品种前，执行：

1. 从 Gt 检索匹配的全局模式 (按 confidence × sample_count 排序)
2. 从 Et 检索最近 20 条相似案例 (按 task_conditions 加权匹配)
3. 合并推荐: W(x_j) = H* + mean(config_delta)
4. 应用适配后的配置到本轮辩论
5. 可选：用适配后的配置作为 RHI 初始 H⁰，进一步微调

### 3.7 停止条件 (RHI 改进率)

```
sⁱ = (∑_{k=1..i} 1[outputᵏ ≻ outputᵏ⁻¹]) / i

条件:
  - sⁱ < 0.3: 连续无改进，停止 (RHI 论文建议)
  - i >= N (max=5): 达最大轮次，停止
  - 改进但质检 FAIL 数增加: 回退到前一轮 Hⁱ⁻¹
```

## 4. 组件与文件

| 组件 | 文件 | 说明 |
|:-----|:-----|:------|
| Harness 三层规范定义 | `contracts/rhi_harness_spec.py` | HarnessSpec TypedDict |
| Pairwise Evaluator | `scripts/rhi_pairwise_eval.py` | 两轮产出对比评分 |
| Harness Optimizer (LLM) | `scripts/rhi_harness_optimizer.py` | LLM 基于偏好历史更新 Harness |
| RHI 主循环 | `fdt_langgraph/rhi_graph.py` | RHI LangGraph 子图 |
| 经验库存储 | `memory/experience/records/` | Et 逐条文件 (已有) |
| 蒸馏模式存储 | `memory/experience/patterns/` | Gt 文件 (已有) |
| 检索适配引擎 | `scripts/harness_adapter.py` | 核心逻辑 (已有) |
| 蒸馏引擎 | `scripts/pattern_distiller.py` | 批量蒸馏 (已有) |

## 5. 集成点

- **自进化闭环** (evolution_graph.py): RHI 作为自进化的新增分支（与 improve/calibrate/evolve/ml_train 同级）
- **Pre-loop Hook** (daily-debate.contract.yaml): 插入 MemoHarness 式案例适配
- **Post-loop Hook**: 辩论完成后写入 Et + 偏好历史
- **Pattern Distiller**: 新增 RHI 迭代次数作为蒸馏指标
- **全局 Harness** (CLAUDE.md): 同一套 RHI 模式，但作用于项目级 prompt 规范

## 6. 实施阶段

| 阶段 | 内容 | 交付物 |
|:----:|:-----|:--------|
| Phase 1 | HarnessSpec TypedDict + 现有组件映射 | `contracts/rhi_harness_spec.py` |
| Phase 2 | Pairwise Evaluator — 两轮产出四维对比 | `scripts/rhi_pairwise_eval.py`, 测试 |
| Phase 3 | Harness Optimizer — LLM 基于偏好历史更新 Harness | `scripts/rhi_harness_optimizer.py` |
| Phase 4 | RHI Loop — evolution_graph.py 集成 RHI 分支 | `fdt_langgraph/rhi_graph.py`, 测试 |
| Phase 5 | 经验库集成 — Et 记录偏好历史 + Gt 标注 RHI 迭代次数 | `scripts/harness_adapter.py` 更新 |
| Phase 6 | 全局 Harness — CLAUDE.md RHI 自优化 | `scripts/rhi_global_harness.py` |

## 7. 风险与应对

| 风险 | 应对 |
|:-----|:------|
| Pairwise 评估噪声大 (LLM 判断不稳定) | 使用 quality_inspector 结构化指标做硬评分，LLM 仅做 Reason 生成 |
| Harness 更新后破坏现有功能 | Hⁱ → Hⁱ⁺¹ 前后运行 regression test，失败自动回退 |
| 多轮 RHI 累积使 Harness 过度特化 | 每轮限制修改幅度 + 最大 5 轮硬限制 |
| RHI 与现有 evolution_graph 冲突 | RHI 作为独立分支（decision 路由），不修改现有 improve/calibrate 路径 |

## 8. 评价指标

| 指标 | 目标 | 度量方式 |
|:-----|:----:|:---------|
| RHI 收敛轮次 | ≤ 5 | 达到 sⁱ < 0.3 的轮次 |
| 每轮改进率 | > 0.3 | sⁱ 值 |
| 质检通过率提升 | +10% | 对比 H⁰ vs H* |
| 风控 green 占比提升 | +15% | 同上 |
| 跨品种迁移成功率 | > 60% | H* 在新品种上不退化 |
| RHI 额外耗时 | < 5min/轮 | 对比标准辩论耗时 |

## 9. 与现有文档的关系

| 文档 | 关系 |
|:-----|:------|
| `01-architecture.md` §6.3 | RHI 作为自进化闭环新增分支，更新架构图 |
| `02-lifecycle.md` §3 | 新增 "RHI 迭代" 阶段定义 |
| `03-configuration.md` | 新增 RHI 相关环境变量 (FDT_RHI_MAX_ITER, FDT_RHI_EPSILON) |
| `05-observability.md` | RHI 迭代轨迹指标 (改进率、收敛轮次) |
| `06-testing.md` | 新增 RHI 测试用例计数 |
| `07-operations.md` | 版本号追踪 |
| `08-gap-analysis.md` | G112 RHI 集成、G113 MemoHarness 全局模式蒸馏 |
