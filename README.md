# 期货交易辩论专家团（Futures Trading Debate Team）

> **v4.0 数据辩论** · 自动生成: 2026-07-04 18:29
>
> 数技源定方向 → 研究员供证据（工具查询真实数据） → 正反方辩手验证（因子溯源） → 闫判官判胜负（收敛自适应） → 策执远出策略（含情景分析） → 风控明审方案 → 明鉴秋复盘归档
>
> 数技师定方向 → 研究员供证据 → 正反方辩手验证 → 判官判胜负 → 策执远出策略 → 风控审方案

本仓库存放 [futures-debate-team](futures-debate-team/) 专家包，含完整Agent定义、规则、记忆库、头像及全部8个关联Skill。

## 目录结构

```
experts/
└── futures-debate-team/           ← 专家包根目录（唯一需要关注的目录）
    ├── agents/                    ← 11 个子Agent定义
    ├── avatars/                   ← 11个头像
    ├── memory/                    ← 辩论记忆库
    ├── rules/                     ← 辩论规则
    └── skills/                    ← 8个关联Skill（辩论专家专用）
        ├── commodity-chain-analysis/   产业链分析
        ├── debate-argument-builder/    论点构建
        ├── debate-judge/              裁判主持+评分
        ├── debate-risk-manager/        风控审核
        ├── debate-trading-planner/     策略合成
        ├── futures-data-technician/    数据管道
        ├── futures-trading-analysis/   主协调Skill
        └── quant-daily/                量化分析引擎
```

## 子Agent（11个）

  - `futures-affirmative-debater.md` | Affirmative Debater.Md
  - `futures-chain-analyst.md` | Chain Analyst.Md
  - `futures-datatech.md` | Datatech.Md
  - `futures-debate-team-team-lead.md` | Debate Team Team Lead.Md
  - `futures-fundamental-researcher.md` | Fundamental Researcher.Md
  - `futures-judge.md` | Judge.Md
  - `futures-opposition-debater.md` | Opposition Debater.Md
  - `futures-quant-analyst.md` | Quant Analyst.Md
  - `futures-risk-manager.md` | Risk Manager.Md
  - `futures-technical-researcher.md` | Technical Researcher.Md
  - `futures-trading-strategist.md` | Trading Strategist.Md


## 关联Skill（8个）

  - `commodity-chain-analysis/` | 402 行 SKILL.md
  - `debate-argument-builder/` | 331 行 SKILL.md
  - `debate-judge/` | 224 行 SKILL.md
  - `debate-risk-manager/` | 225 行 SKILL.md
  - `debate-trading-planner/` | 287 行 SKILL.md
  - `futures-data-technician/` | 143 行 SKILL.md
  - `futures-trading-analysis/` | 1017 行 SKILL.md
  - `quant-daily/` | 270 行 SKILL.md


## 安装

1. 将 `futures-debate-team/` 复制到 `~/.workbuddy/plugins/marketplaces/my-experts/plugins/`
2. 在 WorkBuddy 中激活该专家即可使用（关联skill自动加载）

## 数据源

K线数据通过通达信本地客户端（TQ-Local HTTP, 127.0.0.1:17709）获取，需先启动通达信软件。

## 相关仓库

此仓库仅包含 `futures-debate-team` 专家包。不相关的内容已迁移至各自的专属仓库。
