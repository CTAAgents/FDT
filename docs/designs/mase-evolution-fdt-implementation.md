# MASE 自演化框架在 FDT 中的落地实施方案

> 基于 Fang et al. (2025) / Gao et al. (2026) 自演化综述 + FDT 现有架构分析
> 创建：2026-07-26 | 当前 FDT 版本：v10.4.2
> 关联文档：evomem-patch-memory-fdt-optimization.md, human-ai-hybrid-finance-fdt-optimization.md, code-reasoning-boundary.md
> 前置依赖：Harness 规范 12 项检查清单、L1/L2/L3 验证档位

---

## 0. 当前状态诊断：FDT 位于 MAO 阶段

FDT 当前的 Multi-Agent 辩论系统精确落在 MAO（多Agent编排）阶段：

| 维度 | FDT 当前特征 | 说明 |
|:-----|:------------|:-----|
| 是否改参数 | 不改（θ冻结） | LLM 参数不更新 |
| 反馈来源 | Agent间消息/辩论 | P2/P3/P4 之间的结构化辩论 |
| 编排方式 | **固定线性拓扑** | P1→P1.5→P2→P3→P3.5→P4→P5，每段代码硬编码 |
| 人工配置程度 | 中 | Prompt 手工维护，workflow 代码固定 |

### 存在但未形式化的 MASE 元素

FDT 有一些组件已经具备了 MASE 的雏形，只是没有被统一理论框架约束：

| 已有组件 | MASE 映射 | 缺口 |
|:---------|:----------|:-----|
| session_memory JSONL | → Optimiser 的输入信号 | 缺乏结构化补丁格式和自动反馈环 |
| gap-analysis.md | → 自演化的差距追踪 | 手动维护，未自动化 |
| 上线四步评估 | → 自演化验证护栏 | 只用于首次上线，不覆盖持续演化 |
| 口径变更 YAML 事件库 | → 环境变化记录 | Agent 运行时不可查 |

---

## 1. 总体架构：三环嵌套

```
┌─────────────────────────────────────────────────┐
│              三定律护栏（全局不可违反）              │
│  Endure：代码-推理边界 / P0 铁律 / 止损硬约束       │
│  Excel：L1/L2/L3 验证 / 上线四步评估               │
│  Evolve：在 Endure+Excel 前提下自主优化             │
└─────────────────────────────────────────────────┘
        ▲                    ▲                    ▲
        │                    │                    │
┌───────┴───────┐  ┌───────┴───────┐  ┌───────┴───────┐
│  快环（在线）    │  │  中环（每日）    │  │  慢环（版本级）  │
│  Self-Refine   │  │  Prompt优化    │  │  拓扑演化       │
│  单Agent自我修正 │  │  经验模式提取   │  │  辩论流程重组    │
│  每次运行时     │  │  每日回顾       │  │  里程碑评估      │
└───────────────┘  └───────────────┘  └───────────────┘
```

### 三环的节奏与约束

| 环 | 频率 | 操作范围 | 安全门禁 |
|:---|:-----|:---------|:---------|
| **快环（Self-Refine）** | 每次 Agent 输出前 | 仅当前输出文本 | L1 自检（JSON Schema） |
| **中环（经验反馈）** | 每次辩论结束后 | Prompt 权重 / Memory 结构 | L2 测试套件 |
| **慢环（结构演化）** | 每 N 轮辩论 / 版本迭代 | 拓扑 / Workflow / Tool | L3 独立审查 + 金丝雀放量 |

---

## 2. Phase 1：快环 — Self-Refine（预计 2 天）

### 目标

每个 Agent 在输出最终分析/论点前，执行一次自我审查和修正。基于 Madaan et al. (2023) Self-Refine 方法——同一 LLM 同时作为生成器、反馈提供者和精炼器。

### 实现方式

```
Agent 原始输出
    │
    ▼
Self-Critic Prompt：「请审查上述分析是否存在以下问题：
    1. 数据引用是否可溯源？
    2. 逻辑推理是否有明显跳跃？
    3. 是否遗漏了关键反面证据？
    请标注具体问题点。」
    │
    ▼
是否发现 >= 1 个问题？
    ├── 是 → Refine Prompt：「请根据上述批评修正分析，保留正确部分，仅修改有问题的部分」
    │         → 输出修正版（保留修正前后的版本用于分析）
    └── 否 → 直接输出（记录"无需修正"）
```

### 代码改动范围

```
agents/nodes.py 或各 Agent 的 node 函数：
- 在 return 之前插入 Self-Refine 步骤
- 输出结构增加 fields：original_output / refined_output / self_critic_issues
- 增加计数器：self_refine_rate = 触发修正的次数 / 总输出次数

config/agent_profiles.yaml：
- 每个 Agent profile 增加 self_refine 开关（默认开启）
- 增加 self_refine_max_rounds（默认 1 轮，防止无限循环）
```

### 成功标准

| 指标 | 基线 | 目标 |
|:-----|:-----|:-----|
| P4 裁决前修正率 | 0% | 15-30%（预期约 20% 的初始输出有可修正缺陷） |
| 单次输出延迟增量 | 0ms | < 3 秒（额外一次 LLM 调用） |
| Agent 幻觉/逻辑跳跃减少 | - | 人工抽查 50 份报告，问题率减半 |

