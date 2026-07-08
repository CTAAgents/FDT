# Agent 通信协议 v3.0

> 定义 futures-debate-team 10角色间的结构化通信契约。每个 Agent 的输入/输出必须符合对应的 schema。
> 解决 "telephone effect"——信息在 Agent 间传递时因格式混搭导致的失真。

## 📐 协议标准层次

| 层次 | 标准 | 来源 |
|:-----|:-----|:-----|
| **数据格式** | JSON Schema (Draft 2020-12) | JSON Schema / OpenAPI 3.1 **行业标准** |
| **通信契约** | Pydantic v2 models (`contracts/`) | 内部定义，可导出为JSON Schema |
| **编码** | UTF-8 | **行业标准** |
| **时间格式** | ISO 8601 (`YYYY-MM-DD HH:MM`) | ISO **国际标准** |
| **品种代码** | 交易所标准代码（rb.SHF, CU.SHF） | 各交易所 **行业标准** |
| **金额格式** | 浮点数，不包含货币符号 | 内部约定 |

### JSON Schema 文件位置

所有 schema 的 JSON Schema 定义（Draft 2020-12 / OpenAPI 3.1 兼容）在 `docs/schemas/` 目录下：

| Schema | JSON Schema 文件 | Pydantic源 |
|:-------|:----------------|:-----------|
| ChainAnalysisOutput | `docs/schemas/ChainAnalysisOutput.json` | `contracts/chain_analysis.py` |
| ChainMetric | `docs/schemas/ChainMetric.json` | `contracts/chain_analysis.py` |
| ArgumentOutput | `docs/schemas/ArgumentOutput.json` | `contracts/debate.py` |
| StructuredDebate | `docs/schemas/StructuredDebate.json` | `contracts/debate.py` |
| DimensionItem | `docs/schemas/DimensionItem.json` | `contracts/debate.py` |
| EvidenceItem | `docs/schemas/EvidenceItem.json` | `contracts/debate.py` |
| RiskOutput | `docs/schemas/RiskOutput.json` | `contracts/risk.py` |
| VerdictItem | `docs/schemas/VerdictItem.json` | `contracts/risk.py` |
| OverallJudgment | `docs/schemas/OverallJudgment.json` | `contracts/risk.py` |

Agent输出必须与 `docs/schemas/` 下的JSON Schema定义一致。可使用任意JSON Schema验证工具进行校验。

---

## 协议总图

```
┌─────────────────────────────────────────────────────────────────┐
│                   明鉴秋 — 辩论独立协调员                         │
│            TeamDecisionOutput (team_decision.py)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ 联络 main + 归档
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                   闫判官 — 辩论主持与裁决                          │
│  ┌────────────────────┐   ┌────────────────────┐                 │
│  │ PrepBrief          │   │ FinalJudgment      │                 │
│  │ (evidence_brief.py)│   │ (evidence_brief.py)│                 │
│  └──┬──────────┬──────┘   └────▲──────────▲────┘                 │
│     │          │               │          │                      │
│     证据简报    辩论启动       判决输出    策执远+风控结果          │
└─────┼──────────┼───────────────┼──────────┼──────────────────────┘
      │          │               │          │
      ▼          ▼               │          │
┌────────┐ ┌──────────┐         │          │
│ 探源   │ │ 观澜     │         │          │
│ Funda- │ │ Technical│         │          │
│ mental │ │ Output   │         │          │
│ State  │ │ (techni- │         │          │
│ Vector │ │ cal.py)  │         │          │
│ (funda- │ └──────────┘         │          │
│ mental_ │                     │          │
│ state.  │                     │          │
│ py)    │                     │          │
└────────┘                     │          │
      │                        │          │
      ▼                        │          │
┌──────────────────┐           │          │
│ 证真 ⇄ 慎思      │           │          │
│ ArgumentOutput   │           │          │
│ (debate.py)      │           │          │
└──────────────────┘           │          │
      │                        │          │
      ▼                        │          │
┌──────────────┐               │          │
│ 策执远       │◄──────────────┘          │
│ TradingPlan │                          │
│ Output      │                          │
│ (trading_   │                          │
│  plan.py)   │                          │
└──────┬───────┘                          │
       │                                  │
       ▼                                  │
┌──────────────┐                          │
│ 风控明       │◄─────────────────────────┘
│ RiskOutput   │
│ (risk.py)    │
└──────┬───────┘
       │
       ▼
  闫判官 (收到风控verdict后裁决)
       │
       ▼
  明鉴秋 (最终决策)
```

## 角色与阶段对照

> v5.2.1更新：废除"闫判官全权主持"→明鉴秋全程调度

