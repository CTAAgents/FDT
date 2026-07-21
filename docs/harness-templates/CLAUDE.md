# Harness 工程规范 — 通用行为准则

> 本文件是 Harness Engineering 的通用模板。
> 将此文件复制到你的项目根目录，按项目实际情况修改。

## 核心原则

1. **文档先行**：任何架构/流程变更，必须先更新文档再写代码
2. **契约优先**：先定义 Schema/TypedDict/接口契约，再实现代码
3. **测试随重构**：每阶段先写测试，测试全绿才能进入下一阶段
4. **trace_id 全链路**：trace_id 必须贯穿所有模块、文档和日志
5. **角色边界钉死**：Agent 职责不可越界
6. **差距管理**：重大技术债务必须登记，按 P0/P1/P2 优先级推进
7. **版本号纪律**：每阶段完成后必须 bump 版本号

## 检查清单

### commit 前 12 项检查

1. 数据流/架构变更 → 01-architecture.md
2. 阶段/文件名/产出物 → 02-lifecycle.md / 04-resilience.md
3. 新配置项 → 03-configuration.md
4. 降级/熔断/超时 → 04-resilience.md
5. 新指标/日志 → 05-observability.md
6. 测试文件和用例数 → 06-testing.md
7. 版本号和版本历史 → 07-operations.md
8. 差距登记/关闭 → 08-gap-analysis.md
9. 晋级里程碑 → 09-advancement-plan.md
10. 流程文档同步 → execution_modes_flowchart.md / business_flow.md
11. 角色MD职责 → agents/*.md
12. 入口文档同步 → CLAUDE.md / CODE_WIKI.md / README.md

### 10 条反模式自查

| # | 反模式 | 说明 |
|:-:|--------|------|
| 1 | 巨型 Prompt | AGENTS.md > 300 行，或 system_prompt 过长 |
| 2 | 跳过审核直接编码 | 无 plan/spec 直接提交代码 |
| 3 | Rules 不维护 | 规则文件超过 30 天未修改 |
| 4 | MCP 过度接入 | MCP 服务 > 10 个 |
| 5 | Skill 不原子化 | 单个 Skill > 200 行 |
| 6 | 盲目信任 AI 输出 | 生产路径无独立验证环节 |
| 7 | 循环无停止条件 | Loop Contract 中 stop 为空 |
| 8 | 多循环共写 STATE | 多个 Loop 输出同目录 |
| 9 | Chat 历史当文档 | 关键知识仅在对话历史 |
| 10 | 一个 PR 改所有 | 单个 PR 涉及 > 20 个文件 |
