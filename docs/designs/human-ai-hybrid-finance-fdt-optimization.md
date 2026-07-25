# Human-AI Hybrid Finance 框架下的 FDT 系统优化方案

> 基于 Financial Innovation (Springer, 2026) 论文《Human–AI Hybrid Finance: An Integrated Decision-System Framework》的跨领域应用分析
> 创建：2026-07-26 | 最后更新：2026-07-26 @ v10.4.2
> 关联文档：01-architecture.md, 02-lifecycle.md, 06-testing.md, 07-operations.md, 08-gap-analysis.md

---

## 1. 背景与核心论点

论文提出从"AI in Finance"到 **"Human–AI Hybrid Finance"** 的范式转移，核心难题是：**强独立的 AI ≠ 强混合金融决策**。一旦 AI 嵌入金融工作流，结果不仅取决于模型性能，还取决于决策权分配、人类依赖校准、可解释性、实质性监督和反馈循环。

FDT 当前已实现的高度自动化 Multi-Agent 辩论→裁决流程（**v10.4.2**，12 Agent，3 张 LangGraph 子图，双层循环架构，**代码-推理边界硬切割**），正是论文描述的"混合决策系统"的典型实例。本文基于论文的五个核心构念，评估 FDT 当前在此框架下的成熟度，并提出下一阶段优化方向。

> **版本说明**：本文创建时 FDT 为 v9.x 时代。截至 v10.4.2，FDT 已完成：
> - FDC→AKShare 数据源迁移（v10.0.0）
> - 记忆系统全面重构（MemoryManager + VectorMemory + 自进化规则注入）
> - 数据清洗层 Phase 1-3（K线完整性 + 期货专项 + 基本面清洗）
> - fundamental-data-collector 数据结构化升级 + DuckDB 优先 + 清洗管线对接
> - 口径变更 YAML 事件库 + Agent Prompt 数据质量警告注入
> - **P2.5 多因子注入**：波动率/跨品种价差/期限结构/多空持仓因子数据层（v10.2.0-10.3.0）
> - **代码-推理边界硬切割**：stop_loss/target 代码计算(L0)、仓位钳制(L0)、技术评分 LLM±10微调(L1)（v10.4.0）
> - **nodes.py 模块拆分**：2031 行 nodes.py 拆为 8 个 _nodes_*.py 模块（v10.4.1）
> - **scripts/ 目录结构化**：verification/ + harness/ 子目录整理（v10.4.2）

### FDT 对论文建议的采纳策略

本文分析论文五大构念时，并非全盘接受所有建议，而是基于 FDT 作为**全自动 CTA 决策系统**的设计意图进行筛选：

| 态度 | 论文建议 | FDT 立场 |
|:-----|:---------|:---------|
| ✅ **采纳 + 增强** | 反身性 AI 循环、委派前沿、XAI、置信度校准 | 与自动化目标兼容，可作为 Phase A-E 实施 |
| ⚡ **采纳 + 已有** | 有意义的监督（三层次验证） | L0-L3 验证已实现，T3 待增强 |
| ❌ **不采纳** | 实时人工介入、降低自动化程度 | CTA 策略要求毫秒级执行，人工在规则层（非交易层）介入 |

FDT 在论文框架之外有自己的独创设计——**L0 代码硬约束**、**数据清洗层**、**Harness 工程规范**——这些是论文未覆盖但在工程实践中必要的补充。

---

## 2. 五大构念与 FDT 优化映射

### 2.1 反身性 AI 循环（Reflexive AI Loop）→ 建立决策反馈闭环

**当前状态（v10.4.2）**：

