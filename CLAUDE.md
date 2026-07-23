CLAUDE.md — FDT编码行为准则
本文件定义 FDT 项目的 AI 编码行为准则，适用于所有 AI 助手和开发者。 作为项目标准文件，不因开发环境变化而变化。

权衡：以下准则偏向谨慎而非速度。对简单任务可自行判断。

1. 先思考，再编码
不要猜测。不要隐藏疑惑。把 tradeoff 摊在桌上。

实施之前：

明确陈述你的假设。 如果不确定，就问。
如果存在多种解释，全部列出来——不要悄悄选一个。
如果有更简单的方案，直接说出来。 该反对时就反对。
如果某件事不清楚，停下来。 说出疑惑点，然后问。

2. 简单至上
解决该问题的最小代码量。不写投机代码。

不做需求之外的额外功能。
不为一次性代码做抽象。
不写没人要求的"灵活性"或"可配置性"。
不为不可能发生的场景写错误处理。
如果你写了 200 行但本可以 50 行搞定，重写它。
自问："一个高级工程师会觉得这写复杂了吗？" 如果是，简化。

3. 外科手术式修改
只动必须动的。只清理自己的烂摊子。

修改现有代码时：

不要"顺手改进"旁边的代码、注释或格式。
不要重构没坏的东西。
遵循原有风格，即便你自己会写不同风格。
如果发现无关的 dead code，提一嘴——别删它。
你的改动产生孤儿代码时：

清理因你的改动而不再使用的 import/变量/函数。
不要删除早就存在的 dead code，除非被要求。
检验标准：每一行改动的代码都应能直接追溯到用户的请求。

4. 目标驱动执行
定义成功标准。循环验证直至达标。

把任务转化为可验证的目标：

模糊任务	明确目标
"加个验证"	"给无效输入写测试，然后让它们通过"
"修这个 bug"	"写一个复现它的测试，然后让测试通过"
"重构 X"	"确保重构前后测试全部通过"
多步骤任务先简述计划：

1. [步骤] → 验证：[检查方式]
2. [步骤] → 验证：[检查方式]
3. [步骤] → 验证：[检查方式]
强的成功标准让你能自主循环迭代。弱的标准（"让它工作就行"）需要持续澄清。

5. HARNESS工程规范优先 — 强制性规则
本准则优先级高于以上所有规则。任何工作必须严格遵守 docs/harness/ 目录下的工程规范。

5.1 文档先行原则
任何架构/流程变更，必须先更新以下文档再写代码：
- docs/harness/01-architecture.md（架构图 + Loop Engineering 视角 + Hook 链架构）
- docs/harness/02-lifecycle.md（阶段定义 + 双层循环）
- docs/harness/03-configuration.md（配置项 + 成本工程规范）
- docs/harness/04-resilience.md（降级策略）
- docs/harness/05-observability.md（日志指标）
- docs/harness/06-testing.md（测试用例 + 验证器质量度量）
- docs/harness/07-operations.md（版本历史 + 上线四步评估）
- docs/harness/08-gap-analysis.md（差距管理）
- docs/harness/09-advancement-plan.md（晋级计划）
- docs/harness/10-coding-standards.md（编码规范 + D3 Generation 控制）
- docs/harness/loop-contracts/README.md（循环契约 + 验证档位 + 权限三档）
- docs/harness/harness-rules.yaml（12 项机读检查规则 + 10 条反模式检测）

5.2 commit前12项检查清单 — 必须全部通过（v9.6.0 已升级为自动化）
12 项检查已编码为机读规则 + pre-commit 自动扫描：

机读规则: docs/harness/harness-rules.yaml（C01-C12，含 trigger_pattern / severity / scope）
自动检查: python scripts/pre_commit_harness_check.py（从 YAML 加载规则，JSON 结构化输出）

