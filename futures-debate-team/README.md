# Futures Debate Team — 期货交易辩论专家团 v5.7.0

> 🏗 **v5.7.0 驾驭工程（Harness Engineering）成熟度 4.7/5.0**：从配置校验(G1)到结构化日志(G15)，15项差距全覆盖。Pydantic schema校验启动即拒非法配置、trace_id全链路贯穿、unified_logger JSON格式切换、43用例回归测试、graceful drain优雅停机、合约版本双向迁移(28条路径)、APM-CS实时看板+HTTP健康端点。4阶段推进，成熟度从4.0提升至4.7。

## 类型

Team 型（10角色多角色协作团队，全Agent自进化）

## 快速开始

通过 LLM 对话直接使用，无需手动操作：

```
"全量分析商品期货"
"分析螺纹钢期货的多空博弈情况"
"对比铜期货的多空论点"
```

系统自动执行 6 阶段完整流程：数据采集 → 产业链分析 → 闫判官筛选 → 研究员供弹 → 多空辩论 → 风控审核 → 方案输出。

## 系统架构

```
🔴 自进化前置（所有模式强制，全自动）
     │   检测未验证裁决 → validate_verdicts.py
     │   已验证≥5条 → calibrate_weights.py → evolve_agents.py
     │   加载最新 calibration.json + agent_profiles.json
     ▼
P1  通道突破全量扫描               数技源(quant-daily - channel_breakout策略)
     │                           产出: full_scan_channel_breakout_*.json
     │                           信号检查闸门：无STRONG信号则提前终止
     ▼
P1.5 产业链分析                    链证源(commodity-chain-analysis)
     │                           产出: 产业链景气度快照 + redundant_pairs
     │                           基于通道突破品种，不做全覆盖
     ▼
P2  闫判官筛选辩论品种             闫判官(judge)
     │                           输入: 通道突破信号 + 链分析
     │                           按R26指定正方方向(signal_type隐含方向)
     │                           同链冗余硬过滤(r>0.80保留最强)
     ▼
P3  研究员并行供弹                 观澜(技术面禁WebSearch) + 探源(基本面允WebSearch)
     │                           中立产出，verdict=null
     ▼
P4  多空辩论                      证真(正方) + 慎思(反方)
     │                           基于研究员资料提炼论据，禁止自行搜索
     ▼
P5  裁决→方案→风控→决策（串行）      闫判官→策执远→风控明→明鉴秋
     │                           六维评分→6层风控→execute/hold/rematch
     ▼
P6  汇总输出                      明鉴秋
                                 4铁律核验→debate_results.json→HTML报告
```

### 角色与阶段对照

| 角色 | Agent | P1 | P1.5 | P2 | P3 | P4 | P5 |
|:-----|:------|:--:|:----:|:--:|:--:|:--:|:--:|
| **数技源** | datatech | ● 通道突破信号 | | | | | |
| **链证源** | chain-analyst | | ● 产业链 | | | | |
| **闫判官** | judge | | | ● 选品种+定方向 | | | ● 裁决 |
| **探源** | fundamental | | | | ● 基本面供弹 | | |
| **观澜** | technical | | | | ● 技术面供弹 | | |
| **证真** | affirmative | | | | | ● 正方论据 | |
| **慎思** | opposition | | | | | ● 反方论据 | |
| **策执远** | strategist | | | | | | ● 交易方案 |
| **风控明** | risk | | | | | | ● 6层风控审核 |
| **明鉴秋** | team-lead | ● 启动+调度 | | | ● 轮询传递 | ● 调度 | ● 归档+报告 |

## 10 角色详情

| # | 角色 | Agent ID | 对应Skill | 核心职责 |
|:-:|:----|:---------|:----------|:--------|
| 1 | 🎯 明鉴秋 | `futures-debate-team-team-lead` | — | 选题+调度+汇总+流程守护 |
| 2 | 📡 数技源 | `futures-datatech` | `quant-daily` | 运行通道突破全量扫描，产出原始信号 |
| 3 | 🔗 链证源 | `futures-chain-analyst` | `commodity-chain-analysis` | 产业链事实描述+景气度分析（不下多空） |
| 4 | ⚪ 闫判官 | `futures-judge` | `debate-judge` | 选辩论品种+定方向+评分+裁决 |
| 5 | 🧑‍🔬 观澜 | `futures-technical-researcher` | `quant-daily` + `technical-analysis` | 技术分析+支撑阻力（中立，verdict=null，禁WebSearch） |
| 6 | 🧑‍🔬 探源 | `futures-fundamental-researcher` | `fundamental-data-collector` | 基本面分析（供需库存利润，允许WebSearch） |
| 7 | 🔵 证真 | `futures-affirmative-debater` | `debate-argument-builder` | 正方论据（动态方向，禁止自行搜索） |
| 8 | 🔴 慎思 | `futures-opposition-debater` | `debate-argument-builder` | 反方驳论（动态方向，禁止自行搜索） |
| 9 | 📋 策执远 | `futures-trading-strategist` | `debate-trading-planner` | 合约选型+执行方案 |
| 10 | 🟡 风控明 | `futures-risk-manager` | `debate-risk-manager` | 6层风控引擎：选锚/仓位/动态/覆写/反馈/组合 |

