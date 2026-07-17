---
description: >-
  v8.7.0 — 9 Agent 辩论式期货分析专家团。闫判官直接输出完整交易参数，
  LangGraph图编排替代S04轮询。6策略v2管线可插拔。
  Use when: 期货分析、多空辩论、交易建议、螺纹钢铁矿石原油黄金期货、
  做多做空、趋势分析、商品期货深度分析、期货交易辩论。
alwaysApply: true
enabled: true
updatedAt: 2026-07-17T18:00:00.000Z
provider:
---

# 期货辩论专家团 — 运行规则（v8.7.0）

## 1. 9 Agent 职责与工具权限

| Agent | 类型 | 工具 | 职责 |
|:------|:-----|:-----|:-----|
| **📡 数技源** | 直调Python | 无（库函数模式） | 运行 `scan_all.py` 通道突破扫描(唐奇安DC20/DC55+布林带)，产出信号汇总。**不做分析，不下结论** |
| **🔗 链证源** | general-purpose | Read, Write, SendMessage | 产业链事实描述+景气度分析，识别同链冗余(如RB≈HC)。**不下多空结论** |
| **🧑‍🔬 观澜** | general-purpose | Read, Write, SendMessage | 技术面研究员。基于K线+指标+支撑阻力计算(`support_resistance.py`)产出技术面快照。**中立，verdict=null** |
| **🧑‍🔬 探源** | general-purpose | **WebSearch**, Read, Write, SendMessage | 基本面研究员。WebSearch搜集供需/库存/利润/政策数据，产出基本面状态向量。**中立，verdict=null** |
| **🔵 证真** | general-purpose | Read, Write, SendMessage | 多头分析员。从研究员+链证源资料中提取多头论据。**禁止WebSearch自行搜索** |
| **🔴 慎思** | general-purpose | Read, Write, SendMessage | 空头分析员。从研究员+链证源资料中提取空头论据。**禁止WebSearch自行搜索** |
| **⚪ 闫判官** | general-purpose | Read, Write, SendMessage | 辩论裁决官。初判定品种+方向+调度源(P2)，终裁判胜负+直接输出交易参数(P5) |
| **🟡 风控明** | general-purpose | Read, Write, SendMessage | 风控审核官。杠杆/回撤/叙事质检/同链冗余排除，v8.7.0直接审核闫判官交易参数 |
| **🎯 明鉴秋** | 主skill常驻 | Read, Bash, SendMessage | 团队主管。选题+按闫判官指令spawn子Agent+汇总产出一致性+记忆写入 |

**spawn原则**：链证源/观澜/探源/辩手/闫判官/风控明均使用 `subagent_type="general-purpose"`，prompt中加载角色定义。数技源直调Python不spawn。

## 2. 执行流程（S1→S5）

```
S1  ── 数技源 scan_all.py 通道突破扫描 → full_scan_summary_{date}.json
     产出: signal_summary(all_ranked含grade/total/direction/adx等)

S1.5 ── 链证源产业链分析（先于闫判官）
     产出: p1_chain_analysis.json（产业链归属/趋势/一致性/期限结构/基差）
     ⚠️ 必须 S1 → S1.5 串行

P2.5 ── FDC数据预采集（LangGraph node_prepare_data）
     K线+技术指标+期限结构+基差+价差+仓单+持仓排名+F10 → fdc_data
     并行采集各品种，注入S3研究员prompt

S2/P2 ── 闫判官综合决策
     读取signal_summary + 链证源快照 → 定辩论品种列表+正方方向
     决策依据: 方向分歧度+产业链位置+信号强度+ADX角色反转
     产出: judge_direction + selected_symbols + dispatch_sources

S3/P3 ── 三源并行 → 汇总 → 多空辩论
     ├── 链证源: 产业链深度分析（并行）
     ├── 观澜: 技术面分析（并行）← 注入FDC技术数据
     ├── 探源: 基本面分析（并行）← 注入FDC基本面数据 + WebSearch
     ├── merge_research: 汇总三源
     └── debate: 证真(多头) ⇄ 慎思(空头) 交叉质询

S4/P5 ── 裁决 → 风控 → 信号输出 → 报告
     ├── node_verdict: 闫判官终裁（含交易参数: 方向/入场/止损/目标/仓位/合约）
     ├── node_risk_check: 风控明审核（risk_color: green/yellow/red）
     ├── node_signal_output: CTP信号输出（green/yellow通过阈值→sent，red→blocked）
     ├── node_report: 生成HTML报告 + debate_results.json
     └── 明鉴秋汇总 + 记忆写入

⏱ 全过程由 LangGraph (fdt_langgraph/) 图编排
   → 可选 mode: default/fast/deep_research/tournament
   → 状态持久化: SQLite(默认) / PostgreSQL(环境变量切换)
```

