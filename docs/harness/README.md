# FDT Harness 工程文档

> 从 Agent/LLM Harness 工程范式视角，对期货交易辩论专家团（Futures Debate Team, FDT）的编排层、配置注入、生命周期管理、错误恢复和可观测性进行系统性梳理。

## 文档索引

| # | 文档 | 内容 |
|:-:|:-----|:-----|
| 01 | [架构总览](01-architecture.md) | Harness 分层架构、组件关系图、数据流总览 |
| 02 | [生命周期与编排](02-lifecycle.md) | 入口引导、6 阶段流水线、Agent 生成/销毁、状态机 |
| 03 | [配置管理](03-configuration.md) | 配置文件清单、环境变量、优先级覆盖链、校验机制 |
| 04 | [错误恢复与鲁棒性](04-resilience.md) | L1-L5 五层防线、S04 轮询协议、D06 降级、熔断 |
| 05 | [可观测性](05-observability.md) | APM-CS 五轴、统一日志、健康自检、ViBench 回放 |
| 06 | [测试策略](06-testing.md) | 测试金字塔、契约校验、门禁审计、覆盖率 |
| 07 | [运维与部署](07-operations.md) | 部署模式、调度器、看门狗、运维 Runbook |
| 08 | [差距分析与改进路线](08-gap-analysis.md) | 现状 vs 目标、缺失项清单、优先级排序 |
| 09 | [晋级计划](09-advancement-plan.md) | Harness 成熟度晋级路线、Phase 1-5 里程碑 |
| 10 | [编码规范](10-coding-standards.md) | 文档先行、契约优先、测试随重构、12 项 check commit 纪律 |

## 快速参考

```
FDT 项目根路径:
  ~/.workbuddy/plugins/marketplaces/my-experts/plugins/futures-debate-team/

入口点:
  bootstrap.py          — 一键启动 (once/daemon/interactive)
  pipeline/runner.py    — 全自动零干预流水线
  scheduler/engine.py   — 心跳调度发动机

核心铁律数: 8 条 (时序/串线/文件就绪/辩手禁搜/胶水代码/记忆独立/鲁棒性/P5降级)
鲁棒性层数: 5 层 (L1-L5)
可观测轴数: 5 轴 (D1-D5 APM-CS)
Agent 数:   12 个 (10 核心 + 副判官 + 一致性裁判)
Skill 数:   13 个 (skills/ 目录)
脚本数:     61 个 (scripts/)
测试文件:   24 个 (12 个目录)  ← 已全部修复，pipeline 10/10 全绿
```

## 术语表

| 术语 | 含义 |
|:-----|:-----|
| Harness | Agent 框架的脚手架层——入口编排、配置注入、生命周期管理、错误恢复、可观测性 |
| Agent | FDT 中的独立角色（如闫判官、证真、慎思），通过 LLM spawn 执行 |
| Spawn | 通过 Agent tool 生成子 Agent 实例 |
| Phase | 流水线阶段（P1-P6），每个阶段有明确的输入/输出/参与者 |
| Trace ID | 一轮辩论的唯一标识符，贯穿全流水线 |
| L1-L5 | 五层鲁棒性防线（产出校验→熔断降级→信号门→路径发现→健康自检） |
| D06 | 闫判官 spawn 2 次失败后的降级裁决机制 |
| S04 | Agent 产出文件轮询协议（poll_file_ready） |
| APM-CS | Agent Performance Management — Coherence & Stability 五轴评分卡 |