## 信号解读

### 通道突破信号（主信号）

| 信号类型 | 含义 | 权重组合 |
|:---------|:-----|:---------|
| channel_breakout | 通道突破 | DC20(40%) + DC55(35%) + BB(15%) + 成交量(10%) |
| trend_confirmation | 趋势确认 | DC55中期位置+趋势方向 |
| bb_squeeze_prebreakout | 布林带挤压预警 | BB带宽低位+挤压状态 |

### 评分等级

| 等级 | 绝对值范围 | 含义 |
|:----|:--------:|:-----|
| STRONG | ≥ 60 | 最强信号，多层通道共振 |
| WATCH | 40-59 | 重点信号，方向一致 |
| WEAK | 20-39 | 信号一般，需验证 |
| NOISE | < 20 | 噪音，忽略 |

## 数据源

| 数据源 | 优先级 | 盘中 | 盘后 | 实时价 |
|:-------|:-----:|:----:|:----:|:------:|
| **通达信TDX TQ-Local** | 0（最高） | ✅ 优先 | ✅ 优先 | ✅ close=实时价 |
| **TqSDK** | 1（降级） | ✅ live模式 | ✅ | ✅ close=实时价 |
| **东方财富** | 2 | ✅ | ✅ | ❌ |
| **AKShare** | 3（最后降级） | ❌ | ✅ | ❌ |

中国期货市场日线惯例：一根 TDX 日线覆盖一个完整交易日（前夜盘21:00→当日日盘15:00），`close` 为该交易周期内最后成交价。

## CLI 使用

```bash
# 通道突破全量扫描（默认策略）
python skills/quant-daily/scripts/scan_all.py

# 指定品种
python skills/quant-daily/scripts/scan_all.py --symbols CU,RB,PK

# 输出到指定目录
python skills/quant-daily/scripts/scan_all.py -o ./reports -p full_scan

# 列出可用策略
python skills/quant-daily/scripts/scan_all.py --list-strategies
```

## 依赖的 Skills

| Skill | 版本 | 用途 |
|:------|:----|:-----|
| `quant-daily` | v2.12.0 | 数据采集+通道突破信号+信号触发文件 |
| `futures-trading-analysis` | v3.6.0 | 主流程编排+5层鲁棒性防线+报告生成 |
| `commodity-chain-analysis` | v2.15.0 | 产业链分析 |
| `fundamental-data-collector` | v1.3.0 | 基本面分析(供需库存利润) |
| `technical-analysis` | v2.2.0 | 技术面分析(支撑阻力+事件日历) |
| `debate-argument-builder` | v2.2.0 | 正反方论点构建 |
| `debate-judge` | v2.0.1 | 辩论裁决 |
| `debate-risk-manager` | v4.0.0 | 风控审核(6层引擎) |
| `debate-trading-planner` | v2.1.0 | 交易方案规划 |

## v5.5 新能力（OmniOpt 分类法集成）

v5.5 将 OmniOpt 论文(arXiv:2607.04033) 的双维度分类法和几何统一方法论引入辩论裁决流程，使闫判官的评估从"综合判断"升级为**基于策略族分类的加权评估**。

### F1-F5 论证策略族分类
- **F1 技术面量价**：均线、MACD、布林带、ADX、RSI、CCI 等技术指标
- **F2 基本面供需**：库存、基差、利润、开工率、供需平衡表
- **F3 持仓资金**：主力持仓变化、持仓量创新高、净多/净空头
- **F4 宏观政策**：利率决议、财政政策、地缘事件、贸易政策
- **F5 套利结构**：跨期价差、跨品种价差、展期收益

### 品种×策略族适应性矩阵
- `memory/instrument_strategy_matrix.json` — 每个品种对各策略族的历史胜率权重
- EMA 在线更新（学习率 0.3），每次裁决后自动校准
- 初始值按品种大类预设（黑色系/有色/能化/农产品/贵金属）
- `scripts/update_matrix.py` 提供 CLI 批量/单条更新接口

