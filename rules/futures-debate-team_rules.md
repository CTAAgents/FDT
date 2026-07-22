---
description: >-
  v9.11.2 — 10 Agent 多角色交叉质询 CTA 决策系统。LangGraph 图编排，
  四源并行（链证源+观澜+探源+读心），六阶段辩论，闫判官直接输出完整交易参数。
  Use when: 期货分析、多空辩论、交易建议、螺纹钢铁矿石原油黄金期货、
  做多做空、趋势分析、商品期货深度分析、期货交易辩论。
alwaysApply: true
enabled: true
updatedAt: 2026-07-22T14:00:00.000Z
provider:
---

# 期货辩论专家团 — 运行规则（v9.11.2）

## 1. 10 Agent 职责与工具权限

| Agent | 类型 | 工具 | 职责 |
|:------|:-----|:-----|:-----|
| **📡 数技源** | 直调Python | 无（库函数模式） | 运行 `scan_all.py` 通道突破扫描(唐奇安DC20/DC55+布林带)，产出信号汇总。**不做分析，不下结论** |
| **🔗 链证源** | general-purpose | Read, Write, SendMessage | 产业链事实描述+景气度分析，识别同链冗余(如RB≈HC)。**不下多空结论** |
| **🧑‍🔬 观澜** | general-purpose | Read, Write, SendMessage | 技术面研究员。基于K线+指标+支撑阻力计算产出技术面快照（含FDC技术数据增强）。**中立，verdict=null** |
| **🧑‍🔬 探源** | general-purpose | **WebSearch**, Read, Write, SendMessage | 基本面研究员。WebSearch搜集供需/库存/利润/政策数据，产出基本面状态向量（含FDC基本面数据增强）。**中立，verdict=null** |
| **🧑‍🔬 读心** | general-purpose | **MCP(金十)**, Read, Write, SendMessage | 新闻情绪研究员。金十MCP快讯+WebSearch多源采集，产出结构化情绪状态向量（SentimentStateVector）。**中立，verdict=null** |
| **🔵 多头分析员** | general-purpose | Read, Write, SendMessage | 多头分析员。从四研究员资料中提取做多论据。**禁止WebSearch自行搜索** |
| **🔴 空头分析员** | general-purpose | Read, Write, SendMessage | 空头分析员。从四研究员资料中提取做空论据。**禁止WebSearch自行搜索** |
| **⚪ 闫判官** | general-purpose | Read, Write, SendMessage | 辩论裁决官。初判定品种+方向+调度四源(P2)，终裁判胜负+直接输出完整交易参数(P5) |
| **🟡 风控明** | general-purpose | Read, Write, SendMessage | 风控审核官。杠杆/回撤/叙事质检/同链冗余排除，直接审核闫判官交易参数 |
| **🎯 明鉴秋** | 主skill常驻 | Read, Bash, SendMessage | 团队主管。选题+按闫判官指令spawn子Agent+汇总产出一致性+记忆写入 |

**spawn原则**：链证源/观澜/探源/读心/辩手/闫判官/风控明均使用 `subagent_type="general-purpose"`，prompt中加载角色定义。数技源直调Python不spawn。

## 2. 执行流程（P0→P6）

```

    ┌─────────────────────────────────────────────────────────────┐
    │              P0: 数技源 品种扫描 & 数据准备                  │
    │  scan_all.py channel_breakout → full_scan_summary_{date}.json│
    │  FDC node_prepare_data → fdc_data（K线/指标/期限/基差等）   │
    └─────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              P1: 链证源 产业链分析                           │
    │  产业链归属/趋势/一致性/期限结构/基差                       │
    │  产出: p1_chain_analysis.json                              │
    └─────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              P2: 闫判官 初判调度                             │
    │  读取scan_results + 链证源 → 定辩论品种+方向               │
    │  决策: 方向分歧度+产业链位置+信号强度+ADX角色反转           │
    │  产出: judge_direction + selected_symbols + dispatch_sources│
    └─────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              P3: 四源并行 → merge_research                    │
    │  ┌──────┬──────┬──────┬──────┐                             │
    │  │链证源 │ 观澜 │ 探源 │ 读心 │  ← 四源并行               │
    │  └──┬───┴──┬───┴──┬───┴──┬───┘                             │
    │     │      │      │      │                                  │
    │     ▼      ▼      ▼      ▼                                  │
    │  [chain] [technical] [fundamental] [sentiment]              │
    │     │      │      │      │                                  │
    │     └──────┴──┬───┴──────┘                                  │
    │               ▼                                              │
    │        merge_research（四源汇总）                            │
    └─────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              P4: 六阶段辩论（多空交叉质询）                   │
    │  P4_1 多头立论 → P4_2 空头立论                              │
    │  P4_3 空头驳论 → P4_4 多头驳论                              │
    │  P4_5 空头结辩 → P4_6 多头结辩                              │
    └─────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              P5: 裁决 → 风控 → 信号输出 → 报告              │
    │  ├── node_verdict: 闫判官终裁（六维评分+交易参数）          │
    │  ├── node_risk_check: 风控明审核（risk_color）              │
    │  ├── node_signal_output: CTP信号输出（sent/blocked）        │
    │  ├── node_report: HTML报告 + debate_results.json            │
    │  └── 明鉴秋汇总 + 记忆写入                                  │
    └─────────────────────────────────────────────────────────────┘

⏱ 全过程由 LangGraph (fdt_langgraph/) 图编排
   → 可选 mode: default/fast/deep_research/tournament
   → 状态持久化: SQLite(默认) / PostgreSQL(环境变量切换)
   → trace_id 全链路贯穿
```