| 方面 | 已实现 | 未实现 |
|:-----|:-------|:-------|
| 历史存储 | ✅ VectorMemory 存储裁决/方向/PnL，支持跨 session 查询 | ❌ 无结构化裁决数据库与事后走势配对 |
| 历史注入 | ✅ `_build_fdc_fundamental_context()` 注入 VectorMemory 历史记忆 | ❌ 无校准后的历史准确率 |
| 自触发 | ✅ Outer Loop APM-CS 五轴评分 + RHI 自改进 | ❌ 无"连续偏差→品藻深度分析"触发 |
| 反馈闭环 | ✅ evolution_graph 含 improve/calibrate/evolve 节点 | ❌ 各 Agent 权重不自适应 |
| 代码硬约束 | ✅ L0 边界（stop_loss/target/仓位）由代码精确计算 | — |

**优化建议**：

| 层级 | 措施 | 优先级 | 前置条件 |
|:-----|:-----|:------:|:---------|
| **A. 裁决数据库升级** | 将当前 VectorMemory 的裁决记录扩展为结构化 `裁决结果表`，每轮辩论 ID 与事后 N 日实际走势配对 | P1 | 无 |
| **B. 历史准确率注入** | 在 P4 闫判官/ P5 风控 context 中注入"系统对该品种/类似形态的历史判断准确率分布" | P1 | 裁决数据库就绪 |
| **C. 偏差自触发** | 当 D2 (Acuity) 连续 3 轮下降或裁决偏差超阈值时，自动触发 P3.5 品藻深度分析 | P2 | APM D2 持续运行 |
| **D. 动态权重** | 建立"裁决→校准→权重调整"闭环，各 Agent 及信号权重随历史表现动态调整 | P2 | A+B 完成后 |

---

### 2.2 委派前沿（Delegation Frontier）→ 显化 Multi-Agent 委派协议

**当前状态（v10.4.2）**：

FDT 当前 12 个 Agent 角色采用 **LangGraph 条件边路由**，v10.4.0 新增代码-推理边界。
人机边界采用**非对称设计**——实时交易零人工干预，规则/门禁/审计层保留人工：

| 层面 | 人机策略 | FDT 实现 |
|:-----|:---------|:---------|
| 🚫 **实时交易决策** | 零人工干预 | 全自动辩论→裁决→信号输出，CTA 策略目标 |
| 👤 **规则/阈值设定** | 人工定义 | Harness 规范、decode_config、仓位上限、新鲜度阈值 |
| 👤 **异常标记** | 分歧超阈值→人工复核 | 副判官分歧标记（已有机制） |
| 👤 **事后审计** | 人工阅读报告 | HTML 辩论报告供人评估 |
| 🤖 **L0 代码硬约束** | LLM 不可覆盖 | `_compute_stop_target()` / `_clamp_position()` 精确计算 |
| 🎛️ **L1 评分微调** | LLM ±10 范围 | `technical_score.py` 代码计算基准分，LLM 仅微调 |

> L0/L1 是代码层约束（§2.1 已详述），非流程路由，不在下方重复列出。

**条件委派路径分析**：

基于 FDT 实际流程（P1→P1.5→P2→P3→P4→P3.5→P5→P6），当前委派/条件路由已实现：

| 委派点 | 当前实现 | 说明 |
|:-------|:---------|:-----|
| P0b 新鲜度闸门 | ✅ 数据不达标→降级裁决 | 已有 |
| P3 源超时 | ✅ 单源 300s 超时跳过 | 已有 |
| P3.5 质检重试 | ✅ FAIL<2 次退回重修 | 已有 |
| G19 无品种跳转 | ✅ 质检全 FAIL 跳过辩论+终裁 | 已有 |
| 副判官分歧 | ✅ 分歧超阈值→人工复核标记 | 已有 |

**可新增的条件委派路径**（基于已有约束，非臆测）：

| 场景 | 委派策略 | 依据 | 优先级 |
|:-----|:---------|:-----|:------:|
| P3 某源连续 N 轮历史准确率 < 40% | 主动跳过该源（不等 300s 超时） | 已有超时降级机制，可提前决策 | P2 |
| P4 闫判官初判置信度 > 85% + 多空明确 | 跳过副判官独立裁决层级 | 副判官分歧阈值已存在，可反向应用 | P2 |
| P3 基本面与 P2 技术面矛盾 | 在 P4 辩论 prompt 中标注"矛盾点"供论辩聚焦 | prompt 工程，不改流程 | P2 |

