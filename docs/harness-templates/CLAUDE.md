# 通用编码行为准则

本文件定义跨项目的编码行为准则，适用于所有 AI 助手和开发者。作为全局标准文件，不因项目环境变化而变化，各项目可在自己根目录的 CLAUDE.md 中覆写或扩展。

## 1. 先思考，再编码

不要猜测。不要隐藏疑惑。把 tradeoff 摊在桌上。

实施之前：
- 明确陈述你的假设。如果不确定，就问。
- 如果存在多种解释，全部列出来——不要悄悄选一个。
- 如果有更简单的方案，直接说出来。该反对时就反对。
- 如果某件事不清楚，停下来。说出疑惑点，然后问。

## 2. 简单至上

解决该问题的最小代码量。不写投机代码。
- 不做需求之外的额外功能。
- 不为一次性代码做抽象。
- 不写没人要求的"灵活性"或"可配置性"。
- 不为不可能发生的场景写错误处理。
- 如果你写了 200 行但本可以 50 行搞定，重写它。
- 自问："一个高级工程师会觉得这写复杂了吗？" 如果是，简化。

## 3. 外科手术式修改

只动必须动的。只清理自己的烂摊子。

修改现有代码时：
- 不要"顺手改进"旁边的代码、注释或格式。
- 不要重构没坏的东西。
- 遵循原有风格，即便你自己会写不同风格。
- 如果发现无关的 dead code，提一嘴——别删它。

你的改动产生孤儿代码时：
- 清理因你的改动而不再使用的 import/变量/函数。
- 不要删除早就存在的 dead code，除非被要求。

检验标准：每一行改动的代码都应能直接追溯到用户的请求。

## 4. 目标驱动执行

定义成功标准。循环验证直至达标。

把任务转化为可验证的目标：

| 模糊任务 | 明确目标 |
|----------|----------|
| "加个验证" | "给无效输入写测试，然后让它们通过" |
| "修这个 bug" | "写一个复现它的测试，然后让测试通过" |
| "重构 X" | "确保重构前后测试全部通过" |

多步骤任务先简述计划：
1. [步骤] → 验证：[检查方式]
2. [步骤] → 验证：[检查方式]
3. [步骤] → 验证：[检查方式]

强的成功标准让你能自主循环迭代。弱的标准需要持续澄清。

---

# Harness 工程规范

## 核心原则

1. **文档先行**：任何架构/流程变更，必须先更新文档再写代码
2. **契约优先**：先定义 Schema/TypedDict/接口契约，再实现代码
3. **测试随重构**：每阶段先写测试，测试全绿才能进入下一阶段
4. **trace_id 全链路**：trace_id 必须贯穿所有模块、文档和日志
5. **角色边界钉死**：Agent 职责不可越界
6. **差距管理**：重大技术债务必须登记，按 P0/P1/P2 优先级推进
7. **版本号纪律**：每阶段完成后必须 bump 版本号

## commit 前检查清单

> v9.20.2 新增：文档一致性自动化校验（Layer 2），详见第 13 项。

1. 数据流/架构变更 → `docs/harness/01-architecture.md`
2. 阶段/文件名/产出物 → `docs/harness/02-lifecycle.md` / `04-resilience.md`
3. 新配置项 → `docs/harness/03-configuration.md`
4. 降级/熔断/超时 → `docs/harness/04-resilience.md`
5. 新指标/日志 → `docs/harness/05-observability.md`
6. 测试文件和用例数 → `docs/harness/06-testing.md`
7. 版本号和版本历史 → `docs/harness/07-operations.md`
8. 差距登记/关闭 → `docs/harness/08-gap-analysis.md`
9. 晋级里程碑 → `docs/harness/09-advancement-plan.md`
10. 流程文档同步 → `execution_modes_flowchart.md` / `business_flow.md`
11. 角色MD职责 → `agents/*.md`
12. 入口文档同步 → `CLAUDE.md` / `CODE_WIKI.md` / `README.md`
13. **文档一致性自动化校验** (C15) → 运行 `python scripts/verify_doc_consistency.py`

## 文档一致性三层保障（全局要求 v9.20.2+）

确保 `docs/harness/` 下的文档与系统状态严格一致：

### Layer 1 — 结构化一致性元数据
每篇 `docs/harness/*.md` 末尾必须包含 `## 一致性元数据` 表格，标明其引用的代码文件/函数与可验证断言（函数存在、路径正确、版本一致等）。

表格格式：
```markdown
## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `path/to/file.py::function` | §X.X | 断言描述 | `grep -n "def function"` |
```

### Layer 2 — 自动校验脚本
```bash
python scripts/verify_doc_consistency.py
```
自动解析各文档的一致性元数据表格，执行每行检验命令并报告 PASS/FAIL。
C15 规则已纳入 `harness-rules.yaml`。每次涉及 `docs/harness/` 的变更后必须运行。

### Layer 3 — 数据驱动文档
易过时的配置数据（版本号、路由表、Agent 入口点等）应放在 `docs/harness/_data/*.yaml`，文档通过引用保持最新。代码变更仅需更新 YAML。

## 10 条反模式自查

| ID | 反模式 | 严重度 | 检测条件 |
|:--:|--------|:------:|----------|
| AP01 | 巨型 Prompt | P1 | AGENTS.md > 300 行 |
| AP02 | 跳过审核直接编码 | P0 | 无 plan/spec 直接提交 |
| AP03 | Rules 不维护 | P1 | 规则文件 > 30 天未改 |
| AP04 | MCP 过度接入 | P2 | MCP 服务 > 10 个 |
| AP05 | Skill 不原子化 | P1 | 单 Skill > 200 行 |
| AP06 | 盲目信任 AI 输出 | P0 | 生产路径无独立验证 |
| AP07 | 循环无停止条件 | P0 | Loop Contract stop 为空 |
| AP08 | 多循环共写 STATE | P1 | 多 Loop 同 state 目录 |
| AP09 | Chat 历史当文档 | P2 | 知识仅在对话历史 |
| AP10 | 一个 PR 改所有 | P1 | PR > 20 文件 |

## 自动部署检查

项目根目录存在 `scripts/pre_commit_harness_check.py` 时，每次 commit 前自动运行：
```bash
python scripts/pre_commit_harness_check.py
```
从 `docs/harness/harness-rules.yaml` 加载机读规则，输出 JSON 结构化检查结果。

项目根目录存在 `scripts/verify_doc_consistency.py` 时，每次涉及 `docs/harness/` 的变更后运行：
```bash
python scripts/verify_doc_consistency.py
```

---

> **来源**：本文件由 [HarnessStarterKit](D:\HarnessStarterKit\) 提供，是跨项目编码行为准则与工程规范的统一入口。
## RHI 递归 Harness 自进化（v9.22.0+）

本项目的 CLAUDE.md 支持 RHI 自优化。将 CLAUDE.md 作为可迭代的 Harness prompt，
每次 step 比较当前版本与上一版本的输出质量评分。

使用方式：
```bash
python scripts/rhi_global_setup.py init     # 首版快照
python scripts/rhi_global_setup.py step     # 执行一轮自优化
python scripts/rhi_global_setup.py status   # 查看评分与收敛状态
```

评分维度：memory_coverage(0.30) + rule_completeness(0.30) + consistency(0.20) + clarity(0.20)
改进率低于 0.3 或达最大轮次后自动收敛。

参考：
- RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
- MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159

> 项目根目录的 CLAUDE.md 可在此基础之上扩展项目专属内容（如 Agent 列表、项目流程等）。