## 3. 文件产出清单

所有文件写入 `memory/{round_id}/` 目录：

| 文件 | 阶段 | 产出者 | 说明 |
|:-----|:------|:--------|:------|
| `full_scan_summary_{date}.json` | P0 | 数技源 | 通道突破全品种信号汇总 |
| `fdc_data_{sym}.json` | P0 | `node_prepare_data` | FDC预采集数据（K线/指标/期限/基差/仓单） |
| `p1_chain_analysis.json` | P1 | 链证源 | 产业链分析（含chain_results） |
| `p0_judge_directive.json` | P2 | 闫判官初判 | 辩论品种+方向+产业链调度指令 |
| `p3_technical_{sym}.json` | P3 | 观澜 | 技术面分析（支撑阻力/指标），FDC增强 |
| `p3_fundamental_{sym}.json` | P3 | 探源 | 基本面状态向量，FDC增强 |
| `p3_sentiment_{sym}.json` | P3 | 读心 | 新闻情绪状态向量（SentimentStateVector） |
| `p4_bullish_{sym}.json` | P4 | 多头分析员 | 多头辩论论据 |
| `p4_bearish_{sym}.json` | P4 | 空头分析员 | 空头辩论论据 |
| `p5_judge_{sym}.json` | P5 | 闫判官终裁 | 裁决方向+六维评分分解 |
| `p5_trading_plan_{sym}.json` | P5 | 闫判官(交易参数) | 入场/止损/目标/仓位/合约 |
| `p5_risk_review_{sym}.json` | P5 | 风控明 | 风控审核结果 |
| `debate_results.json` | P6 | 明鉴秋汇总 | 全品种裁决+交易参数汇总 |
| `debate_report_{date}.html` | P6 | 报告生成 | 可视化HTML报告 |

## 4. 数据流拓扑

```
数技源 scan_all.py channel_breakout → full_scan_summary.json
    │
    ▼
P2.5 FDC数据准备 → fdc_data（并行采集各品种技术+基本面数据）
    │
    ▼
闫判官(P2) ─── 选定品种+方向
    │
    ├──→ 链证源(P3) ──→ p1_chain_analysis.json
    ├──→ 观澜(P3) ────→ p3_technical_{sym}.json  ← FDC技术数据注入
    ├──→ 探源(P3) ────→ p3_fundamental_{sym}.json ← FDC基本面+WebSearch
    └──→ 读心(P3) ────→ p3_sentiment_{sym}.json  ← 金十MCP+WebSearch
    │
    ▼
merge_research（四源汇总）
    │
    ▼
P4_1 多头立论 → P4_2 空头立论 → P4_3 空头驳论 → P4_4 多头驳论 → P4_5 空头结辩 → P4_6 多头结辩
    │
    ▼
闫判官终裁(P5) → 风控明审核(P5) → signal_output → report → 记忆写入
(六维评分+交易参数)      (green/yellow/red)
```

**数据流单向性原则**：Agent只能读自己阶段之前的文件，不能读后续产出。明鉴秋汇总时反向验证完整性。

## 5. 降级策略

| 层级 | 机制 | 触发条件 | 降级行为 |
|:-----|:------|:---------|:---------|
| **L1** | 产出校验 | Agent产出JSON损坏/Schema不合规 | 标记无效→触发L2重试 |
| **L2** | 熔断降级 | L1校验失败→retry 2次 | D06: 明鉴秋基于已有论据独立裁决 |
| **L3** | 信号门 | 全品种\|total\|<DEBATE_ENTRY_MIN_ABS | 不spawn辩论Agent，回报"无有效信号" |
| **L4** | 数据源降级 | 数据采集失败 | DataCore→TDX→TqSdk→QMT→WebFallback 五级降级，每级独立熔断器（连续5次失败→60秒冷却） |
| **L5** | P3研究员降级 | 四源中某源超时(300s) | 自动跳过该源，标记缺失字段，剩余源继续merge_research |
| **L6** | P4辩论降级 | 辩论阶段超时(600s) | 自动跳过该阶段，`arguments=[]` 继续后续阶段 |
| **L7** | 健康自检 | 辩论启动前环境检查 | 检测数据源/路径/脚本/Agent定义完整性 |

**Spawn重试协议**：子Agent spawn时遇402等瞬时错误→自动重试2次(间隔5s)→仍失败进入D06降级。