**实现路径**：创建 `delegation-protocol.md`，每条规则包含触发条件、跳过步骤、恢复条件、回退机制，并编码为 LangGraph 条件边。

---

### 2.3 有意义的监督（Meaningful Oversight）→ 验证标准分层

**当前状态（v10.4.2）**：

验证体系已较完善。v10.4.0 引入代码-推理边界后，**L0 验证**成为新增层次：

| 验证层 | 覆盖范围 | FDT 实现 | 成熟度 |
|:-------|:---------|:---------|:------:|
| **L0 代码验证** | 交易参数硬约束 | `_compute_stop_target()` 精确计算 + `_clamp_position()` 钳制上限 | ✅ 强 |
| **T1 技术主张** | 信号提取/指标计算 | L1 JSON Schema + 数据清洗层 66 测试 + `technical_score.py` 代码化评分 | ✅ 强 |
| **T2 组织主张** | 工作流决策质量 | L2 测试套件 + 品藻质检（含 conditional_required）+ 副判官独立裁决 + 一致性裁判审计 | ✅ 中强 |
| **T3 稳定主张** | 外部性与长期效果 | ④ 上线四步评估（Shadow→Golden→度量→Canary）+ APM D2/D5 + RHI 自改进 | ⚠️ 待增强 |

**T3 增强方向**：

| 措施 | 说明 | 优先级 |
|:-----|:-----|:------:|
| **连续偏差跟踪** | 每轮裁决的实际走势与预测方向配对，计算滚动偏差率 | P1 |
| **策略一致性指标** | 同一品种在不同波动率区间下的裁决一致性 | P2 |
| **报告裁决溯源树** | HTML 报告中标注"每个交易参数由哪些 Agent 论点支撑" | P2 |
| **T3 纳入检查清单** | 将 T3 验证标准写入 `harness-rules.yaml` C13 | P2 |

---

### 2.4 决策有用的 XAI → 最小关键证据集

**当前状态（v10.4.2）**：

| 阶段 | 当前 XAI 水平 | 现状 |
|:-----|:--------------|:-----|
| P1/P1.5 | 10 通道独立打分（NO_FUSION 零融合），不标注影响权重 | 无 Top-N 标注 |
| P2 观澜 | LLM 推理生成 TechnicalOutput，含关键指标列表 | 无分歧点聚焦 |
| P2.5 多因子 | `technical_score.py` 代码化评分（4维度加权），LLM 在 ±10 范围微调 | 评分可溯源但未展示给读者 |
| P3 探源 | LLM 推理生成 FundamentalStateVector | 无边际贡献排序 |
| P4 闫判官 | 六维评分裁决 + L0 代码硬约束 stop_loss/target/仓位 | 无关键推理路径 |
| P5 风控 | green/yellow/red 审核 + 红线 conditions | 红线条件可用 |

**优化做法**：

| 阶段 | 优化做法 | 改动量 |
|:-----|:---------|:------:|
| P1/P1.5 | `scan_all.py` 输出 Top-3 对方向判断影响最大的指标 | 小（新增字段） |
| P2 观澜 | LLM prompt 要求输出**关键分歧点**（与 scan 判断不一致处） | 小（Prompt 修改） |
| P3 探源 | 聚焦对方向有**边际影响**的因素，标注"关键转折数据" | 小 |
| P4 闫判官 | 输出**如果-那么推理链**（If X then bull; If Y then bear; X>Y→bull） | 中 |
| **报告输出** | 裁决溯源树：每个交易参数标注支撑它的 Agent 及关键论点 | 中 |

---

### 2.5 依赖楔子（Reliance Wedge）→ 置信度校准

**当前状态（v10.4.2）**：

- Agent 输出原始置信度（0-100），无校准
- VectorMemory 记录历史裁决结果，可用于事后校准
- evolution_graph 的 `calibrate_weights` 节点仅校准 LLM 参数权重，不校准置信度
- v10.4.0 引入**技术评分校准**：`technical_score.py` 计算基准分，LLM 仅在 ±10 范围微调——这是**评分层**的校准，但置信度校准尚未实施

