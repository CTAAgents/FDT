# 期货交易辩论专家团 — 依赖关系梳理

> 生成时间：2026-07-03 10:34 | 版本：v3.0.0 | 角色数：9 | Skill数：8

---

## 一、总览：专家团 → Skills 映射

```
┌─────────────────────────────────────────────────────────────────┐
│                   期货交易辩论专家团                              │
│              plugin.json / marketplace.json                     │
│  skills: ["./skills/futures-trading-analysis"]                   │
└──────────┬──────────────────────────────┬──────────────────────┘
           │                              │
           ▼                              ▼
  9 个 Agent MD 文件               8 个 Skill
  (agents/*.md)                    (~/.workbuddy/skills/*/SKILL.md)
```

---

## 二、Agent → Skill 映射（逐角色）

| # | 角色 | Agent ID | 花名 | 对应 Skill |
|:-:|:----|:---------|:-----|:-----------|
| 🎯 | **团队主管** | `futures-debate-team-team-lead` | 明鉴秋 | `futures-trading-analysis` |
| 📡 | **数技师** | `futures-datatech` | (无) | `futures-data-technician` |
| 🟢 | **基本面研究员** | `futures-fundamental-researcher` | (无) | `commodity-chain-analysis` |
| 🟢 | **技术面研究员** | `futures-technical-researcher` | (无) | `quant-daily` |
| 🔵 | **多头辩手** | `futures-bull-researcher` | 牛势研 | `debate-argument-builder` |
| 🔴 | **空头辩手** | `futures-bear-researcher` | 熊谋略 | `debate-argument-builder` |
| ⚪ | **裁判/主持** | `futures-judge` | 闫判官 | `debate-judge` |
| 🟡 | **风控** | `futures-risk-manager` | 风控明 | `debate-risk-manager` |
| 📋 | **策略师** | `futures-trading-strategist` | 策执远 | `debate-trading-planner` |

---

## 三、Skill → Skill 依赖树

```
futures-debate-team (专家团)
├── plugin.json → skills: ["./skills/futures-trading-analysis"]
│
└─┬ futures-trading-analysis (v3.0.0) ─── 主协调
  │ ├── 依赖 contracts/ (Pydantic schema 定义)
  │ │
  │ ├─→ futures-data-technician (v1.0.0) ─── 数技师专用
  │ │   └─→ quant-daily (v1.0.1) ─── 数据采集+指标计算
  │ │       ├── 内部：data/ (MultiSourceAdapter, DuckDB)
  │ │       ├── 内部：indicators/ (numpy向量化, TDX bridge)
  │ │       ├── 内部：signals/ (L1-L4评分系统)
  │ │       └── 外部：通达信TQ-Local HTTP (127.0.0.1:17709)
  │ │
  │ ├─→ commodity-chain-analysis (v2.13.0) ─── 基本面研究员+链分析
  │ │   ├── scripts/chains.py (产业链归类映射)
  │ │   ├── scripts/term_basis.py (期限结构+基差)
  │ │   ├── scripts/chain_verifier.py (一致性检验)
  │ │   └── WebSearch/WebFetch (基本面数据补充)
  │ │
  │ ├─→ debate-argument-builder (v2.1.0) ─── 多/空辩手
  │ │   ├── LLM推理 + WebSearch/WebFetch (基本面搜索)
  │ │   └── 5硬约束(附和禁止/证据格式/角色锚定/场景分离/认错信号)
  │ │
  │ ├─→ debate-judge (v2.0.0) ─── 裁判主持
  │ │   ├── 4阶段流程(准备/辩论/评审/判决)
  │ │   └── 5维评分模型
  │ │
  │ ├─→ debate-risk-manager (v3.0.0) ─── 风控
  │ │   ├── 6步决策链(口径/算账/对冲/逻辑/verdict)
  │ │   └── 期货特有红线(杠杆/止损/叙事/交割)
  │ │
  │ └─→ debate-trading-planner (v2.0.0) ─── 策略师
  │     ├── 8工具(合约/仓位/对冲/建仓/止损/止盈/移仓/退出)
  │     ├── 凯利公式/固定分数模型仓位计算
  │     └── 风控red回退机制
  │
  └── 非依赖但关联的外部 skill（已合并进 quant-daily，不直接调用）
      ├── futures-data-search (v4.1.0) ─── 已合入 quant-daily
      ├── commodity-trend-signal (v2.18.0) ─── 已合入 quant-daily
      └── technical-indicator-calc (v2.4.2) ─── 已合入 quant-daily
```

