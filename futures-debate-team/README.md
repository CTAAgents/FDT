# Futures Debate Team — 期货交易辩论专家团 v4.0

## 类型

Team 型（11角色多角色协作团队，闫判官全权主持辩论子流程）

## 架构

4层数据输入 → 3阶段串行管道，1名协调员 + 10角色：

```
用户
  ↓
明鉴秋（独立协调员）→ Stage 1: 选题 + 数技源数据采集 + 量析师策略层打分
  ↓
闫判官全权主持 Stage 2: 辩论全流程
  ├─ 准备期: 探源(基本面) + 观澜(技术面) + 链证源(产业链景气度) + 量析师(策略层信号包)
  ├─ 辩论期: 证真(正方) ⇄ 慎思(反方) → 引用4层数据辩论（基本面+技术面+产业链+量化信号）
  ├─ 评审期: 策执远出方案 → 风控明审核
  └─ 判决期: 多维评分 + 最终判决
  ↓
明鉴秋 Stage 3: execute/hold/rematch → 追加记忆 → HTML报告 → 交付用户
```

## 核心设计原则（v4.0）

```
修改Agent方法 → 只改对应skill
修改辩论流程 → 只改主SKILL.md（角色+编排+边界）
研究员中立   → 只供证据不下结论
链证源中   → 只做产业链事实描述和景气度分析，不下多空结论
量析师     → 策略驱动打分（strategies/目录可插拔，默认L1-L4）
无胶水代码 → 所有操作通过已有skill完成
记忆系统   → 跨轮记忆+知识库+规则库，三层次迭代
```

| Agent | 阶段 | 工作方法定义在 |
|:------|:----:|:---------------|
| 数技源 | S1 | `quant-daily`（纯数据管道）|
| 量析师 | S1 | `quant-daily`（策略层打分引擎）|
| 探源 | S2a | `commodity-chain-analysis` |
| 观澜 | S2a | `quant-daily` |
| 链证源 | S2a | `commodity-chain-analysis` |
| 证真 | S2b | `debate-argument-builder` |
| 慎思 | S2b | `debate-argument-builder` |
| 策执远 | S2c | `debate-trading-planner` |
| 风控明 | S2c | `debate-risk-manager v3` |
| 闫判官 | S2a-S2d | `debate-judge` |
| 明鉴秋 | S1+S3 | `futures-trading-analysis` |

## 团队成员

| 角色 | Agent ID | 职责 |
|:-----|:---------|:-----|
| 协调员 | `futures-debate-team-team-lead` | 选题、拍板、汇总输出、追加记忆 |
| 数技源 | `futures-datatech` | 数据采集（纯数据管道，不做分析） |
| 量析师 | `futures-quant-analyst` | 策略层量化打分（L1-L4/自定义策略，可插拔） |
| 探源 | `futures-fundamental-researcher` | 基本面快照（中立） |
| 观澜 | `futures-technical-researcher` | 技术面快照（中立） |
| 链证源 | `futures-chain-analyst` | 产业链事实描述+景气度分析（不下多空结论） |
| 证真 | `futures-affirmative-debater` | 正方辩手：论证方向正确性（引用4层证据） |
| 慎思 | `futures-opposition-debater` | 反方辩手：挑战方向可靠性（引用4层证据） |
| 闫判官 | `futures-judge` | 辩论主持人+裁判 |
| 风控明 | `futures-risk-manager` | 风险管理 |
| 策执远 | `futures-trading-strategist` | 交易策略 |

## 数据流（v4.0 策略可插拔层）

```
S1:   数技源 → 原始数据包（K线+指标+持仓，含 _meta 溯源字段）
      量析师 → 策略层信号包（strategies/目录可插拔，默认layered_l1l4）
S2a:  探源 + 观澜 + 链证源(景气度) → research_snapshot
      量析师信号包 → quant_signal_package（含策略名称+子层分数+否决标记）
S2b:  证真/慎思 → 引用4层数据（基本面+技术面+产业链+量化信号）
      每层证据必须注明来源（探源/观澜/链证源/量析师[策略名]）
S2c:  策执远 → executable_plan → 风控明审核
S2d:  闫判官 → p_judge_final.json + 提炼论证模式→memory/
S3:   明鉴秋拍板 → debate_results.json + 追加记忆 → HTML报告
```

## 记忆系统

专家内建 `memory/` 目录，包含三层记忆库：

| 层 | 文件 | 用途 | 写入者 |
|:--|:----|:----|:------|
| T1 | `memory/debate_journal.json` | 跨轮辩论日志 | 明鉴秋 |
| T2 | `memory/data_sources.md` | 数据源可靠性跟踪 | 风控明 |
| T2 | `memory/argument_patterns.md` | 有效论证模式 | 闫判官 |
| T2 | `memory/debater_profiles.md` | 角色表现记录 | 闫判官 |
| T2 | `memory/execution_followup.json` | 执行回溯 | 策略师 |
| T3 | `memory/rules/veto_rules.md` | 否决规则库 | 风控明+明鉴秋 |
| T3 | `memory/rules/weighting_rules.md` | 评分权重记录 | 闫判官+明鉴秋 |

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v4.0** | **2026-07-04** | **策略可插拔架构**：新增量析师(futures-quant-analyst)，策略层驱动打分(L1-L4默认，true_layered废弃)；链证源聚焦产业链描述+景气度(不下多空结论)；正反方引4层证据(+量析师信号包)；quant-daily strategies/独立层 |
| v3.3 | 2026-07-04 | quant-daily真分层打分集成 |
| v3.2 | 2026-07-04 | 九宫格模糊隶属度分类器 |
| v3.1 | 2026-07-03 | 链证源全面集成 |
| v3.0 | 2026-07-03 | 架构重构 |