**待实现**：

1. **置信度-准确率校准曲线**：历史裁决按置信度分桶（0-20/20-40/.../80-100），计算每桶实际准确率
2. **校准后置信度**：报告输出校准后的置信度，而非 Agent 原始置信度
3. **校准触发**：当校准偏差（校准后-原始 > 15%）超阈值时自动触发 `calibrate_weights`

```python
# 示例：置信度校准逻辑
buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
for low, high in buckets:
    subset = [v for v in verdicts if low <= v.confidence < high]
    accuracy = sum(1 for v in subset if v.outcome == v.prediction) / len(subset)
    calibration_map[(low, high)] = accuracy
```

---

## 3. 三个主张层次在 FDT 的应用

| 主张层次 | FDT 示例 | 验证方式 | 当前成熟度 |
|:---------|:---------|:---------|:-----------|
| **L0 代码验证** | stop_loss/target/仓位精确计算，不可被 LLM 覆盖 | `_compute_stop_target()` + `_clamp_position()` 代码测试 | 🟢 强 |
| **技术主张** | K 线 OHLC 一致性、RSI 计算、技术评分 4 维度加权 | L1 自检 + JSON Schema + 数据清洗层 66 测试 + `technical_score.py` | 🟢 强 |
| **组织主张** | Multi-Agent 辩论→裁决→风控全链路 | L2 测试套件 (595+) + 副判官独立裁决 + 一致性裁判审计 | 🟡 中强 |
| **市场/福利主张** | 策略历史胜率、波动率匹配、长期一致性 | Shadow→Golden→度量→Canary 四步评估 + APM D2/D5 + RHI | 🟠 待增强 |

**治理差距**：FDT 对 T3（市场/福利主张）的验证仍较薄弱。当前仅通过 APM D2/D5 和 RHI 自改进覆盖，缺乏独立于回测的市场效果评估。

---

## 4. 另类数据治理

论文关键区分：**预测信号 ≠ 决策相关证据**。

FDT v10.4.2 在数据治理方面的进展：

| 数据源 | 已实现的治理 | 待加强点 |
|:-------|:------------|:---------|
| K 线数据 | ✅ Phase 1-2 清洗（OHLC/去重/离群值/复权/期货专项） | 无 |
| 基本面快照 | ✅ Phase 3 清洗（缺失/值校验/新鲜度/口径/修订）+ 结构化 _meta | 无 |
| 多因子数据 | ✅ P2.5 因子层（波动率/价差/期限结构/多空持仓）+ 代码化技术评分 | 无 |
| 网络 RSI/ADX | ✅ 数据源标记（FDC vs 网络）+ ⚠ 警告框 | **来源稳定性标注** + **代理偏见标注**（待实现） |
| 新闻 | ✅ `NewsRouter` 多源聚合 + 金十 MCP + 去重 + 质量报告 | **信息层级标注**（一手/二手/推测）待实现 |
| 产业链数据 | ✅ data_adapter 统一接口 + freshness_level | **异常事件标签**待实现 |
| 口径变更 | ✅ YAML 事件库 + caliber_warnings 注入 Agent context | 无 |
| 交易参数 | ✅ L0 代码硬约束（stop_loss/target/仓位不可被 LLM 覆盖） | 无 |

---

## 5. 实施路线

| Phase | 焦点 | 关键交付物 | 优先级 | 前置依赖 |
|:------|:-----|:----------|:------:|:---------|
| **Phase A** | 裁决数据库 + 历史准确率注入 | 裁决结果表 Schema + VectorMemory 增强 + 校准曲线 | P1 | 无 |
| **Phase B** | 最小关键证据集 | P1 Top-N 指标 + XAI 推理链 + 裁决溯源树组件 | P1 | Phase A（提供历史对比基准） |
| **Phase C** | 置信度校准 | `calibrate_confidence()` 模块 + 校准后置信度输出 | P2 | Phase A（历史数据积累） |
| **Phase D** | 条件委派协议 | `delegation-protocol.md` + LangGraph 条件边扩展 | P2 | 无 |
| **Phase E** | T3 验证增强 | 连续偏差跟踪 + 策略一致性指标 + 纳入 harness-rules | P2 | Phase A+D |
| **Phase F** | P3 源主动跳过 | 连续准确率跟踪 + 源调度智能跳过 | P2 | Phase D（委派协议就绪） |