| 角色 | Agent | P1 | P1.5 | P2 | P3 | P4 |
|:----|:------|:-:|:----:|:--:|:--:|:--:|
| 数技源 | datatech | ● 三类信号 | | | |
| 链证源 | chain-analyst | | ● 产业链 | | |
| **闫判官** | judge | | | **● 选品种+定方向** | |
| 探源 | fundamental | | | | ● 供弹 |
| 观澜 | technical | | | | ● 供弹+支撑/阻力 |
| 证真 | affirmative | | | | ● 正方论据 |
| 慎思 | opposition | | | | ● 反方论据 |
| 策执远 | strategist | | | | ● 方案(3挡) |
| 风控明 | risk | | | | ● 审核 |
| **明鉴秋** | team-lead | **● 启动** | | | **● 轮询+传递** | **● 归档+报告** |

---

## 每轮辩论的数据流（P1→P5）

### P1：数据采集（数技源）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 数技源 | symbols list | `scan_all.py --dual [--ml]` | `full_scan_l1l4_*.json` | 无（原始数据JSON） | `reports/` |
| | | | `full_scan_factor_timing_*.json` | 无（原始数据JSON） | `reports/` |
| | | | `full_scan_ml_*.json` (可选) | 无（原始数据JSON） | `reports/` |

### P1.5：产业链分析（链证源）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 链证源 | 数技源 JSON | WebSearch 产业链验证 | 产业链景气度快照 | `ChainAnalysisOutput` | 内存/`chain_*.json` |

### P2：研究员供弹（并行）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 探源 | 数技源 JSON + WebSearch | 5维度基本面分析 | 基本面状态向量 | `FundamentalStateVector` | `fundamental_state_*.json` |
| 观澜 | 数技源 JSON + technical-analysis | 技术面分析 | 技术面快照 | `TechnicalOutput` | `technical_*.json` |

### P3：辩论（闫判官主持）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 闫判官 | 数技源+链证源+探源+观澜 | 汇总证据简报 → 选品种+定方向 | `PrepBrief`（内部） | `PrepBrief` | 内存 |
| 证真 | 闫判官的方向指定 + 两份策略数据 | 提炼多头论据 | `ArgumentOutput(role="证真")` | `ArgumentOutput` | `debate_bull_*.json` |
| 慎思 | 同上（空方向） | 提炼空头论据 | `ArgumentOutput(role="慎思")` | `ArgumentOutput` | `debate_bear_*.json` |
| 闫判官 | 证真+慎思的论据 | 主持交锋+裁决 | `FinalJudgment` | `FinalJudgment` | `judge_final_*.json` |

### P4：方案+风控（并行）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 策执远 | 胜方提案 | 合约选型+执行方案 | `TradingPlanOutput` | `TradingPlanOutput` | `plan_*.json` |
| 风控明 | 执行方案 | 5层风控审核 | `RiskOutput` | `RiskOutput` | `risk_*.json` |

### P5：归档（明鉴秋）

| Agent | 输入 | 动作 | 输出 | Schema | 文件 |
|:------|:-----|:-----|:-----|:-------|:-----|
| 明鉴秋 | FinalJudgment + RiskOutput + 所有中间产物 | 最终决策 | `TeamDecisionOutput` | `TeamDecisionOutput` | `debate_results.json` |
| | | 归档 + 发报告 | debate_results.json + HTML | — | `docs/` |

---

## 契约定义（Schema 索引）

所有 schema 定义在 `skills/futures-trading-analysis/contracts/` 目录下（Pydantic v2 models），同步导出为 JSON Schema 文件 `docs/schemas/`：

| schema | 源文件 | JSON Schema | 版本 | 生产者 | 消费者 |
|:-------|:-------|:------------|:----|:-------|:-------|
| `PhaseMeta` | `base.py` | — (通用元数据) | 3.0 | 所有 Agent | 编排层 |
| `BaseSkillOutput` | `base.py` | — (基类) | 3.0 | 所有 Agent（基类） | 编排层 |
| `DataCollectionOutput` | `data_collection.py` | — | 2.0 | 数聚石（旧） | 分析层 |
| `TechnicalOutput` | `technical.py` | — | 2.0 | 观澜 | 闫判官+证真+慎思 |
| `ChainAnalysisOutput` | `chain_analysis.py` | `ChainAnalysisOutput.json` | 3.0 | 链证源 | 闫判官 |
| `FundamentalStateVector` | `fundamental_state.py` | — | 1.0 🆕 | 探源 | 闫判官+证真+慎思 |
| `ArgumentOutput` | `debate.py` | `ArgumentOutput.json` | 3.0 | 证真/慎思 | 闫判官 |
| `StructuredDebate` | `debate.py` | `StructuredDebate.json` | 3.0 | 证真/慎思 (v3) | 闫判官 |
| `PrepBrief` | `evidence_brief.py` | — | 1.0 🆕 | 闫判官（辩论前） | 辩论角色 |
| `FinalJudgment` | `evidence_brief.py` | — | 1.0 🆕 | 闫判官（裁决） | 明鉴秋 |
| `RiskOutput` | `risk.py` | `RiskOutput.json` | 3.0 | 风控明 | 闫判官 |
| `TradingPlanOutput` | `trading_plan.py` | — | 2.0 | 策执远 | 风控明 |
| `TeamDecisionOutput` | `team_decision.py` | — | 1.0 🆕 | 明鉴秋 | main + 归档 |

