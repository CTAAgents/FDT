# Futures Debate Team — 期货交易辩论专家团 v7.9.0

> 🚀 **v7.9.0 辩论机制重构（G19）**：6策略管线场景下，正反方机制（证真/慎思）改为多空头机制（多头分析员/空头分析员）。多头分析员独立列举做多论据，空头分析员独立列举做空论据，闫判官在双方论据中裁决方向。不再依赖"闫判官预设方向"的辩论框架。
>
> 🧬 **当前架构基线**：6策略并行管线（趋势跟踪/套利/均值回归/宏观制度/事件驱动/ML）全量扫描不过滤 → 多因子增强验证器自动执行（OI/基差/低波） → 辩论触发（STRONG/WATCH等级）→ 多空头辩论 → 终裁 → 风控 → 报告。本 README 基于权威流程文档（`docs/business_flow.md`、`docs/execution_modes_flowchart.md`），版本号唯一真相源为 `pyproject.toml`。

## 类型

Team 型（10 角色多 Agent 协作团队，全 Agent 自进化）

## 快速开始

通过 LLM 对话直接使用，无需手动操作：

```
"全量分析商品期货"
"分析螺纹钢期货的多空博弈情况"
"对比铜期货的多空论点"
```

系统自动执行 7 阶段完整流程：6策略管线扫描 → 链证源分析 → 闫判官初判 → 观澜技术分析 → 多空辩论（多头+空头并行） → 闫判官终裁 → 策执远+风控明 → 报告输出。

## 系统架构

```
🔴 自进化前置（所有模式强制，全自动）
     │   检测未验证裁决 → validate_verdicts.py
     │   已验证≥5条 → calibrate_weights.py → evolve_agents.py
     │   检查 debate 新样本≥50 → ML TrainingOrchestrator.run_daily_check()
     │   加载最新 calibration.json + agent_profiles.json
     ▼
P0.5 6策略管线扫描（并行，no-filter 不过滤）
     ├─ trend_following    通道突破(DC20/DC55+布林带)
     ├─ arbitrage          跨期/跨品种/期现套利
     ├─ mean_reversion     RSI/CCI 极端反转 + ADX<25 震荡市
     ├─ macro_regime       板块轮动(5板块46品种)
     ├─ event_driven       事件日历(72条预排)
     └─ ml                 ONNX 桥接（无模型时优雅降级）
     多因子增强验证器自动执行（OI确认/基差/低波/伪突破拦截 P0-4）
     ▼
P1  产业链分析                    链证源(commodity-chain-analysis)
     │                           产出: chain_analysis_{date}.json（景气度 + redundant_pairs）
     │                           高相关品种标记冗余（如 LU/FU 相关0.98 → FU排除）
     ▼
P2  闫判官初判 + 辩论计划          闫判官(judge_initial) + run_debate.py
     │                           spawn_plan 生成：品种/链/执行阶段(P0-P7)
     │                           多空头机制：闫判官不预设方向，多头+空头均辩论
     ▼
P3  观澜技术分析                  技术分析(support_resistance)
     │                           支撑/阻力/POC/多周期共振（不下方向结论）
     ▼
P4  多空辩论（并行）               多头分析员 + 空头分析员
     │                           各自独立列举≥3条论据，不交叉rebuttal
     ▼
P5  终裁 → 方案 → 风控（串行）     闫判官→一致性裁判→策执远→风控明
     │                           在多空论据间裁决方向，bull_score/bear_score 量化
     ▼
P6  汇总输出                      明鉴秋 / finalize
                                 4铁律核验→debate_results.json→HTML报告
```

### 角色与阶段对照

| 角色 | Agent | P0.5 | P1 | P2 | P3 | P4 | P5 |
|:-----|:------|:----:|:--:|:--:|:--:|:--:|:--:|
| **数技源** | datatech | ● 6策略管线 | | | | | |
| **观澜** | technical | | | | ● 支撑阻力 | | |
| **探源** | fundamental | | | | ● 基本面 | | |
| **链证源** | chain-analyst | | ● 产业链 | | | | |
| **闫判官** | judge | | | ● 初判+终裁 | | | ● 裁决 |
| **多头分析员** | bullish | | | | | ● 多头论据 | |
| **空头分析员** | bearish | | | | | ● 空头论据 | |
| **策执远** | strategist | | | | | | ● 交易方案 |
| **风控明** | risk | | | | | | ● 6层风控审核 |
| **明鉴秋** | team-lead | ● 启动+调度 | | ● spawn | | ● 调度 | ● 归档+报告 |

## 核心特色

期货交易辩论专家团不是「一个模型给建议」，而是一套**多 Agent 交叉质询 + 自进化闭环**的 CTA 决策系统。区别于普通量化脚本的关键能力：