## 3. 文件产出清单

所有文件写入 `{workspace}/` 目录：

| 文件 | 阶段 | 产出者 | 说明 |
|:-----|:------|:--------|:------|
| `full_scan_summary_{date}.json` | S1 | 数技源 | 通道突破全品种信号汇总 |
| `p1_chain_analysis.json` | S1.5 | 链证源 | 产业链分析（含chain_results） |
| `p0_judge_directive.json` | P2 | 闫判官初判 | 辩论品种+方向+产业链调度指令 |
| `p3_technical_{sym}.json` | P3 | 观澜 | 技术面分析（支撑阻力/指标） |
| `p3_fundamental_{sym}.json` | P3 | 探源 | 基本面状态向量 |
| `p4_bullish_{sym}.json` | P3 | 证真 | 多头辩论论据 |
| `p4_bearish_{sym}.json` | P3 | 慎思 | 空头辩论论据 |
| `p5_judge_{sym}.json` | P5 | 闫判官终裁 | 裁决方向+评分分解 |
| `p5_trading_plan_{sym}.json` | P5 | 闫判官(交易参数) | 入场/止损/目标/仓位/合约 |
| `p5_coherence_{sym}.json` | P5 | 一致性裁判 | 审计裁决是否源于辩论论据 |
| `p5_risk_review_{sym}.json` | P5 | 风控明 | 风控审核结果 |
| `debate_results.json` | P6 | 明鉴秋汇总 | 全品种裁决+交易参数汇总 |
| `intermediate_data.json` | P6 | 明鉴秋 | 报告生成中间数据 |
| `spawn_plan_{ts}.json` | plan | 明鉴秋 | spawn子Agent计划（含prompt） |

## 4. 数据流拓扑

```
scan_all.py channel_breakout
    │ full_scan_summary.json
    ▼
闫判官(P2) ─── 选定品种+方向
    │
    ├──→ 链证源(P3) ──→ p1_chain_analysis.json
    ├──→ 观澜(P3) ────→ p3_technical_{sym}.json  ← FDC技术数据注入
    └──→ 探源(P3) ────→ p3_fundamental_{sym}.json ← FDC基本面+WebSearch
    │
    ▼
merge_research → 辩论(P4) → 终裁(P5) → 风控(P5) → signal_output → report
                              ↑              ↑
                        闫判官裁决     风控明审核
                        (含交易参数)    (green/yellow/red)
```

**数据流单向性原则**：Agent只能读自己阶段之前的文件，不能读后续产出。明鉴秋汇总时反向验证完整性。

## 5. 降级策略

| 层级 | 机制 | 触发条件 | 降级行为 |
|:-----|:------|:---------|:---------|
| **L1** | 产出校验 | Agent产出JSON损坏/Schema不合规 | 标记无效→触发L2重试 |
| **L2** | 熔断降级 | L1校验失败→retry 2次 | D06: 明鉴秋基于已有论据独立裁决 |
| **L3** | 信号门 | 全品种\|total\|<DEBATE_ENTRY_MIN_ABS | 不spawn辩论Agent，回报"无有效信号" |
| **L4** | 路径自发现 | 报告生成时CLI参数缺失 | CLI参数→环境变量→自动发现(三级fallback) |
| **L5** | 健康自检 | 辩论启动前环境检查 | 检测数据源/路径/脚本/Agent定义完整性 |

