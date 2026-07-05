# Futures Debate Team — 期货交易辩论专家团 v4.1

## 类型

Team 型（10角色多角色协作团队，闫判官自主决定辩论品种与方向）

## 架构

```
用户 → 明鉴秋（协调员）
           ↓
Stage 1: 数技源 → scan_all.py --dual
           ├── full_scan_l1l4_{date}.json         ← L1-L4 技术信号
           ├── full_scan_factor_timing_{date}.json ← factor_timing 因子信号
           └── full_scan_summary_{date}.json      ← 双策略并排汇总
           ↓
Stage 1.5: 链证源 → 产业链分析（先于闫判官决策，不下多空结论）
           ↓
Stage 2: 闫判官综合双策略信号 + 产业链信息 → 选辩论品种 + 定正方方向
           ↓
   ┌───────┼───────┐
   ↓               ↓
 观澜(技术分析)   探源(基本面分析)
   │               │
   └───────┬───────┘
           ↓
    ┌──────┴──────┐
    ↓              ↓
 证真(多方)      慎思(空方)
    └──────┬──────┘
           ↓
    策执远出方案 → 风控明审核
           ↓
    闫判官裁决 → 明鉴秋汇总
           ↓
    debate_results.json + HTML 报告
```

## 核心设计原则（v4.1）

```
数技源边界   → 只输出原始数值，不做判断
闫判官决策   → 自行决定辩论品种与方向
研究员中立   → 只供证据不下多空结论
链证源中立   → 只做产业链事实描述，不下多空结论
双策略并行   → L1-L4 + factor_timing 各输出一份
无胶水代码   → 所有操作通过已有skill完成
自动写记忆   → 每个Agent运行后自动写memory/
```

## 10大角色

| 角色 | Agent ID | 工作方法定义在 | 职责 |
|:-----|:---------|:--------------|:-----|
| 明鉴秋 | `futures-debate-team-team-lead` | `futures-trading-analysis` | 选题、调度、汇总、拍板 |
| 数技源 | `futures-datatech` | `quant-daily` | 运行 --dual 产出双策略信号（纯数据） |
| 探源 | `futures-fundamental-researcher` | `commodity-chain-analysis` | 基本面分析（factor_timing数据+互联网） |
| 观澜 | `futures-technical-researcher` | `quant-daily` | 技术分析（L1-L4数据+自算指标+图形） |
| 链证源 | `futures-chain-analyst` | `commodity-chain-analysis` | 产业链事实描述+景气度（不下多空） |
| 证真 | `futures-affirmative-debater` | `debate-argument-builder` | 多方：从研究员资料中提取多头论据 |
| 慎思 | `futures-opposition-debater` | `debate-argument-builder` | 空方：从研究员资料中提取空头论据 |
| 闫判官 | `futures-judge` | `debate-judge` | 选辩论品种+定方向+主持+评分+裁决 |
| 风控明 | `futures-risk-manager` | `debate-risk-manager` | 杠杆/回撤/叙事质检 |
| 策执远 | `futures-trading-strategist` | `debate-trading-planner` | 合约选型+执行方案 |

## 数据流（v4.1 双策略并行）

```
S1: 数技源 → scan_all.py --dual
     ├─ full_scan_l1l4_{date}.json         — 40+技术指标数值
     └─ full_scan_factor_timing_{date}.json — 5因子择时数值

S1.5: 链证源 → 产业链分析（先于闫判官决策，不下多空结论）

S2: 闫判官综合双策略信号 + 产业链信息 → 决定辩论品种与方向

S3: 观澜(技术分析) + 探源(基本面分析) 并行供弹
     → 证真(多方) ⇄ 慎思(空方) 辩论
     → 策执远出方案 → 风控明审核 → 闫判官裁决

S4: 明鉴秋汇总 → debate_results.json + HTML + memory更新
```

## 记忆系统

所有 Agent 通过 `scripts/memory_writer.py` 自动写入 `memory/` 目录：

| 文件 | 用途 | 写入者 |
|:----|:----|:------|
| `debate_journal.json` | 跨轮操作日志 | 全员自动写入 |
| `data_sources.md` | 数据源可靠性 | 探源+风控明 |
| `argument_patterns.md` | 有效论证模式 | 证真+慎思+闫判官 |
| `debater_profiles.md` | 角色表现 | 闫判官 |
| `execution_followup.json` | 执行回溯 | 策执远 |
| `debates/INDEX.md` | 辩论索引 | 明鉴秋+闫判官 |
| `policies/veto_policies.md` | 否决规则库 | 风控明+明鉴秋 |
| `policies/weighting_history.md` | 评分权重记录 | 闫判官+明鉴秋 |

## 依赖的Skills

| Skill | 用途 |
|:------|:-----|
| `quant-daily` | 数据采集 + L1-L4 + factor_timing 双策略计算 |
| `futures-trading-analysis` | 主流程编排 + 报告生成 |
| `commodity-chain-analysis` | 基本面 + 产业链分析 |
| `debate-argument-builder` | 正反方论点构建 |
| `debate-judge` | 闫判官辩论主持裁决 |
| `debate-risk-manager` | 风控审核 |
| `debate-trading-planner` | 交易策略规划 |

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v4.1** | **2026-07-05** | **方案C仲裁者裁决**：量析师移除(10角色)；数技源改为--dual双策略输出(L1-L4+factor_timing)；闫判官自主决定辩论品种与方向；多方/空方从研究员资料中提取论据；所有Agent自动写memory；废弃文件清理 |
| v4.0 | 2026-07-04 | 策略可插拔架构：新增量析师，策略层驱动打分；链证源聚焦景气度(不下多空)；正反方引4层证据 |
| v3.3 | 2026-07-04 | quant-daily真分层打分集成 |