### 安全约束（Endure）

- 只修正文本级问题（逻辑 / 引用 / 遗漏），不涉及数值计算
- 数值计算仍由代码层（L0）执行，Self-Refine 无权修改数据
- 修正轮数上限 = 1（禁止递归修正，防止无限循环）
- 修正前的原始输出必须完整保留在追踪记录中

---

## 3. Phase 2：中环 — 经验反馈闭环（预计 5 天）

### 目标

利用 EvoMem 补丁记忆格式，将每次辩论的偏差经验自动反馈为 Agent Prompt 的权重调整和 Memory 的结构化更新。

### 3.1 偏差检测 → 补丁创建

```
辩论完成 → 事实验证（实际走势 vs 裁决方向）
    │
    ├── 方向正确 → 记录"准确案例"，不入补丁链
    │
    └── 方向错误 → 触发偏差分析
        │
        ├── 是什么导致了偏差？
        │   - P1 数据源有误？ → 创建补丁：数据源标记
        │   - P2/P3 分析逻辑缺陷？ → 创建补丁：逻辑模式
        │   - P4 权重分配不当？ → 创建补丁：裁决权重
        │
        └── 创建 EvoMem 格式补丁（复用 evomem-patch-memory-fdt-optimization.md 定义的格式）
```

### 3.2 Prompt 权重自调整

每个 Agent 的 Prompt 内部设一组可调参数（由代码约束范围）：

**示例 — P2 观澜 Agent 的 prompt 权重参数：**

```yaml
# config/agent_profiles.yaml 中 P2 的权重段
p2_technical_weights:
  trend_weight: 0.30          # 趋势判断权重（代码范围 0.2-0.4）
  volume_weight: 0.25         # 量能分析权重（代码范围 0.15-0.35）
  structure_weight: 0.25      # 期限结构权重（代码范围 0.15-0.35）
  momentum_weight: 0.20       # 动量指标权重（代码范围 0.1-0.3）
  adjustment_step: 0.02       # 单次调整步长
  adjustment_history: []       # 调整历史，用于回滚
```

**调整规则（代码硬约束）：**

```
def adjust_weights(deviation_analysis):
    # 代码执行，LLM 无权触碰
    if 偏差原因是 "过度依赖趋势判断":
        p2_weights.trend_weight = clamp(
            p2_weights.trend_weight - p2_weights.adjustment_step,
            0.2, 0.4    # 硬边界
        )
        p2_weights.volume_weight = clamp(
            p2_weights.volume_weight + p2_weights.adjustment_step,
            0.15, 0.35
        )
    p2_weights.adjustment_history.append({
        "timestamp": now(),
        "prev_value": 旧值,
        "new_value": 新值,
        "reason": 偏差原因摘要
    })
    # 每次调整后运行 L2 测试套件，确保不退化
```

### 3.3 中环安全门禁

| 维度 | 规则 |
|:-----|:-----|
| 权重边界 | 每个参数有代码硬编码的 [min, max] 区间 |
| 单次调整 | 不超过 adjustment_step（0.02） |
| N 轮最大调整 | 任一参数累计调整不超过 ±0.1 后自动冻结，需人工审核解锁 |
| 调整后验证 | 自动运行 L2 测试套件，pass^3 要求（连续 3 次通过） |
| 回滚机制 | adjustment_history 支持精确回滚到任意历史版本 |

### 3.4 Memory 自动补丁化

复用 `evomem-patch-memory-fdt-optimization.md` 中定义的补丁格式，将偏差学习中提炼的经验教训自动写入 `_session_memory/patches.jsonl`：

```jsonl
{"patch_id":"patch-20260726-xxx","domain":"生猪|裁决偏差",
 "pre_state":"生猪做多权重=0.6，基于产能去化预期",
 "post_state":"生猪做多权重=0.4，加入屠宰量同比前置指标",
 "rationale":"过去3次偏差分析显示：屠宰量同比变化比产能消息提前2-3周",
 "evidence":["P5偏差追踪记录#20260721","P4裁决回测#20260723"],
 "conditions":{"applicable_regime":["range_market"],"valid_from":"2026-07-26",...}}
```

---

## 4. Phase 3：慢环 — 拓扑自演化（预计 8 天）

### 目标

从固定的 P1→P5 线性链条进化到条件化、可动态重组的辩论流程。

### 4.1 条件委派路径

当前固定链条：
```
P1 → P1.5 → P2 → P3 → P3.5 → P4 → P5
```

目标动态图（DAG）：
```
P1 ───→ P1.5 ───→ 信号比对 ───→ [一致] → 快速路径 → P4 → P5
                              ↘ [分歧] → P2 → P3 → P3.5 → P4 → P5
                                         ↓
                                    [P3与P2矛盾] → 强制P3.5介入
```

### 4.2 拓扑决策器

不需要引入另一个 LLM 来决策拓扑。使用**代码规则引擎**：

