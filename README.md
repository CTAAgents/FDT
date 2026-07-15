# Futures Debate Team — 期货交易辩论专家团 v8.1.0

> 🧬 **架构基线**：7策略并行管线(NO_FUSION) → 策略内验证器 → 多因子增强验证器 → 辩论触发 → 多空辩论 → 闫判官终裁 → 风控 → 报告。
> 辩论结论天然优先于扫描信号：多头分析员和空头分析员独立举证，闫判官在双方论据中裁决，可正面否决扫描层的方向判断（已验证：2026-07-15 fu 扫描 bull+514，辩论后判 bear）。
>
> 📈 **v8.0.4 TSMOM 时间序列动量（G31）**：`trend_following` 由 8 子信号扩展为 9 子信号共振——新增 TSMOM 时间序列动量（Moskowitz-Ooi-Pedersen 2012）。FDC 新增 `calculate_tsmom(close, windows=(21,63,126,252))` 纯函数（简单累计收益，不足窗口返回 NaN），主管线唯一计算入口单点注入 `TSMOM_1M/3M/6M/12M`（自动贯穿 scan_all + 所有回测）。`_score_tsmom` 对四窗口收益取平均符号定方向、`abs(avg)/10%` 缩放定强度（多窗口合成本身即降噪）。零新数据源（纯 OHLC 派生）。
>
> 📈 **v8.0.5 Vol Targeting 波动率目标化（G32）**：现代 CTA 趋势跟踪第二基石（与 TSMOM 并列），落点=执行/风险 overlay 层（非信号评分层，与 G34 Turtle N 单位统一）。FDC 新增 `calculate_realized_vol`（日收益 std×√252 年化）+ `calculate_vol_target_scale`（target/realized 截断 [0.2,3.0]），主管线唯一计算入口单点注入 `REALIZED_VOL`/`VOL_SCALE`（自动贯穿 scan_all + 所有回测）。`VolTargetingOverlay`（`StrategyPipeline` Phase 4.5）向每个信号注入 `extra.vol_target_scale`，`trade_plan` 据其缩放仓位——高波动降仓、低波动加仓，使组合波动贡献恒定（默认目标 10% 年化）。零新数据源（纯 OHLC 派生）。
>
> 📈 **v8.0.6 Dual Thrust 日内突破（G33）**：`trend_following` 由 9 子信号扩展为 10 子信号共振——新增 Dual Thrust 日内突破（Michael Chalek 经典算法，Tony Crabel 1990 实证）。FDC 新增 `calculate_dual_thrust(high,low,close,open_,lookback=1,k1=0.5,k2=0.5)` 纯函数（前 lookback 日 H/L/C 区间 + 当日 open±k*range 触发轨，返回 dt_range/upper/lower），主管线唯一计算入口单点注入 `DT_RANGE`/`DT_UPPER`/`DT_LOWER`（自动贯穿 scan_all + 所有回测）。`_score_dual_thrust` 比较 close 与触发轨定方向、偏离幅度相对 range 定强度。零新数据源（纯 OHLC 派生）。
>
> 🐢 **v8.0.7 Turtle 完整系统（G34）**：行业标杆（Dennis/Eckhardt 1983）收官。落点=执行/风险 overlay 层（`StrategyPipeline` Phase 4.6，接 G32 Vol Targeting 之后）。FDC 新增 `calculate_turtle_n(high,low,close,window=20)`（20 日 TR 的 Wilder 平滑，Turtle N 波动率基准），主管线唯一计算入口单点注入 `TURTLE_N`（自动贯穿 scan_all + 所有回测）。`TurtleSystemOverlay` 读 DC20/55 突破状态识别 S1/S2 系统、按 abs_score 定 1-4 单位预算、算 0.5N 金字塔加仓阶梯与 2N 退出止损，注入 `extra`；`trade_plan` 按 `turtle_units` 单位预算轻度缩放仓位（默认 1.0x，零回归）。复用 G30 DC20/55+ATR、G32 vol scale。零新数据源（纯 OHLC 派生）。
>
> 📈 **v8.0.3 趋势跟踪指标衍生扩展（G30）**：`trend_following` 由 3 子信号扩展为 8 子信号共振——DC20/DC55/BB（原）+ Keltner 通道突破 / Supertrend 趋势状态 / Parabolic SAR 转向 / Chandelier Exit 吊灯退出 / MACD 系统。FDC 新增 `calculate_keltner`/`calculate_chandelier_exit`，主管线唯一计算入口单点注入 5 字段（自动贯穿 scan_all + 所有回测），零新数据源。
>
> 🌐 **v8.0.2 宏观因子接入真实公开源（G29）**：`futures_data_core/f10/macro.py` 异步直连东方财富宏观数据中心（免费公开、零鉴权），`MultiFactorStrategy` 的 `pmi_proxy`/`rate_proxy` 由硬 0 替换为真实评分。实盘验证：PMI 50.3 / LPR1Y 3.0%（grade=DAILY）。
>
> 🚀 **v8.0.0 多因子量化策略（G24）**：`MultiFactorStrategy` 四维加权打分（量价40%/产业30%/宏观20%/另类10%），纯趋势/强弱对冲/行业中性三模式。通过 FDC 读取基差/OI/持仓排名，独立触发 ec/jm/SS 等信号。
>
> ⚙️ **v7.11.0 NO_FUSION 默认**：7策略不再融合成一个总分，各策略信号扁平输出，方向冲突时双方都保留给 debate 裁决。