### 闫判官加权裁决（WEAS）
在六维评分前增加族加权预处理步骤：
```
WEAS = Σ IMPACT_numeric(论据) × w(策略族, 品种)
IMPACT映射: HIGH=3.0, MEDIUM=1.5, LOW=0.5
族覆盖 ≥3 → 证据充分性 +1分
族覆盖 ≤1 → 证据充分性 -1分
```
裁决 `reasoning` 字段追加 WEAS 摘要，使裁决可量化、可追溯。

## v5.4 新能力（可观测性与自改进）

v5.4 在 v5.3 通道突破主信号源之上，补齐了**系统级可观测性**与**自动自改进**能力，使专家团的决策质量可被量化、审计与迭代。

### APM-CS 五轴评分卡（D1–D5）
- **D1 论据一致性**：held-out 一致性裁判评估"裁决是否真正源于辩论论据"（CLQT §6.4.1），非阻断审计。
- **D2 Acuity 辨识力**：Spearman 秩相关 ρ(PnL, 信息) − ρ(PnL, 噪音)；成本感知 PnL（COST_BPS=2.0）建模交易摩擦。
- **D3 镇定度**：stop~ADX 回归，≥5 轮辩论自动点亮。
- **D4 纪律遵守**：R13/R14/R-resonance 仓位上限，落库前 `enforce_discipline.py` 强制钳制。
- **D5 可靠性**：剔除陈旧基础设施失败后的 fresh 完成率。
- 触发：每周一自动运行（`scheduler/triggers.py`）。

### Telescope 失败模式聚类
- `scripts/cluster_failures.py`：7 维特征提取 + 单维/二维交叉/品种方向聚类 + 规则关联诊断 + 严重度评估，输出 `memory/failure_clusters.json`。

### ViBench 历史回放（阶段二）
- `scripts/run_benchmark.py --replay` + `scripts/replay_harness.py`：按 `(round_id, 品种)` 结构一致性回放，金标准集 `benchmarks/test_cases.json`。

### self_improve 自改进脚手架（阶段三）
- `scripts/self_improve.py`：消费 APM/failure_clusters/benchmark 生成改进建议（proposal，不直接改 Agent），写入 `memory/self_improve_log.json`。

### 全周期 K 线
- 日/周/月/240m/60m/15m/5m/1m + 自定义周期（90m/180m），`PERIOD_CONFIG` 统一路由，指标窗口按 `bar_min` 缩放。

### 反馈闭环
- 自进化前置（validate → calibrate → evolve）全自动；`debate_journal.json` 升级捕获辩手论据 + held-out judge，双副本同步。

## 核心铁律

| 铁律 | 内容 |
|:----|:------|
| **时序铁律** | 链证源先于闫判官 → 闫判官决策 → 研究员供弹 → 辩手立论，顺序不可逆 |
| **禁止串线** | Agent间不得SendMessage，统一写文件由明鉴秋传递 |
| **文件就绪** | 下游必须poll上游文件就绪(存在+size稳定≥5秒) |
| **辩手禁搜** | 证真/慎思不得自行WebSearch，论据必须来自研究员资料 |
| **胶水代码零容忍** | 所有操作通过已有skill的CLI/库函数/Agent spawn完成 |
| **记忆独立** | 专家团记忆仅写入自身memory/目录，不入宿主工作空间 |
| **鲁棒性防线** | L1-L5五层防线(校验+降级+信号门+路径发现+自检)确保流程不静默断裂 |
| **P5降级D06** | 闫判官2次spawn失败→明鉴秋基于P3+P4论据独立裁决 |

## 输出文件结构

```
Commodities/Reports/商品期货深度分析/{date}/
├── full_scan_channel_breakout_{date}.json     ← 通道突破信号
├── research_snapshots/
│   ├── p2_chain_{symbol}.json                 ← 链证源产业链分析
│   ├── p2_judge_direction.json                ← 闫判官决策
│   ├── p3_technical_{symbol}.json             ← 观澜技术面快照
│   ├── p3_fundamental_{symbol}.json           ← 探源基本面快照
│   ├── p3_affirmative_{symbol}.json           ← 证真正方论据
│   ├── p3_opposition_{symbol}.json            ← 慎思反方论据
│   ├── p4_trading_plan_{symbol}.json          ← 策执远交易方案
│   ├── p4_risk_verdict_{symbol}.json          ← 风控明审核
│   └── p_judge_final_{trace_id}.json          ← 闫判官最终裁决
├── debate_results.json                        ← 汇总决策记录
└── debate_results.html                        ← HTML可视化报告
```

## 依赖安装