```python
# topology_router.py — 代码执行，无 LLM 参与

def decide_path(signal_agreement_score, volatility_regime, history_accuracy):
    """
    0. signal_agreement_score: P1 与 P1.5 的结论一致性（0-1）
    1. volatility_regime: 低/中/高（从市场状态读取）
    2. history_accuracy: 该品种近期裁决准确率趋势
    """
    if (signal_agreement_score > 0.8 
        and volatility_regime == "low" 
        and history_accuracy > 0.65):
        return "fast_path"      # 跳过P2部分分析
    
    if signal_agreement_score < 0.4:
        return "full_debate"    # 完整辩论
    
    return "standard_path"      # 常规路径
```

### 4.3 拓扑演化触发器

拓扑本身不主动"进化"，而是**由 A/B 测试驱动**：

```
当前路径配置 A（标准线性）
    vs
候选路径配置 B（条件委派）

→ 运行各 N 轮（建议 N=20）
→ 比较指标：准确率、token 成本、延迟、极端风险事件数
→ 若 B 在准确率上非劣（p<0.1 显著性检验）且成本更低 → 切换至 B
→ 切换后冻结 M 轮（M=20），之后可以再次测试新候选
```

### 4.4 慢环安全门禁

| 规则 | 约束 |
|:-----|:-----|
| 拓扑变更必须经过 A/B 测试 | 至少各 N=20 轮 |
| 每次只变一个维度 | 不变更拓扑的同时又调整 prompt 权重 |
| 有回滚预案 | 拓扑变更产生代码版本标签，单行命令回退 |
| 金丝雀先行 | 先在 1-2 个品种上运行，再扩展到全品种 |
| Endure 不妥协 | 止损/仓位/风控代码在任何拓扑下都最后执行 |

---

## 5. 执行优先级与资源评估

| Phase | 内容 | 预估工期 | 风险 | 对 FDT 的收益 |
|:------|:-----|:--------|:-----|:-------------|
| **Phase 1** | Self-Refine 快环 | 2 天 | 低 | 即时提升输出质量（~+20%），最快的ROI |
| **Phase 2a** | 偏差检测+补丁创建 | 3 天 | 低 | 开始积累结构化经验 |
| **Phase 2b** | Prompt 权重自调整 | 2 天 | 中 | 需要精心设计参数边界 |
| **Phase 3** | 拓扑自演化 | 8 天 | 高 | 架构级改动，需充分测试 |
| **持续** | A/B 测试基础设施 | 3 天 | 低 | 托底所有演化的验证 |

### 建议实施顺序

**Week 1-2**：Phase 1（Self-Refine）+ Phase 2a（偏差检测）
→ 快速见效果，积累运行数据

**Week 3-4**：Phase 2b（Prompt 权重调整）+ A/B 测试基础设施
→ 利用 Phase 2a 积累的数据驱动权重调整

**Week 5-6**：Phase 3（拓扑自演化）
→ 利用前两个阶段的运行经验和验证结果

---

## 6. 与现有 FDT 架构的兼容性

| 现有组件 | 兼容性 |
|:---------|:-------|
| 代码-推理边界（P0） | 本方案完全遵循：代码负责所有权重调整/拓扑决策/边界控制，LLM 只负责文本生成与自我审查 |
| Harness 12 项检查清单 | 需增加 C20（自演化合规检查）、C21（A/B 测试记录完整性） |
| L1/L2/L3 验证 | Self-Refine 纳入 L1；Prompt 调整纳入 L2；拓扑变更纳入 L3 |
| project_memory.md | 每个 Phase 实施后在 project_memory 中记录经验教训 |
| debate_journal.json | 增加 self_refine 字段记录，用于后续分析修正效果 |

---

## 7. 不做的事（明确界限）

为防止自演化滑向规范博弈（Specification Gaming），明确以下不可演化的东西：

| 不可演化项 | 原因 | 对应 Endure 原则 |
|:-----------|:-----|:----------------|
| 止损/目标价计算逻辑 | 基于 ATR 的精确计算，不可由 LLM 调整 | 代码层硬约束 |
| 仓位上限 | 风控红线，与辩论结果无关 | P0 铁律 |
| 风控审批流程 | P5 必须独立于辩论 Agent | 角色边界钉死 |
| 数据源选择优先级 | FDC/AKShare 层级由代码决定 | 代码-推理边界 |
| 辩论轮数上限 | 防止无限循环，保证系统终止 | AP07 反模式 |

---

## 8. 与已有优化文档的关系

| 已有文档 | 与本方案的关系 |
|:---------|:--------------|
| human-ai-hybrid-finance-fdt-optimization.md | Phase 2 的"委派前沿"概念在 Phase 3 中实现为条件委派路径 |
| evomem-patch-memory-fdt-optimization.md | Phase 2 的补丁格式直接复用该文档定义；Patch Memory 提供 MASE 所需的反馈信号 |
| code-reasoning-boundary.md | 本方案全部调参/拓扑决策由代码执行（L0），LLM 只做文本自我审查（遵循三级分类） |
| 08-gap-analysis.md | 三个 Phase 完成后关闭对应的 GAP 条目 |