## 类型

Team 型（10 角色多 Agent 协作团队，全 Agent 自进化）

## 快速开始

通过 LLM 对话直接使用，无需手动操作：

```
"全量分析商品期货"
"分析螺纹钢期货的多空博弈情况"
"对比铜期货的多空论点"
```

系统自动执行 7 阶段完整流程：7策略管线(NO_FUSION)扫描 → 链证源分析 → 闫判官初判 → 观澜技术分析 → 多空辩论（多头+空头并行） → 闫判官终裁 → 策执远+风控明 → 报告输出。

**辩论结论优先于扫描方向** — 多头和空头分析员的论据质量决定最终裁决，而非扫描总分。

## 系统架构

```
🔴 自进化前置（所有模式强制，全自动）
     │   检测未验证裁决 → validate_verdicts.py
     │   已验证≥5条 → calibrate_weights.py → evolve_agents.py
     │   检查 debate 新样本≥50 → ML TrainingOrchestrator.run_daily_check()
     │   加载最新 calibration.json + agent_profiles.json
     ▼
P0.5 7策略管线扫描（并行，NO_FUSION，no-filter 不过滤）
     ├─ trend_following    通道突破(DC20/DC55+布林带)    ◎ 28品种
     ├─ arbitrage          跨品种配对套利(Z-score)        ○ 仅配对品种
     ├─ mean_reversion     RSI/CCI 极端反转+ADX<25震荡市  ○ 极端反转时触发
     ├─ macro_regime       板块轮动(5板块46品种)          ○ 需宏观信号激活
     ├─ event_driven       事件日历(72条预排)             ○ 仅事件窗口内
     ├─ ml                 ONNX 桥接                     ◇ 无模型时降级空
     └─ multi_factor       四维因子加权                   ◎ 12品种
     策略内验证器 + 多因子增强验证器自动执行（OI/基差/低波/伪突破拦截）
     ◎=活跃  ○=条件触发  ◇=降级空
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
     │                           ▸ 辩论结论可推翻扫描方向
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
| **数技源** | datatech | ● 7策略管线 | | | | | |
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

### 1. 多空头辩论架构 — 结论优先于扫描（v7.9+）
7策略管线(NO_FUSION)输出各策略独立打分（趋势给多、回归给空、多因子量化四维综合），互不融合。多头分析员和空头分析员**独立并行**列举论据，闫判官在双方论据中裁决方向——**裁决结论可正面否决扫描层的方向判断**（已验证场景：强多信号 +514 经辩论后翻转看空）。更真实地模拟市场合力的形成过程。

### 2. 10-Agent 分工制衡
10 个专职 Agent 各司其职、相互制衡：**数技源只采信号不下结论、研究员只供事实不打分、多空分析员只列论据不裁决、闫判官只裁决不分析、策执远只出方案不改方向、风控明只审核不站队**。任何单一维度的噪声都需经结构化辩论才能进入最终决策。

### 3. 7策略并行管线 + 实际运行状态（v6.4+ → v8.0）
趋势跟踪、套利、均值回归、宏观制度、事件驱动、ML、多因子量化七策略并行计算，NO_FUSION 模式各策略独立拓扑输出，方向冲突不留情面直接送给 debate。

各策略实际运行状态（基于实盘扫描数据）：

| 策略 | 平均覆盖品种 | 状态 | 说明 |
|:-----|:----------:|:----:|:-----|
| trend_following | 28 | ◎ 活跃 | 通道突破+布林带为主驱动 |
| multi_factor | 12 | ◎ 活跃 | 量价/产业/宏观/另类四维 |
| mean_reversion | 5 | ○ 条件触发 | 极端反转信号产生 |
| arbitrage | 4 | ○ 条件触发 | 仅配对品种（TA-EG等） |
| macro_regime | — | ○ 可激活 | 需要宏观信号注入触发 |
| event_driven | — | ○ 事件窗口 | 仅 USDA/MPOB/美联储等窗口期 |
| ml_signal | — | ◇ 无模型 | 内置 ONNX 桥接，无模型时优雅降级为空 |

◎=稳定活跃  ○=条件触发（数据/事件到位时）  ◇=降级空

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
# 1) 7策略管线扫描（不过滤）
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
| `scan_daily_{date}.json` | 7策略管线扫描结果（含 strategy_breakdown 各策略贡献） |
| `scan_daily_ranking_{date}.html` | 全品种排名报告（含7策略分解列：趋势/套利/回归/宏观/事件/ML/多因子 + 策略数） |
| `spawn_plan_{date}.json` | 辩论 spawn 计划（含多空头 prompt） |
| `p4_bullish_{sym}.json` | 多头分析员论据 |
| `p4_bearish_{sym}.json` | 空头分析员论据 |
| `p5_judge_{sym}.json` | 闫判官终裁 |
| `debate_report_{date}.html` | 完整辩论报告 |
| `debate_results.json` | 机器可读决策记录 |
| `a2a_results.json` | A2A 协议信封 |