12 项检查:
1. 数据流/架构变更 → docs/harness/01-architecture.md
2. 阶段/文件名/产出物 → docs/harness/02-lifecycle.md / 04-resilience.md
3. 新配置项 → docs/harness/03-configuration.md
4. 降级/熔断/超时 → docs/harness/04-resilience.md
5. 新指标/日志 → docs/harness/05-observability.md
6. 测试文件和用例数 → docs/harness/06-testing.md
7. 版本号和版本历史 → docs/harness/07-operations.md
8. 差距登记/关闭 → docs/harness/08-gap-analysis.md
9. 晋级里程碑 → docs/harness/09-advancement-plan.md
10. 流程文档同步 → execution_modes_flowchart.md / business_flow.md
11. 角色MD职责 → agents/*.md
12. 入口文档同步 → CLAUDE.md / CODE_WIKI.md / README.md

5.3 契约优先原则
先定义 Schema/TypedDict/接口契约，再实现代码。

5.4 测试随重构原则
每阶段先写测试，测试全绿才能进入下一阶段。

5.5 trace_id全链路原则
trace_id 必须贯穿所有模块、文档和日志。

5.6 角色边界原则
Agent 职责不可越界，严格按照 docs/harness/02-lifecycle.md 定义执行。

5.7 差距管理原则
重大技术债务必须登记到 docs/harness/08-gap-analysis.md，按 P0/P1/P2 优先级推进。

5.8 版本号纪律原则
每阶段完成后必须 bump 版本号，更新 pyproject.toml 和 docs/harness/07-operations.md。

5.9 反模式检测规则（v9.6.0 新增）
10 条核心反模式定义在 docs/harness/harness-rules.yaml 的 anti_patterns 节。
pre-commit 自动检测，遇到即告警：

| ID | 名称 | 严重度 | 检测条件 |
|:--:|------|:------:|----------|
| AP01 | 巨型 Prompt | P1 | AGENTS.md > 300 行 |
| AP02 | 跳过审核直接编码 | P0 | 无 plan/spec 直接提交 |
| AP03 | Rules 不维护 | P1 | harness-rules.yaml > 30 天未改 |
| AP04 | MCP 过度接入 | P2 | MCP 服务 > 10 个 |
| AP05 | Skill 不原子化 | P1 | 单 Skill > 200 行 |
| AP06 | 盲目信任 AI 输出 | P0 | 生产路径无独立验证 |
| AP07 | 循环无停止条件 | P0 | Loop Contract stop 为空 |
| AP08 | 多循环共写 STATE | P1 | 多 Loop 同 state 目录 |
| AP09 | Chat 历史当文档 | P2 | 知识仅在对话历史 |
| AP10 | 一个 PR 改所有 | P1 | PR > 20 文件 |

生效标志
这些准则生效的标志：

diff 中不必要的改动减少
因过度复杂而重写的次数减少
澄清性问题在实现之前提出（而非在犯错之后）
所有代码变更都有对应的文档更新
所有 commit 前都通过了 12 项检查清单
trace_id 贯穿所有模块和日志

## 项目上下文（供 AI 新会话快速上手）

FDT (Futures Debate Team) 是一个 **13-Agent 多角色交叉质询 CTA 决策系统** v9.23.0，基于 **LangGraph 图编排 + 双层循环 (Loop Engineering)** 架构。

### 架构范式

#### 双重循环（Loop Engineering）
FDT 以 **双层循环** 组织所有自动行为，每循环持有明确契约：

```
                        ┌─────────────────────────────────────┐
                        │  Outer Loop — 跨会话 Harness 进化    │
                        │  Master Graph 调度触发               │
                        │  └→ Evolution Graph: 质量采集→APM   │
                        │     →决策→[改进/校准/进化/ML训练]    │
                        └──────────────┬──────────────────────┘
                                       │ handoff
                                       ▼
┌──────────────────────────────────────────────────────────────┐
│              Inner Loop — 单次辩论 Per-Symbol 循环            │
│  辩论图 (debate_graph): P0→P1→P1.5→P2→P3→P4→P3.5→P5→P6→P6a  │
│  内嵌 D06 降级、质检重试(≤2次)、Maker-Checker 分离            │
└──────────────────────────────────────────────────────────────┘
```

| 维度 | Inner Loop (辩论图) | Outer Loop (进化图) |
|:-----|:-------------------|:-------------------|
| 触发 | 品种信号命中 | Master 调度 / 累计样本达标 |
| 范围 | 单品种产出一份裁决 | 跨 session 经验 + 配置进化 |
| 验证档位 | L3 (independent_agent) | L2 (test_suite) |
| 权限 | Write (CTP 信号输出) | Draft (写隔离区) |
| 停止条件 | 质检 PASS 或重试耗尽 | 决策动作完成或无样本 |
| 契约文件 | `daily-debate.contract.yaml` | `self-evolve.contract.yaml` |

多循环间通过 **handoff 消息** 协作，不共享状态（AP08 反模式保底）。

#### LangGraph 图编排（Graph Engineering）
FDT 的所有编排逻辑落地为 **三张编译 LangGraph 子图**，通过状态机模式驱动：

| 子图 | 入口 | 节点数 | 模式 |
|:-----|:-----|:------:|:----:|
| `debate_graph` | `fdt_cli.py run` | ~20 | 串行 + 条件路由 + fan-out/fan-in 并行 |
| `evolution_graph` | `fdt_cli.py evolve` / 辩论后自动 | ~8 | 串行 + 条件分支决策 |
| `master_graph` | `fdt_cli.py daemon` | ~13 | 调度判断 + 子图 fork |

- **状态机基元**：State (TypedDict) → Node (函数) → Edge (条件/无条件)
- **并行模式**：P3 四源通过 fan-out 派发 → fan-in merge，逐品种隔离
- **子图组合**：master_graph 可 fork debate_graph / evolution_graph 作为子图运行
- **Checkpoint**：LangGraph 内置 checkpoint，支持断点续跑

### 13 Agent 速览

| Agent | 职责 | 关键约束 |
|:------|:-----|:---------|
| **数技源** | `scan_all.py` 10 通道突破扫描 | 不下结论 |
| **链证源** | 产业链分析（P1.5 独立阶段） | 不下多空结论 |
| **观澜** | 技术面分析（FDC 增强） | 中立，verdict=null |
| **探源** | 基本面分析（WebSearch + FDC） | 中立，verdict=null |
| **读心** | 新闻情绪分析（金十 MCP） | 中立，verdict=null |
| **多头分析员** | 构建做多论据 | 禁止自行搜索 |
| **空头分析员** | 构建做空论据 | 禁止自行搜索 |
| **闫判官** | P2 初判（选品种+方向）+ P4 终裁（含交易参数） | 六维评分 |
| **副判官** | 独立裁决校验，与闫判官并行裁决，分歧超阈值触发人工复核 | 不参与辩论，独立产生裁决 |
| **一致性裁判** | held-out judge，审计裁决是否真正由辩论论据推出（CLQT §6.4.1） | 不参与辩论，只读审计 |
| **风控明** | 风控审核（green/yellow/red） | 独立审查，不参与报告生成 |
| **品藻** | P3.5 辩论质检 + P6 汇编 + P6a CTP 信号输出 | Schema 校验，conditional_required |
| **明鉴秋** | 团队主管：选题 + spawn + 调度 + 汇总 + 记忆写入 + 进化闭环 | 不代写辩论 |

### 执行流程 P0→P6a

```
P0:   自进化前置（校准/验证）+ FDC 数据准备
  → P0b: 数据新鲜度闸门（新鲜度不达标→降级裁决）
  → P1: 数技源 10 通道突破扫描
  → P1.5: 链证源产业链分析
  → P2: 闫判官初判（品种+方向+调度四源）
  → P3: 四源并行（链证源/观澜/探源/读心）→ merge_research
  → P4: 六阶段辩论（立论→驳论→结辩，多空交叉质询）
  → P3.5: 品藻质检（Schema 校验，neutral 方向不强制 entry_price/stop_loss/target1）
  → P5: 闫判官终裁（含交易参数）→ 风控明审核（green/yellow/red）
  → G19: 无品种跳转（质检全部 FAIL 时跳过辩论+终裁）
  → P6: 品藻汇编 → 辩论报告生成 HTML → 记忆写入
  → P6a: CTP 信号输出（风控 red 阻断）

## RHI 自进化（v9.22.0+）

开启 `FDT_RHI=true` 后，在自进化闭环中新增 RHI 分支（improve→calibrate→evolve→rhi→ml→complete），自动优化三层 Harness 规范（Agent Candidates / Workflow(Contract+Hop) / Auxiliary Rules）。

也可手动触发：
```bash
python scripts/rhi_global_cli.py status
python scripts/rhi_global_cli.py step
```

参考：RHI (arXiv:2607.15524) + MemoHarness (arXiv:2607.14159)
```

### 核心原则

- **NO_FUSION 零融合**：10 通道策略独立打分，不融合不加权，方向冲突交辩论层裁决
- **逐品种隔离**：每品种独立完成辩论 → 裁决 → 质检 → 输出，不因历史行情做归纳判断
- **质检与重试**：Schema 校验 + conditional_required（neutral 方向不强制交易参数），FAIL 且重试 < 2 次时退回重修
- **数据铁律**：单向流通（Agent 只读前置产出）、超 5 天不作为主论据、DataCore→TDX→TqSdk→QMT→Web 逐级熔断降级
- **通信铁律**：Agent 只写文件不通信，辩手禁搜禁止代写
- **运行时降级**：四源缺员(300s)跳过不阻断，辩论(600s)超时跳过后继续
- **trace_id 全链路**：贯穿所有模块、文档和日志