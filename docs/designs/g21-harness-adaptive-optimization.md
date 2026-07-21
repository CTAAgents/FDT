# G21: Harness 自适应优化设计文档

> **版本**: v0.1 (设计草案)
> **日期**: 2026-07-20
> **关联**: MemoHarness (arXiv:2607.14159), AHE (Agentic Harness Engineering)

## 1. 问题陈述

当前 FDT 的 Outer Loop（自进化闭环）只优化 Agent 参数和 ML 权重，不优化 Harness 配置本身。在辩论过程中，固定 Harness 配置无法根据具体品种特性、数据可用性、市场状态进行自适应调整。

**举例**：
- 品种 ADX < 20 时，应更多依赖链证源基本面分析，减少技术面权重
- 数据源 TQ 连续失败时，应自动切换到 TqSDK 数据并调整相关 Agent 的上下文
- 上周同品种辩论分歧度持续高时，自动增加一轮反驳轮次

## 2. 设计目标

1. **运行时自适应**：基于历史执行经验，在每轮辩论启动前自动调整 Harness 六维配置
2. **正确性优先**：主指标（辩论胜率/准确率）决定排名，成本仅作平局次级指标
3. **渐进式部署**：与现有自进化循环兼容，不破坏现有逻辑

## 3. 架构设计

### 3.1 双层经验库

**E_t: 逐案例执行记录**
```python
@dataclass
class ExecutionRecord:
    trace_id: str
    loop_id: str                     # "daily-debate"
    timestamp: datetime
    task_conditions: dict            # {symbol, adx_range, source_available, ...}
    harness_config: dict             # 六维配置快照
    result: dict                     # {success, score, cost, duration}
    diagnosis: dict | None           # {failure_step, root_cause}
```

**G_t: 全局蒸馏模式**
```python
@dataclass
class DistilledPattern:
    pattern_id: str
    pattern_type: str                # "success" | "failure"
    conditions: dict                 # 匹配条件
    config_delta: dict               # 推荐的配置修正
    confidence: float                # 置信度
    sample_count: int                # 样本数
    last_updated: datetime
```

### 3.2 案例检索与适配

输入：当前任务条件（品种、ADX 区间、数据源可用性等）

流程：
1. 从 G_t 中检索条件匹配的全局模式（按 confidence * sample_count 排序）
2. 从 E_t 中检索最近 20 条相似案例（按 task_conditions 加权匹配）
3. 合并推荐：W(x_j) = W_base + mean(config_delta) — 对每个维度取 delta 均值
4. 应用适配后的配置到本轮辩论

### 3.3 模式蒸馏

触发条件：累计 20 条新 E_t 或每日凌晨

流程：
1. 对 E_t 按 task_conditions 聚类
2. 每个聚类内，对比成功案例 vs 失败案例的 config 差异
3. 生成 G_t 条目：{conditions, config_delta, confidence, sample_count}

## 4. 组件与文件

| 组件 | 文件 | 说明 |
|------|------|------|
| 经验库存储 | `memory/experience/records/` | E_t 逐条文件 |
| 蒸馏模式存储 | `memory/experience/patterns/` | G_t 文件 |
| 检索适配引擎 | `scripts/harness_adapter.py` | 核心逻辑 |
| 蒸馏引擎 | `scripts/pattern_distiller.py` | 批量蒸馏 |

## 5. 集成点

- **Pre-loop Hook**：`daily-debate.contract.yaml` pre_loop 中插入 harness_adapter
- **Post-loop Hook**：辩论完成后记录 E_t
- **与自进化循环集成**：`self-evolve.contract.yaml` 的 pipeline 中插入 pattern_distiller

## 6. 风险与应对

| 风险 | 应对 |
|------|------|
| 配置过度拟合历史数据 | 设置 min_sample_count = 5，置信度低于 0.3 不采纳 |
| 检索延迟增加辩论耗时 | 经验库使用本地 JSON 文件，检索 < 100ms |
| 蒸馏引入错误模式 | 新增 G_t 条目先进入 staging，人工确认后才生效 |
