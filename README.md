# 期货交易辩论专家团（Futures Trading Debate Team）

> **九角色五阶段**：研究员(供弹)→辩手(开火)→裁判(控场)→风控(叫停)→主管(拍板)

## 架构

```
experts/
├── futures-debate-team/          ← WorkBuddy 专家包（plugin.json + agents + avatars）
│   ├── .codebuddy-plugin/plugin.json
│   ├── agents/                   ← 9个Agent定义（MD文件）
│   ├── avatars/                  ← 11个头像（PNG）
│   └── skills/                   ← 内含主协调 skill
│       └── futures-trading-analysis/
└── skills/                       ← 全部8个 Skill 定义
    ├── futures-trading-analysis/     (v3.0.0) 主协调
    ├── futures-data-technician/      (v1.0.0) 数技师数据管道
    ├── commodity-chain-analysis/     (v2.13.0) 基本面研究+产业链
    ├── debate-argument-builder/      (v2.1.0) 多/空辩手论点构建
    ├── debate-judge/                 (v2.0.0) 裁判主持+评分
    ├── debate-risk-manager/          (v3.0.0) 风控三合一
    ├── debate-trading-planner/       (v2.0.0) 策略师方案合成
    └── quant-daily/                  (v1.0.1) 数据采集+指标计算（底层）
```

## 九角色

| 序号 | 角色 | 花名 | Agent ID |
|:---:|:----|:-----|:---------|
| 1 | 🎯 团队主管 | 明鉴秋 | futures-debate-team-team-lead |
| 2 | 📡 数技师 | 数技源 | futures-datatech |
| 3 | 🟢 基本面研究员 | 探源 | futures-fundamental-researcher |
| 4 | 🟢 技术面研究员 | 观澜 | futures-technical-researcher |
| 5 | 🔵 多头辩手 | 牛势研 | futures-bull-researcher |
| 6 | 🔴 空头辩手 | 熊谋略 | futures-bear-researcher |
| 7 | ⚪ 裁判/主持 | 闫判官 | futures-judge |
| 8 | 🟡 风控 | 风控明 | futures-risk-manager |
| 9 | 📋 策略师 | 策执远 | futures-trading-strategist |

## 五阶段

| 阶段 | 时间 | 主导 | 关键产出 |
|:----|:----:|:----|:---------|
| 选题与准备 | T-60min | 🎯 团队主管 | 品种+周期+权益 |
| 研究出图 | T-40min | 🟢 研究员 x2 | 两份快照（基本面+技术面） |
| 辩论 | T-30~T+0 | ⚪ 裁判主持 | 双方final提案 |
| 策略+风控 | T+0~T+25 | 📋策略师→🟡风控 | 可执行方案+verdict |
| 决策归档 | T+25~T+30 | 🎯 团队主管 | 执行/搁置/重辩 |

## 分工铁律

- **研究员不站队** — 只列事实+边际变化，不下结论（verdict=null强制）
- **辩手不造假** — 逻辑链必须追溯到研究员证据，不能编数据
- **策略师不改方向** — 只把胜方提案翻译成可执行方案
- **风控不改多空** — 有否决权，无改方向权
- **裁判不站队** — 只控场+记录+评分

## 安装

1. 将 `futures-debate-team/` 复制到 `~/.workbuddy/plugins/marketplaces/my-experts/plugins/`
2. 运行注册脚本：`python3 scripts/register_expert.py <path>`
3. 将 `skills/` 下的8个skill复制到 `~/.workbuddy/skills/`

## 数据源

K线数据通过通达信本地客户端（TQ-Local HTTP, 127.0.0.1:17709）获取，需先启动通达信软件。