---

## 四、深度依赖关系（路由视角）

```
用户
  │
  ▼
🎯 明鉴秋 ─── futures-trading-analysis
  │
  ├──(选题)──→ 📡 数技师 ─── futures-data-technician ───→ quant-daily
  │                                                           │
  │                              ◄── 通达信TQ-Local HTTP ────┘
  │
  ├──(主持)──→ ⚪ 闫判官 ─── debate-judge
  │             │
  │             ├──(spawn)──→ 🟢 基本面研究员 ─── commodity-chain-analysis
  │             ├──(spawn)──→ 🟢 技术面研究员 ─── quant-daily
  │             ├──(TeamCreate)──→ 🔵 多头辩手 ─── debate-argument-builder
  │             │               └──→ 🔴 空头辩手 ─── debate-argument-builder
  │             ├──(判胜负)──→ 📋 策执远 ─── debate-trading-planner
  │             │               │
  │             │               └──(传方案)──→ 🟡 风控明 ─── debate-risk-manager
  │             └──(收verdict)──→ 🔄 策执远(修改)←───┘
  │
  └──(拍板)──→ debate_results.json → HTML → 交付
```

---

## 五、Skill 版本清单

| Skill | 版本 | 最后更新 | 核心作用 |
|:------|:----:|:---------|:---------|
| `futures-trading-analysis` | **3.0.0** | 2026-07-03 | 主协调+调度+汇总 |
| `futures-data-technician` | **1.0.0** | 2026-07-03 | 数技师数据管道 |
| `quant-daily` | 1.0.1 | 2026-07-03 | 底层数据采集+指标（保留不动） |
| `commodity-chain-analysis` | **2.13.0** | 2026-07-03 | 产业链分析+基本面研究员接口 |
| `debate-argument-builder` | **2.1.0** | 2026-07-03 | 多/空辩手论点构建 |
| `debate-judge` | **2.0.0** | 2026-07-03 | 裁判主持+评分判胜负 |
| `debate-risk-manager` | **3.0.0** | 2026-07-03 | 风控三合一(仓位沙盘+逻辑质检) |
| `debate-trading-planner` | **2.0.0** | 2026-07-03 | 策略师方案合成+风控回退 |

---

## 六、已合并不直接依赖的旧 Skill

以下技能的能力已被 `quant-daily` (v1.0.1) 吸收，辩论团队不再直接依赖它们：

| 旧 Skill | 原版本 | 能力去向 |
|:---------|:------:|:---------|
| `futures-data-search` | v4.1.0 | data/ → quant-daily/data/ (MultiSourceAdapter 多源降级链) |
| `commodity-trend-signal` | v2.18.0 | signals/ → quant-daily/signals/ (L1-L4四层打分) |
| `technical-indicator-calc` | v2.4.2 | indicators/ → quant-daily/indicators/ (44项指标numpy计算) |

---

## 七、数据流（哪些数据流过哪些 skill）

```
数技师阶段:
  通达信TQ-Local ──→ quant-daily/scan_all.py ──→ futures-data-technician
                                                     ↓
研究员阶段:                                      数据包JSON
  commodity-chain-analysis ──→ 基本面快照
  quant-daily ──→ 技术面快照
                          ↓
辩手阶段:               合并快照 ←—— 闫判官
  debate-argument-builder ──→ bull/bear 论点
                          ↓
裁判阶段:             论点+待回应清单
  debate-judge ──→ 胜负+评分
                          ↓
策略师阶段:           胜方提案
  debate-trading-planner ──→ 可执行方案
                          ↓
风控阶段:             方案+账户
  debate-risk-manager ──→ verdict + flags
                          ↓
汇总阶段:           最终判决
  futures-trading-analysis ──→ debate_results.json → HTML
```
