# Futures Debate Team — 期货交易辩论专家团 v5.0

> 🧬 **v5.0 里程碑**: 自进化闭环系统 — 全9Agent自进化 + 裁决修正经验库 + 闭环追踪验证 + 评分5维自校准

## 类型

Team 型（10角色多角色协作团队，全Agent自进化）

## 架构

```
P0   🆕 进化链(2026-07-06)          validate→calibrate→evolve 自动运行
     │                             产出: calibration.json + agent_profiles.json
     │                             反馈: 9个Agent读取各自进化参数
     ▼
P1  数据采集与双通道分离           数技源(quant-daily)
     │                           scan_all.py --dual → debate_brief.py
     │                           产出: full_scan_summary.json + candidates.json
     │                              ├─ trading_recommendations[] 共识+launch+非极端(免辩论)
     │                              ├─ watch_list[]              观察级品种
     │                              └─ debate_candidates[]       分歧/极端/链补(需辩论)
     ▼
P1.5 产业链分析                  链证源(commodity-chain)
     │                           产出: 产业链快照 + redundant_pairs(同链相关性)
     ▼
P2  闫判官双通道分流             闫判官(judge)
     │                           输入: 信号 + candidates + 链数据 + calibration.json
     ├── 通道A: 直接推荐
     │   ├── 闫判官: 复核方向 → 基于price/ATR/ADX设定入场/止损/目标
     │   └── 策执远: 合约选型 + 仓位计算 + 建仓节奏
     │
     └── 通道B: 辩论
         ├── 研究员供弹(观澜技术面 + 探源基本面)
         ├── 证真(多方) vs 慎思(空方) 多轮辩论
         └── 闫判官: 六维评分(含5维自校准)→判决→胜方提案
     │
     ▼
P3  方案合成与风控审核          策执远(strategist) → 风控明(risk)
     │                           双通道统一过: 合约→仓位→风控→净盈亏比
     │                           red退回修改 / green通过
     ▼
P4  合并双通道 → 归档           明鉴秋(team-lead)
                                 TeamDecisionOutput → debate_results.json → HTML报告
```

### 角色与阶段对照

| 角色 | Agent | P1 | P1.5 | P2 | P3 | P4 |
|:-----|:------|:--:|:----:|:--:|:--:|:--:|
| **数技源** | datatech | ● 信号 | | | | |
| **链证源** | chain-analyst | | ● 产业链 | | | |
| **闫判官** | judge | | | ● 双通道分流 | ● 判决 | |
| **探源** | fundamental | | | | ● 供弹 | |
| **观澜** | technical | | | | ● 供弹 | |
| **证真(多方)** | affirmative | | | | ● 辩论 | |
| **慎思(空方)** | opposition | | | | ● 辩论 | |
| **策执远** | strategist | | | ● 通道A仓位 | ● 方案合成 | |
| **风控明** | risk | | | | | ● 审核 |
| **明鉴秋** | team-lead | ● 启动 | | | | ● 合并归档 |

## 核心设计原则（v5.0 - 自进化闭环版）

```
数技源边界     → 只输出原始数值，不做判断
双通道分离     → 共识+launch+非极端=直接推荐(免辩论), 其余=辩论
闫判官决策     → 自行决定辩论品种与方向 + 为直接推荐设定交易参数
研究员中立     → 只供证据不下多空结论
链证源中立     → 先于闫判官做产业链分析，不下多空
双策略并行     → L1-L4 + factor_timing 各输出一份
无胶水代码     → 所有操作通过已有skill完成
自动写记忆     → 每个Agent运行后自动写memory/
分歧品种门槛   → 分歧入池需至少一边信号>=MODERATE(避免为辩论而辩论)
极端分歧标记   → 极端位置+分歧=左侧反转机会(正方=逆转方向)
直接参数设定   → 闫判官基于price/ATR/ADX手动给入场/止损/目标(策执远校验)
风控6层引擎    → 选锚→仓位→动态调整→场景覆写→反馈闭环
双通道合并     → 辩论+直接推荐统一经策执远→风控→明鉴秋合并输出
观澜v2.1       → ZigZag+VP支撑阻力/硬软分类/ATR容差/失效条件/多周期共振
P3全量实现     → ML方向预测+事件日历+跨品种联动+PnL反馈闭环
P0_P1增强      → 情感因子+流动性风险+摩擦精细化+DAG并行化+特征注入+Agent协议
P2_P3增强      → 实盘执行引擎+运维告警+合规审计+MARL+对手盘建模+自动因子挖掘+双判官制衡
Bridgewater    → 五维辩论价值评分+研报质量过滤+ML训练自动化+历史反馈闭环
TqSdk数据源    → 盘中时段TqSdk主力连续K线降级(TDX→TqSdk→东方财富→AKShare)
```