```bash
# 核心依赖
pip install numpy pandas pyyaml duckdb requests akshare pydantic psutil lightgbm scikit-learn

# TqSDK（可选，TDX降级备用）
pip install tqsdk
```

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v5.7.0** | **2026-07-10** | **🏗 驾驭工程（Harness Engineering）完整落地**: 15项差距全部修复，成熟度4.0→4.7。Phase1正确性修复(G1 Pydantic配置校验/G2 trace_id全链路/G3 pipeline日志统一/G4 bootstrap动态版本)→Phase2测试补齐(G5 pipeline集成10用例/G6 scheduler集成10用例/G7覆盖率扩展到全skill/G8 memory集成9用例)→Phase3运维增强(G9 graceful drain/G10兼容矩阵/G13熔断可配/G14合约版本迁移28条路径)→Phase4体验优化(G11 APM-CS实时看板/G12 HTTP健康端点/G15 JSON结构化日志)。43用例全绿，contracts桥接层统一入口。|
| **v5.6.0** | **2026-07-09** | **🛡 5层鲁棒性架构**：L1产出校验(validate_agent_output.py)+L2熔断降级(debate_orchestrator.py+D06铁律)+L3信号门(daily_debate.py v2.0触发文件)+L4路径自发现(phase3 v3.2 CLI参数化)+L5健康自检(selfcheck.py)。D05-D06辩论完整性铁律。闫判官spawn Bug修复(futures-judge.md v2.1)。JSON产出规范J01-J03注入慎思+证真Agent MD。|
| **v5.5.0** | **2026-07-09** | **🧬 OmniOpt 分类法集成**：F1-F5 论证策略族分类系统；品种×策略族适应性矩阵(EMA在线更新)；闫判官加权裁决(WEAS族加权预处理+族多样性检查)；正反方辩手输出格式扩展(含策略族标签) |
| **v5.4.1** | **2026-07-07** | **🔧 信息源扩充**：新增 `memory/info_portals.md` 定性信息门户目录 — 三层级分类框架(监管/交易所→综合资讯聚合→产业垂直聚合)，合并金瑞期货权威清单与资深交易员实战配置，共30+权威站点，附品种映射速查表；`data_sources.md` 新增定性门户交叉引用节（与 A/B/C/D 定量评级体系隔离）；团队主管 SOP 新增定性信息取证职责 |
| **v5.4.0** | **2026-07-07** | **🧬 可观测性与自改进里程碑**：APM-CS五轴评分卡(D1-D5)+Telescope失败聚类；D1/D3/ViBench回放+held-out一致性裁判；D2 Acuity真实计算+成本感知PnL(COST_BPS)；D4纪律钳制enforce_discipline(R13/R14/R-resonance仓位上限)；D2信号退化标记/D5陈旧失败过滤/Stage3 self_improve脚手架；全周期K线(日/周/月/240m/60m/15m/5m/1m+自定义)；bug修复(MA60真实合约口径/scan_all原子写入/portfolio_backtest裸except/RuleChecker浮点边界/triggers闭包)；5门禁审计全100% |
| **v5.3.0** | **2026-07-07** | **🧬 通道突破策略里程碑**：唐奇安DC20/DC55+布林带替换三类信号为主信号源；TqSDK live模式盘中实时价(非backtest)；盘中/盘后自适应数据获取；信号检查闸门(无信号早停)；单策略默认(非--dual)；多数据源格式对齐(TDX/TqSDK/EM/AKShare统一schema)；TDX date字段str()防TypeError；日盘14:30自动化全流程含辩论团P0-P6；管理员手册合并入README；日线跨夜盘说明新增 |
| **v5.2.1** | **2026-07-07** | **🔧 全面修复**: ADX仅风控不参与评分+Agent输出格式统一+JSON Schema标准导出+时序通信铁律S01-S05+胶水代码清零 |
| **v5.2** | **2026-07-06** | **🧬 架构重构**: 三类信号替代L1-L4+因子择时为主信号源，全部信号全辩论，ADX角色反转，证真/慎思动态正反方 |
| **v5.1** | **2026-07-06** | **🔄 Phase 1独立化**: 内建调度器scheduler/、bootstrap一键启动、daemon看门狗、自循环闭环升级 |
| **v5.0** | **2026-07-06** | **🧬 自进化闭环里程碑**: P0进化链(validate→calibrate→evolve)、全9Agent自进化、裁决修正经验库 |
| **v4.5** | **2026-07-06** | Bridgewater方法论落地: 五维辩论评分+研报质量过滤+辩论档案+ML训练自动化 |
| **v4.4** | **2026-07-05** | P0+P1全面实施: 情感因子+流动性风险+交易摩擦+DAG并行+记忆反思 |
| **v4.2** | **2026-07-05** | P3全量实现: 事件日历+ML特征管道+方向分类器+PnL反馈闭环+风控6层引擎 |
