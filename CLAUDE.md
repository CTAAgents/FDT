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

FDT (Futures Debate Team) 是一个 **10-Agent 多角色交叉质询 CTA 决策系统**，基于 LangGraph 图编排。

### 10 Agent 速览

| Agent | 职责 | 关键约束 |
|:------|:-----|:---------|
| **数技源** | `scan_all.py` 通道突破扫描 | 不下结论 |
| **链证源** | 产业链分析 | 不下多空结论 |
| **观澜** | 技术面分析（FDC 增强） | 中立，verdict=null |
| **探源** | 基本面分析（WebSearch + FDC） | 中立，verdict=null |
| **读心** | 新闻情绪分析（金十 MCP） | 中立，verdict=null |
| **多头分析员** | 构建做多论据 | 禁止自行搜索 |
| **空头分析员** | 构建做空论据 | 禁止自行搜索 |
| **闫判官** | P2 初判 + P5 终裁（含交易参数） | 六维评分 |
| **风控明** | 风控审核（green/yellow/red） | 独立审查 |
| **明鉴秋** | 选题 + spawn + 汇总 + 记忆写入 | 不代写辩论 |

### 执行流程 P0→P6

```
P0: 数技源扫描 + FDC 数据准备
  → P1: 链证源产业链分析
  → P2: 闫判官初判（品种+方向+调度四源）
  → P3: 四源并行（链证源/观澜/探源/读心）→ merge_research
  → P4: 六阶段辩论（立论→驳论→结辩，多空交叉质询）
  → P5: 闫判官终裁 → 风控审核 → CTP信号输出 → 报告
  → P6: 明鉴秋汇总 + 记忆写入
```

### 核心原则

- **NO_FUSION 零融合**：8 策略独立打分，方向冲突交辩论层裁决
- **数据源降级**：DataCore→TDX→TqSdk→QMT→WebFallback，每级独立熔断器
- **通信铁律**：Agent 只写文件不通信，辩手禁搜，禁止代写
- **P3 四源缺员不阻断**：任一源超时(300s)跳过，其余继续
- **辩论降级**：辩论阶段超时(600s)跳过，`arguments=[]` 继续
- **数据流单向性**：Agent 只能读自己阶段之前的产出
- **trace_id 全链路贯穿**所有模块、文档和日志
- **ADX 角色反转规则**：ADX<20 鼓励确认，ADX≥60 不得作为致命伤，提及占比≤1/3