> 💡 **Validation**: 任何 JSON Schema 文件 (`.json`) 均可使用标准 JSON Schema 验证工具校验。Pydantic 模型可通过 `.model_validate()` 在 Python 中直接校验。

---

---

## 通信规则

### 1. 文件通信

Agent 之间通过 JSON 文件传递数据，非直接调用。

```
产出方: 写 JSON 文件到约定目录
消费方: 从文件路径读取 → 按 schema 解析
编排层: 验证 schema + 版本迁移
```

### 2. 路径约定

```
reports/
├── full_scan_l1l4_{date}.json          # 数技源
├── full_scan_factor_timing_{date}.json  # 数技源
├── full_scan_summary_{date}.json       # 数技源
├── chain_analysis_{date}.json          # 链证源
├── fundamental_state_{symbol}_{date}.json  # 探源
├── technical_{symbol}_{date}.json      # 观澜
├── debate_bull_{trace_id}.json         # 证真
├── debate_bear_{trace_id}.json         # 慎思
├── judge_final_{trace_id}.json         # 闫判官
├── plan_{trace_id}.json                # 策执远
├── risk_{trace_id}.json                # 风控明
└── debate_results_{trace_id}.json      # 明鉴秋（最终）
```

### 3. 数据保鲜

- 所有输出必须包含 `meta.created_at`（时间戳）
- 消费方读取时检查时效：`staleness = now - created_at`
- >3 天打置信度 7折 / >7天 5折 / >14天 弃用

### 4. 版本兼容

```
产出方: 写入 `version` 字段
消费方: 读取 `version` → 如有迁移路径，自动升级/降级
编排层: `contracts/migrations.py` 管理版本迁移
         `apply_migration(skill_type, data, target_version)`
```

### 5. 校验规则

```
编排层在传递前校验：
□ schema.model_validate(data) 不抛异常
□ required fields 不空
□ confidence ∈ [0, 1] 或 [0, 100]
□ 无 verdict 字段（研究员输出红线）
□ meta.agent_name 与产出方一致
```

---

## 每个 Agent 需要遵循的 Output 规则

| 角色 | 输出必须包含 meta | 输出必须符合 schema | 禁止字段 |
|:-----|:-----------------|:--------------------|:---------|
| 数技源 | ✅ file timestamp | 无（原始数据） | 方向判断、推荐 |
| 链证源 | ✅ | `ChainAnalysisOutput` | 品种级别多空判断 |
| 探源 | ✅ | `FundamentalStateVector` | `verdict`、多空结论 |
| 观澜 | ✅ | `TechnicalOutput` | `verdict`、多空结论 |
| 证真 | ✅ | `ArgumentOutput(role="证真")` | — |
| 慎思 | ✅ | `ArgumentOutput(role="慎思")` | — |
| 闫判官 | ✅ | `PrepBrief` (辩论前) / `FinalJudgment` (判决) | — |
| 策执远 | ✅ | `TradingPlanOutput` | 未经风控审核的方案 |
| 风控明 | ✅ | `RiskOutput` | `confidence > 0.9` |
| 明鉴秋 | ✅ | `TeamDecisionOutput` | — |

---

## memory 记录规范

所有 Agent 在完成输出后，向 `memory/debate_journal.json` 追加记录：

```python
from scripts.memory_writer import append_debate_journal

append_debate_journal(agent_name, action, {
    "symbols": [...],
    "trace_id": "...",
    "schema_version": "3.0",
    "key_findings": [...],
})
```

---

## 修改历史

| 日期 | 版本 | 变更 |
|:-----|:-----|:-----|
| 2026-07-05 | 3.0 | 创建。新增 `FundamentalStateVector`、`PrepBrief`、`FinalJudgment`、`TeamDecisionOutput` schema。修复 `debate.py` 缺失的 `BaseSkillOutput` 导入。完整10角色协议映射。 |
