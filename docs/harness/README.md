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
| 11 | [循环契约规范](loop-contracts/README.md) | Loop Contract 六维度定义、验证档位、权限三档、现有循环清单 |

## 快速参考

```
FDT 项目根路径:
  `<FDT_ROOT>` (克隆后的项目目录)

入口点:
  fdt_cli.py            — 独立 CLI 入口 (run/daemon/db，v8.3.0+ LangGraph 模式)
  fdt_api.py            — 独立 FastAPI HTTP 服务入口 (/api/v1/debate，v8.3.0+)
  pipeline/runner.py    — 全自动零干预流水线（支持 FDT_USE_LANGGRAPH A/B 切换）
  scheduler/engine.py   — 心跳调度发动机

LangGraph A/B 切换环境变量:
  FDT_USE_LANGGRAPH     — true/false，控制 pipeline 走 LangGraph 或 subprocess（默认 false）
  FDT_LANGGRAPH_MODE    — default/fast/deep_research/tournament（默认 default）
  FDT_CHECKPOINTER      — pg/sqlite，Checkpointer 后端（默认 sqlite，PG 不可用时自动降级）

核心铁律数: 8 条 (时序/串线/文件就绪/辩手禁搜/胶水代码/记忆独立/鲁棒性/P5降级)
鲁棒性层数: 5 层 (L1-L5)
可观测轴数: 5 轴 (D1-D5 APM-CS)
Agent 数:   9 个 (数技源/观澜/探源/链证源/多头分析员/空头分析员/闫判官/风控明/明鉴秋)
Skill 数:   13 个 (skills/ 目录)
脚本数:     61 个 (scripts/)
测试文件:   24 个
类型注解:   580+ 函数（全部公共函数已覆盖） (12 个目录)  ← 已全部修复，pipeline 10/10 全绿
循环契约:   1 个 (daily-debate，L3 验证档位)
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