**缺员降级**：某品种缺p4产出→闫判官论据不全仍出裁决(标记partial_evidence)。缺p5_judge→assemble跳过该品种不阻断其他。缺p5_risk_review→标"仅裁决"仍进报告。

## 6. 通信铁律

1. **时序铁律**: 链证源→闫判官→四研究员→辩手。此顺序不可颠倒
2. **串线铁律**: Agent之间不得互相SendMessage。产出一律写文件
3. **文件优先**: Agent产出只写文件，明鉴秋用poll_file_ready轮询
4. **辩手禁搜**: 多头/空头分析员不得自行搜索数据，所有论据从四研究员资料中提取
5. **禁止代写**: 明鉴秋不得自行撰写论据/裁决/方案，必须spawn对应Agent
6. **品种独立**: 每个品种独立spawn完整Agent链条，严禁一个Agent同时处理多品种
7. **文件就绪**: spawn下游前，上游文件必须已稳定≥5秒
8. **Phase门禁**: 汇总前检查缺失产出，缺失拒绝生成报告

## 7. 策略管线概述

v2可插拔策略管线(`strategies/registry_v2.py`)：7策略注册 + 2个内部Pipeline，NO_FUSION零融合（各策略独立打分，方向冲突→辩论层裁决）。

| 策略 | 注册名 | 状态 | 说明 |
|:-----|:-------|:-----|:------|
| **趋势跟踪** | trend_following | ✅ 活跃（唯一） | 唐奇安通道突破（DC20/DC55）+ 布林带通道 |
| **均值回归** | mean_reversion | ⏸ 暂停 | RSI/布林带超买超卖回归 |
| **套利策略** | arbitrage | ⏸ 暂停 | 跨期/跨品种价差套利(待完善) |
| **配对回归** | pairs_reversion | ⏸ 暂停 | 产业链配对回归(如RB⇄HC) |
| **价差回归** | spread_reversion | ⏸ 暂停 | 跨期价差均值回归 |
| **基差回归** | basis_reversion | ⏸ 暂停 | 基差过大回归交易 |
| **宏观制度** | macro_regime | ⏸ 暂停 | 宏观制度切换识别 |
| **ML信号** | ml_signal | ⏸ 暂停 | ONNX模型推理(模型库空) |
| **Pipeline: 扫描** | scan_all | ✅ 生产 | channel_breakout 单策略 62品种扫描 |
| **Pipeline: 辩论** | fdt_langgraph | ✅ 生产 | 10-Agent LangGraph图编排 |

CLI `--strategies` 显式指定可覆盖禁用集，启用暂停策略。

## 8. 10 Agent 辩论制衡

```
                     明鉴秋(主管)
                     ／     |     ＼
                闫判官(初判)  |   闫判官(终裁)
                /    |    |   \   |    |    |
            链证源  观澜  探源  读心 多头 空头 风控明
            (事实) (技术)(基本面)(情绪) (多) (空) (审核)
```

- **数技源**: 数据层，产出客观信号，不参与辩论
- **链证源**: 事实层，提供产业链景气度事实，不下多空结论
- **观澜/探源/读心**: 研究员层，提供技术+基本面+新闻情绪分析素材（中立，verdict=null）
- **多头分析员/空头分析员**: 对抗层，从相同素材提取不同方向的论据，交叉质询
- **闫判官**: 裁决层，初判定方向（P2）+终裁判胜负+输出交易参数（P5）
- **风控明**: 审核层，独立审查闫判官交易参数的风险合理性
- **明鉴秋**: 协调层，选题+调度+汇总+记忆写入，不代写辩论内容

ADX角色反转规则贯穿全流程：ADX低位(<20)视为趋势启动早期鼓励确认，ADX高位(≥60)为过热警示不得作为致命伤。ADX提及占比≤1/3。

### 辩论六阶段

```
P4_1 多头立论（Bullish Opening）→ 多头分析员基于四研究员资料构建做多论据
P4_2 空头立论（Bearish Opening）→ 空头分析员基于四研究员资料构建做空论据
P4_3 空头驳论（Bearish Rebuttal）→ 空头分析员反驳多头论据
P4_4 多头驳论（Bullish Rebuttal）→ 多头分析员反驳空头论据
P4_5 空头结辩（Bearish Final）→ 空头分析员总结陈述
P4_6 多头结辩（Bullish Final）→ 多头分析员总结陈述
```

### 四源并行LLM推理

| 分析源 | Agent | 输入 | 输出 |
|:-------|:------|:-----|:-----|
| 技术面 | 观澜 | K线+FDC技术数据+技术指标 | TechnicalStateVector |
| 基本面 | 探源 | FDC基本面数据+WebSearch | FundamentalStateVector |
| 产业链 | 链证源 | 扫描信号+WebSearch | ChainAnalysisOutput |
| 新闻情绪 | 读心 | 金十MCP快讯+WebSearch | SentimentStateVector |

- P3 阶段四源并行，无依赖关系
- merge_research 节点在四源全部完成后汇总
- 任一源超时或失败不影响其他三源
- 闫判官终裁时四维加权评分