### 版本建议

- Phase A+B → v10.5.0（裁决反馈闭环 + 关键证据集）
- Phase C+D → v10.6.0（置信度校准 + 条件委派协议）
- Phase E+F → v10.7.0（T3 验证增强 + P3 源主动跳过）

### Phase 详细实施规划

#### Phase A：裁决数据库 + 历史准确率注入（P1）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① 裁决结果表 Schema 已定义并生效，可存储每轮辩论 ID + 品种 + 方向 + 置信度 + 事后 N 日走势 ② VectorMemory 扩展支持按品种/方向/置信度区间查询历史准确率 ③ 校准曲线模块可输出置信度-准确率分布桶（每 20% 一档） ④ P4/P5 Agent context 已注入"该品种历史判断准确率分布" |
| **改动范围** | `memory/` → 新增裁决结果表 TypedDict/Schema；`memory/vector_memory.py` → 扩展 `query_accuracy()` 接口；`fdt_langgraph/_nodes_*.py` → P4/P5 context 构建函数注入历史准确率；`docs/harness/01-architecture.md` → 更新记忆架构图 |
| **风险/难点** | 裁决历史数据回填可能需要迁移已有 VectorMemory 记录；事后走势窗口（N 日）选择需人工确定（建议默认 5 交易日） |

#### Phase B：最小关键证据集（P1）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① `scan_all.py` 输出新增 `top_n_indicators` 字段（Top-3 对方向判断影响最大的指标） ② 观澜 prompt 要求输出"与 scan 判断不一致的关键分歧点" ③ 探源 prompt 标注"具有边际影响的关键转折数据" ④ 闫判官裁决包含 `if_that_reasoning` 字段（如果-那么推理链） ⑤ HTML 报告新增裁决溯源树组件，每个交易参数标注支撑 Agent 及关键论点 |
| **改动范围** | `scripts/scan_all.py` → 新增 Top-N 输出字段；`fdt_langgraph/_nodes_technical.py` → 观澜 prompt 修改；`fdt_langgraph/_nodes_fundamental.py` → 探源 prompt 修改；`fdt_langgraph/_nodes_verdict.py` → 裁决输出扩展；`fdt_langgraph/templates/` → 报告模板新增溯源树 |
| **风险/难点** | Prompt 修改可能影响现有输出格式，需做好 pydantic Schema 版本兼容 |

#### Phase C：置信度校准（P2）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① `calibrate_confidence()` 模块实现：按置信度分桶（0-20/20-40/.../80-100）计算每桶实际准确率 ② 报告输出校准后置信度（而非 Agent 原始置信度） ③ 校准偏差超阈值时自动触发 `calibrate_weights` 节点 ④ 校准曲线可查询（存为 VectorMemory 键值对或 JSON，按品种分类） |
| **改动范围** | `memory/calibration/` → 新增 `calibrate.py`（校准算法）+ `calibrate_test.py`（校准测试）；`fdt_langgraph/evolution_nodes.py` → 校准触发逻辑；`fdt_langgraph/_nodes_verdict.py` → 报告置信度输出替换 |
| **前置依赖** | Phase A（需积累足够历史裁决数据才有统计意义） |