## 系统架构（v4.5 — 新增根级基础设施层）

```
futures-debate-team/
├── debate/                    ← 辩论系统基础设施
│   ├── history.py             ← 辩论历史记录（append-only JSON档案）
├── ml/                        ← ML/AI 训练基础设施
│   ├── trainer.py             ← TrainingOrchestrator + DisputePredictor
├── pipeline/                   ← 数据预处理/管道
│   ├── quality_filter.py      ← 研报质量过滤（B-Minimal + B-Standard）
│   └── runner.py              ← 全自动流水线（scan→chain→debate→report→ML）
├── skills/                    ← 专业技能层
│   ├── quant-daily/           ← 数据采集 + 信号计算
│   ├── commodity-chain-analysis/
│   └── ...
└── tests/                     ← 统一测试目录
    └── quant-daily/
```

**关键原则**：跨层 cross-cutting 功能放在根级目录，不塞入具体 skill。

## Bridgewater 方法论 × CTA 落地（v4.5 新增）

基于 Bridgewater AIA Labs 论文方法论的 3 条路径全量实施：

| 路径 | 描述 | 产出 | 覆盖率 |
|:-----|:-----|:-----|:------|
| **Path A** | 研报质量评估 — B-Minimal五维checklist + B-Standard自动标注 | `pipeline/quality_filter.py` | 96% |
| **Path B** | 辩论历史反馈闭环 — 轻量JSON档案，记录/读取/分值计算 | `debate/history.py` | 94% |
| **Path C** | ML训练自动化 — TrainingOrchestrator + DisputePredictor | `ml/trainer.py` | 87% |

### 五维辩论价值评分（debate_brief.py 增强）

`compute_debate_score()` 为每个品种计算五维加权评分，替代简单分歧度排序：

| 维度 | 权重 | 评分依据 |
|:-----|:----:|:---------|
| 信号强度 | 40% | L1-L4总得分 + factor_timing总得分，分歧加倍 |
| 趋势质量 | 25% | ADX(趋势强度) + 阶段(launch>trending>quiet) + 共识数 |
| 极端值 | 20% | RSI极端 + Z分数极端 + 超买/超卖标签 |
| 数据可靠性 | 10% | veto扣分(每-1扣2分) |
| 产业链重要性 | 5% | 黑色系/贵金属=5分，其他=3分 |

### 自动流水线（零人工干预）

`pipeline/runner.py` 全自动串联交易日流程：

```
16:15 (收盘后) → scan_all.py --dual → chain_analysis → debate_brief(五维评分)
                → assemble_intermediate → report → history记录 → ML训练检查
```

自动化调度：
- **工作日 16:15**：全自动辩论流水线
- **周日 17:00**：ML模型自动训练检查

| 角色 | Agent ID | 工作方法定义在 | 职责 |
|:-----|:---------|:--------------|:-----|
| 明鉴秋 | `futures-debate-team-team-lead` | `futures-trading-analysis` | 选题、调度、汇总、拍板 |
| 数技源 | `futures-datatech` | `quant-daily` | 运行 --dual 产出双策略信号（纯数据） |
| 探源 | `futures-fundamental-researcher` | `commodity-chain-analysis` | 基本面分析（factor_timing数据+互联网） |
| 观澜 | `futures-technical-researcher` | `quant-daily` + `technical-analysis` | 技术分析（L1-L4数据+支撑阻力v2.1+图形） |
| 链证源 | `futures-chain-analyst` | `commodity-chain-analysis` | 产业链事实描述+景气度（先于决策，不下多空） |
| 证真 | `futures-affirmative-debater` | `debate-argument-builder` | 多方：从研究员资料中提取多头论据 |
| 慎思 | `futures-opposition-debater` | `debate-argument-builder` | 空方：从研究员资料中提取空头论据 |
| 闫判官 | `futures-judge` | `debate-judge` | 选辩论品种+定方向+主持+评分+裁决 |
| 风控明 | `futures-risk-manager` | `debate-risk-manager` | 5层风控引擎：选锚/仓位/动态调整/场景覆写/反馈 |
| 策执远 | `futures-trading-strategist` | `debate-trading-planner` | 合约选型+执行方案 |