### 1. 多空头辩论架构（v7.9）
6策略管线输出多策略打分（趋势跟踪可能给多、均值回归可能给空），多空机制让多头分析员和空头分析员**独立并行**列举论据，闫判官在双方论据中裁决方向——更真实地模拟市场合力的形成过程。

### 2. 10-Agent 分工制衡
10 个专职 Agent 各司其职、相互制衡：**数技源只采信号不下结论、研究员只供事实不打分、多空分析员只列论据不裁决、闫判官只裁决不分析、策执远只出方案不改方向、风控明只审核不站队**。任何单一维度的噪声都需经结构化辩论才能进入最终决策。

### 3. 6策略并行管线（v6.4+）
趋势跟踪、套利、均值回归、宏观制度、事件驱动、ML 六策略并行计算，每策略独立打分，经 StrategyPipeline 融合输出。**趋势和回归天然是信号的一体两面**（同一品种同时有多空评分），多空头辩论正是在这种矛盾中做方向决策。

### 4. 伪突破 P0-4 拦截
19 种伪突破模式校验（末根极值未破前20根/成交量不足/OI未确认等），重校验拦截后降级 NOISE，有效降低信号噪声。跳过过滤时（--disable-filter），多因子增强验证器自动执行。

### 5. 闫判官裁决 + 一致性审计
闫判官在多空论据间给出 bull_score/bear_score 量化评分，一致性裁判独立审计裁决是否源于辩论论据。策执远基于裁决制定可执行交易方案（入场/止损/目标/RR），风控明审核风控红线。

### 6. 自进化闭环（validate → calibrate → evolve → ML）
每轮辩论结束后自动触发反馈闭环：拉 T+1 K 线**验证**裁决方向 → 累计≥5 条已验证样本**校准**评分权重 → 累计≥5 样本**进化** Agent 参数 → 新样本≥50 条触发 LightGBM **增量训练**与部署。

### 7. 5 层鲁棒性防线（L1–L5）
L1 产出校验 → L2 熔断降级（重试+D06） → L3 信号门 → L4 路径自发现 → L5 健康自检。

### 8. A2A 协议文件桥
`agent-card.json` 声明 FDT 符合 Google A2A v1.0 规范；`run_debate.py finalize` 自动导出 `a2a_results.json`。

### 9. 品种知识库 + 周期发现
五层知识体系（`memory/knowledge/`），辩论后自动萃取，质量门控 confidence≥0.6 才入库。周期发现层自动选最优交易周期。

## 一键辩论驱动（run_debate.py）

> 编排收敛层：`plan → spawn → finalize` 三阶段。脚本产出标准化的 spawn 计划 JSON，不替代 Agent 调度。

```bash
# 1) 6策略管线扫描（不过滤）
python scripts/fdt_cli.py pipeline --mode no-filter --workspace <dir>/<YYYY-MM-DD> --pipeline

# 2) 产出 spawn 计划（含多空头辩论模板）
python scripts/run_debate.py plan \
  --scan <dir>/<YYYY-MM-DD>/scan_daily_<date>.json \
  --workspace <dir>/<YYYY-MM-DD> --mode trigger

# 3) spawn 执行 -> 各阶段文件就绪后 finalize
python scripts/run_debate.py finalize \
  --scan <dir>/<YYYY-MM-DD>/scan_daily_<date>.json \
  --workspace <dir>/<YYYY-MM-DD>
```

### 8 阶段 spawn 计划（闫判官驱动）

| 阶段 | Agent | 并发 | 依赖 |
|:----|:------|:----:|:----:|
| P0 judge_initial | 闫判官初判 | 1 | — |
| P1 chain | 链证源分析 | 1 | P0 |
| P2 technical | 观澜支撑阻力 | 4 | P1 |
| P3 bullish/bearish | 多空辩论 | 4 | — |
| P4 judge | 闫判官终裁 | 4 | P0, P2, P3 |
| P5 coherence | 一致性裁判 | 4 | P4 |
| P6 trading_plan | 策执远方案 | 4 | P2, P4 |
| P7 risk | 风控明审核 | 4 | P6 |

## 关键产出文件

| 文件 | 说明 |
|:-----|:-----|
| `scan_daily_{date}.json` | 6策略管线扫描结果 |
| `scan_daily_ranking_{date}.html` | 全品种排名报告 |
| `spawn_plan_{date}.json` | 辩论 spawn 计划（含多空头 prompt） |
| `p4_bullish_{sym}.json` | 多头分析员论据 |
| `p4_bearish_{sym}.json` | 空头分析员论据 |
| `p5_judge_{sym}.json` | 闫判官终裁 |
| `debate_report_{date}.html` | 完整辩论报告 |
| `debate_results.json` | 机器可读决策记录 |
| `a2a_results.json` | A2A 协议信封 |
