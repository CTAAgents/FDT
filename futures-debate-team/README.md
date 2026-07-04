# Futures Debate Team — 期货交易辩论专家团 v3.3

## 类型

Team 型（11角色多角色协作团队，闫判官全权主持辩论子流程）

## 架构

4层数据输入 → 3阶段串行管道，1名协调员 + 10角色：

```
用户
  ↓
明鉴秋（独立协调员）→ Stage 1: 选题 + 数技源数据采集 + quant-daily真分层打分
  ↓
闫判官全权主持 Stage 2: 辩论全流程
  ├─ 准备期: 探源(基本面) + 观澜(技术面) + 链证源(产业链快照) + quant-daily量化信号包
  ├─ 辩论期: 证真(正方) ⇄ 慎思(反方) → 引用4层数据辩论
  ├─ 评审期: 策执远出方案 → 链证源(风控证据包) → 风控明审核(含veto系数) → veto
  └─ 判决期: 六维评分(含量化一致性) + 最终判决 + 提炼论证模式入库
  ↓
明鉴秋 Stage 3: execute/hold/rematch → 追加记忆 → HTML报告 → 交付用户
```

## 核心设计原则（v3.3）

```
修改Agent方法 → 只改对应skill
修改辩论流程 → 只改主SKILL.md（角色+编排+边界）
研究员中立 → 只供证据不下结论
链证源双线 → 准备期供研究员快照，评审期供风控明证据包
量化支撑 → quant-daily 7因子真分层+九宫格左右侧分类
无胶水代码 → 所有操作通过已有skill完成
记忆系统 → 跨轮记忆+知识库+规则库，三层次迭代
```

| Agent | 阶段 | 工作方法定义在 |
|:------|:----:|:---------------|
| 数技源 | S1 | `quant-daily` |
| 量化分析 | S1 | `quant-daily`（真分层打分引擎）|
| 探源 | S2a | `commodity-chain-analysis` |
| 观澜 | S2a | `quant-daily` |
| 链证源 | S2a+S2c | `commodity-chain-analysis` |
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
| 数技源 | `futures-datatech` | 数据采集与评分（库函数模式） |
| 量化分析师 | `futures-datatech` | 真分层打分：7因子截面排序+九宫格分类+左右侧识别 |
| 探源 | `futures-fundamental-researcher` | 基本面快照（中立） |
| 观澜 | `futures-technical-researcher` | 技术面快照（中立） |
| 链证源 | `futures-chain-analyst` | 双线服务：产业链快照→研究员 + 风控证据包→风控明 |
| 证真 | `futures-affirmative-debater` | 正方辩手：论证方向正确性 |
| 慎思 | `futures-opposition-debater` | 反方辩手：挑战方向可靠性 |
| 闫判官 | `futures-judge` | 辩论主持人+裁判（6维评分） |
| 风控明 | `futures-risk-manager` | 风险管理（含quant-daily veto系数审核） |
| 策执远 | `futures-trading-strategist` | 交易策略（含执行回溯写入记忆） |

## 数据流（v3.3 新增量化层）

```
S1:   数技源 → scan_all.json（含 _meta 溯源字段）
      量化分析 → true_layered_{date}.json（7因子+九宫格+左右侧）
S2a:  探源 + 观澜 + 量化数据包 → research_snapshot
      链证源 → chain_snapshot（给探源+明鉴秋）
S2b:  证真/慎思 → 引用4层数据（基本面+技术面+产业链+量化信号）
S2c:  策执远 → executable_plan
      链证源 → chain_risk_evidence（集中度+冗余→给风控明）
      风控明 → risk_verdict（含veto_penalty<0.5 red红线）
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

## 变更日志

| 版本 | 日期 | 变更 |
|:----|:----|:-----|
| **v3.3** | **2026-07-04** | **quant-daily真分层打分集成**：新增量化信号包(7因子+九宫格+左右侧)；评分模型新增"量化一致性"维度(15%)；辩手数据来源4层；风控新增veto_penalty红线；内置记忆系统(7文件三层库) |
| v3.2 | 2026-07-04 | 九宫格模糊隶属度分类器；左右侧识别；`_get_adx`嵌套bug修复 |
| v3.1 | 2026-07-03 | 链证源全面集成：双线输出（准备期供研究员快照+评审期供风控明证据包）。消息协议7接口。风控明输入增加链证源证据。 |
| v3.0 | 2026-07-03 | 架构重构：3阶段辩论流程。Agent升级：数技源(库函数)、探源/观澜(中立研究员)、证真/慎思(辩手分离)。风控v3(仓位沙盘+叙事质检)。6标准消息协议。 |