## 数据流（v4.4 — 全量优化完成）

```
S1: 数技源 → scan_all.py --dual
     ├─ full_scan_l1l4_{date}.json         — 40+技术指标数值
     └─ full_scan_factor_timing_{date}.json — 6因子择时数值（含情感第6因子）
     └─ 每个品种含 risk_input 字段（confidence/ATR/ADX/pattern_risk/invalid_condition）

S1.5: 链证源 → 产业链分析（先于闫判官决策，不下多空结论）

S2: 闫判官综合双策略信号 + 产业链信息 → 决定辩论品种与方向
    风控明同时做辩论前预审（pre_check_symbol: 换月/交割/事件检查）

S3: 观澜(技术分析·v2.1) + 探源(基本面分析) 并行供弹
    观澜输出包含：hard/soft支撑阻力 + ATR容差 + 失效条件 + 多周期共振标签
    探测源输出包含：基本面核心数据 + 数据源可靠性评级
    链证源参与置信度修正（adjust_confidence_with_chain）
     → 证真(多方) ⇄ 慎思(空方) 辩论
     → 策执远出方案（含初始止损）
     → 风控明6层引擎审核：
         L1: select_stop_anchor() — 0.8~2.5ATR选锚+整数关口避开
         L2: calculate_position() — confidence+pattern_risk折减
         L3: evaluate_dynamic_adjustments() — 逻辑止损/ATR扩张/trailing
         L4: special_scenario_override() — 换月/交割/夜盘/宏观事件
         L5: build_feedback_entry() — 反馈回流
     → 闫判官裁决

S4: 明鉴秋汇总 → debate_results.json + HTML + memory更新
    PnL反馈闭环（trade_journal.py）→ 反向标注→技术Agent置信度校准
```

## 技术分析 v2.1（观澜核心升级）

支撑阻力识别从"LLM肉眼扫K线"升级为结构化算法：

| 能力 | 实现 | 辩论价值 |
|:-----|:-----|:---------|
| ZigZag拐点检测 | `find_swing_points()` — 换月跳空可屏蔽 | 消除伪前高前低 |
| Volume Profile | `calculate_poc()` — POC/VAH/VAL | 量价密集区支撑压力 |
| 硬/软分类 | `classify_level_hardness()` | hard=VP-POC/整数关口, soft=均线/趋势线 |
| ATR容差带 | hard=0.3×ATR, medium=0.5×ATR, soft=1.0×ATR | 防插针扫止损 |
| 失效条件 | `_fail_condition()` — 收盘破+确认+OI配合 | 辩手直接引用设止损 |
| 多周期共振 | `cross_validate_timeframes()` | 日线+1H+15min叠加入信 |
| 来源追溯 | 每个level标注 VP-POC/MA20/ZigZag | 可被Bull/Bear挑战 |
| OI/量能确认 | `_check_oi_confirmation()` — OI趋势+量比 | hardness升降调整 |
| 假突破验证 | `check_fake_breakout()` — 自动收盘确认 | 防虚假叙事 |

## 风控明6层引擎（risk_engine.py+L6组合风控）

风控明吃观澜的hard支撑+ATR+置信度输出，在5个层级上逐步落实风控：

| 层级 | 函数 | 输入 | 输出 |
|:-----|:-----|:-----|:-----|
| L1: 选锚 | `select_stop_anchor()` | supports+ATR+当前价 | 最优锚价(0.8~2.5ATR)+整数避开 |
| L2: 仓位 | `calculate_position()` | 入场价/止损/权益/confidence/pattern | 置信折减+形态折减后手数 |
| L3: 动态 | `evaluate_dynamic_adjustments()` | 盘中价格/新支撑/ATR变化 | 逻辑止损/trailing/ATR重算 |
| L4: 覆写 | `special_scenario_override()` | 换月/交割/夜盘/事件 | 强制降仓+放宽止损 |
| L5: 反馈 | `build_feedback_entry()` + `aggregate_feedback()` | 止损记录+假破率 | 同类型支撑置信度校准 |

**交易摩擦**：`calc_transaction_cost()` — 基于fee_table.py（62品种费率）计算手续费+滑点+冲击成本，回测时可配置 `--fee-rate` 参数

## 交易记忆 & 反思（v4.3新增）

`futures-trading-analysis/scripts/trading_memory.py` + `quant-daily/scripts/feedback/trade_journal.py` 记录每笔辩论决策→平仓结果→记忆注入：