#### Phase D：条件委派协议（P2）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① `delegation-protocol.md` 文档完成，每条委派规则包含触发条件 → 跳过步骤 → 恢复条件 → 回退机制 ② 3 条条件委派路径编码为 LangGraph 条件边（见 §2.2 可新增条件委派路径表） ③ 委派日志记录至操作历史（品种 + 触发条件 + 跳过的阶段 + 时间戳） ④ 配置化启用/禁用（`decode_config` 中新增 `delegation_rules` 配置项） |
| **改动范围** | `docs/designs/delegation-protocol.md` → 新建；`fdt_langgraph/_nodes_debate.py` → 条件边扩展；`config/decode_config.yaml` → 委派规则配置项；`docs/harness/01-architecture.md` → 更新 LangGraph 路由图 |
| **风险/难点** | 委派规则可能引入隐藏依赖（例如跳过副判官后，一致性裁判审计逻辑需适配） |

#### Phase E：T3 验证增强（P2）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① 连续偏差跟踪模块实现：每轮裁决后，自动将实际走势与预测方向配对，计算滚动偏差率 ② 策略一致性指标可查询：同一品种在不同波动率区间下的裁决方向一致性 ③ T3 验证标准写入 `harness-rules.yaml` C13 ④ 报告包含裁决溯源树（与 Phase B 复用） |
| **改动范围** | `memory/tracking/` → 新增偏差跟踪模块；`docs/harness/harness-rules.yaml` → 新增 C13 T3 验证规则；`scripts/pre_commit_harness_check.py` → 扩展 C13 检查；`docs/harness/06-testing.md` → 更新验证分层 |
| **前置依赖** | Phase A（裁决数据库提供偏差计算基础）+ Phase D（委派协议提供偏差触发条件） |

#### Phase F：P3 源主动跳过（P2）

| 维度 | 内容 |
|:-----|:------|
| **验收标准** | ① 连续准确率跟踪模块实现（复用 Phase A 裁决数据库，扩展按源分类的准确率查询） ② P3 源调度支持主动跳过模式（当某源连续 N 轮准确率 < 阈值时，不等 300s 超时直接跳过） ③ 跳过条件可配置源级（准确率阈值、连续轮数，在 `decode_config` 中声明） ④ 跳过日志记录源 + 触发条件 + 跳过节次 + 时间戳，可在操作历史中查询 |
| **改动范围** | `fdt_langgraph/_nodes_debate.py` → P3 源调度逻辑扩展；`config/decode_config.yaml` → 跳过条件配置项；`docs/designs/delegation-protocol.md` → 更新委派规则 |
| **前置依赖** | Phase D（委派协议定义了通用条件委派框架，P3 跳过是具体应用） |

### 实施就绪度评估

以下检查项确认本方案已具备直接进入编码阶段的条件：

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| 1 | 6 个 Phase 均有明确焦点和交付物 | ✅ |
| 2 | 6 个 Phase 均有验收标准 | ✅ |
| 3 | 6 个 Phase 均有改动范围 | ✅ |
| 4 | 版本关系清晰，无冲突 | ✅ |
| 5 | 依赖关系验证通过（Phase A/F → 无前置；Phase B→A；C→A；D→无；E→A+D；F→D） | ✅ |
| 6 | 无循环依赖 | ✅ |
| 7 | 关联文档已标注（01-architecture.md / 06-testing.md / 07-operations.md / 08-gap-analysis.md） | ✅ |
| 8 | §2.2 委派点现状单一权威列表（无冗余） | ✅ |
| 9 | 所有论文术语与实际 FDT 概念名一致 | ✅ |
| 10 | 每个 Phase 标注了风险/难点（实施者可提前规避） | ✅ |

> **编码起点建议**：从 Phase A（无前置依赖，P1 优先）开始，Phase D（条件委派协议文档，也无前置依赖）可并行启动。

---

## 6. 参考文献

- Human–AI Hybrid Finance: An Integrated Decision-System Framework. Financial Innovation (Springer), 2026. doi: 10.1186/s40854-026-00941-w
- Vaccaro et al. (2024). When combinations of humans and AI are useful. *Nature Human Behaviour*, 8(12), 2293–2303.
- Fügener et al. (2022). Cognitive challenges in human–artificial intelligence collaboration. *Information Systems Research*, 33(2), 678–696.