**Spawn重试协议**：子Agent spawn时遇402等瞬时错误→自动重试2次(间隔5s)→仍失败进入D06降级。

**缺员降级**：某品种缺p4产出→闫判官论据不全仍出裁决(标记partial_evidence)。缺p5_judge→assemble跳过该品种不阻断其他。缺p5_risk_review→标"仅裁决"仍进报告。

## 6. 通信铁律

1. **时序铁律**: 链证源→闫判官→研究员→辩手。此顺序不可颠倒
2. **串线铁律**: Agent之间不得互相SendMessage。产出一律写文件
3. **文件优先**: Agent产出只写文件，明鉴秋用poll_file_ready轮询
4. **辩手禁搜**: 证真/慎思不得自行搜索数据，所有论据从研究员资料中提取
5. **禁止代写**: 明鉴秋不得自行撰写论据/裁决/方案，必须spawn对应Agent
6. **品种独立**: 每个品种独立spawn完整Agent链条，严禁一个Agent同时处理多品种
7. **文件就绪**: spawn下游前，上游文件必须已稳定≥5秒
8. **Phase门禁**: 汇总前检查缺失产出，缺失拒绝生成报告

## 7. 6策略v2管线概述

v2可插拔策略管线(`strategies/registry_v2.py`)：10策略注册，按依赖拓扑排序执行，NO_FUSION零融合(各策略独立打分，方向冲突交辩论层裁决)。

| 策略 | 注册名 | 状态 | 说明 |
|:-----|:-------|:-----|:------|
| **趋势跟踪** | trend_following | ✅ 活跃 | 唐奇安+均线+ADX趋势确认 |
| **均值回归** | mean_reversion | ✅ 活跃 | RSI/布林带超买超卖回归 |
| **套利策略** | arbitrage | ⏸ 暂停 | 跨期/跨品种价差套利(待完善) |
| **配对回归** | pairs_reversion | ⏸ 暂停 | 产业链配对回归(如RB⇄HC) |
| **价差回归** | spread_reversion | ⏸ 暂停 | 跨期价差均值回归 |
| **基差回归** | basis_reversion | ⏸ 暂停 | 基差过大回归交易 |
| **宏观制度** | macro_regime | ⏸ 暂停 | 宏观制度切换识别 |
| **事件驱动** | event_driven | ⏸ 暂停 | 预排事件日历(缺实时源) |
| **ML信号** | ml_signal | ⏸ 暂停 | ONNX模型推理(模型库空) |
| **多因子** | multi_factor | ⏸ 暂停 | 四维因子加权(因子源缺口) |

CLI `--strategies` 显式指定可覆盖禁用集，启用暂停策略。

## 8. 9 Agent 辩论制衡

```
                     明鉴秋(主管)
                     ／     |     ＼
                闫判官(初判)  |   闫判官(终裁)
                /    |    \  |   /    |    \
            链证源  观澜  探源 证真  慎思  风控明
            (事实) (技术) (基本面) (多头) (空头) (审核)
```

- **数技源**: 数据层，产出客观信号，不参与辩论
- **链证源**: 事实层，提供产业链景气度事实，不下多空结论
- **观澜/探源**: 研究员层，提供技术+基本面分析素材(中立，verdict=null)
- **证真/慎思**: 对抗层，从相同素材提取不同方向的论据，交叉质询
- **闫判官**: 裁决层，初判定方向+终裁判胜负+输出交易参数
- **风控明**: 审核层，独立审查闫判官交易参数的风险合理性
- **明鉴秋**: 协调层，选题+调度+汇总+记忆写入，不代写辩论内容

ADX角色反转规则贯穿全流程：ADX低位(<20)视为趋势启动早期鼓励确认，ADX高位(≥60)为过热警示不得作为致命伤。ADX提及占比≤1/3。