- `record_decision()` — 记录辩论决策（方向/入场/理由/置信度）
- `record_outcome()` — 平仓回填PnL
- `build_reflection_prompt()` — 更新辩论环节自动注入历史反思
- `get_performance_summary()` — 整体表现摘要（胜率/总盈亏/最大盈亏）

## 标准回测报告（v4.3新增）

`quant-daily/scripts/backtest/backtest_report.py` + `backtest_v3.py` 生产级回测引擎：

| 功能 | 说明 |
|:----|:-----|
| CR/AR/SR/MDD全指标 | 累计/年化收益、夏普、最大回撤、卡玛比 |
| 3基线对比 | 买入持有 / MA金叉死叉 / RSI超买超卖 |
| 蒙提卡罗 | 2000次随机抽样，p值统计显著性检验 |
| 摩擦折减 | `--fee-rate` 参数，摩擦前/后对比 |
| HTML报告 | 自包含交互式报告（见 docs/reports/） |

### RB回测摘要（180天数据，v3引擎）

| 策略变体 | CR | SR | 胜率 | 盈亏比 | 最大回撤 | 摩擦影响 |
|:---------|:--:|:--:|:----:|:------:|:--------:|:--------|
| WEAK+SELL | +8.37% | 1.12 | 59.4% | 1.23 | 23.1% | 摩擦0.1%后~+8.3% |
| WATCH+BUY | -35.93% | — | 45.9% | — | — | 熊市做多逆势 |
| ML增强版 | +19.47% | 0.61 | 50.4% | — | — | — |

> 📁 完整报告：`docs/reports/backtest_report_RB_20260705.html`

### Agent通信协议 v3.1（Pydantic v2兼容）

10角色间结构化通信由 `contracts/` 包定义，覆盖全链路：

| 协议 | Schema | 生产者 | 消费者 |
|:-----|:-------|:-------|:-------|
| 基本面状态向量 | `FundamentalStateVector` | 探源 | 闫判官+证真+慎思 |
| 技术面快照 | `TechnicalOutput` | 观澜 | 闫判官 |
| 产业链快照 | `ChainAnalysisOutput` | 链证源 | 闫判官 |
| 辩论论点 | `ArgumentOutput` | 证真/慎思 | 闫判官 |
| 证据简报+判决 | `PrepBrief` / `FinalJudgment` | 闫判官 | 所有人 |
| 风控审核 | `RiskOutput` | 风控明 | 闫判官 |
| 交易计划 | `TradingPlanOutput` | 策执远 | 风控明 |
| 团队决策 | `TeamDecisionOutput` | 明鉴秋 | 归档 |

详见 [`docs/agent-protocol.md`](docs/agent-protocol.md)

## P3 技术债务实施（全部完成）

| Phase | 项目 | 文件 | 状态 |
|:------|:-----|:-----|:-----|
| **Phase 1** | 事件日历mask | `technical-analysis/scripts/event_calendar.py` | ✅ FOMC/NFP/USDA/EIA/CPI 全年自动生成 |
| **Phase 1** | 跨品种联动 | `technical-analysis/scripts/cross_correlation.py` | ✅ 滚动相关系数+板块关联+全品种矩阵 |
| **Phase 2** | ML特征工程 | `quant-daily/scripts/feature_pipeline/feature_engineering.py` | ✅ 30+维度（动量/OI/技术/期限/跨品种） |
| **Phase 3** | ML方向分类器 | `quant-daily/scripts/ml_models/direction_classifier.py` | ✅ LightGBM+EnsemblePredictor（规则+ML加权） |
| **Phase 4** | PnL反馈闭环 | `quant-daily/scripts/feedback/trade_journal.py` | ✅ 交易记录+反向标注+replay buffer+性能汇总 |

## 记忆系统

所有 Agent 通过 `scripts/memory_writer.py` 自动写入 `memory/` 目录：

| 文件 | 用途 | 写入者 |
|:----|:----|:------|
| **v4.6.1** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| **v4.5.5** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| **v4.5.4** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| **v4.5.3** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| **v4.5.2** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| **v4.5.1** | **2026-07-06** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |
| `debate_journal.json` | 跨轮操作日志 | 全员自动写入 |
| `data_sources.md` | 数据源可靠性 | 探源+风控明 |
| `argument_patterns.md` | 有效论证模式 | 证真+慎思+闫判官 |
| `debater_profiles.md` | 角色表现 | 闫判官 |
| `execution_followup.json` | 执行回溯 | 策执远 |
| `debates/INDEX.md` | 辩论索引 | 明鉴秋+闫判官 |
| `policies/veto_policies.md` | 否决规则库 | 风控明+明鉴秋 |
| `policies/weighting_history.md` | 评分权重记录 | 闫判官+明鉴秋 |

