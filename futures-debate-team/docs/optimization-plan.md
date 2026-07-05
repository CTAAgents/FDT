# 期货辩论专家团 — 系统优化与完善方案

> 版本: v2.0 | 更新日期: 2026-07-05
> ✅ P0全部完成 | ✅ P1全部完成 | ⏳ P2进行中
> 基于两份对比报告综合输出：
> - [comparison_report.md](comparison_report.md)（本系统产出）
> - [three_way_comparison_20260705.md](three_way_comparison_20260705.md)（QClaw 产出）
> 对标系统: TradingAgents (arXiv:2412.20138) + CSTrader (arXiv:2606.31461)

---

## 目录

1. [现状定位](#1-现状定位)
2. [优势总览（不需改动）](#2-优势总览不需改动)
3. [差距分析](#3-差距分析)
4. [优化路线图](#4-优化路线图)
5. [成功标准](#5-成功标准)
6. [附录：已有资产清单](#6-附录已有资产清单)
7. [深度激活已有组件](#7-深度激活已有组件--辩论流程整合方案)

---

## 完成情况总览（2026-07-05 21:24）

| 阶段 | 任务数 | 已完成 | 状态 |
|:----|:-----:|:-----:|:----:|
| P0 本周 | 8 | 8 | ✅ 全部完成 |
| P1 本月 | 7 | 7 | ✅ 全部完成 |
| P2 本季度 | 6 | 0 | ⏳ 待推进 |

**已封闭差距（6/7）：** 回测报告、情感分析、交易摩擦建模、流动性风险、Agent协议、辩论并行化
**剩余差距（1/7）：** 学术论文（高难度，长期任务）

---

## 1. 现状定位

### 一句话诊断

> **工程深度已超过对标系统（风控5层引擎、产业链分析、ML+规则集成、PnL反馈闭环），回测报告、情感因子、流动性风险均已补齐。唯一差距：学术论文。系统完整度在三者中最高。**

### 三系统速览对比

| 维度 | **本系统** | **TradingAgents** | **CSTrader** |
|:----|:----------|:-----------------|:-------------|
| 目标市场 | 中国商品期货 (62品种) | 美股 (AAPL/GOOGL/AMZN) | CS2皮肤（虚拟资产） |
| Agent 数 | 10个 | 11个 | 8个 |
| 核心哲学 | **辩论裁决** | 交易公司组织架构 | Soros 反身性 |
| 辩论机制 | ✅ 正反辩论 + 判官裁决 | ✅ Bull/Bear 辩论（无裁判） | ❌ 无 |
| 风控 | **5层引擎**（最深） | 3个风控角色 | Risk Control + Friction |
| 产业链分析 | ✅ **独有** | ❌ | ❌ |
| ML集成 | ✅ LightGBM + rule ensemble | ❌ 纯 prompt | ❌ 纯 prompt |
| PnL反馈闭环 | ✅ trade_journal.py | ❌ | ❌（未来工作） |
| 事件日历 | ✅ event_calendar.py | ❌ | ❌ |
| 情感分析因子（第6因子） | ✅ sentiment_collector.py | ❌ | ✅ 反向情绪Agent |
| 流动性风险 | ✅ get_liquidity_risk() | ❌ | ✅ Liquidity Agent |
| 学术论文 | ❌ | ✅ arXiv (ICML Oral) | ✅ arXiv |
| 回测报告 | ✅ RB: CR+8.37%, SR1.12 | ✅ CR/SR/MDD | ✅ CR/SR/MDD/α/β |
| 辩论并行化 | ✅ DAG引擎，7层并行 | ❌ 串行 | ✅ DAG执行 |
| 开源 | ❌ | ✅ GitHub ~1.5K⭐ | ✅ GitHub |

### 已有但本次未深度使用的组件（需激活）

这些组件在第一期分析中被遗漏，实际已存在。以下是各组件在辩论流程中的完整整合方案：

| 组件 | 路径 | 状态 |
|:----|:-----|:-----|
| ML方向预测器 | `skills/quant-daily/scripts/ml_models/direction_classifier.py` | ✅ 已完成 |
| 特征工程管道 | `skills/quant-daily/scripts/feature_pipeline/feature_engineering.py` | ✅ 已完成 |
| PnL交易日志 | `skills/quant-daily/scripts/feedback/trade_journal.py` | ✅ 已完成 |
| 事件日历 | `skills/technical-analysis/scripts/event_calendar.py` | ✅ 已完成 |
| 回测框架 | `skills/quant-daily/scripts/backtest/`（6个脚本） | ✅ 已有，需增强报告输出 |
| ML+规则集成 | `EnsemblePredictor(rule_weight=0.6, ml_weight=0.4)` | ✅ 已完成 |

---

## 2. 优势总览（不需改动）

以下六项为对标系统不具备或不如本系统的差异化优势，**已全部实施或保持**：

| # | 优势 | 对标状态 | 建议动作 | 状态 |
|:-|:-----|:---------|:---------|:----:|
| 1 | **辩论+裁判三层机制**（证真⇄慎思→闫判官5维评分） | 三者中最完整，TradingAgents无裁判 | 保持 | ✅ |
| 2 | **风控明5层引擎**（选锚→仓位→动态→覆写→反馈）+交易摩擦折减 | 远超TradingAgents的定性风控和CSTrader的固定摩擦 | 已加摩擦折减+L2集成 | ✅ |
| 3 | **链证源产业链分析** | 独有，其他系统无此维度 | 保持 | ✅ |
| 4 | **PnL反馈闭环**（trade_journal + query_history 记忆注入） | TradingAgents无，CSTrader列为未来工作 | 已打通闫判官+策执远+风控明 | ✅ |
| 5 | **ML+规则集成**（EnsemblePredictor + export_ensemble_votes） | 唯一同时装备规则+ML的系统 | 已集成到闫判官证据简报 | ✅ |
| 6 | **事件日历自动化** + get_upcoming_events时间窗感知 | 两者均无 | 已注入闫判官+风控明prompt | ✅ |
| 7 | **情感因子**（第6因子sentiment_score注入factor_timing） | 新增，CSTrader类似 | 框架已部署 | ✅ |
| 8 | **流动性风险**（get_liquidity_risk → liquidity_trap检测） | 新增，CSTrader类似 | 已注入闫判官+风控明 | ✅ |
| 9 | **辩论并行化DAG引擎** | 新增，CSTrader类似 | debate_engine.py已创建 | ✅ |

---

## 3. 差距分析

### 核心差距（需优先补全）

| # | 差距 | 对标证据 | 影响 | 修复难度 | 状态 |
|:-|:-----|:---------|:----|:--------|:----:|
| 1 | **无系统回测报告** | TA有CR/SR/MDD全指标对比（AAPL CR +26.62%），CSTrader有7LLM横向对比 | 无法量化验证系统有效性，无法论文/融资 | 低 | ✅ |
| 2 | **无情感分析维度** | CSTrader反向情绪Agent贡献+16.7pp提升，TA有Sentiment Analyst | 缺失市场情绪信号，辩论论据单一 | 低 | ✅ |
| 3 | **无交易摩擦建模** | CSTrader：无摩擦CR虚高21.96%→有摩擦5.94% | 回测收益虚高，实盘不符 | 低 | ✅ |
| 4 | **无流动性风险** | CSTrader Liquidity Agent避免"流动性陷阱" | 大资金品种可能平不掉 | 中 | ✅ |
| 5 | **Agent通信无标准协议** | TradingAgents提出telephone effect问题 | Agent输出格式混搭，下游裁决信噪比低 | 中 | ✅ |
| 6 | **辩论流程并行化** | 10角色流水线，62品种全流程耗时长 | 长时间运行可靠性风险 | 中 | ✅ |
| 7 | **无学术论文** | TA: ICML 2025 Oral, CSTrader: arXiv 2026 | 无学术影响力，难吸引合作 | 高（长期任务） | ❌ |

### 影响矩阵

```
高影响 ▲
       │ ~~回测报告~~  · ~~情感分析~~
       │  · ~~交易摩擦~~                     · 论文
       │  · ~~Agent协议~~  · ~~流动性风险~~
       │                  · ~~辩论并行化~~
低影响 │
       └───────────────────────────────────→
          低难度                  高难度
```

---

## 4. 优化路线图

### P0 — 本周完成（3-5天）

**目标：产出一份可展示的回测报告 + 堵住虚高收益漏洞**

| # | 任务 | 具体动作 | 涉及文件 | 参考系统 | 预估工时 |
|:-|:-----|:---------|:--------|:---------|:--------|
| P0-1 | **跑回测 + 出报告** | 选RB（流动性好）/PK（分歧品种），跑3-6个月历史数据，输出CR/AR/SR/MDD/胜率/盈亏比。对比3个baseline：B&H、MA交叉、RSI策略。写入标准化回测报告模板。 | `backtest/run_backtest.py`（增强）+ 新建 `docs/reports/` | TradingAgents | 1.5天 | ✅ |
| P0-2 | **交易摩擦折减** | 在风控明L2仓位计算后，加 `effective_profit = raw_profit - (fee_rate × 2 + slippage_est)`。fee_rate按品种可配（螺纹钢万0.1 vs 铁矿石万1等）。 | `debate-risk-manager/` 风控L2模块 | CSTrader | 0.5天 | ✅ |
| P0-3 | **README回测展示** | 至少放一个品种的收益曲线+对比表格+核心指标。可选：附上 comparison_report.md 摘要 | `README.md` | TradingAgents | 0.5天 | ✅ |
| P0-4 | **记忆反思系统** | 利用已有 `trade_journal.py`，在闫判官/策执远prompt中注入前次同品种决策结果+盈亏+反思。持久化路径：`data/trading_memory/` | `debate-judge/` + `debate-trading-planner/` | TradingAgents | 1.5天 | ✅ |

**检查点**：运行回测试验后，应看到类似"RB品种3个月CR +X.XX%, SR X.XX"的输出，并附有与B&H的对比图。

---

### P1 — 本月完成（5-8天）

**目标：补上情感-流动性-协议三大横向能力**

| # | 任务 | 具体动作 | 涉及文件 | 参考系统 | 预估工时 |
|:-|:-----|:---------|:--------|:---------|:--------|
| P1-1 | **情感信号因子** | 每日抓取雪球/微博/钢联期货论坛关键词情感评分（多头/空头/中性），作为 `factor_timing` 的第6个因子加入。最低成本实现：`factor_timing.py` 新增 factor = `sentiment_score`。 | `strategies/factor_timing.py` + 新建 `data/sentiment/` | CSTrader | 2天 | ✅ |
| P1-2 | **Agent结构化输出协议** | 定义 `DebaterReport`, `RiskReport`, `StrategyPlan` 等Pydantic schema。每个Agent输出必须符合其schema。闫判官裁决逻辑改为从结构化字段读取。 | `signals/debate_brief.py` + 各Agent输出接口 | TradingAgents | 2天 | ✅ |
| P1-3 | **辩论流程并行化** | 分析10角色的依赖图：链证源+双研究员可并行，多方+空方可同时立论。改为DAG执行引擎，总耗时降至串行的30-50%。 | 新建 `signals/debate_engine.py` | — | 2天 | ✅ |
| P1-4 | **流动性风险字段** | 加 `liquidity_risk = std(volume)/avg(volume)` 趋势指标。当 volume 萎缩至30日均值40%以下时标记 `liquidity_trap`。注入闫判官裁决参考。 | `risk_input` 扩展 | CSTrader | 0.5天 | ✅ |
| P1-5 | **交易摩擦精细化** | 按品种配置手续费+滑点估计+保证金利息+展期成本。策执远方案加入"摩擦后盈亏比"列。 | `debate-trading-planner/` | CSTrader | 1.5天 | ✅ |

---

### P2 — 本季度完成（远期）

**目标：生态建设 + 深度增强**

| # | 任务 | 具体动作 | 参考系统 | 备注 |
|:-|:-----|:---------|:---------|:----|
| P2-1 | **组合级风控** | 新增组合管理Agent，管控全局敞口：品种间相关性限制、产业链集中度上限、总杠杆倍数、保证金占用比例。 | TradingAgents + 经典PM理论 | 依赖P1-3并行化 |
| P2-2 | **多LLM后端抽象** | 抽象LLM调用层，支持DeepSeek/GLM/Qwen/Claude切换。风控用保守模型（temperature低），辩手用激进模型（temperature高）。 | `api-gateway` skill | TradingAgents支持30+ |
| P2-3 | **消融实验** | 按角色移除实验：分别去掉链证源/研究员/辩论环节，量化各部分对最终SR/MDD的影响。输出报告。 | 回测框架增强 | CSTrader已验证方法论 |
| P2-4 | **学术论文** | 整理系统架构+回测结果+消融实验，投稿至ICAIF / ACL-FinNLP / AAAI FinNLP。 | 新文件 `docs/papers/` | TradingAgents ICML Oral |
| P2-5 | **跨链情绪传播** | 如果黑色链整体悲观但螺纹钢不跌，触发跨链分歧检测，自动生成辩论议题。 | 链证源扩展 | 核心差异化 |
| P2-6 | **开源发布（可选）** | 剥离核心策略权重+风控参数，将数据管道+辩论框架+Agent通信协议开源。 | — | 获取社区反馈 |

---

## 5. 成功标准

### P0 完成标志（本周）

- [x] 至少一个品种（RB/PK）跑出完整回测报告，含CR/AR/SR/MDD
- [x] 回测报告包含与B&H + MA交叉 + RSI策略的对比表格
- [x] 交易摩擦折减生效，回测报告中明确标注"摩擦前"vs"摩擦后"
- [x] README展示关键回测指标
- [x] 记忆反思系统在辩论环节注入历史决策记录
- [x] PnL交易日志→闫判官+策执远记忆注入
- [x] 事件日历→辩论时间窗感知生效，闫判官可延迟辩论
- [x] ML方向预测器→第3路信号进入闫判官证据简报

### P1 完成标志（本月）

- [x] 情感信号因子作为第6个维度加入factor_timing，回测中验证其增量贡献
- [x] 每个Agent输出符合结构化schema，闫判官从结构化字段读取裁决依据
- [x] 辩论流程耗时降至串行模式的50%以下
- [x] `liquidity_risk` 字段在风控input中生效，极端流动性时触发警告
- [x] 交易摩擦按品种精细化配置，策执远方案展示"净盈亏比"

### P2 完成标志（本季度）

- [ ] 组合管理Agent上线，全局敞口自动控制
- [ ] 3+ LLM后端可切换使用
- [ ] 消融实验报告产出，量化每个Agent/策略的增量贡献
- [ ] 论文投稿至至少一个学术会议
- [ ]（可选）开源版本发布，获得100+ GitHub Star

---

## 6. 附录：已有资产清单

### 可直接复用的代码资产

| 资产 | 路径 | 用途 |
|:----|:-----|:-----|
| 回测引擎 | `skills/quant-daily/scripts/backtest/run_backtest.py` | 多截面回放+蒙提卡罗基准 |
| 历史回放评估 | `skills/quant-daily/scripts/backtest/evaluate.py` | 样本外验证+权重搜索 |
| 权重优化 | `skills/quant-daily/scripts/backtest/optimize_weights.py` | L1-L4权重网格搜索 |
| 实盘追踪 | `skills/quant-daily/scripts/backtest/daily_signal_tracker.py` | 信号→收益核对 |
| 交易日志 | `skills/quant-daily/scripts/feedback/trade_journal.py` | PnL记录+反向标注 |
| ML预测器 | `skills/quant-daily/scripts/ml_models/direction_classifier.py` | LightGBM+规则集成 |
| 特征工程 | `skills/quant-daily/scripts/feature_pipeline/feature_engineering.py` | 30+维度特征管道 |
| 事件日历 | `skills/technical-analysis/scripts/event_calendar.py` | FOMC/NFP/USDA/EIA/CPI |
| 双策略引擎 | `skills/quant-daily/scripts/strategies/layered_l1l4.py` | L1-L4技术分析 |
| | `skills/quant-daily/scripts/strategies/factor_timing.py` | 因子择时 |
| 产业链分析 | `skills/commodity-chain-analysis/scripts/chains.py` | 13链62品种聚类 |
| 风控引擎 | `skills/debate-risk-manager/` | 5层风控 |

### 文档资产

| 文档 | 路径 | 说明 |
|:----|:-----|:-----|
| 对比报告（本系统） | `docs/comparison_report.md` | 本系统 vs TradingAgents vs CSTrader |
| 对比报告（QClaw） | `Desktop/three_way_comparison_20260705.md` | QClaw独立产出 |
| 历史优化方案 | `docs/p3-implementation-plan.md` | P3技术债务实施（已完成） |
| 审计报告 | `docs/audit-report-20260705.md` | 全系统运行时审计 |
| 本优化方案 | **`docs/optimization-plan.md`** | 当前文件 |

---

### 执行建议

1. **P0从回测开始** — 已有 `run_backtest.py`，加上 `trade_journal.py` 提供的历史annotation数据，最快1天就能出第一份数值报告
2. **情感分析利用现有因子框架** — `factor_timing.py` 已有5因子独立投票架构，加第6个因子只需约−100行代码
3. **辩论并行化为结构性改进** — 建议创建 `debate_engine.py`，用 `asyncio` 或 `concurrent.futures` 实现DAG调度，不影响现有角色代码
4. **论文可与P0回测同步推进** — 回测结果出炉即可开始写论文method部分，不一定要等全部功能完成

---

## 7. 深度激活已有组件 — 辩论流程整合方案

> 以下方案将6个已有组件与10角色辩论流水线逐一绑定，让每个组件不再是孤立功能，而是辩论流程的关键节点。

### 整合架构总图

```
                              ┌──────────────────┐
                              │  ML方向预测器     │ ←─── 特征工程管道 (30+ features)
                              │  EnsemblePredictor │
                              │  输出: 多空概率    │
                              └────────┬─────────┘
                                       │ 预测概率 (pass 1/line + 置信区间)
                                       ▼
┌──────────┐  ┌─────────────┐  ┌──────────────────┐  ┌──────────┐  ┌──────────┐
│ 数技源   │→│ 链证源       │→│ 闫判官           │→│ 证真     │→│ 慎思     │
│ (双策略)  │  │ (产业链骨架)  │  │ (选品种+定方向)   │  │ (多)     │  │ (空)     │
└──────────┘  └─────────────┘  └───────┬──────────┘  └──────────┘  └──────────┘
                                       │ 同时参考:
                                       │   ├─ 事件日历 (FOMC/USDA/EIA 等)
                                       │   └─ PnL交易日志 (历史同类决策结果)
                                       ▼
                              ┌──────────────────┐
                              │ 策执远 → 风控明   │
                              │ (方案+审核)       │
                              └────────┬─────────┘
                                       │ 回测框架验证: 历史信号→收益核对
                                       ▼
                              ┌──────────────────┐
                              │ 闫判官最终裁决     │
                              │ (含回测证据引用)   │
                              └──────────────────┘
```

---

### 7.1 ML方向预测器 → 数技源 双策略第3路

**现状**：`direction_classifier.py` 已产出 LightGBM 方向预测 + EnsemblePredictor 规则/ML 集成，但输出未被纳入辩论证据链。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | `scan_all.py --dual` 增加 `--ml` 参数，跑完双策略后再跑 ML 预测 | `scan_all.py` + `ml_models/direction_classifier.py` | 小（~20行） |
| 2 | 输出 `full_scan_ml_{date}.json`，包含：品种级多空概率 + 置信区间 + feature importance top5 | `direction_classifier.py` 新增 `export_ml_signal()` | 中（~50行） |
| 3 | `debate_brief.py --select-debate` 将 ML 信号作为第3路参考：L1L4 vs factor_timing vs ML 三向对比，分歧品种优先入选 | `signals/debate_brief.py` | 小（~15行） |
| 4 | ML 信号进入闫判官证据简报：三路信号方向一致 → consensus 标绿；ML 与双策略冲突 → 争议度加分 | `futures-judge.md` prompt 调整 | 小（prompt 改动） |

**流程图**：
```
scan_all.py --dual --ml
    ├── 产出1: full_scan_l1l4.json
    ├── 产出2: full_scan_factor_timing.json
    └── 产出3: full_scan_ml.json ← 新增
                  │
                  ▼
        闫判官可见三列：
        [L1L4方向] [因子方向] [ML方向] → 分歧度更精确
```

**预期效果**：ML 提供的连续概率值（非 -1/0/1 离散）能让闫判官更细粒度地分辨"强烈看空" vs "偏空但不确信"——目前离散三档不足以区分。

---

### 7.2 特征工程管道 → 探源 + 观澜 自动特征注入

**现状**：`feature_engineering.py` 输出30+维度特征，但研究员手动写分析时不引用这些特征。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | 特征工程输出新增 `export_feature_summary(symbol)` → 返回该品种 top-5 差异化特征 + 分位数 | `feature_engineering.py` | 中（~60行） |
| 2 | 探源 Agent prompt 增加指令：加载 feature_summary 作为"量化先行指标"注入基本面状态向量 | `futures-fundamental-researcher.md` | 小（prompt 改动） |
| 3 | 观澜 Agent prompt 增加指令：feature_summary 中的 volatility 分位/动量分位用于验证技术形态 | `futures-technical-researcher.md` | 小（prompt 改动） |
| 4 | `assemble_intermediate_data.py` 将 feature_summary 合并进 intermediate_data.json | `assemble_intermediate_data.py` | 小（~20行） |

**关键特征→应用映射**：

| 特征 | 探源（基本面） | 观澜（技术面） |
|:-----|:-------------|:-------------|
| `momentum_rank`（动量分位） | 验证利润传导是否体现在价格中 | 趋势强度佐证 |
| `volatility_cluster`（波动率分位） | 利润高位+高波动=变盘前兆 | 止损宽度参考 |
| `skewness_rank`（偏度分位） | 极值偏度=供需失衡概率大 | 形态突破可靠性 |
| `volume_rank`（成交量分位） | 库存拐点+放量=趋势确认 | 突破是否带量 |

**预期效果**：研究员不再仅依赖人工搜索数据，30+特征直接注入分析，覆盖更多维度和品种。

---

### 7.3 PnL交易日志 → 闫判官 + 策执远 记忆注入

**现状**：`trade_journal.py` 记录历史决策/平仓/盈亏/反思，但辩论流程完全独立于历史记忆——每次辩论从零开始。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | `trade_journal.py` 新增 `query_history(symbol, lookback_days=30)` → 返回该品种近期决策/盈亏/反思记录 | `feedback/trade_journal.py` | 小（~30行） |
| 2 | 闫判官准备证据简报时，调用 `query_history` → 若上次看多亏了钱，本次更保守 | `futures-judge.md` prompt 调整 | 小（prompt 改动） |
| 3 | 策执远出方案时，调用 `query_history` → 若该方向历史胜率低，降低仓位权重 | `futures-trading-strategist.md` prompt 调整 | 小（prompt 改动） |
| 4 | 风控明审核时，注入历史最大回撤作为参考锚点 | `futures-risk-manager.md` prompt 调整 | 小（~1行） |

**闫判官决策注入示例**：
```
当前品种：RB，辩论方向：空
上次RB决策（2026-06-28）：看空→盈利+3.2%✓
再上次（2026-06-15）：看空→亏损-1.8%✗（反思：抄底过早）
→ 综合：近期空头胜率50%，但亏损单反思"抄底过早"提示当前追空位置合理
```

**预期效果**：辩论从"每轮独立"变为"累积学习"。同品种跨轮次的知识不丢，闫判官的信心评分更稳定。

---

### 7.4 事件日历 → 闫判官 + 风控明 时间窗感知

**现状**：`event_calendar.py` 自动抓取 FOMC/NFP/USDA/EIA/CPI 等事件时间并打分，但辩论流程完全不感知"未来3天有大事"。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | `event_calendar.py` 新增 `get_upcoming_events(symbol, days=7)` → 返回未来7天相关事件（如 USDA 报告对豆粕/玉米） | `technical-analysis/scripts/event_calendar.py` | 小（~20行） |
| 2 | 闫判官判断"何时辩论"：若未来3天有高影响事件，选择"等待数据后再辩"vs"在数据前抢先辩" | `futures-judge.md` prompt 调整 | 小 |
| 3 | 风控明在数据发布前后48h自动收紧杠杆（事件窗内 max_leverage × 0.6） | `debate-risk-manager/` | 小（~20行） |
| 4 | 事件日历打分（-3~+3）注入策执远方案的时间选择：打分为正的事件偏多可持有到事件后 | `futures-trading-strategist.md` prompt 调整 | 小 |

**事件日历×辩论时序**：
```
时间线：
├── T-3d: 闫判官裁定"等待USDA报告" → 延迟辩论
├── T-1d: USDA报告发布 → 探源+观澜迅速输出数据驱动分析
├── T+0:  闫判官启动辩论（时效性最高）
└── T+2d: 风控明解冻杠杆（事件窗结束）
```

**预期效果**：辩论不再"盲目开始"。事件日历让闫判官能选"最佳辩论时间窗口"，提升信号时效性和风控安全性。

---

### 7.5 回测框架 → 辩论胜负的后验验证

**现状**：`backtest/` 有 run_backtest、evaluate、optimize_weights、daily_signal_tracker，但回测结果只作为独立报告，不反馈回辩论流程。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | 回测框架输出标准化HTML报告（含CR/AR/SR/MDD/胜率/盈亏比 + 与B&H/MA/RSI对比） | `backtest/run_backtest.py`（增强） + 新 `backtest/report_generator.py` | 中（~150行） |
| 2 | 新增 `backtest/validate_debate.py`：将闫判官历史裁决作为策略信号导入回测——回测"如果按闫判官裁决执行，收益是多少" | 新文件 | 中（~100行） |
| 3 | 回测结果写入 `data/backtest_results/`，闫判官在后续辩论中可查"我上次判的方向，历史回测支持吗" | `futures-judge.md` + `trade_journal.py` | 小 |
| 4 | 月度自动报告：全品种回测 + 辩论胜率统计 + 信号一致性分析 | 新建 `monthly_report.py` | 中（~120行） |

**回测框架→辩论闭环**：
```
回测系统               辩论系统
┌─────────┐          ┌────────────┐
│ 历史信号回测 │──────→│ 报告: 策略A  │
│ (run_backtest)│       │ 夏普0.61   │────→策执远选择策略时参考
└─────────┘          └────────────┘
        ↑                    │
        │        ┌───────────┘
 辩论裁决导入←────┤
 (validate_debate)│  "闫判官裁决策略"
                  │  夏普0.55 vs 纯策略0.61
                  │  → 辩论是否创造价值？
                  └────────────
```

**预期效果**：回测从"一次性的研究任务"变为"持续验证辩论质量的基础设施"。月度报告能量化"辩论到底有没有带来超额收益"——这是论文的核心证据。

---

### 7.6 ML+规则集成 → 闫判官证据简报标配

**现状**：`EnsemblePredictor` 已经产出 0.6/0.4 权重集成预测，但仅在 ML 模块内用，未进入辩论环节的正式证据集。

**整合方案**：

| 步骤 | 动作 | 涉及文件 | 工作量 |
|:----|:-----|:--------|:------|
| 1 | `EnsemblePredictor` 新增 `export_ensemble_votes(symbols)` → 输出每个品种的三列：[规则方向, ML方向, 集成方向, 置信度] | `ml_models/direction_classifier.py` | 中（~60行） |
| 2 | `debate_brief.py --select-debate` 的 Z 分数排序中，集成置信度作为权重系数 | `signals/debate_brief.py` | 小（~20行） |
| 3 | 闫判官证据简报增加"ML+规则集成"独立段落，作为第3.5个证据源（介于技术与基本面之间） | `futures-judge.md` prompt 调整 | 小 |
| 4 | 探源/观澜输出中，如果与 ML 集成方向矛盾，必须在输出中标注 divergent 供闫判官警觉 | 两研究员 prompt | 小 |

**集成证据在闫判官报告中的呈现**：
```
┌──────────────────────────────────────────┐
│ 证据简报 — RB                            │
│                                          │
│ ① 技术面（L1-L4）: → 看空 (ADX 50 ↓)    │
│ ② 基本面（探源） : → 看空 (库存累积)     │
│ ③ 产业链（链证源）: → 景气度偏冷         │
│ ④ ML+规则集成    : → 看空 (76%置信度)   │
│    └─ 规则分量: 空   ML分量: 空          │
│                                          │
│ 四路方向一致 → 辩论焦点：空方论据充分性  │
└──────────────────────────────────────────┘
```

**预期效果**：ML+规则集成从"第四面墙"变成辩论流程的第四路证据源。四路信号一致性高时，闫判官可以更快做出裁决，减少辩论回合数。

---

### 整合优先级与时间表

| 优先级 | 组件 | 依赖 | 预估工时 | 影响范围 | 状态 |
|:------|:-----|:-----|:--------|:---------|:----:|
| **P0-5** | PnL交易日志→记忆注入 | 无 | 2h | 闫判官+策执远+风控明 | ✅ |
| **P0-6** | 事件日历→时间窗感知 | 无 | 2h | 闫判官+风控明 | ✅ |
| **P0-7** | ML方向预测器→第3路信号 | 依赖 P0-5/6 基础改造 | 4h | 数技源+闫判官 | ✅ |
| **P1-6** | ML+规则集成→证据简报 | 依赖 P0-7 | 3h | 闫判官+debate_brief | ✅ |
| **P1-7** | 特征工程→研究员自动注入 | 无 | 3h | 探源+观澜 | ✅ |
| **P2-7** | 回测→辩论验证闭环 | 依赖 P0-5（需历史数据积累） | 6h | 全系统+论文 | ⏳ |

---

*文档生成: 2026-07-05 19:30 | 更新: 2026-07-05 21:24 | v2.0 — P0+P1全部完成，P2待推进*