## 依赖的Skills

| Skill | 用途 | 版本 |
|:------|:-----|:-----|
| `quant-daily` | 数据采集 + L1-L4 + factor_timing 双策略 + P3 ML管道 + P4四路集成 | v2.5.0 |
| `futures-trading-analysis` | 主流程编排 + 报告生成 + Pydantic v2契约 | v3.3.0 |
| `commodity-chain-analysis` | 基本面 + 产业链分析 | v2.16.0 |
| `technical-analysis` | 观澜独立技术分析工具（支撑阻力v2.2+事件日历+跨品种+regime） | v2.2.0 |
| `debate-argument-builder` | 正反方论点构建（v2.3） | v2.3.0 |
| `debate-judge` | 闫判官辩论主持裁决 + 双判官制衡 | v2.1.0 |
| `debate-risk-manager` | 风控审核（6层引擎+L6组合风控） | v4.1.0 |
| `debate-trading-planner` | 交易策略规划 + 多周期辩论 | v2.2.0 |
| `debate-trading-planner` | 交易策略规划 | — |

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v5.0** | **2026-07-06** | **🧬 自进化闭环里程碑**：P0进化链(validate→calibrate→evolve 3脚本自动串联); 全9Agent自进化(闫判官5维评分/风控明ATR+仓位/策执远RR+仓位/辩手论证策略/链证源去重阈值/数技源重试/探源基本面权重/观澜ATR周期); 裁决修正经验库(R01-R05 5条硬规则); 闭环追踪(record_verdicts→validate_verdicts→execution_followup.json); 评分自校准(5维度权重自适应·学习率0.3·钳制±10); 新增4脚本+5memory文件; v9全品种辩论算法(14链覆盖·max2/c·安全边际排序) |
| **v4.5** | **2026-07-06** | **Bridgewater方法论×CTA落地全量实施**：五维辩论价值评分(compute_debate_score); 研报质量过滤B-Minimal/B-Standard; 辩论历史档案debate_history; ML训练自动化TrainingOrchestrator+DisputePredictor; 全自动流水线pipeline/runner.py; 零胶水代码强化; 测试统一迁移到tests/; 新增根级debate/ml/pipeline/基础设施模块; 全量代码审计修复22处硬编码路径与152文件ruff格式化; 100测试全绿; quality_filter 96% debate_history 94% trainer 87% 覆盖率 |
| **v4.4** | **2026-07-05** | **P0+P1全面实施**：情感因子(第6因子)+sentiment_collector; 流动性风险liquidity_trap检测; 交易摩擦精细化(利息+移仓+净盈亏比); Agent通信协议v3.0(contracts包+10角色schema); DAG并行化引擎(debate_engine.py); 记忆反思 query_history 注入; 事件日历时间窗 get_upcoming_events; 特征工程 export_feature_summary 注入研究员; ML export_ensemble_votes 第3路信号; 优化计划P0 8/8 + P1 7/7全部完成 |
| **v4.2** | **2026-07-05** | **P3全量实现**：Phase1 事件日历+跨品种联动 / Phase2 ML特征管道(30+维) / Phase3 DirectionClassifier+EnsemblePredictor / Phase4 PnL反馈闭环；风控明6层引擎(risk_engine.py)；观澜技术分析v2.1支撑阻力(hardness/容差/失效/共振)；换月跳空屏蔽+OI/量能确认；risk_input字段注入信号汇总；全审计8项修复；CONS/ADX假警报排查(indicators_legacy除零修复)；胶水代码防复发（assemble_intermediate_data / debate_brief --select-debate）；对比分析TradingAgents+CSTrader并制定P0-P2优化路线图 |
| v4.1 | 2026-07-05 | 方案C仲裁者裁决：量析师移除(10角色)；数技源改为--dual双策略输出；链证源前置(S1.5)；所有Agent自动写memory；`memory/rules/` → `memory/policies/` |
| v4.0 | 2026-07-04 | 策略可插拔架构：新增量析师，策略层驱动打分；链证源聚焦景气度(不下多空)；正反方引4层证据 |
| v3.3 | 2026-07-04 | quant-daily真分层打分集成 |
